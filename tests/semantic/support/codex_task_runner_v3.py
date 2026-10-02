"""Scenario-scoped fresh Codex task execution for the V3 heavy suite."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tests.semantic.support.codex_business_oracle_plan_v3 import (
    BUSINESS_ORACLE_PLAN_FILE,
    BusinessOraclePlanEvidence,
    BusinessOraclePlanError,
    business_family_for_api,
    read_business_oracle_plan_envelope,
)
from tests.semantic.support.codex_eval_bundle_v3 import OnlineScenario
from tests.semantic.support.codex_eval_protocol_v3 import V3GatewayProtocol
from tests.semantic.support.codex_gateway_broker import (
    CodexGatewayBroker,
    GatewayBrokerEvidence,
    GatewayBrokerReconciliation,
    TrustedSubscriptionAckObserver,
    TrustedSubscriptionAckSpec,
    TrustedStepObserver,
    TrustedStepPreObserver,
    business_draft_setup_step_prefix,
    gateway_step_sequence_matches,
)
from tests.semantic.support.codex_gateway_contracts import (
    task_local_runner_matches_normalized,
)
from tests.semantic.support.codex_filesystem_security import write_utf8_text_bytes
from tests.semantic.support.codex_harness import (
    CodexCliTask,
    CodexCommandRecord,
    CodexGatewayErrorExpectation,
    CodexHarnessConfig,
    CodexHarnessError,
    CodexInfrastructureError,
    CodexInfrastructureFailure,
    CodexRunResult,
    WindowsPowerShellCoreHost,
    gateway_continuation_binding_errors,
    normalized_gateway_command_argv,
    prepare_workspace_skill_install,
    recoverable_preprocess_attempt_indexes,
    semantic_task_developer_instructions,
    parse_jsonl_events,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PROMPT_MATERIALIZATION_RECEIPT_CONTRACT,
    PROMPT_MATERIALIZATION_RECEIPT_FILE,
    PROMPT_PROVENANCE_FILE,
    prompt_materialization_receipt,
    read_prompt_provenance,
)
from tests.semantic.support.codex_prompt_asset_reads_v3 import (
    PromptAssetReadError,
    remove_validated_command_occurrences,
    validated_prompt_asset_cat_commands,
)
from tests.semantic.support.codex_typed_draft_evidence_v3 import (
    TypedDraftEvidenceError,
    classify_composer_failure_stage,
    validate_typed_draft_evidence,
)
from wwise_waapi.audio_import_business_contracts import (
    AUDIO_IMPORT_BUSINESS_BATCH_MAX_ROWS,
)


TASK_RESULT_CONTRACT = "waapi-skill.codex-semantic-task-result/v5"
TASK_INFRASTRUCTURE_FAILURE_CONTRACT = (
    "waapi-skill.codex-semantic-task-infrastructure-failure/v3"
)
TASK_COMMAND_LIFECYCLE_FAILURE_CONTRACT = (
    "waapi-skill.codex-semantic-command-lifecycle-failure/v1"
)
TASK_GATE_FAILURE_CONTRACT = "waapi-skill.codex-semantic-task-gate-failure/v1"
PROMPT_MATERIALIZATION_CONTRACT = PROMPT_MATERIALIZATION_RECEIPT_CONTRACT
PROMPT_MATERIALIZATION_FILE = PROMPT_MATERIALIZATION_RECEIPT_FILE
_CODEX_INFRASTRUCTURE_CATEGORIES = frozenset(
    {
        "authentication",
        "quota_or_rate_limit",
        "service_unavailable",
        "timeout_before_agent_action",
        "turn_failed_before_agent_action",
    }
)
_PACKAGED_LANE_REFERENCES = frozenset(
    {
        "references/waapi-coverage.md",
        "references/waapi-operate.md",
        "references/waapi-query.md",
        "references/waapi-setup.md",
    }
)


class V3TaskRunnerError(RuntimeError):
    """The fresh task failed a harness/broker invariant."""

    def __init__(self, message: str, *, thread_id: str | None = None) -> None:
        super().__init__(message)
        self.thread_id = thread_id


class V3CommandLifecycleError(CodexHarnessError):
    """Codex ended a turn while one or more command items were incomplete."""


@dataclass(frozen=True, slots=True)
class V3TurnGrade:
    index: int
    prompt_sha256: str
    broker_prefix_count: int
    reconciliation: GatewayBrokerReconciliation
    common_gates: Mapping[str, bool]
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.reconciliation.passed
            and bool(self.common_gates)
            and all(self.common_gates.values())
            and not self.errors
        )


@dataclass(frozen=True, slots=True)
class V3TaskRun:
    scenario_id: str
    version: str
    task_root: Path
    thread_id: str
    turns: tuple[CodexRunResult, ...]
    turn_grades: tuple[V3TurnGrade, ...]
    broker_evidence: GatewayBrokerEvidence
    broker_protocol_passed: bool = False

    @property
    def passed(self) -> bool:
        return (
            (self.broker_evidence.passed or self.broker_protocol_passed)
            and all(item.passed for item in self.turn_grades)
        )

    @property
    def terminal_indeterminate(self) -> bool:
        return (
            bool(getattr(self.broker_evidence, "terminal_indeterminate", False))
            and bool(self.turn_grades)
            and all(item.passed for item in self.turn_grades)
        )

    @property
    def final_response(self) -> str:
        return self.turns[-1].final_response if self.turns else ""


TurnObserver = Callable[[int, CodexRunResult, GatewayBrokerEvidence], None]


def _expansion_effect_groups(artifact: Mapping[str, Any], before: Mapping[str, Any]) -> tuple[tuple[str, ...], ...]:
    """Build notice obligations from the already approved immutable request.

    This recognizes the expansion's closed operation families, not arbitrary
    prose or native API requests. Unknown/missing effect data fails closed.
    """
    request = artifact.get("request", {})
    if not isinstance(request, Mapping):
        return ()
    arguments = request.get("arguments", {})
    operation = request.get("operation")
    if not isinstance(arguments, Mapping):
        return ()
    identities: dict[str, tuple[str, ...]] = {}

    def index_rows(value: Any) -> None:
        if isinstance(value, Mapping):
            if isinstance(value.get("id"), str):
                names = tuple(value[key] for key in ("name", "path") if isinstance(value.get(key), str) and value[key])
                if names:
                    identities[value["id"].casefold()] = names
            for child in value.values():
                index_rows(child)
        elif isinstance(value, list):
            for child in value:
                index_rows(child)

    index_rows(before)
    groups: list[tuple[str, ...]] = []

    def target(selector: Any) -> None:
        value = selector.get("value") if isinstance(selector, Mapping) else selector
        if isinstance(value, str):
            names = identities.get(value.casefold())
            groups.append(names or (value,))

    def properties(rows: Any) -> None:
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping) and row.get("name") == "Volume" and type(row.get("value")) in {int, float}:
                groups.extend((("volume", "音量", "增益"), (format(row["value"], "g"),)))

    if operation == "audio.import":
        groups.append(("import", "replace", "reimport", "create", "update", "导入", "替换", "重导", "创建", "建立", "新增", "更新"))
        defaults = arguments.get("defaults", {})
        for item in arguments.get("imports", []):
            row = {**defaults, **item}
            path = row.get("object_path")
            if not isinstance(path, str):
                return ()
            name = re.sub(r"<[^>]+>", "", path).rsplit("\\", 1)[-1]
            groups.append((name, path))
            language = row.get("import_language")
            if language and language != "SFX":
                groups.append((language, "日语", "日文") if language == "Japanese" else (language,))
            properties(row.get("properties"))
    elif operation == "object.setRTPC":
        target(arguments.get("object"))
        target(arguments.get("control_input"))
        groups.extend((("rtpc", "曲线", "curve"), ("volume", "音量", "增益"),
                       ("update", "replace", "set", "change", "更新", "替换", "修改", "设置", "改成")))
    elif operation == "object.createPlugin":
        target(arguments.get("target"))
        plugin = arguments.get("plugin", {})
        groups.extend(((str(plugin.get("name", "")),),
                       ("effect", "plugin", "效果", "插件"),
                       ("add", "create", "insert", "添加", "创建", "新增", "插入")))
    elif operation == "object.setReference":
        target(arguments.get("object"))
        target(arguments.get("target"))
        groups.extend((("trigger", "触发器"),
                       ("retarget", "change", "set", "replace", "指向", "改为", "修改", "替换", "设置")))
    elif operation == "waapi.call" and arguments.get("api") == "ak.wwise.core.object.setAttenuationCurve":
        target(arguments.get("args", {}).get("object"))
        groups.extend((("volume", "音量", "干声", "dry"), ("curve", "曲线"),
                       ("update", "set", "change", "replace", "更新", "修改", "替换", "设置", "改成")))
    else:
        return ()
    return tuple(groups) if groups and all(all(term for term in group) for group in groups) else ()


def _bound_context_notice(artifact: Mapping[str, Any], before: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Resolve a type pronoun only through matching sealed and independent roles."""
    request, prepared = artifact.get("request", {}), artifact.get("prepared_operation", {})
    if not isinstance(request, Mapping) or not isinstance(prepared, Mapping):
        return None
    args, state, plan = request.get("arguments", {}), prepared.get("pre_state", {}), prepared.get("verification_plan", {})
    if not all(isinstance(value, Mapping) for value in (args, state, plan)):
        return None
    operation, version = request.get("operation"), request.get("version")
    if (prepared.get("operation") != operation or prepared.get("version") != version
            or version not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}):
        return None
    def identity(row: Any, observed: Any) -> bool:
        return (isinstance(row, Mapping) and isinstance(observed, Mapping)
                and isinstance(row.get("id"), str)
                and all(isinstance(row.get(key), str) for key in ("name", "type", "path"))
                and re.fullmatch(r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}", row["id"]) is not None
                and all(row.get(key) == observed.get(key) for key in ("id", "name", "type", "path")))
    if operation == "object.createPlugin":
        source, observed = state.get("target"), before.get("owner")
        guard, plugin = state.get("plugin_creation_guard", {}), args.get("plugin", {})
        if not isinstance(guard, Mapping) or not isinstance(plugin, Mapping) or not identity(source, observed):
            return None
        descriptor = plan.get("descriptor")
        if (source["type"] != "Sound" or args.get("target") != {"kind": "id", "value": source["id"]}
                or plan.get("kind") != "object-plugin-created" or plan.get("target_id") != source["id"]
                or plan.get("target_type") != "Sound" or plan.get("version") != version
                or guard.get("target_id") != source["id"] or guard.get("target_type") != "Sound"
                or guard.get("version") != version or guard.get("descriptor") != descriptor
                or not isinstance(descriptor, Mapping) or descriptor.get("kind") != "effect"
                or type(descriptor.get("class_id")) is not int or descriptor["class_id"] <= 0
                or any(descriptor.get(key) != value for key, value in plugin.items())):
            return None
        placement = plan.get("placement", {})
        if (not isinstance(placement, Mapping) or placement.get("kind") != "effect_slot_append"
                or placement.get("create_only") is not True or placement.get("list_mode") != "append"
                or placement.get("replace_existing_allowed") is not False):
            return None
        groups = [(source["id"], source["name"], source["path"], "该 sound", "this sound"),
                  (descriptor.get("name", ""),), ("effect", "效果", "插件"), ("新增", "添加", "插入", "add", "create", "append")]
        if descriptor.get("notes"):
            groups.append((descriptor["notes"],))
        return {"groups": groups, "ids": (source["id"],), "protected": ("volume", "音量", "路由", "output bus", "原效果", "existing effect"),
                "action": r"新增|添加|插入|add|create|append", "kind": "plugin"}
    if operation == "object.setReference":
        source, target = state.get("object"), state.get("target")
        observed, expected = before.get("stinger"), before.get("target")
        if not identity(source, observed) or not identity(target, expected):
            return None
        owner, siblings = before.get("owner", {}), before.get("siblings")
        if (source["type"] != "MusicStinger" or target["type"] != "Trigger"
                or args.get("object") != {"kind": "id", "value": source["id"]}
                or args.get("target") != {"kind": "id", "value": target["id"]} or args.get("reference") != "Trigger"
                or plan.get("kind") != "same-guid-reference" or plan.get("object_id") != source["id"]
                or plan.get("field") != "Trigger" or plan.get("expected_target_id") != target["id"]
                or plan.get("expected_clear") is not False or not isinstance(owner, Mapping)
                or not isinstance(siblings, list) or sum(isinstance(row, Mapping) and row.get("id") == source["id"] for row in siblings) != 1
                or not isinstance(owner.get("@Stingers"), list)
                or sum(isinstance(row, Mapping) and row.get("id") == source["id"] for row in owner["@Stingers"]) != 1):
            return None
        return {"groups": [(source["id"], source["path"], "该 musicstinger", "该 stinger", "this musicstinger"),
                           (target["id"], target["name"], target["path"]), ("trigger", "触发器"),
                           ("改动", "更新", "修改", "改为", "指向", "update", "change", "retarget")],
                "ids": (source["id"], target["id"]), "protected": ("segment", "音乐段", "容器", "container"),
                "action": r"改动|更新|修改|改为|指向|update|change|retarget", "kind": "reference"}
    return None


def _bound_context_effect(text: str, context: Mapping[str, Any]) -> bool:
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    ids = re.findall(r"\{[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}", text)
    if any(value not in {value.casefold() for value in context["ids"]} for value in ids):
        return False
    if not all(any(term and term.casefold() in text for term in group) for group in context["groups"]):
        return False
    affirmative = False
    for clause in re.split(r"[。；;\n]|\bbut\b|但", text):
        anchored = any(term and term.casefold() in clause for term in context["groups"][0])
        actions = tuple(re.finditer(r"新增|添加|插入|改动|更新|修改|改为|指向|变更|删除|移除|替换|设置|\b(?:add|create|append|update|change|retarget|delete|remove|replace|set|modify|edit|alter|insert)\b", clause))
        for index, action in enumerate(actions):
            claim = clause[action.start():actions[index + 1].start() if index + 1 < len(actions) else len(clause)]
            effect_anchor = any(term and term.casefold() in claim for term in context["groups"][2])
            approved_value = any(term and term.casefold() in claim for term in context["groups"][1])
            expected = re.fullmatch(context["action"], action.group()) is not None
            negated = _notice_qualifier_is_negated(clause[:action.start()])
            if negated:
                if expected and anchored and effect_anchor and (approved_value
                        or re.search(r"目标|名为|为|\bto\b", claim) is None):
                    return False
                continue
            # Verification and the execute-summary noun do not author another
            # change. They cannot certify the expected effect by themselves.
            prefix = clause[:action.start()]
            if re.search(r"(?:核验|verify|验收)\s*$", prefix) or (context["kind"] == "reference"
                    and re.search(r"执行.*引用$", prefix) and action.group() == "更新"):
                continue
            if any(term in clause for term in context["protected"]):
                return False
            if not expected or not effect_anchor or not approved_value:
                return False
            if expected and anchored:
                affirmative = True
    return affirmative


def _rtpc_notice_context(artifact: Mapping[str, Any], before: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Attest one existing Volume association before inheriting its identity.

    The immutable request, prepared snapshot/verification plan and independent
    baseline must agree. No identity is inferred from free-form tool prose.
    """
    request = artifact.get("request", {})
    prepared = artifact.get("prepared_operation", {})
    if not isinstance(request, Mapping) or not isinstance(prepared, Mapping):
        return None
    args = request.get("arguments", {})
    plan = prepared.get("verification_plan", {})
    state = prepared.get("pre_state", {})
    if not all(isinstance(value, Mapping) for value in (request, prepared, args, plan, state)):
        return None
    def guid(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}", value) is not None
    owner, control, association = (plan.get(key) for key in ("object_id", "control_input_id", "existing_rtpc_id"))
    if (not all(guid(value) for value in (owner, control, association))
            or request.get("operation") != prepared.get("operation") or prepared.get("operation") != "object.setRTPC"
            or request.get("version") not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}
            or request.get("version") != prepared.get("version") or plan.get("version") != request.get("version")
            or plan.get("kind") != "object-rtpc-state" or plan.get("action") != "update"
            or args.get("object") != {"kind": "id", "value": owner}
            or args.get("control_input") != {"kind": "id", "value": control}
            or args.get("property") != "Volume" or plan.get("property") != "Volume"
            or args.get("mode") != "add_or_replace" or "notes" in args
            or plan.get("notes_supplied") is not False or plan.get("expected_notes") is not None):
        return None
    old_owner, controls, rtpcs = before.get("owner"), before.get("controls"), before.get("rtpcs")
    snapshot = state.get("rtpc_snapshot", {})
    if (not isinstance(old_owner, Mapping) or old_owner.get("id") != owner
            or not isinstance(controls, list) or not isinstance(rtpcs, Mapping)
            or not isinstance(snapshot, Mapping) or snapshot.get("object_id") != owner):
        return None
    matched = [row for row in controls if isinstance(row, Mapping) and row.get("id") == control]
    if len(matched) != 1:
        return None
    for baseline, row in ((old_owner, state.get("object")), (matched[0], state.get("control_input"))):
        if not isinstance(row, Mapping) or any(row.get(key) != baseline.get(key) for key in ("id", "name", "type", "path")):
            return None
    rows = snapshot.get("rows")
    plan_rows = plan.get("before_rows")
    if (not isinstance(plan_rows, list) or any(not isinstance(row, Mapping) or not guid(row.get("id")) for row in plan_rows)
            or len({row["id"] for row in plan_rows}) != len(plan_rows)):
        return None
    if (not isinstance(rows, list) or any(not isinstance(row, Mapping) or not guid(row.get("id")) for row in rows)
            or len({row["id"] for row in rows}) != len(rows)
            or {row["id"]: row for row in rows} != dict(rtpcs)
            or {row["id"]: row for row in plan_rows} != dict(rtpcs)):
        return None
    volume = [row for row in rows if row.get("@PropertyName") == "Volume"]
    if (len(volume) != 1 or volume[0].get("id") != association
            or not isinstance(volume[0].get("@ControlInput"), Mapping)
            or volume[0]["@ControlInput"].get("id") != control):
        return None
    def points(value: Any) -> list[tuple[float, float]] | None:
        if not isinstance(value, list) or not value:
            return None
        result = []
        for point in value:
            if (not isinstance(point, Mapping) or set(point) != {"x", "y", "shape"}
                    or point["shape"] != "Linear" or any(type(point[key]) not in {int, float}
                    or not math.isfinite(point[key]) for key in ("x", "y"))):
                return None
            result.append((point["x"], point["y"]))
        return result if all(a[0] < b[0] for a, b in zip(result, result[1:])) else None
    curve = volume[0].get("@Curve", {})
    old = points(curve.get("points")) if isinstance(curve, Mapping) else None
    new = points(args.get("points"))
    if old is None or new is None or plan.get("points") != args.get("points") or old == new:
        return None
    delta = [point for point in new if point not in old]
    foreign_names = {row["@PropertyName"] for row in rows
                     if isinstance(row.get("@PropertyName"), str) and row["@PropertyName"] != "Volume"}
    foreign_names.update(row[key] for row in controls if isinstance(row, Mapping) and row.get("id") != control
                         for key in ("name", "path") if isinstance(row.get(key), str) and row[key])
    return {"ids": (owner, control, association), "old": old, "new": new, "delta": delta,
            "foreign_names": tuple(sorted(foreign_names)),
            "control_names": tuple(matched[0][key] for key in ("name", "path")
                                   if isinstance(matched[0].get(key), str) and matched[0][key]),
            "same_domain": [p[0] for p in old] == [p[0] for p in new]}


def _notice_qualifier_is_negated(qualifier: str) -> bool:
    return re.search(r"不|未|非|(?<![a-z])(?:not|never|without|non)(?![a-z])|n't", qualifier) is not None


def _affirmative_linear_interpolation(effect_clause: str) -> bool:
    """Require the requested shape, with polarity scoped to this effect."""
    mentions = tuple(re.finditer(r"线性|(?<![a-z])linear(?![a-z])", effect_clause))
    for mention in mentions:
        # A qualifier may contain an intervening predicate ("不保持线性",
        # "not keep linear"). Any negator in that local qualifier makes the
        # requested affirmative shape unclear; do not guess its scope.
        qualifier = re.split(r"[，,、。；;\n]", effect_clause[:mention.start()])[-1]
        if _notice_qualifier_is_negated(qualifier):
            return False
    return bool(mentions)


def _rtpc_visible_shape_plan(text: str, context: Mapping[str, Any]) -> bool | None:
    """Return the latest relevant plan's validity, or None for unrelated prose."""
    if not (("curve" in text or "曲线" in text) and ("点" in text or "points" in text)
            and (any(term in text for term in ("volume", "音量", "增益"))
                 or any(name.casefold() in text for name in context["control_names"]))):
        return None
    number = r"[+-]?\d+(?:\.\d+)?"
    stated_points = [(float(x), float(y)) for x, y in re.findall(
        rf"[（(]\s*({number})\s*[,，]\s*({number})\s*[)）]", text.replace("\u2212", "-"))]
    arrow_points = [(float(x), float(y)) for x, y in re.findall(
        rf"({number})\s*→\s*({number})", text.replace("\u2212", "-"))]
    if arrow_points:
        if stated_points:
            return False
        stated_points = arrow_points
    stated_ids = re.findall(r"\{[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}", text)
    return (all(value in {key.casefold() for key in context["ids"]} for value in stated_ids)
            and len(context["new"]) == 3 and (not stated_points or stated_points == context["new"])
            and any(term in text for term in ("volume", "音量", "增益"))
            and any(name.casefold() in text for name in context["control_names"])
            and re.search(r"三(?:个)?点|(?<!\d)3\s*points|three points", text) is not None
            and _affirmative_linear_interpolation(text))


def _rtpc_notice_effect(text: str, context: Mapping[str, Any], *, earlier_points: bool, earlier_shape: bool = False) -> tuple[bool, bool]:
    """Recognize a full curve or accurate point delta in the attested context."""
    numeric = text.replace("\u2212", "-")
    ids = re.findall(r"\{[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}", text)
    if any(value not in {key.casefold() for key in context["ids"]} for value in ids):
        return False, False
    # A negated change preserves the field. Polarity is local to a clause;
    # an English coordinated verb may share it, but a later clause cannot.
    protected = r"(?:备注|身份|其他控制曲线|notes|identity|pitch|time)"
    changes = re.compile(rf"(?:修改|更新|删除|改变|\b(?:change|update|delete|remove)\b)\s*(?:这条关系的|该\s*\w+\s*的\s*)?{protected}|{protected}\s*(?:改为|改成|更新为|修改为)")
    for clause in re.split(r"[。；;,，.\n]|\bbut\b|但", text):
        previous_end = 0
        negated = False
        for change in changes.finditer(clause):
            prefix = clause[:change.start()]
            local_negation = re.search(r"(?:不(?:会|再|要)?|\b(?:not|never)|n't)\s*$", prefix) is not None
            shared_negation = (negated and previous_end > 0
                               and re.fullmatch(r"\s*(?:and|or)\s*", clause[previous_end:change.start()]) is not None)
            negated = local_negation or shared_negation
            if not negated:
                return False, False
            previous_end = change.end()
    number = r"[+-]?\d+(?:\.\d+)?"
    def pairs(part: str) -> list[tuple[float, float]]:
        return [(float(x), float(y)) for x, y in re.findall(
            rf"[（(]\s*({number})\s*[,，]\s*({number})\s*[)）]", part)]
    full = False
    effect = False
    clauses = re.split(r"[。；;\n]", numeric)
    whole_target = (context["ids"][2].casefold() in text or
                    (any(term in text for term in ("volume", "音量", "增益"))
                     and any(term in text for term in ("curve", "曲线", "关系", "association", "relationship"))))
    same_target_clauses = [clause for clause in clauses if not any(
        re.search(rf"(?<![a-z0-9_]){re.escape(name.casefold())}(?![a-z0-9_])", clause)
        for name in context["foreign_names"])
        and not (re.search(r"(?:其他|另一条|other|sibling).*?(?:曲线|curve|关系|association|relationship)", clause)
                 and not re.search(r"改为|改成|更新为|修改为|设为|设置为|update|replace|change|set", clause))]
    retention = "\n".join(same_target_clauses)
    # A remainder already matching the sealed goal implies preservation only
    # when that exact remainder was unchanged in the approved request.
    rest_already_matches = (len(context["new"]) == 3 and len(context["delta"]) == 1
        and context["same_domain"] and re.search(r"其余(?:两|2)点|remaining (?:two|2) points", retention) is not None
        and any(term in retention for term in ("符合目标", "match the target")))
    shape_clauses = "\n".join(clause for clause in same_target_clauses if "linear" in clause or "线性" in clause)
    notice_shape = _affirmative_linear_interpolation(shape_clauses) if shape_clauses else earlier_shape
    def requested_shape(part: str) -> bool:
        return notice_shape and (not ("linear" in part or "线性" in part)
                                 or _affirmative_linear_interpolation(part))
    old, new = context["old"], context["new"]
    middle_edit = (len(old) == len(new) == 3 and context["same_domain"]
                   and old[0] == new[0] and old[2] == new[2] and context["delta"] == [new[1]])
    complete_current_curve = False
    for clause_index, clause in enumerate(clauses):
        point_reference = "该点" in clause
        if point_reference and middle_edit:
            prefix = "\n".join(clauses[:clause_index]) + clause.split("该点", 1)[0]
            antecedents = pairs(prefix)
            if antecedents == [old[1]] and re.search(r"中点|中间点|midpoint|middle point", prefix):
                clause = clause.replace("该点", "中点")
            else:
                return False, False
        scalar_middles = tuple(re.finditer(
            rf"(?:中点|中间点|midpoint|middle point)\s*(?:改为|改成|设为|设置为|(?:will be )?set to|change to)\s*({number})(?![a-z\d_.])", clause))
        target_clause = (any(term in clause for term in ("volume", "音量", "增益"))
                         and any(term in clause for term in ("curve", "曲线", "rtpc"))) or whole_target
        historical = (any(term in clause for term in ("现有", "当前", "现状", "existing", "current"))
                      or re.search(r"(?:中点|中间点|midpoint|middle point)\s*(?:从|from)", clause) is not None)
        if (target_clause or scalar_middles) and historical:
            # Validate claimed history before either tuple or scalar dispatch.
            previous = pairs(re.split(r"改为|改成|更新为|修改为|设为|设置为|update|replace|change|set", clause)[0])
            if any(point not in context["old"] for point in previous):
                return False, False
            if clause in same_target_clauses and previous == old:
                complete_current_curve = True
        if scalar_middles:
            if len(context["new"]) != 3:
                return False, False
            if any(float(claim.group(1)) != context["new"][1][1]
                   or _notice_qualifier_is_negated(re.split(r"[，,、]", clause[:claim.start()])[-1])
                   or any(re.search(rf"(?<![a-z0-9_]){re.escape(name.casefold())}(?![a-z0-9_])",
                                    re.split(r"[，,、]", clause[:claim.start()])[-1])
                          for name in context["foreign_names"])
                   for claim in scalar_middles):
                return False, False
            scalar_middle = scalar_middles[-1]
            old, new = context["old"], context["new"]
            following = clause[scalar_middle.end():]
            # This point role has one meaning only in an attested three-point
            # curve whose sole change is the middle y value. Endpoints must
            # be stated, not inferred from a generic preservation claim.
            inherited_endpoints = (point_reference and earlier_points and not pairs(following)
                                   and re.search(r"保留(?:两端点|首尾点)", following) is not None)
            if (len(old) != 3 or len(new) != 3 or not context["same_domain"]
                    or old[0] != new[0] or old[2] != new[2]
                    or context["delta"] != [new[1]] or old[1][1] == new[1][1]
                    or float(scalar_middle.group(1)) != new[1][1]
                    or not (inherited_endpoints or (pairs(following) == [new[0], new[2]]
                        and any(term in following for term in ("保持", "unchanged", "retain"))
                        and any(term in following for term in ("不变", "原值", "unchanged"))))
                    or not _affirmative_linear_interpolation(following)):
                return False, False
            effect = True
            continue
        if not target_clause:
            continue
        for action in re.finditer(r"更新为|替换为|修改为|改为|改成|设为|设置为|update|replace|change|set", clause):
            following = clause[action.end():]
            stated = pairs(following)
            if stated and any(re.search(rf"(?<![a-z0-9_]){re.escape(name.casefold())}(?![a-z0-9_])",
                                       clause[:action.start()]) for name in context["foreign_names"]):
                return False, False
            # A changed-point explanation followed by the exact full result is
            # two compatible claims, not four authored curve points. Require
            # the closed middle-y role and this exact sequence; never dedup.
            direct_middle_claim = re.search(
                rf"(?:中点|中间点|midpoint|middle point)\s*(?:(?:从|from)\s*[（(]\s*{number}\s*[,，]\s*{number}\s*[)）])?\s*$",
                clause[:action.start()]) is not None
            first_pair = re.search(rf"[（(]\s*{number}\s*[,，]\s*{number}\s*[)）]", following)
            separate_result = (first_pair is not None and re.match(
                r"\s*[,，]\s*(?:曲线点(?:为|是)|curve points(?: are| will be)?)\s*[（(]",
                following[first_pair.end():]) is not None)
            if middle_edit and direct_middle_claim and separate_result and stated == context["delta"] + new:
                stated = new
            if stated == context["new"] and requested_shape(following):
                full = effect = True
            elif (stated == context["delta"] and stated and context["same_domain"]
                  and (rest_already_matches or (middle_edit and direct_middle_claim and complete_current_curve) or
                       (any(term in retention for term in ("两端", "其余点", "endpoints", "other points"))
                        and any(term in retention for term in ("保持", "不变", "unchanged"))))
                  and requested_shape(following)):
                effect = True
            elif (not stated and earlier_points and any(term in following for term in (
                    "指定", "上述", "前述", "requested", "specified", "above"))
                  and _affirmative_linear_interpolation(following)):
                effect = True
            elif stated:
                return False, False
    return effect, full


def expansion_preview_notice(result: Any, command_records: Sequence[Any], *,
                             version: str, execute_expected: bool,
                             preview_artifact: Mapping[str, Any],
                             before_snapshot: Mapping[str, Any]) -> bool:
    """Require a reviewable expected effect after Preview and before Execute.

    A reference to an earlier visible expected result is sufficient only if
    that result itself meets the sealed request's concrete effect obligations.
    Generic progress, a bare Preview mention, and tool output are not notices.
    """
    groups = _expansion_effect_groups(preview_artifact, before_snapshot)
    if not groups:
        return False
    prepared_rtpc = (preview_artifact.get("request", {}).get("operation") == "object.setRTPC"
                     and "prepared_operation" in preview_artifact)
    rtpc_context = _rtpc_notice_context(preview_artifact, before_snapshot) if prepared_rtpc else None
    if prepared_rtpc and rtpc_context is None:
        return False
    context_operation = preview_artifact.get("request", {}).get("operation") in {"object.createPlugin", "object.setReference"}
    bound_context = _bound_context_notice(preview_artifact, before_snapshot) if context_operation and "prepared_operation" in preview_artifact else None
    if context_operation and "prepared_operation" in preview_artifact and bound_context is None:
        return False
    earlier_points = False
    earlier_shape = False
    notice_messages: list[str] = []
    commands = {}
    for record in command_records:
        argv = normalized_gateway_command_argv(record.argv, expected_wwise_version=version)
        if len(argv) >= 4:
            commands[record.command] = argv[3]
    preview_seen = False
    notice_seen = False
    earlier_effect = False
    for event in parse_jsonl_events(result.stdout):
        item = event.get("item")
        if not isinstance(item, Mapping):
            continue
        command = commands.get(item.get("command"))
        if item.get("type") == "command_execution" and command == "execute":
            return notice_seen if execute_expected else False
        if event.get("type") != "item.completed":
            continue
        if item.get("type") == "command_execution" and command == "preview-from-draft":
            preview_seen = True
        elif item.get("type") == "agent_message":
            text = str(item.get("text", "")).casefold()
            def mentions(term: str) -> bool:
                if re.fullmatch(r"-?\d+(?:\.\d+)?", term):
                    return any(float(value) == float(term) for value in
                               re.findall(r"(?<![\w.\-])-?\d+(?:\.\d+)?(?![\d.])", text.replace("\u2212", "-")))
                return term.casefold() in text
            effect = all(any(mentions(term) for term in group) for group in groups)
            if bound_context is not None:
                if preview_seen:
                    notice_messages.append(text)
                effect = _bound_context_effect("\n".join(notice_messages) if preview_seen else text, bound_context)
                if preview_seen:
                    notice_seen = effect
            if rtpc_context is not None:
                if preview_seen:
                    notice_messages.append(text)
                notice_text = "\n".join(notice_messages) if preview_seen else text
                effect, full_points = _rtpc_notice_effect(notice_text, rtpc_context,
                    earlier_points=earlier_points, earlier_shape=earlier_shape)
                earlier_points = earlier_points or full_points
                if not preview_seen:
                    shape_plan = _rtpc_visible_shape_plan(text, rtpc_context)
                    if shape_plan is not None:
                        earlier_shape = shape_plan
                        number = r"[+-]?\d+(?:\.\d+)?"
                        arrow = [(float(x), float(y)) for x, y in re.findall(
                            rf"({number})\s*→\s*({number})", text.replace("\u2212", "-"))]
                        if arrow:
                            earlier_points = shape_plan and arrow == rtpc_context["new"]
                if preview_seen:
                    # Re-evaluate the complete notice so later contradictions
                    # cannot hide behind an earlier successful fragment.
                    notice_seen = effect
            reference = rtpc_context is None and bound_context is None and earlier_effect and any(term in text for term in (
                "expected result above", "expected changes above", "changes described above",
                "result just described", "plan above", "上述预期", "上面的预期", "刚才说明的", "上述变更", "按以上方案"))
            if preview_seen and (effect or reference):
                notice_seen = True
            earlier_effect = earlier_effect or effect
    return notice_seen and not execute_expected


def run_expansion_codex_task(
    *, unit: Any, prepared: Any, task_root: Path, options: Any,
    runner_environment: Mapping[str, str], scoped_paths: Mapping[str, str],
    reconcile_after_failure: Callable[[], Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Use the existing fresh task/Broker with the opt-in outcome policy.

    Unlike frozen recipe profiles, accepted Gateway calls are reconciled to
    authenticated records rather than an exact hidden command count. Independent
    case oracles and the same isolation/no-bypass facts remain hard gates.
    """
    from tests.semantic.support.codex_expansion_broker_policy import ExpansionBrokerPolicy
    from wwise_waapi.transactions import TransactionStore
    from tests.semantic.support.codex_expansion_policy import CumulativeAgentBudget, canonical_digest, classify_expansion_outcome

    root = Path(task_root)
    if root.exists():
        raise V3TaskRunnerError("expansion requires a fresh task evidence directory")
    root.mkdir(parents=True)
    workspace = root / "agent-workspace"
    skill_install = prepare_workspace_skill_install(workspace, options.skill_source)
    policy = ExpansionBrokerPolicy(prepared=prepared, version=unit.version,
                                    skill_source=options.skill_source, scoped_paths=scoped_paths)
    budget = CumulativeAgentBudget()
    prompts = (prepared.prompt,)
    if prepared.policy == "ask_before_changes":
        prompts += ("这一步预览没问题，按当前预览执行并核验结果。",)
    plan = {
        "contract": "waapi-skill.integration-expansion-task-plan/v1",
        "unit_id": unit.unit_id, "version": unit.version, "policy": prepared.policy,
        "operation": prepared.operation, "request_schema_uri": prepared.request_schema_uri,
        "accepted_verification_states": sorted(prepared.accepted_verification_states),
        "prompts": list(prompts), "before": prepared.before,
        "required_assertions": sorted(prepared.required_assertions),
        "read_scope_sha256": policy.reads.scope.digest,
        "read_scope": {key: sorted(value) if isinstance(value, frozenset) else value
                       for key, value in asdict(policy.reads.scope).items()},
        "oracle_parameters": dict(prepared.archive_oracle_parameters),
        "preview_parameters": dict(prepared.archive_preview_parameters),
        "inputs_sha256": options.campaign_inputs_sha256,
        "platform_name": os.name,
        "skill_source": str(options.skill_source.resolve()),
        "trusted_python": str(Path(sys.executable).resolve()),
        "windows_powershell_core_host": (asdict(options.windows_powershell_core_host)
                                         if options.windows_powershell_core_host else None),
        "scoped_paths": dict(scoped_paths),
        "agent_budget": {"hard_seconds": 600, "slow_seconds": 420},
        "model": options.model, "reasoning_effort": options.reasoning_effort,
        "service_tier": options.service_tier,
    }
    _write_json(root / "expansion-plan.json", {**plan, "sha256": canonical_digest(plan)})
    allowed_subcommands = (
        "status", "operations", "operation-schema", "request-schema", "query-schema", "query-object", "metadata",
        "draft-start", "draft-bind-object", "draft-discover-fields", "draft-discover-types",
        "draft-inspect", "draft-check", "draft-business-configure", "draft-declare-import-batch",
        "draft-declare-rtpc", "draft-declare-new", "draft-declare-existing", "draft-declare-field-change", "draft-declare-core-plan",
        "draft-revise-declaration", "draft-remove-declaration", "draft-add-media",
        "preview-from-draft", "transaction-show", "confirm", "execute", "verify",
    )
    config = CodexHarnessConfig(
        workspace=workspace, skill_source=options.skill_source, codex_binary=options.codex_binary,
        auth_json=options.auth_json, model=options.model, reasoning_effort=options.reasoning_effort,
        service_tier=options.service_tier, timeout_seconds=600,
        windows_powershell_core_host=options.windows_powershell_core_host,
        expected_gateway_subcommands=allowed_subcommands, expected_wwise_version=unit.version,
        sandbox_mode="workspace-write", allow_output_write=False, network_access=True,
        developer_instructions=semantic_task_developer_instructions(
            options.skill_source / "scripts" / "run.py", task_skill_source=skill_install,
            expected_skill_reads=(("SKILL.md", "references/waapi-operate.md"),),
            expansion_modification_policy=prepared.policy,
        ),
    )
    broker = CodexGatewayBroker(
        skill_source=options.skill_source, invocation_skill_source=skill_install,
        expected_steps=(), expected_wwise_version=unit.version,
        project_modification_policy=prepared.policy, runner_environment=runner_environment,
        working_root=root / "broker", transport="tcp", runner_timeout_seconds=120,
        expansion_outcome_policy=policy,
    )
    cumulative_argvs: list[tuple[str, ...]] = []
    cumulative_command_records: list[CodexCommandRecord] = []
    turn_rows: list[dict[str, Any]] = []
    allowed_references = {"SKILL.md", "references/waapi-operate.md", "references/waapi-query.md",
                          "references/waapi-setup.md", "references/waapi-coverage.md"}
    thread_id = ""
    failure: Exception | None = None
    infrastructure: Mapping[str, Any] | None = None
    try:
        with broker:
            with CodexCliTask(config, extra_env=broker.model_environment_overrides(),
                              agent_case_budget=budget) as task:
                for index, prompt in enumerate(prompts, start=1):
                    policy.begin_turn(index, prompt)
                    output_dir = root / "turns" / f"turn-{index:02d}"
                    elapsed_before = budget.elapsed_seconds
                    try:
                        result = (task.run_initial(prompt, output_dir=output_dir) if index == 1 else
                                  task.run_followup(prompt, output_dir=output_dir))
                    except CodexInfrastructureError as exc:
                        infrastructure = asdict(exc.failure)
                        thread_id = task.thread_id
                        reconciliation = broker.reconcile(cumulative_argvs, require_complete=False)
                        grade = V3TurnGrade(index, _sha256_text(prompt), len(broker.evidence().records),
                            reconciliation, {"completed_turn": False}, (str(exc),))
                        _archive_turn(output_dir, prompt=prompt, result=exc.result, grade=grade)
                        raise
                    thread_id = task.thread_id
                    cumulative_argvs.extend(_gateway_candidate_argvs(
                        result, skill_source=options.skill_source, alternate_skill_sources=(skill_install,),
                        expected_wwise_version=unit.version))
                    reconciliation = broker.reconcile(cumulative_argvs, require_complete=False)
                    facts = result.command_facts
                    references = tuple(facts.skill_read_files)
                    records = facts.command_records
                    effective_count = len(records) - len(recoverable_preprocess_attempt_indexes(records))
                    command_rows = _gateway_candidate_records(result, skill_source=options.skill_source,
                                                              alternate_skill_sources=(skill_install,),
                                                              expected_wwise_version=unit.version)
                    cumulative_command_records.extend(command_rows)
                    reconciliation = _bind_gateway_prefix_reconciliation(
                        reconciliation, command_records=cumulative_command_records,
                        broker_evidence=broker.evidence(),
                        windows_powershell_core_host=task.windows_powershell_core_host,
                        allow_expansion_read_interleaving=True,
                    )
                    gates = {
                        "memory_isolated": result.isolation_audit.passed and not result.prompt_audit.has_memory,
                        "completed_turn": result.exit_status == 0 and not result.timed_out and result.session_audit.passed,
                        "one_target_skill": result.prompt_audit.passed,
                        "no_collaboration": result.collab_call_count == 0,
                        "only_packaged_references": (len(references) <= 12 and set(references).issubset(allowed_references)
                                                      and (index != 1 or bool(references) and references[0] == "SKILL.md")),
                        "only_authenticated_gateway_and_skill_reads": (
                            effective_count == len(command_rows) + len(facts.allowed_read_commands)
                            and not facts.non_gateway_unexpected_commands),
                        "no_discovery_or_direct_waapi": not facts.discovery_commands and not facts.direct_waapi_client_commands,
                        "no_write_like_commands": not facts.write_like_commands,
                        "source_and_workspace_unchanged": (result.file_change_count == 0 and result.skill_tree_unchanged
                            and not result.created_source_files and not result.modified_source_files and not result.deleted_source_files),
                        "broker_provenance": reconciliation.passed,
                        "policy_checkpoint": (policy.transaction.state == "previewed"
                            if prepared.policy == "ask_before_changes" and index == 1 else policy.complete),
                        "visible_preview_notice": (index != 1 or expansion_preview_notice(
                            result, command_rows, version=unit.version,
                            execute_expected=prepared.policy == "allow_changes",
                            preview_artifact=(TransactionStore(broker.state_directory).load_preview(
                                policy.transaction_id).artifact if policy.transaction_id else {}),
                            before_snapshot=prepared.before)),
                        "final_response_present": bool(result.final_response.strip()),
                        "cumulative_agent_budget": budget.elapsed_seconds <= budget.hard_seconds,
                    }
                    grade = V3TurnGrade(index, _sha256_text(prompt), len(broker.evidence().records),
                                        reconciliation, gates, tuple(key for key, passed in gates.items() if not passed))
                    _archive_turn(output_dir, prompt=prompt, result=result, grade=grade)
                    turn_rows.append({"index": index, "gates": gates,
                                      "agent_seconds": budget.elapsed_seconds - elapsed_before})
                    if not grade.passed:
                        raise V3TaskRunnerError("expansion turn failed: " + ", ".join(grade.errors), thread_id=thread_id)
                broker.seal_expansion_outcome()
                final_reconciliation = broker.reconcile(cumulative_argvs)
                if not final_reconciliation.passed:
                    raise V3TaskRunnerError("expansion final Broker reconciliation failed", thread_id=thread_id)
    except Exception as exc:
        failure = exc
    finally:
        if failure is not None:
            # Both contexts have exited: the Broker must reap its runner before
            # independent reads can observe project state. Never retry execute.
            if getattr(broker, "_started", False):
                policy.oracle_evidence["reconciliation"] = {
                    "status": "error", "child_reaped": False, "subprocesses_reaped": False,
                    "seconds": 30, "read_seconds": 10, "elapsed_seconds": 0.0,
                    "error": {"type": "BrokerCleanupUnproven", "message": "Broker runner teardown did not complete"},
                }
            else:
                try:
                    policy.oracle_evidence["reconciliation"] = dict(reconcile_after_failure())
                except Exception as exc:
                    policy.oracle_evidence["reconciliation"] = {
                        "status": "error", "child_reaped": False, "subprocesses_reaped": False,
                        "seconds": 30, "read_seconds": 10, "elapsed_seconds": 0.0,
                        "error": {"type": type(exc).__name__, "message": str(exc).encode("utf-8")[:2048].decode("utf-8", "ignore")},
                    }
        if failure is not None and len(budget.turn_measurements) > len(turn_rows):
            turn_rows.append({"index": len(turn_rows) + 1, "gates": {}, "incomplete": True,
                              "agent_seconds": budget.turn_measurements[-1]["elapsed_seconds"]})
        _write_json(root / "expansion-broker.json", broker.evidence().as_dict(include_output=True))
        _write_json(root / "expansion-oracle.json", policy.oracle_evidence)
        _write_json(root / "expansion-agent-budget.json", {
            "hard_seconds": budget.hard_seconds, "slow_seconds": budget.slow_seconds,
            "elapsed_seconds": budget.elapsed_seconds, "slow": budget.slow, "turns": turn_rows,
            "measurement_scope": "CodexCliTask._record_turn including prompt audit and fresh/resume CLI",
            "turn_measurements": budget.turn_measurements,
        })
        passed = failure is None and policy.complete and broker.evidence().passed
        journal = (TransactionStore(broker.state_directory).read_events(policy.transaction_id)
                   if policy.transaction_id else ())
        status = classify_expansion_outcome(passed=passed,
            records=broker.evidence().as_dict(include_output=True).get("records", ()), events=journal,
            infrastructure=infrastructure)
        reconciliation_receipt = policy.oracle_evidence.get("reconciliation")
        if reconciliation_receipt and (reconciliation_receipt.get("child_reaped") is not True
                or reconciliation_receipt.get("subprocesses_reaped") is not True):
            status = "BLOCKED"
        outcome = {
            "contract": "waapi-skill.integration-expansion-task-result/v1",
            "unit_id": unit.unit_id, "version": unit.version, "thread_id": thread_id,
            "passed": passed, "status": status, "infrastructure": infrastructure,
            "error": None if failure is None else f"{type(failure).__name__}: {failure}",
            "terminal_state": policy.transaction.state,
            "assertions": dict(policy.assertions), "required_assertions": sorted(prepared.required_assertions),
            "gateway_verification_state": policy.transaction.gateway_verification_state,
            "agent_seconds": budget.elapsed_seconds, "slow": budget.slow,
            "plan_sha256": canonical_digest(plan), "turns": turn_rows,
        }
        _write_json(root / "expansion-task-result.json", outcome)
    return outcome


def run_v3_codex_task(
    *,
    scenario_id: str,
    version: str,
    scenario: OnlineScenario,
    prompts: Sequence[str],
    protocol: V3GatewayProtocol,
    task_root: Path,
    skill_source: Path,
    codex_binary: Path,
    auth_json: Path,
    model: str,
    reasoning_effort: str,
    service_tier: str,
    timeout_seconds: float,
    runner_environment: Mapping[str, str],
    required_reference: str | None,
    business_oracle_plan: BusinessOraclePlanEvidence,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
    turn_reference_schedule: Sequence[Sequence[str]] | None = None,
    trusted_subscription_ack: TrustedSubscriptionAckSpec | None = None,
    trusted_subscription_ack_observer: TrustedSubscriptionAckObserver | None = None,
    trusted_step_pre_observer: TrustedStepPreObserver | None = None,
    trusted_step_observer: TrustedStepObserver | None = None,
    turn_observer: TurnObserver | None = None,
    project_modification_policy: str = "ask_before_changes",
    expected_primary_dispatch_count: int | None = None,
    developer_instructions: str = "",
) -> V3TaskRun:
    """Run every natural turn in one exact, memory-isolated Codex thread."""

    prompt_values = tuple(str(prompt) for prompt in prompts)
    if len(prompt_values) != len(protocol.turn_prefix_counts):
        raise V3TaskRunnerError(
            "prompt count must equal protocol turn-boundary count: "
            f"prompts={len(prompt_values)} prefixes={len(protocol.turn_prefix_counts)}"
        )
    expected_skill_reads = _normalize_turn_reference_schedule(
        prompt_count=len(prompt_values),
        required_reference=required_reference,
        turn_reference_schedule=turn_reference_schedule,
    )
    root = Path(task_root).expanduser().resolve(strict=False)
    if (
        root.name != "codex-task"
        or root.parent.name != "evidence"
        or root.parent.parent / "evidence" / PROMPT_PROVENANCE_FILE
        != root.parent / PROMPT_PROVENANCE_FILE
    ):
        raise V3TaskRunnerError(
            "task root must be the fixed scenario_root/evidence/codex-task path"
        )
    if root.exists():
        raise V3TaskRunnerError(f"fresh task root already exists: {root}")
    if scenario.id != scenario_id or version not in scenario.versions:
        raise V3TaskRunnerError("task scenario/version identity is misbound")
    root.mkdir(parents=True, exist_ok=False)
    provenance = read_prompt_provenance(
        root.parent / PROMPT_PROVENANCE_FILE,
        scenario=scenario,
        version=version,
        scenario_root=root.parent.parent,
        expected_prompts=prompt_values,
        expected_protocol=protocol,
        require_paths=True,
    )
    plan_payload = business_oracle_plan.payload
    expected_family = business_family_for_api(str(scenario.api))
    expected_runner = "cli" if expected_family == "cli" else "project"
    primary_dispatch = getattr(scenario, "primary_dispatch", None)
    scenario_primary_count = getattr(primary_dispatch, "count", None)
    expected_primary_count = (
        scenario_primary_count
        if expected_primary_dispatch_count is None
        else expected_primary_dispatch_count
    )
    if (
        business_oracle_plan.path != root.parent / BUSINESS_ORACLE_PLAN_FILE
        or plan_payload.get("scenario_id") != scenario_id
        or plan_payload.get("version") != version
        or plan_payload.get("api") != scenario.api
        or plan_payload.get("runner") != expected_runner
        or plan_payload.get("family") != expected_family
        or plan_payload.get("scenario_root") != str(root.parent.parent)
        or plan_payload.get("protocol_sha256")
        != provenance.payload["protocol"]["sha256"]
        or plan_payload.get("provenance_sha256") != provenance.sha256
        or type(expected_primary_count) is not int
        or expected_primary_count < 0
        or plan_payload.get("primary_dispatch_count") != expected_primary_count
    ):
        raise V3TaskRunnerError(
            "business-oracle plan common identity is not bound to the task"
        )
    try:
        sealed_plan = read_business_oracle_plan_envelope(
            business_oracle_plan.path,
            scenario_id=scenario_id,
            version=version,
            api=str(scenario.api),
            runner=expected_runner,
            family=expected_family,
            scenario_root=root.parent.parent,
            fixture_spec=plan_payload["fixture_spec"],
            protocol_sha256=provenance.payload["protocol"]["sha256"],
            provenance_sha256=provenance.sha256,
            primary_dispatch_count=expected_primary_count,
        )
    except (BusinessOraclePlanError, KeyError, TypeError) as exc:
        raise V3TaskRunnerError(
            f"business-oracle plan cannot be independently re-read: {exc}"
        ) from exc
    if (
        sealed_plan.path != business_oracle_plan.path
        or sealed_plan.sha256 != business_oracle_plan.sha256
        or sealed_plan.payload != business_oracle_plan.payload
    ):
        raise V3TaskRunnerError(
            "business-oracle plan evidence changed before task startup"
        )
    prompt_materialization_path = _archive_prompt_materialization(
        root,
        provenance=provenance,
        business_oracle_plan=sealed_plan,
    )
    workspace = root / "agent-workspace"
    skill_install = _prepare_agent_workspace(workspace, skill_source)
    sealed_developer_instructions = (
        semantic_task_developer_instructions(
            skill_source / "scripts" / "run.py",
            task_skill_source=skill_install,
            expected_skill_reads=expected_skill_reads,
            base_developer_instructions=developer_instructions,
        )
        if developer_instructions
        else ""
    )
    broker_root = root / "broker"
    results: list[CodexRunResult] = []
    grades: list[V3TurnGrade] = []
    cumulative_gateway_argvs: list[tuple[str, ...]] = []
    cumulative_gateway_records: list[CodexCommandRecord] = []
    previous_prefix = 0
    broker_evidence: GatewayBrokerEvidence | None = None
    infrastructure_error: CodexInfrastructureError | None = None

    subcommands = _ordered_unique(step.subcommand for step in protocol.steps)
    gateway_errors = tuple(
        CodexGatewayErrorExpectation(
            command=step.expected_result_command,
            error_code=step.expected_error_code,
        )
        for step in protocol.steps
        if step.allowed_exit_codes == (2,)
    )
    config = CodexHarnessConfig(
        workspace=workspace,
        skill_source=skill_source,
        codex_binary=codex_binary,
        windows_powershell_core_host=windows_powershell_core_host,
        auth_json=auth_json,
        model=model,
        reasoning_effort=reasoning_effort,
        service_tier=service_tier,
        timeout_seconds=timeout_seconds,
        expected_gateway_subcommands=subcommands,
        expected_wwise_version=version,
        sandbox_mode="workspace-write",
        allow_output_write=False,
        network_access=True,
        expected_gateway_errors=gateway_errors,
        developer_instructions=sealed_developer_instructions,
    )
    broker = CodexGatewayBroker(
        skill_source=skill_source,
        invocation_skill_source=skill_install,
        expected_steps=protocol.steps,
        commutative_read_only_step_groups=(
            protocol.commutative_read_only_step_groups
        ),
        commutative_composer_setup_step_groups=(
            protocol.commutative_composer_setup_step_groups
        ),
        optional_topic_schema_step_groups=(
            protocol.optional_topic_schema_step_groups
        ),
        optional_query_schema_step_names=(
            protocol.optional_query_schema_step_names
        ),
        optional_expected_initial_operations_discovery=(
            protocol.optional_initial_operations_discovery
            and not protocol.optional_workflow_operations_discovery_step_names
        ),
        optional_expected_operations_discovery_step_names=(
            protocol.optional_workflow_operations_discovery_step_names
        ),
        optional_expected_workflow_read_step_names=(
            protocol.optional_workflow_query_schema_step_names
            + protocol.optional_workflow_revalidation_step_names
        ),
        expected_wwise_version=version,
        project_modification_policy=project_modification_policy,
        runner_environment=runner_environment,
        working_root=broker_root,
        transport="tcp",
        runner_timeout_seconds=max(120.0, timeout_seconds),
        trusted_step_pre_observer=trusted_step_pre_observer,
        trusted_step_observer=trusted_step_observer,
        trusted_subscription_ack=trusted_subscription_ack,
        trusted_subscription_ack_observer=trusted_subscription_ack_observer,
        optional_initial_query_schema=(
            protocol.optional_initial_query_schema
            and not protocol.optional_query_schema_step_names
        ),
    )
    try:
        with broker:
            with CodexCliTask(config, extra_env=broker.model_environment_overrides()) as task:
                for turn_index, (prompt, expected_prefix) in enumerate(
                    zip(prompt_values, protocol.turn_prefix_counts, strict=True),
                    start=1,
                ):
                    output_dir = root / "turns" / f"turn-{turn_index:02d}"
                    try:
                        result = (
                            task.run_initial(prompt, output_dir=output_dir)
                            if turn_index == 1
                            else task.run_followup(prompt, output_dir=output_dir)
                        )
                    except CodexInfrastructureError as exc:
                        # Snapshot the trusted broker before either context is
                        # allowed to unwind.  A failed archive is deliberately
                        # not suppressed: without complete fixed-path evidence,
                        # the caller must not treat this task as retryable.
                        failure_broker_evidence = broker.evidence()
                        _validate_infrastructure_failure(
                            prompt=prompt,
                            result=exc.result,
                            failure=exc.failure,
                            broker_evidence=failure_broker_evidence,
                            expected_step_names=tuple(
                                step.name for step in protocol.steps
                            ),
                            previous_broker_prefix=previous_prefix,
                            allow_complete_prefix_failure=(
                                bool(protocol.allowed_turn_prefix_counts)
                                and previous_prefix == len(protocol.steps)
                                and expected_prefix == previous_prefix
                            ),
                        )
                        _archive_infrastructure_failure(
                            root,
                            output_dir=output_dir,
                            scenario_id=scenario_id,
                            version=version,
                            turn_index=turn_index,
                            expected_turn_count=len(prompt_values),
                            prior_completed_turn_count=len(results),
                            previous_broker_prefix=previous_prefix,
                            expected_failed_turn_prefix=expected_prefix,
                            prior_thread_id=(results[0].thread_id if results else None),
                            prompt=prompt,
                            result=exc.result,
                            failure=exc.failure,
                            broker_evidence=failure_broker_evidence,
                            prompt_materialization_path=prompt_materialization_path,
                        )
                        infrastructure_error = exc
                        break
                    if _exhausted_windows_267_after_only_skill_read(
                        result,
                        broker_evidence=broker.evidence(),
                        previous_broker_prefix=previous_prefix,
                    ):
                        raise V3CommandLifecycleError(
                            "native Windows exhausted its one permitted identical "
                            "CreateProcessAsUserW 267 retry after only the sealed "
                            "Skill read; no Gateway or Wwise command ran"
                        )
                    results.append(result)
                    turn_gateway = _gateway_candidate_argvs(
                        result,
                        skill_source=skill_install,
                        alternate_skill_sources=(skill_source,),
                        expected_wwise_version=version,
                    )
                    turn_gateway_records = _gateway_candidate_records(
                        result,
                        skill_source=skill_install,
                        alternate_skill_sources=(skill_source,),
                        expected_wwise_version=version,
                    )
                    cumulative_gateway_argvs.extend(turn_gateway)
                    cumulative_gateway_records.extend(turn_gateway_records)
                    broker_evidence = broker.evidence()
                    terminal_indeterminate = bool(
                        getattr(broker_evidence, "terminal_indeterminate", False)
                    )
                    actual_prefix = len(broker_evidence.consumed_step_names)
                    allowed_prefixes = protocol.allowed_prefixes_for_turn(
                        turn_index
                    )
                    effective_prefix = (
                        actual_prefix
                        if terminal_indeterminate
                        or protocol.allowed_turn_prefix_counts
                        else expected_prefix
                    )
                    prefix_errors: list[str] = []
                    if (
                        not terminal_indeterminate
                        and effective_prefix not in allowed_prefixes
                    ):
                        prefix_errors.append(
                            "broker prefix is outside the allowed turn choices: "
                            f"observed={effective_prefix} allowed={allowed_prefixes!r}"
                        )
                    if effective_prefix < previous_prefix:
                        prefix_errors.append(
                            "broker prefix moved backwards across Codex turns"
                        )
                    if effective_prefix < 1:
                        reconciliation = GatewayBrokerReconciliation(
                            passed=False,
                            observed_command_count=len(cumulative_gateway_argvs),
                            accepted_record_count=len(
                                broker_evidence.accepted_records
                            ),
                            errors=tuple(
                                prefix_errors
                                or ("broker consumed no expected gateway step",)
                            ),
                        )
                    else:
                        raw_reconciliation = broker.reconcile_prefix(
                            cumulative_gateway_argvs,
                            expected_step_count=effective_prefix,
                        )
                        reconciliation = _bind_gateway_prefix_reconciliation(
                            raw_reconciliation,
                            command_records=cumulative_gateway_records,
                            broker_evidence=broker_evidence,
                            prefix_errors=prefix_errors,
                            windows_powershell_core_host=(
                                windows_powershell_core_host
                            ),
                        )
                    terminal_execute_exit2_count = _terminal_execute_exit2_count(
                        protocol,
                        broker_evidence,
                        start=previous_prefix,
                        stop=effective_prefix,
                    )
                    errors, gates = _grade_common_turn(
                        result,
                        turn_index=turn_index,
                        required_reference=required_reference,
                        expected_skill_reads=expected_skill_reads[
                            turn_index - 1
                        ],
                        previous_skill_reads=tuple(
                            read_file
                            for previous_result in results[:-1]
                            for read_file in previous_result.command_facts.skill_read_files
                        ),
                        expected_gateway_count=effective_prefix - previous_prefix,
                        expected_terminal_execute_exit2_count=(
                            terminal_execute_exit2_count
                        ),
                        prompt_provenance=provenance,
                    )
                    grade = V3TurnGrade(
                        index=turn_index,
                        prompt_sha256=_sha256_text(prompt),
                        broker_prefix_count=effective_prefix,
                        reconciliation=reconciliation,
                        common_gates=gates,
                        errors=errors,
                    )
                    grades.append(grade)
                    _archive_turn(output_dir, prompt=prompt, result=result, grade=grade)
                    if result.session_audit.incomplete_command_count:
                        _archive_command_lifecycle_failure(
                            root,
                            output_dir=output_dir,
                            scenario_id=scenario_id,
                            version=version,
                            turn_index=turn_index,
                            expected_turn_count=len(prompt_values),
                            prompt=prompt,
                            result=result,
                            broker_evidence=broker_evidence,
                        )
                        raise V3CommandLifecycleError(
                            f"{scenario_id} turn {turn_index} ended with "
                            f"{result.session_audit.incomplete_command_count} "
                            "incomplete Codex command lifecycle item(s); the "
                            "scenario is blocked and must use a fresh sandbox"
                        )
                    if not grade.passed:
                        common_failures = errors or tuple(
                            key for key, value in gates.items() if not value
                        )
                        _archive_task_gate_failure(
                            root,
                            scenario_id=scenario_id,
                            version=version,
                            failed_turn_index=turn_index,
                            expected_turn_count=len(prompt_values),
                            thread_id=result.thread_id,
                            grade=grade,
                            broker_evidence=broker_evidence,
                            prompt_materialization_path=(
                                prompt_materialization_path
                            ),
                            gateway_failure_stage=(
                                _composer_failure_stage(
                                    protocol,
                                    broker_evidence,
                                )
                            ),
                        )
                        raise V3TaskRunnerError(
                            f"{scenario_id} turn {turn_index} failed task gates: "
                            f"common={common_failures}; "
                            f"reconciliation={grade.reconciliation.errors}",
                            thread_id=result.thread_id,
                        )
                    if turn_observer is not None:
                        turn_observer(turn_index, result, broker_evidence)
                    previous_prefix = effective_prefix
                    if terminal_indeterminate:
                        break
            if infrastructure_error is None:
                broker_evidence = broker.evidence()
        if infrastructure_error is not None:
            raise infrastructure_error
    finally:
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=False)

    if broker_evidence is None:
        raise V3TaskRunnerError("fresh task completed without broker evidence")
    run = V3TaskRun(
        scenario_id=scenario_id,
        version=version,
        task_root=root,
        thread_id=results[0].thread_id if results else "",
        turns=tuple(results),
        turn_grades=tuple(grades),
        broker_evidence=broker_evidence,
        broker_protocol_passed=_broker_terminal_protocol_passed(
            protocol,
            broker_evidence,
        ),
    )
    task_result = {
        "contract": TASK_RESULT_CONTRACT,
        "scenario_id": scenario_id,
        "version": version,
        "thread_id": run.thread_id,
        "turn_count": len(run.turns),
        "passed": run.passed,
        "prompt_materialization_sha256": _sha256_file(
            prompt_materialization_path
        ),
        "broker": run.broker_evidence.as_dict(include_output=False),
        "turn_grades": [
            {
                **asdict(item),
                "passed": item.passed,
            }
            for item in run.turn_grades
        ],
    }
    if any(
        step.subcommand.startswith("draft-")
        or step.subcommand == "preview-from-draft"
        for step in protocol.steps
    ):
        broker_payload = run.broker_evidence.as_dict(include_output=False)
        broker_records = broker_payload["records"]
        steps_by_name = {step.name: step for step in protocol.steps}
        try:
            composer_evidence = validate_typed_draft_evidence(
                state_directory=root / "broker" / "state",
                steps=tuple(
                    steps_by_name[str(record["step_name"])]
                    for record in broker_records
                ),
                broker_records=broker_records,
            )
        except (TypedDraftEvidenceError, KeyError) as exc:
            raise V3TaskRunnerError(
                f"Composer task evidence cannot be sealed: {exc}",
                thread_id=run.thread_id,
            ) from exc
        if composer_evidence is None:
            raise V3TaskRunnerError(
                "Composer protocol completed without Composer evidence",
                thread_id=run.thread_id,
            )
        task_result["composer_evidence"] = composer_evidence
    if protocol.allowed_turn_prefix_counts:
        task_result["protocol_terminal_passed"] = run.broker_protocol_passed
        task_result["accepted_terminal_prefixes"] = list(
            protocol.accepted_terminal_prefixes
        )
    _write_json(root / "task-result.json", task_result)
    return run


def _selected_workflow_step_names_are_closed(
    protocol: Any,
    selected_names: Sequence[str],
    *,
    optional_names: set[str],
) -> bool:
    """Validate optional routing plus Broker-proven 1..6-row import chunks."""

    by_name = {step.name: step for step in protocol.steps}
    if (
        len(selected_names) != len(set(selected_names))
        or any(name not in by_name for name in selected_names)
    ):
        return False
    selected_set = set(selected_names)
    canonical_selected: list[str] = []
    rebatched_regions: list[tuple[int, tuple[str, ...], tuple[str, ...]]] = []
    protocol_cursor = 0
    while protocol_cursor < len(protocol.steps):
        step = protocol.steps[protocol_cursor]
        if step.name in optional_names:
            if step.name in selected_set:
                canonical_selected.append(step.name)
            protocol_cursor += 1
            continue
        if step.subcommand != "draft-declare-import-batch":
            if step.name not in selected_set:
                return False
            canonical_selected.append(step.name)
            protocol_cursor += 1
            continue
        block: list[str] = []
        while (
            protocol_cursor < len(protocol.steps)
            and protocol.steps[protocol_cursor].subcommand
            == "draft-declare-import-batch"
        ):
            block.append(protocol.steps[protocol_cursor].name)
            protocol_cursor += 1
        selected_block = tuple(name for name in block if name in selected_set)
        selected_count = len(selected_block)
        minimum_chunks = (
            len(block) + AUDIO_IMPORT_BUSINESS_BATCH_MAX_ROWS - 1
        ) // AUDIO_IMPORT_BUSINESS_BATCH_MAX_ROWS
        if not minimum_chunks <= selected_count <= len(block):
            return False
        if selected_block != tuple(block[:selected_count]):
            return False

        transaction_prefix = step.name.split(".", 1)[0]
        setup_start = len(canonical_selected)
        while setup_start > 0:
            setup_name = canonical_selected[setup_start - 1]
            if business_draft_setup_step_prefix(setup_name) != transaction_prefix:
                break
            setup_start -= 1
        setup_names = tuple(canonical_selected[setup_start:])
        region_start = setup_start
        canonical_selected.extend(selected_block)
        if setup_names:
            rebatched_regions.append(
                (region_start, setup_names, selected_block)
            )

    if set(canonical_selected) != selected_set:
        return False

    normalized = list(selected_names)
    for start, setup_names, declaration_names in rebatched_regions:
        canonical_region = (*setup_names, *declaration_names)
        width = len(canonical_region)
        actual_region = tuple(normalized[start : start + width])
        allowed_regions = {
            (
                *setup_names[:split],
                declaration_names[0],
                *setup_names[split:],
                *declaration_names[1:],
            )
            for split in range(len(setup_names) + 1)
        }
        if actual_region not in allowed_regions:
            continue
        normalized[start : start + width] = canonical_region
    return tuple(normalized) == tuple(canonical_selected)


def _broker_terminal_protocol_passed(
    protocol: V3GatewayProtocol,
    evidence: GatewayBrokerEvidence,
) -> bool:
    """Accept only one sealed complete protocol or declared optional prefix."""

    consumed_count = len(evidence.consumed_step_names)
    if consumed_count not in protocol.accepted_terminal_prefixes:
        return False

    def selected_lane_passed(selected_names: Sequence[str]) -> bool:
        read_groups = getattr(protocol, "commutative_read_only_step_groups", ())
        setup_groups = getattr(
            protocol,
            "commutative_composer_setup_step_groups",
            (),
        )
        return bool(
            gateway_step_sequence_matches(
                selected_names,
                evidence.consumed_step_names,
                read_groups,
                setup_groups,
            )
            and getattr(evidence, "commutative_read_only_step_groups", ())
            == read_groups
            and getattr(
                evidence,
                "commutative_composer_setup_step_groups",
                (),
            )
            == setup_groups
            and len(evidence.records) == len(selected_names)
            and tuple(record.step_name for record in evidence.records)
            == evidence.consumed_step_names
            and not evidence.rejected_records
            and all(record.succeeded for record in evidence.records)
            and evidence.complete
            and evidence.passed
            and evidence.terminal_state == "COMPLETE"
        )
    if protocol.optional_query_schema_step_names:
        protocol_names = tuple(step.name for step in protocol.steps)
        optional_names = set(protocol.optional_query_schema_step_names)
        selected_names = evidence.expected_step_names
        if (
            not selected_names
            or selected_names[-1] != protocol_names[-1]
            or any(name not in optional_names for name in selected_names[:-1])
            or len(selected_names) != len(set(selected_names))
        ):
            return False
        return selected_lane_passed(selected_names)
    if protocol.optional_initial_query_schema:
        protocol_names = tuple(step.name for step in protocol.steps)
        selected_names = evidence.expected_step_names
        if selected_names not in {protocol_names, protocol_names[1:]}:
            return False
        return selected_lane_passed(selected_names)
    optional_workflow_operations = getattr(
        protocol,
        "optional_workflow_operations_discovery_step_names",
        (),
    )
    optional_workflow_query_schema = getattr(
        protocol,
        "optional_workflow_query_schema_step_names",
        (),
    )
    optional_workflow_revalidation = getattr(
        protocol,
        "optional_workflow_revalidation_step_names",
        (),
    )
    if (
        optional_workflow_operations
        or optional_workflow_query_schema
        or optional_workflow_revalidation
    ):
        optional_names = {
            *optional_workflow_operations,
            *optional_workflow_query_schema,
            *optional_workflow_revalidation,
        }
        selected_names = evidence.expected_step_names
        if not _selected_workflow_step_names_are_closed(
            protocol,
            selected_names,
            optional_names=optional_names,
        ):
            return False
        return selected_lane_passed(selected_names)
    if protocol.optional_initial_operations_discovery:
        protocol_names = tuple(step.name for step in protocol.steps)
        selected_names = evidence.expected_step_names
        if selected_names not in {protocol_names, protocol_names[1:]}:
            return False
        return selected_lane_passed(selected_names)
    if protocol.optional_topic_schema_step_groups:
        protocol_names = tuple(step.name for step in protocol.steps)
        optional_names = {
            name
            for group in protocol.optional_topic_schema_step_groups
            for name in group
        }
        selected_names = evidence.expected_step_names
        selected_optional = tuple(
            name for name in selected_names if name in optional_names
        )
        mandatory_names = tuple(
            name for name in protocol_names if name not in optional_names
        )
        if (
            tuple(name for name in selected_names if name not in optional_names)
            != mandatory_names
            or len(selected_names) != len(set(selected_names))
            or any(name not in protocol_names for name in selected_names)
            or any(name not in optional_names for name in selected_optional)
        ):
            return False
        return selected_lane_passed(selected_names)
    expected_names = tuple(
        step.name for step in protocol.steps[:consumed_count]
    )
    if (
        evidence.commutative_read_only_step_groups
        != protocol.commutative_read_only_step_groups
        or evidence.commutative_composer_setup_step_groups
        != protocol.commutative_composer_setup_step_groups
        or not gateway_step_sequence_matches(
            expected_names,
            evidence.consumed_step_names,
            protocol.commutative_read_only_step_groups,
            protocol.commutative_composer_setup_step_groups,
        )
        or len(evidence.records) != consumed_count
        or tuple(record.step_name for record in evidence.records)
        != evidence.consumed_step_names
        or evidence.rejected_records
        or not all(record.succeeded for record in evidence.records)
    ):
        return False
    return bool(
        evidence.passed
        and evidence.complete
        and evidence.terminal_state == "COMPLETE"
    )


def _grade_common_turn(
    result: CodexRunResult,
    *,
    turn_index: int,
    required_reference: str | None,
    expected_skill_reads: Sequence[str] | None = None,
    previous_skill_reads: Sequence[str] = (),
    expected_gateway_count: int,
    expected_terminal_execute_exit2_count: int = 0,
    prompt_provenance: Any | None = None,
) -> tuple[tuple[str, ...], dict[str, bool]]:
    facts = result.command_facts
    allowed_reads = tuple(facts.allowed_read_commands)
    read_files = tuple(facts.skill_read_files)
    expected_reads = (
        tuple(expected_skill_reads)
        if expected_skill_reads is not None
        else (
            (
                ("SKILL.md", required_reference)
                if required_reference is not None
                else ("SKILL.md",)
            )
            if turn_index == 1
            else ()
        )
    )
    expected_reads = _effective_expected_skill_reads(
        expected_reads,
        previous_skill_reads=previous_skill_reads,
    )
    records = facts.command_records
    recoverable_read_indexes = frozenset(
        recoverable_preprocess_attempt_indexes(records)
    )
    effective_records = tuple(
        record
        for index, record in enumerate(records)
        if index not in recoverable_read_indexes
    )
    gateway_count = len(facts.gateway_attempt_commands)
    try:
        prompt_asset_reads = validated_prompt_asset_cat_commands(
            records,
            provenance=prompt_provenance,
            turn_index=turn_index,
        )
    except PromptAssetReadError:
        prompt_asset_reads = ()
    terminal_unexpected = remove_validated_command_occurrences(
        facts.unexpected_commands,
        prompt_asset_reads,
    )
    non_gateway_unexpected = remove_validated_command_occurrences(
        facts.non_gateway_unexpected_commands,
        prompt_asset_reads,
    )
    expected_terminal_unexpected = (
        len(terminal_unexpected) == expected_terminal_execute_exit2_count
        and all(
            command in facts.gateway_attempt_commands
            for command in terminal_unexpected
        )
    )
    gates = {
        "memory_isolated": result.isolation_audit.passed and not result.prompt_audit.has_memory,
        "one_completed_turn": (
            result.exit_status == 0
            and not result.timed_out
            and result.session_audit.passed
            and result.file_change_count == 0
        ),
        "one_target_skill": result.prompt_audit.passed,
        "no_collaboration": result.collab_call_count == 0,
        "skill_reads_exact": _skill_reads_pass_gate(
            expected_reads=expected_reads,
            read_files=read_files,
            allowed_reads=allowed_reads,
        ),
        "read_prefix_exact": _read_prefix_pass_gate(
            records=effective_records,
            allowed_reads=allowed_reads,
            gateway_attempt_commands=facts.gateway_attempt_commands,
            gateway_subcommands=getattr(facts, "gateway_subcommands", ()),
            expected_reads=expected_reads,
        ),
        "gateway_count_exact": gateway_count == expected_gateway_count,
        "no_other_commands": (
            len(effective_records)
            == len(allowed_reads)
            + len(prompt_asset_reads)
            + expected_gateway_count
        ),
        "no_discovery": not facts.discovery_commands,
        "no_direct_waapi": not facts.direct_waapi_client_commands,
        "no_write_like": not facts.write_like_commands,
        "no_unexpected_commands": (
            expected_terminal_unexpected
            and not non_gateway_unexpected
        ),
        "no_files_changed": (
            not result.created_files
            and not result.modified_files
            and not result.deleted_files
            and not result.created_source_files
            and not result.modified_source_files
            and not result.deleted_source_files
            and result.skill_tree_unchanged
        ),
    }
    errors = tuple(key for key, value in gates.items() if not value)
    return errors, gates


def _skill_reads_pass_gate(
    *,
    expected_reads: Sequence[str],
    read_files: Sequence[str],
    allowed_reads: Sequence[str],
) -> bool:
    """Keep historical gate compatibility while softening one harmless preload.

    The task prompt and Skill still require exact progressive disclosure.  A
    query-first task may nevertheless preload the operate reference once,
    immediately after the query reference.  This spends context but neither
    dispatches a command nor weakens the read-only boundary, so public business
    acceptance records it diagnostically instead of failing an otherwise exact
    Wwise workflow.
    """

    expected = tuple(expected_reads)
    observed = tuple(read_files)
    if len(allowed_reads) != len(observed):
        return False
    if observed == expected:
        return True
    return (
        expected == ("SKILL.md", "references/waapi-query.md")
        and observed
        == (
            "SKILL.md",
            "references/waapi-query.md",
            "references/waapi-operate.md",
        )
    )


def _effective_expected_skill_reads(
    expected_reads: Sequence[str],
    *,
    previous_skill_reads: Sequence[str],
) -> tuple[str, ...]:
    """Remove a safely preloaded reference from its later scheduled turn."""

    seen = frozenset(previous_skill_reads)
    return tuple(read_file for read_file in expected_reads if read_file not in seen)


def _read_prefix_pass_gate(
    *,
    records: Sequence[Any],
    allowed_reads: Sequence[str],
    gateway_attempt_commands: Sequence[str],
    gateway_subcommands: Sequence[str],
    expected_reads: Sequence[str],
) -> bool:
    """Allow selected exact-ID readbacks immediately before the operate lane."""

    record_commands = tuple(record.command for record in records)
    reads = tuple(allowed_reads)
    if record_commands[: len(reads)] == reads:
        return True
    if (
        tuple(expected_reads) != ("references/waapi-operate.md",)
        or len(reads) != 1
    ):
        return False
    try:
        read_index = record_commands.index(reads[0])
    except ValueError:
        return False
    gateway_commands = tuple(gateway_attempt_commands)
    subcommands = tuple(gateway_subcommands)
    return (
        read_index > 0
        and record_commands[:read_index] == gateway_commands[:read_index]
        and len(subcommands) >= read_index
        and all(
            subcommand == "query-object"
            for subcommand in subcommands[:read_index]
        )
    )


def _normalize_turn_reference_schedule(
    *,
    prompt_count: int,
    required_reference: str | None,
    turn_reference_schedule: Sequence[Sequence[str]] | None,
) -> tuple[tuple[str, ...], ...]:
    """Close per-turn lane reads while preserving the historical default.

    Callers schedule lane references only.  The runner owns the mandatory
    initial ``SKILL.md`` read, so it cannot be moved to a resumed turn or
    accidentally omitted.  A lane reference may appear at most once in the
    task, matching the Skill's conversation-scoped read contract.
    """

    if type(prompt_count) is not int or prompt_count < 1:
        raise V3TaskRunnerError("prompt_count must be a positive integer")
    if required_reference is not None and (
        not isinstance(required_reference, str)
        or required_reference not in _PACKAGED_LANE_REFERENCES
    ):
        raise V3TaskRunnerError(
            "required_reference must be one packaged waapi lane reference or None"
        )
    if required_reference is None:
        if turn_reference_schedule is not None:
            raise V3TaskRunnerError(
                "a SKILL-only task must not schedule lane references"
            )
        reference_rows = ((),) * prompt_count
        return (("SKILL.md",), *reference_rows[1:])
    if turn_reference_schedule is None:
        reference_rows: tuple[tuple[str, ...], ...] = (
            ((required_reference,),) + ((),) * (prompt_count - 1)
        )
    else:
        if isinstance(turn_reference_schedule, (str, bytes)):
            raise V3TaskRunnerError(
                "turn_reference_schedule must contain one row per prompt"
            )
        try:
            schedule_length = len(turn_reference_schedule)
        except TypeError as exc:
            raise V3TaskRunnerError(
                "turn_reference_schedule must contain one row per prompt"
            ) from exc
        if schedule_length != prompt_count:
            raise V3TaskRunnerError(
                "turn_reference_schedule must contain one row per prompt"
            )
        normalized_rows: list[tuple[str, ...]] = []
        seen: set[str] = set()
        for turn_index, raw_row in enumerate(turn_reference_schedule, start=1):
            if isinstance(raw_row, (str, bytes)):
                raise V3TaskRunnerError(
                    "turn_reference_schedule rows must be reference sequences"
                )
            try:
                row = tuple(raw_row)
            except TypeError as exc:
                raise V3TaskRunnerError(
                    "turn_reference_schedule rows must be reference sequences"
                ) from exc
            max_references = 2 if turn_index == 1 else 1
            if len(row) > max_references:
                raise V3TaskRunnerError(
                    "turn 1 may read at most two reviewed lane references; "
                    "later turns may read at most one"
                )
            for reference in row:
                if (
                    not isinstance(reference, str)
                    or reference not in _PACKAGED_LANE_REFERENCES
                ):
                    raise V3TaskRunnerError(
                        "turn_reference_schedule contains an unreviewed reference"
                    )
                if reference in seen:
                    raise V3TaskRunnerError(
                        "a waapi lane reference may be read only once per task"
                    )
                seen.add(reference)
            normalized_rows.append(row)
        reference_rows = tuple(normalized_rows)
        if not reference_rows[0] or reference_rows[0][0] != required_reference:
            raise V3TaskRunnerError(
                "turn 1 must begin with the required_reference lane"
            )
    return (
        ("SKILL.md", *reference_rows[0]),
        *reference_rows[1:],
    )


def _terminal_execute_exit2_count(
    protocol: V3GatewayProtocol,
    evidence: GatewayBrokerEvidence,
    *,
    start: int,
    stop: int,
) -> int:
    expected = {
        step.name
        for step in protocol.steps[start:stop]
        if step.subcommand == "execute" and step.allowed_exit_codes == (0, 2)
    }
    if not expected:
        return 0
    records = {
        record.step_name: record
        for record in evidence.records
        if record.step_name in expected
    }
    return sum(
        record.succeeded and record.runner_exit_code == 2
        for record in records.values()
    )


def _gateway_candidate_argvs(
    result: CodexRunResult,
    *,
    skill_source: Path,
    alternate_skill_sources: Sequence[Path] = (),
    expected_wwise_version: str,
) -> tuple[tuple[str, ...], ...]:
    expected_runners = tuple(dict.fromkeys(
        os.path.abspath(os.fspath(source / "scripts" / "run.py"))
        for source in (skill_source, *alternate_skill_sources)
    ))
    records = result.command_facts.command_records
    recoverable_indexes = frozenset(
        recoverable_preprocess_attempt_indexes(records)
    )
    candidates: list[tuple[str, ...]] = []
    for index, record in enumerate(records):
        if index in recoverable_indexes:
            continue
        argv = normalized_gateway_command_argv(
            record.argv,
            expected_wwise_version=expected_wwise_version,
        )
        runner = _candidate_runner_path(argv, expected_runners=expected_runners)
        if runner is not None:
            candidates.append((argv[0], runner, *argv[2:]))
    return tuple(candidates)


def _exhausted_windows_267_after_only_skill_read(
    result: CodexRunResult,
    *,
    broker_evidence: GatewayBrokerEvidence,
    previous_broker_prefix: int,
) -> bool:
    """Recognize one exact post-Skill Windows process-launch exhaustion.

    This narrow shape contains no semantic Gateway evidence: the Skill read
    succeeded, one later PowerShell command failed to start twice with the
    permitted identical 267 retry, and nothing reached the Broker or Wwise.
    """

    facts = result.command_facts
    records = tuple(facts.command_records)
    if (
        previous_broker_prefix != 0
        or broker_evidence.records
        or broker_evidence.consumed_step_names
        or facts.skill_read is not True
        or facts.skill_read_files != ("SKILL.md",)
        or facts.gateway_commands
        or facts.gateway_attempt_commands
        or result.collab_call_count != 0
        or result.file_change_count != 0
        or len(records) != 3
    ):
        return False
    first, first_failure, second_failure = records
    return (
        getattr(first, "status", "") == "completed"
        and getattr(first, "exit_code", None) == 0
        and getattr(first_failure, "command", "")
        == getattr(second_failure, "command", "")
        and getattr(first_failure, "argv", ())
        == getattr(second_failure, "argv", ())
        and all(
            getattr(record, "status", "") == "failed"
            and getattr(record, "exit_code", None) == -1
            and getattr(record, "parser_kind", "") == "windows-pwsh-command"
            and not getattr(record, "parse_error", "")
            and not getattr(record, "has_shell_operators", False)
            and "CreateProcessAsUserW failed: 267"
            in getattr(record, "aggregated_output", "")
            for record in (first_failure, second_failure)
        )
    )


def _gateway_candidate_records(
    result: CodexRunResult,
    *,
    skill_source: Path,
    alternate_skill_sources: Sequence[Path] = (),
    expected_wwise_version: str,
) -> tuple[CodexCommandRecord, ...]:
    """Keep raw Codex records for response-derived continuation binding."""

    expected_runners = tuple(dict.fromkeys(
        os.path.abspath(os.fspath(source / "scripts" / "run.py"))
        for source in (skill_source, *alternate_skill_sources)
    ))
    records = result.command_facts.command_records
    recoverable_indexes = frozenset(
        recoverable_preprocess_attempt_indexes(records)
    )
    candidates: list[CodexCommandRecord] = []
    for index, record in enumerate(records):
        if index in recoverable_indexes:
            continue
        argv = normalized_gateway_command_argv(
            record.argv,
            expected_wwise_version=expected_wwise_version,
        )
        if _candidate_runner_path(argv, expected_runners=expected_runners) is not None:
            candidates.append(record)
    return tuple(candidates)


def _candidate_runner_path(
    argv: Sequence[str],
    *,
    expected_runners: Sequence[str],
) -> str | None:
    if len(argv) < 4 or argv[2] != "gateway.py":
        return None
    supplied = Path(argv[1]).expanduser()
    if supplied.is_absolute():
        normalized = os.path.abspath(os.fspath(supplied))
        return normalized if normalized in expected_runners else None
    return next(
        (
            expected
            for expected in expected_runners
            if task_local_runner_matches_normalized(argv[1], expected)
        ),
        None,
    )


def _bind_gateway_prefix_reconciliation(
    raw_reconciliation: GatewayBrokerReconciliation,
    *,
    command_records: Sequence[CodexCommandRecord],
    broker_evidence: GatewayBrokerEvidence,
    prefix_errors: Sequence[str] = (),
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
    platform_name: str | None = None,
    allow_expansion_read_interleaving: bool = False,
) -> GatewayBrokerReconciliation:
    """Add exact response-derived command binding to argv reconciliation."""

    continuation_errors = gateway_continuation_binding_errors(
        command_records,
        broker_evidence.accepted_records,
        platform_name=platform_name,
        windows_powershell_core_host=windows_powershell_core_host,
        allow_expansion_read_interleaving=allow_expansion_read_interleaving and raw_reconciliation.passed,
    )
    return GatewayBrokerReconciliation(
        passed=(
            raw_reconciliation.passed
            and not prefix_errors
            and not continuation_errors
        ),
        observed_command_count=raw_reconciliation.observed_command_count,
        accepted_record_count=raw_reconciliation.accepted_record_count,
        errors=(
            *raw_reconciliation.errors,
            *prefix_errors,
            *continuation_errors,
        ),
    )


def _prepare_agent_workspace(
    workspace: Path,
    skill_source: Path,
    *,
    platform_name: str | None = None,
) -> Path:
    return prepare_workspace_skill_install(
        workspace,
        skill_source,
        platform_name=platform_name,
    )


def _archive_turn(
    output_dir: Path,
    *,
    prompt: str,
    result: CodexRunResult,
    grade: V3TurnGrade,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_utf8_text_bytes(output_dir / "prompt.txt", prompt + "\n")
    write_utf8_text_bytes(output_dir / "events.jsonl", result.stdout)
    write_utf8_text_bytes(output_dir / "stderr.txt", result.stderr)
    write_utf8_text_bytes(output_dir / "final.txt", result.final_response + "\n")
    _write_json(output_dir / "codex-facts.json", result.facts_dict())
    _write_json(
        output_dir / "turn-grade.json",
        {**asdict(grade), "passed": grade.passed},
    )


def _archive_command_lifecycle_failure(
    root: Path,
    *,
    output_dir: Path,
    scenario_id: str,
    version: str,
    turn_index: int,
    expected_turn_count: int,
    prompt: str,
    result: CodexRunResult,
    broker_evidence: GatewayBrokerEvidence,
) -> None:
    """Seal an unmatched Codex command lifecycle as non-retryable BLOCKED.

    The command may already have affected the disposable Wwise sandbox, so
    this is intentionally distinct from the pre-agent infrastructure contract.
    The caller must quarantine the scenario and start a fresh lifecycle.
    """

    anomalies = _command_lifecycle_anomalies(result.stdout)
    if not anomalies:
        raise V3TaskRunnerError(
            "incomplete command count cannot be reconstructed from Codex events"
        )
    broker_path = root / "command-lifecycle-broker-evidence.json"
    _write_json(broker_path, broker_evidence.as_dict(include_output=False))
    artifact_paths = (
        output_dir / "prompt.txt",
        output_dir / "events.jsonl",
        output_dir / "stderr.txt",
        output_dir / "final.txt",
        output_dir / "codex-facts.json",
        output_dir / "turn-grade.json",
        broker_path,
    )
    _write_json(
        root / "command-lifecycle-failure.json",
        {
            "contract": TASK_COMMAND_LIFECYCLE_FAILURE_CONTRACT,
            "scenario_id": scenario_id,
            "version": version,
            "failed_turn_index": turn_index,
            "expected_turn_count": expected_turn_count,
            "prompt_sha256": _sha256_text(prompt),
            "incomplete_command_count": (
                result.session_audit.incomplete_command_count
            ),
            "anomalies": anomalies,
            "non_retryable": True,
            "fresh_sandbox_required": True,
            "artifact_sha256": {
                path.relative_to(root).as_posix(): _sha256_file(path)
                for path in artifact_paths
            },
        },
    )


def _archive_task_gate_failure(
    root: Path,
    *,
    scenario_id: str,
    version: str,
    failed_turn_index: int,
    expected_turn_count: int,
    thread_id: str,
    grade: V3TurnGrade,
    broker_evidence: GatewayBrokerEvidence,
    prompt_materialization_path: Path,
    gateway_failure_stage: str | None = None,
) -> None:
    """Archive bounded diagnostics without changing the semantic verdict."""

    broker_path = root / "task-gate-broker-evidence.json"
    _write_json(broker_path, broker_evidence.as_dict(include_output=False))
    turn_artifacts = tuple(
        root / "turns" / f"turn-{index:02d}" / filename
        for index in range(1, failed_turn_index + 1)
        for filename in (
            "prompt.txt",
            "events.jsonl",
            "stderr.txt",
            "final.txt",
            "codex-facts.json",
            "turn-grade.json",
        )
    )
    artifact_paths = (
        prompt_materialization_path,
        *turn_artifacts,
        broker_path,
    )
    missing = tuple(
        path.relative_to(root).as_posix()
        for path in artifact_paths
        if not path.is_file()
    )
    if missing:
        raise V3TaskRunnerError(
            "task-gate diagnostic archive is incomplete: " + ", ".join(missing)
        )
    payload = {
        "contract": TASK_GATE_FAILURE_CONTRACT,
        "scenario_id": scenario_id,
        "version": version,
        "failed_turn_index": failed_turn_index,
        "expected_turn_count": expected_turn_count,
        "thread_id": thread_id,
        "prompt_sha256": grade.prompt_sha256,
        "broker_prefix_count": grade.broker_prefix_count,
        "reconciliation": asdict(grade.reconciliation),
        "failed_common_gates": [
            key for key, passed in grade.common_gates.items() if not passed
        ],
        "grade_errors": list(grade.errors),
        "diagnostic_only": True,
        "artifact_sha256": {
            path.relative_to(root).as_posix(): _sha256_file(path)
            for path in artifact_paths
        },
    }
    if gateway_failure_stage is not None:
        payload["gateway_failure_stage"] = gateway_failure_stage
    _write_json(root / "task-gate-failure.json", payload)


def _composer_failure_stage(
    protocol: V3GatewayProtocol,
    broker_evidence: GatewayBrokerEvidence,
) -> str | None:
    if not any(
        step.subcommand.startswith("draft-")
        or step.subcommand == "preview-from-draft"
        for step in protocol.steps
    ):
        return None
    steps_by_name = {step.name: step for step in protocol.steps}
    if broker_evidence.records:
        final_name = broker_evidence.records[-1].step_name
        if final_name in steps_by_name and not broker_evidence.records[-1].succeeded:
            return classify_composer_failure_stage(
                steps_by_name[final_name].subcommand
            )
    next_index = len(broker_evidence.consumed_step_names)
    subcommand = (
        protocol.steps[next_index].subcommand
        if next_index < len(protocol.steps)
        else protocol.steps[-1].subcommand
    )
    return classify_composer_failure_stage(subcommand)


def _command_lifecycle_anomalies(stdout: str) -> list[dict[str, Any]]:
    phases: dict[str, dict[str, Mapping[str, Any]]] = {
        "item.started": {},
        "item.completed": {},
    }
    anonymous: list[dict[str, Any]] = []
    for event_index, line in enumerate(stdout.splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type") if isinstance(event, Mapping) else None
        item = event.get("item") if isinstance(event, Mapping) else None
        if (
            event_type not in phases
            or not isinstance(item, Mapping)
            or item.get("type") != "command_execution"
        ):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            anonymous.append(
                {
                    "event_index": event_index,
                    "phase": event_type,
                    "item_id": None,
                    "command": str(item.get("command") or ""),
                    "status": str(item.get("status") or ""),
                }
            )
            continue
        phases[event_type][item_id] = item
    started = phases["item.started"]
    completed = phases["item.completed"]
    anomalies = list(anonymous)
    for item_id in sorted(set(started) ^ set(completed)):
        phase = (
            "started_without_completed"
            if item_id in started
            else "completed_without_started"
        )
        item = started.get(item_id) or completed[item_id]
        anomalies.append(
            {
                "event_index": None,
                "phase": phase,
                "item_id": item_id,
                "command": str(item.get("command") or ""),
                "status": str(item.get("status") or ""),
            }
        )
    return anomalies


def _archive_infrastructure_failure(
    root: Path,
    *,
    output_dir: Path,
    scenario_id: str,
    version: str,
    turn_index: int,
    expected_turn_count: int,
    prior_completed_turn_count: int,
    previous_broker_prefix: int,
    expected_failed_turn_prefix: int,
    prior_thread_id: str | None,
    prompt: str,
    result: CodexRunResult,
    failure: CodexInfrastructureFailure,
    broker_evidence: GatewayBrokerEvidence,
    prompt_materialization_path: Path,
) -> None:
    """Seal a pre-agent Codex failure without persisting exception prose."""

    output_dir.mkdir(parents=True, exist_ok=True)
    failed_turn_files = {
        "prompt.txt": prompt + "\n",
        "events.jsonl": result.stdout,
        "stderr.txt": result.stderr,
        "final.txt": result.final_response + "\n",
    }
    for name, value in failed_turn_files.items():
        write_utf8_text_bytes(output_dir / name, value)
    _write_json(output_dir / "codex-facts.json", result.facts_dict())

    broker_path = root / "broker-evidence.json"
    _write_json(broker_path, broker_evidence.as_dict(include_output=False))

    artifact_paths = (
        prompt_materialization_path,
        output_dir / "prompt.txt",
        output_dir / "events.jsonl",
        output_dir / "stderr.txt",
        output_dir / "final.txt",
        output_dir / "codex-facts.json",
        broker_path,
    )
    artifact_sha256 = {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in artifact_paths
    }
    _write_json(
        root / "infrastructure-failure.json",
        {
            "contract": TASK_INFRASTRUCTURE_FAILURE_CONTRACT,
            "scenario_id": scenario_id,
            "version": version,
            "failed_turn_index": turn_index,
            "expected_turn_count": expected_turn_count,
            "prior_completed_turn_count": prior_completed_turn_count,
            "previous_broker_prefix": previous_broker_prefix,
            "expected_failed_turn_prefix": expected_failed_turn_prefix,
            "prior_thread_id": prior_thread_id,
            "prompt_sha256": _sha256_text(prompt),
            "failure": {
                "category": failure.category,
                "turn_failed": failure.turn_failed,
                "timed_out": failure.timed_out,
                "agent_item_event_count": failure.agent_item_event_count,
            },
            "artifact_sha256": artifact_sha256,
        },
    )


def _archive_prompt_materialization(
    root: Path,
    *,
    provenance: Any,
    business_oracle_plan: BusinessOraclePlanEvidence,
) -> Path:
    """Archive one receipt joining the fixed prompt and business plan."""

    path = root / PROMPT_MATERIALIZATION_FILE
    _write_json(
        path,
        prompt_materialization_receipt(
            provenance,
            business_oracle_plan=business_oracle_plan,
        ),
    )
    return path


def _validate_infrastructure_failure(
    *,
    prompt: str,
    result: CodexRunResult,
    failure: CodexInfrastructureFailure,
    broker_evidence: GatewayBrokerEvidence,
    expected_step_names: tuple[str, ...],
    previous_broker_prefix: int,
    allow_complete_prefix_failure: bool = False,
) -> None:
    """Prove the infrastructure failure preceded every model-side action."""

    facts = result.command_facts
    session = result.session_audit
    command_collections = (
        facts.commands,
        facts.inline_python_commands,
        facts.direct_waapi_client_commands,
        facts.write_like_commands,
        facts.gateway_commands,
        facts.discovery_commands,
        facts.command_records,
        facts.gateway_attempt_commands,
        facts.gateway_subcommands,
        facts.gateway_results,
        facts.gateway_evidence_apis,
        facts.allowed_read_commands,
        facts.skill_read_files,
        facts.unexpected_commands,
        facts.non_gateway_unexpected_commands,
    )
    file_collections = (
        result.created_files,
        result.modified_files,
        result.deleted_files,
        result.created_source_files,
        result.modified_source_files,
        result.deleted_source_files,
    )
    expected_prefix_names = expected_step_names[:previous_broker_prefix]
    broker_records = broker_evidence.records
    gates = {
        "failure_shape": (
            failure.category in _CODEX_INFRASTRUCTURE_CATEGORIES
            and type(failure.turn_failed) is bool
            and type(failure.timed_out) is bool
            and type(failure.agent_item_event_count) is int
        ),
        "failure_pre_agent": failure.agent_item_event_count == 0,
        "failure_timeout_consistent": failure.timed_out is result.timed_out,
        "command_facts_empty": (
            all(not values for values in command_collections)
            and not facts.skill_read
            and not facts.gateway_before_discovery
        ),
        "session_has_no_actions": (
            session.collab_call_count == 0
            and session.file_change_count == 0
            and session.command_started_count == 0
            and session.command_completed_count == 0
            and session.incomplete_command_count == 0
            and not session.unexpected_item_types
        ),
        "result_has_no_actions": (
            result.collab_call_count == 0
            and result.file_change_count == 0
            and result.final_response == ""
            and all(not values for values in file_collections)
        ),
        "jsonl_valid": session.invalid_json_line_count == 0,
        "prompt_isolated": (
            result.prompt_audit.passed
            and not result.prompt_audit.has_memory
            and result.isolation_audit.passed
        ),
        "prompt_bound": bool(prompt),
        "skill_tree_unchanged": (
            result.skill_tree_unchanged
            and _is_sha256(result.skill_tree_sha256_before)
            and result.skill_tree_sha256_before == result.skill_tree_sha256_after
        ),
        "broker_expected_steps_exact": (
            broker_evidence.expected_step_names == expected_step_names
        ),
        "broker_prefix_exact": (
            0 <= previous_broker_prefix <= len(expected_step_names)
            and gateway_step_sequence_matches(
                expected_prefix_names,
                broker_evidence.consumed_step_names,
                broker_evidence.commutative_read_only_step_groups,
                broker_evidence.commutative_composer_setup_step_groups,
            )
            and len(broker_records) == previous_broker_prefix
            and tuple(record.step_name for record in broker_records)
            == broker_evidence.consumed_step_names
            and all(record.succeeded for record in broker_records)
            and (
                (
                    allow_complete_prefix_failure
                    and previous_broker_prefix == len(expected_step_names)
                    and broker_evidence.complete
                    and broker_evidence.passed
                    and broker_evidence.terminal_state == "COMPLETE"
                )
                or (
                    not allow_complete_prefix_failure
                    and previous_broker_prefix < len(expected_step_names)
                    and not broker_evidence.complete
                    and not broker_evidence.passed
                    and broker_evidence.terminal_state == "RUNNING"
                )
            )
        ),
    }
    failures = tuple(name for name, passed in gates.items() if not passed)
    if failures:
        raise V3TaskRunnerError(
            "Codex infrastructure failure lacks clean pre-agent proof: "
            + ", ".join(failures)
        )


def _ordered_unique(values: Sequence[str] | Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_text_bytes(
        path,
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2, default=str)
        + "\n",
    )


__all__ = [
    "PROMPT_MATERIALIZATION_CONTRACT",
    "PROMPT_MATERIALIZATION_FILE",
    "TASK_COMMAND_LIFECYCLE_FAILURE_CONTRACT",
    "TASK_GATE_FAILURE_CONTRACT",
    "TASK_INFRASTRUCTURE_FAILURE_CONTRACT",
    "TASK_RESULT_CONTRACT",
    "V3CommandLifecycleError",
    "V3TaskRun",
    "V3TaskRunnerError",
    "V3TurnGrade",
    "run_v3_codex_task",
]

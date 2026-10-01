"""Read-only replay of expansion evidence inside a verified formal attempt.

The campaign must first verify its existing attempt seal and immutable effective
configuration. This module binds to that configuration digest and checks the
archived protocol; it never launches a host, repairs a transaction store, writes
a grade, or promotes an original failure to a business PASS.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import sys
from dataclasses import asdict
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
from tests.semantic.support.codex_expansion_policy import (
    BoundedExpansionReads, ExpansionReadScope, canonical_digest, classify_expansion_outcome,
)
from tests.semantic.support.codex_expansion_broker_policy import (
    _BUSINESS_EDITS, _DECLARATIONS, _DRAFT_READS, _READ_COMMANDS,
)
from tests.semantic.support.codex_filesystem_security import (
    path_is_link_or_reparse, read_bounded_exclusive_regular_file,
)
from tests.semantic.support.codex_harness import (
    WindowsPowerShellCoreHost, audit_session_events, completed_command_records,
    final_agent_message, classify_task_commands, recoverable_preprocess_attempt_indexes,
    classify_codex_infrastructure_failure,
    workspace_skill_install_path,
)
from tests.semantic.support.codex_gateway_broker import resolve_gateway_invocation, _validate_branching_execute_payload
from tests.semantic.support.codex_transaction_seal import (
    _validate_artifact, _validate_legal_event_states,
)
from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice
from wwise_waapi.transactions import _validate_event, confirmation_token_for, validate_transaction_id


_SHA = re.compile(r"[0-9a-f]{64}")
_CASE_MODULES = {"C01": "voice", "C03": "media", "C06": "rtpc", "C08": "attenuation",
                 "C09": "effects", "M01": "music", "M05": "stinger"}
_READS = set(_READ_COMMANDS)
_GATES = {"memory_isolated", "completed_turn", "one_target_skill", "no_collaboration",
    "only_packaged_references", "only_authenticated_gateway_and_skill_reads",
    "no_discovery_or_direct_waapi", "no_write_like_commands", "source_and_workspace_unchanged",
    "broker_provenance", "policy_checkpoint", "visible_preview_notice", "final_response_present", "cumulative_agent_budget"}


class ExpansionArchiveError(ValueError):
    """A sealed expansion archive cannot prove its recorded outcome."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ExpansionArchiveError(message)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode(raw: bytes) -> Any:
    def invalid(value):
        raise ExpansionArchiveError(f"non-finite JSON constant: {value}")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=invalid)


def _bytes(root: Path, relative: str, *, empty: bool = False) -> bytes:
    cursor = root
    _require(cursor.is_dir() and not path_is_link_or_reparse(cursor), "archive root is missing or linked")
    parts = parse_archive_relative_path(relative).parts
    for part in parts:
        cursor = cursor / part
        _require(not path_is_link_or_reparse(cursor), "archive path is linked")
    return read_bounded_exclusive_regular_file(cursor, max_bytes=32 * 1024 * 1024,
        require_private_posix_mode=False, allow_empty=empty).raw


def _json(root: Path, relative: str) -> dict[str, Any]:
    value = _decode(_bytes(root, relative))
    _require(isinstance(value, dict), f"{relative} must contain an object")
    return value


def _finite(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _case(plan: Mapping[str, Any]) -> tuple[Any, str]:
    case_id = str(plan["unit_id"]).split("-")[-1]
    _require(case_id in _CASE_MODULES, "unknown expansion case")
    return importlib.import_module(
        "tests.semantic.support.codex_expansion_" + _CASE_MODULES[case_id] + "_case"), case_id


def _transaction(root: Path, transaction_id: str) -> tuple[dict, list[dict], dict]:
    validate_transaction_id(transaction_id)
    prefix = f"broker/state/transactions/{transaction_id}/"
    preview = _json(root, prefix + "preview.json")
    state = _json(root, prefix + "state.json")
    raw = _bytes(root, prefix + "events.jsonl")
    _require(raw.endswith(b"\n"), "transaction journal is incomplete")
    events = [_decode(line) for line in raw.splitlines()]
    artifact = preview.get("artifact")
    _require(isinstance(artifact, dict) and preview.get("transaction_id") == transaction_id
             and preview.get("artifact_hash") == canonical_digest(artifact), "preview artifact digest mismatch")
    _validate_artifact(artifact)
    previous_hash, previous_state = "", None
    for index, event in enumerate(events, 1):
        _require(isinstance(event, dict), "transaction event must be an object")
        _validate_event(event, transaction_id=transaction_id, artifact_hash=preview["artifact_hash"],
            expected_sequence=index, expected_previous_hash=previous_hash,
            expected_from_state=previous_state, path=root / prefix / "events.jsonl")
        previous_hash, previous_state = event["event_hash"], event["to_state"]
    _validate_legal_event_states(events)
    _require(state.get("transaction_id") == transaction_id
        and state.get("artifact_hash") == preview["artifact_hash"]
        and state.get("event_sequence") == len(events)
        and state.get("last_event_hash") == previous_hash and state.get("state") == previous_state
        and state.get("created_at") == events[0]["timestamp"]
        and state.get("updated_at") == events[-1]["timestamp"], "transaction state does not match journal")
    return preview, events, state


def _scope(plan: Mapping[str, Any]) -> BoundedExpansionReads:
    value = dict(plan["read_scope"])
    for key in ("object_ids", "operations", "includes", "relationship_sources", "fields", "curve_roles", "platforms"):
        values = value.get(key, [])
        _require(isinstance(values, list) and len(values) == len(set(values)), "read scope set is malformed")
        value[key] = frozenset(values)
    scope = ExpansionReadScope(**value)
    _require(scope.digest == plan["read_scope_sha256"], "read scope digest mismatch")
    spec = importlib.util.spec_from_file_location("waapi_expansion_archive_public_parser",
        Path(plan["skill_source"]) / "scripts" / "gateway.py")
    _require(spec is not None and spec.loader is not None, "packaged public parser is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    parser = module.build_parser()
    def parse(argv):
        _require(bool(argv) and not argv[0].startswith("-") and len(argv) <= 256, "invalid public read argv")
        try:
            return parser.parse_args(["--version", plan["version"], *argv])
        except SystemExit as exc:
            raise ExpansionArchiveError("archived read violates the public parser") from exc
    return BoundedExpansionReads(scope, public_parser=parse)


def _receipts(root: Path, plan: Mapping[str, Any], broker: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = broker.get("records")
    _require(isinstance(records, list) and len(records) <= 128, "broker receipt count is invalid")
    gate = _scope(plan)
    draft_id = authority = revision = None
    failed_accepted = False
    expected_operation = plan.get("request_schema_uri") or plan.get("operation")
    for index, record in enumerate(records, 1):
        _require(isinstance(record, dict) and record.get("sequence") == index, "broker sequence mismatch")
        for key, digest_key in (("model_argv", "raw_argv_sha256"), ("normalized_model_argv", "argv_sha256")):
            argv = record.get(key)
            _require(isinstance(argv, list) and all(isinstance(item, str) for item in argv)
                and record.get(digest_key) == canonical_digest(argv), "broker argv digest mismatch")
        argv = record.get("gateway_arguments")
        _require(isinstance(argv, list) and all(isinstance(item, str) for item in argv), "invalid Gateway argv")
        for key in ("started_at_unix", "finished_at_unix", "duration_seconds"):
            _require(_finite(record.get(key)), "invalid broker timing")
        _require(record["finished_at_unix"] >= record["started_at_unix"], "backwards broker timing")
        if record.get("accepted") is not True:
            _require(record.get("succeeded") is False and bool(record.get("rejection")), "invalid rejected receipt")
            continue
        _require(not failed_accepted, "accepted command followed a terminal failed receipt")
        resolved = resolve_gateway_invocation(record["model_argv"], skill_source=Path(plan["skill_source"]),
            invocation_skill_source=workspace_skill_install_path(root / "agent-workspace"),
            shim_directory=root / "broker" / "bin")
        _require(list(resolved.gateway_arguments) == argv
            and list(resolved.normalized_model_argv) == record["normalized_model_argv"], "recorded Gateway argv differs from actual invocation")
        runner = str((Path(plan["skill_source"]) / "scripts" / "run.py").resolve())
        _require(record.get("runner_command_sha256") == canonical_digest(
            [plan["trusted_python"], runner, "gateway.py", *argv]), "trusted runner command digest mismatch")
        payload = record.get("payload")
        _require(record.get("authenticated") is True and type(record.get("succeeded")) is bool,
                 "broker receipt authentication/outcome mismatch")
        if payload is None:
            _require(record.get("succeeded") is False and record.get("payload_sha256") == ""
                and bool(record.get("payload_error")) and record.get("exit_code") == 125
                and isinstance(record.get("stdout"), str), "missing payload lacks terminal failure evidence")
        else:
            _require(isinstance(payload, dict) and record.get("payload_sha256") == canonical_digest(payload),
                     "broker payload authentication/digest mismatch")
            _require(_decode(record["stdout"].encode("utf-8")) == payload, "stdout differs from receipt payload")
            _require(bool(argv) and payload.get("command") == argv[0], "receipt command mismatch")
        _require(bool(argv), "receipt has no admitted command")
        command = argv[0]
        _require(command in (_READS | _DRAFT_READS | _BUSINESS_EDITS | _DECLARATIONS.get(plan.get("operation"), frozenset())
            | {"draft-start", "preview-from-draft", "transaction-show", "confirm", "execute", "verify"}),
                 "receipt used an unapproved Gateway command")
        semantic = ["runner-owned-version", plan["version"], *argv]
        if command.startswith("draft-") or command == "preview-from-draft":
            if command == "draft-start":
                _require(draft_id is None and argv == ["draft-start", expected_operation], "unexpected second or wrong Draft")
            else:
                _require(len(argv) > 1 and argv[1] == draft_id
                    and "--task-authority" in argv
                    and argv[argv.index("--task-authority") + 1] == authority, "Draft authority changed")
                if command != "draft-inspect":
                    _require("--expected-revision" in argv and argv[argv.index("--expected-revision") + 1] == str(revision),
                             "Draft revision changed")
                    semantic[2 + argv.index("--expected-revision") + 1] = revision
                if command == "draft-bind-object":
                    object_id = argv[argv.index("--object-id") + 1] if "--object-id" in argv else None
                    segments = [argv[position + 1] for position, value in enumerate(argv) if value == "--object-path-segment"]
                    path = "\\" + "\\".join(segments) if segments else None
                    _require(object_id in gate.scope.object_ids or path in plan.get("scoped_paths", {}).values(),
                             "mutation binding exceeds the sealed object scope")
            draft = payload.get("draft") if isinstance(payload, dict) else None
            if isinstance(draft, dict):
                if command == "draft-start":
                    draft_id, authority = draft["draft_id"], payload["task_authority"]
                revision = draft["revision"]
        _require(record.get("semantic_argv_sha256") == canonical_digest(semantic), "semantic argv digest mismatch")
        if command in _READS:
            gate.admit(argv)
            if record.get("succeeded") is True:
                gate.observe(payload)
        if command == "execute" and record.get("succeeded") is True and record.get("allowed_exit_codes") == [0, 2]:
            _validate_branching_execute_payload(payload, exit_code=record.get("runner_exit_code"))
            if payload.get("status") == "indeterminate":
                failed_accepted = True  # terminal non-retryable branch, not a repairable preparation
        if record.get("succeeded") is True:
            _require(record.get("exit_code") == record.get("runner_exit_code")
                and record.get("runner_exit_code") in record.get("allowed_exit_codes", [])
                and not record.get("payload_error"), "successful receipt has inconsistent exit")
        else:
            _require(record.get("exit_code") == 125 and bool(record.get("payload_error")),
                     "failed accepted receipt lacks the Broker terminal failure")
            failed_accepted = True
    return records


def _turns(root: Path, plan: Mapping[str, Any], result: Mapping[str, Any],
           budget: Mapping[str, Any], records: list[Mapping[str, Any]], oracle: Mapping[str, Any]) -> list[dict]:
    turns = budget.get("turns")
    _require(isinstance(turns, list) and len(turns) <= len(plan["prompts"]), "turn budget shape is invalid")
    _require(budget.get("hard_seconds") == 600 and budget.get("slow_seconds") == 420, "budget limits changed")
    measurements = budget.get("turn_measurements")
    _require(isinstance(measurements, list) and len(measurements) == len(turns), "missing Agent time measurements")
    elapsed, prefix = 0.0, 0
    for index, turn in enumerate(turns, 1):
        _require(turn.get("index") == index and _finite(turn.get("agent_seconds")), "turn duration is invalid")
        measured = measurements[index - 1]
        _require(all(_finite(measured.get(key)) for key in ("started_monotonic", "finished_monotonic", "elapsed_seconds"))
            and measured["finished_monotonic"] >= measured["started_monotonic"]
            and math.isclose(measured["finished_monotonic"] - measured["started_monotonic"], measured["elapsed_seconds"], abs_tol=1e-6)
            and math.isclose(turn["agent_seconds"], measured["elapsed_seconds"], abs_tol=1e-6), "Agent measurement mismatch")
        if index > 1:
            _require(measured["started_monotonic"] >= measurements[index - 2]["finished_monotonic"], "overlapping Agent turns")
        elapsed += turn["agent_seconds"]
        if turn.get("incomplete") is True:
            _require(not result["passed"] and index == len(turns) and turn.get("gates") == {}, "incomplete turn cannot pass")
            continue
        directory = f"turns/turn-{index:02d}/"
        prompt = _bytes(root, directory + "prompt.txt").decode("utf-8")
        _require(prompt == plan["prompts"][index - 1] + "\n", "turn prompt changed")
        grade = _json(root, directory + "turn-grade.json")
        facts = _json(root, directory + "codex-facts.json")
        events_raw = _bytes(root, directory + "events.jsonl", empty=True)
        events = [_decode(line) for line in events_raw.splitlines() if line]
        final = _bytes(root, directory + "final.txt", empty=True).decode("utf-8")
        _bytes(root, directory + "stderr.txt", empty=True)
        _require(grade.get("index") == index
            and grade.get("prompt_sha256") == hashlib.sha256(prompt[:-1].encode("utf-8")).hexdigest()
            and grade.get("common_gates") == turn.get("gates")
            and set(grade.get("common_gates", {})) == _GATES, "turn grade binding changed")
        count = grade.get("broker_prefix_count")
        _require(type(count) is int and prefix <= count <= len(records), "broker turn prefix is invalid")
        host = (WindowsPowerShellCoreHost(**plan["windows_powershell_core_host"])
                if plan.get("windows_powershell_core_host") else None)
        commands = completed_command_records(events, platform_name=plan["platform_name"], windows_powershell_core_host=host)
        archived_commands = facts.get("command_facts", {}).get("command_records")
        _require(canonical_digest([asdict(command) for command in commands]) == canonical_digest(archived_commands),
                 "Codex command facts differ from raw events")
        for record in records[prefix:count]:
            matches = [command for command in commands if list(command.argv) == record["model_argv"]]
            _require(bool(matches) and any(command.exit_code == record["exit_code"] for command in matches),
                     "Broker receipt has no matching raw Codex command")
        if result["passed"]:
            classified = classify_task_commands(commands, workspace=root / "agent-workspace",
                skill_source=Path(plan["skill_source"]), expected_wwise_version=plan["version"],
                expected_gateway_subcommands=tuple(sorted({row["gateway_arguments"][0] for row in records if row["gateway_arguments"]})))
            references = classified.skill_read_files
            allowed_references = {"SKILL.md", "references/waapi-operate.md", "references/waapi-query.md",
                                  "references/waapi-setup.md", "references/waapi-coverage.md"}
            _require(not classified.non_gateway_unexpected_commands and not classified.discovery_commands
                and not classified.direct_waapi_client_commands and not classified.write_like_commands
                and len(references) <= 12 and set(references).issubset(allowed_references)
                and (index != 1 or bool(references) and references[0] == "SKILL.md")
                and len(commands) - len(recoverable_preprocess_attempt_indexes(commands))
                    == count - prefix + len(classified.allowed_read_commands), "raw commands violate Skill-only/no-bypass gates")
            _require(index != 1 or expansion_preview_notice(SimpleNamespace(stdout=events_raw.decode("utf-8")),
                commands, version=plan["version"], execute_expected=plan["policy"] == "allow_changes",
                preview_artifact=_transaction(root, oracle["transaction_id"])[0]["artifact"],
                before_snapshot=oracle.get("preview_before") or plan["before"]),
                     "visible post-Preview notice is missing")
            _require(grade.get("passed") is True and not grade.get("errors")
                and all(value is True for value in grade["common_gates"].values())
                and audit_session_events(events).passed
                and facts.get("thread_id") == result.get("thread_id")
                and final_agent_message(events) == facts.get("final_response")
                and final == facts.get("final_response", "") + "\n"
                and facts.get("exit_status") == 0 and facts.get("timed_out") is False
                and facts.get("prompt_audit", {}).get("passed") is True
                and facts.get("prompt_audit", {}).get("has_memory") is False
                and facts.get("isolation_audit", {}).get("passed") is True
                and facts.get("skill_tree_unchanged") is True
                and facts.get("skill_tree_sha256_before") == facts.get("skill_tree_sha256_after"),
                     "passing turn lacks complete raw session evidence")
        prefix = count
    _require(_finite(budget.get("elapsed_seconds")) and math.isclose(elapsed, budget["elapsed_seconds"], abs_tol=1e-6)
        and result.get("agent_seconds") == budget["elapsed_seconds"]
        and budget.get("slow") is (elapsed >= 420) and result.get("slow") is budget["slow"]
        and result.get("turns") == turns, "cumulative Agent budget mismatch")
    if result["passed"]:
        _require(elapsed <= 600 and len(turns) == len(plan["prompts"]) and prefix == len(records),
                 "passing task exhausted budget or omitted a turn")
    return turns


def verify_expansion_task_archive(task_root: Path, *, expected_unit_id: str,
        expected_version: str, expected_inputs_sha256: str) -> dict[str, Any]:
    """Recompute complete task evidence; campaign seal validation is separate."""
    try:
        return _verify_task(Path(task_root), expected_unit_id, expected_version, expected_inputs_sha256)
    except ExpansionArchiveError:
        raise
    except Exception as exc:
        raise ExpansionArchiveError(f"invalid expansion archive: {type(exc).__name__}: {exc}") from exc


def _verify_task(root: Path, unit_id: str, version: str, inputs_sha256: str) -> dict[str, Any]:
    _require(isinstance(inputs_sha256, str) and _SHA.fullmatch(inputs_sha256), "invalid expected inputs digest")
    plan = _json(root, "expansion-plan.json")
    digest = plan.pop("sha256", None)
    _require(digest == canonical_digest(plan), "plan digest mismatch")
    _require(plan.get("inputs_sha256") == inputs_sha256, "immutable campaign inputs mismatch")
    _require(plan.get("contract") == "waapi-skill.integration-expansion-task-plan/v1"
        and plan.get("unit_id") == unit_id and plan.get("version") == version, "task plan identity mismatch")
    module, case_id = _case(plan)
    _require(unit_id == f"EXP{version[2:4]}-{case_id}" and version in {"2022.1", "2025.1"}
        and (case_id, version) != ("M05", "2022.1"), "unit is not an Agent case")
    policy = "ask_before_changes" if case_id in {"C01", "C03"} else "allow_changes"
    _require(plan.get("policy") == policy and isinstance(plan.get("prompts"), list)
        and len(plan["prompts"]) == (2 if policy == "ask_before_changes" else 1)
        and all(isinstance(prompt, str) and prompt for prompt in plan["prompts"]), "prompt/policy contract changed")
    required = getattr(module, case_id + "_ASSERTIONS")
    _require(set(plan.get("required_assertions", [])) == required, "oracle obligations changed")
    result = _json(root, "expansion-task-result.json")
    _require(type(result.get("passed")) is bool and result.get("unit_id") == unit_id
        and result.get("version") == version and result.get("plan_sha256") == digest, "terminal result binding mismatch")
    broker = _json(root, "expansion-broker.json")
    budget = _json(root, "expansion-agent-budget.json")
    oracle = _json(root, "expansion-oracle.json")
    records = _receipts(root, plan, broker)
    turns = _turns(root, plan, result, budget, records, oracle)
    mutations = [row for row in records if row.get("accepted") is True and row["gateway_arguments"][:1] == ["execute"]]
    _require(len(mutations) <= 1, "more than one execution was admitted")
    _require(oracle.get("before") == plan["before"], "independent pre-state changed")
    transaction_id = oracle.get("transaction_id")
    events = ()
    preview_approval: bool | None = None
    transactions_directory = root / "broker" / "state" / "transactions"
    if transactions_directory.exists():
        _require(not path_is_link_or_reparse(transactions_directory), "transaction directory is linked")
        _require({path.name for path in transactions_directory.iterdir()}
            == ({transaction_id} if transaction_id else set()), "unrecorded transaction in the Agent store")
    if transaction_id is not None:
        preview, events, state = _transaction(root, transaction_id)
        _require(oracle.get("artifact_hash") == preview["artifact_hash"], "oracle transaction binding mismatch")
        _require(oracle.get("preview_before") == oracle.get("preview_after")
            and isinstance(oracle.get("preview_before"), dict), "Preview changed business state")
        parameters = dict(plan["preview_parameters"])
        for key in ("replacement",):
            if key in parameters:
                parameters[key] = Path(parameters[key])
        for key in ("mappings", "media"):
            if key in parameters:
                parameters[key] = {name: Path(path) for name, path in parameters[key].items()}
        preview_approval = getattr(module, "approve_" + case_id.lower() + "_preview")(
            preview["artifact"], **parameters)
        _require(type(preview_approval) is bool, "adapter Preview approval is not an exact boolean")
        recorded_approval = oracle.get("preview_approved")
        if preview_approval is True:
            _require("preview_approved" not in oracle or recorded_approval is True,
                     "preview approval record differs from the independent adapter")
        else:
            preview_receipts = [row for row in records if row.get("accepted") is True
                and row["gateway_arguments"][:1] == ["preview-from-draft"]]
            _require(not result["passed"] and recorded_approval is False
                and "preview_approved" in oracle,
                "rejected Preview lacks an explicit false preview approval record")
            _require(len(preview_receipts) == 1 and preview_receipts[0].get("succeeded") is True
                and preview_receipts[0].get("payload", {}).get("transaction_id") == transaction_id
                and preview_receipts[0].get("payload", {}).get("artifact_hash") == preview["artifact_hash"],
                "rejected Preview identity is not bound to its authenticated Gateway receipt")
            _require(not any(row["gateway_arguments"][:1] in (["confirm"], ["execute"])
                    for row in records)
                and not any(event.get("to_state") in {"confirmed", "executing"} for event in events)
                and "authorization" in oracle and oracle["authorization"] is None
                and "permit" in oracle and oracle["permit"] is None,
                "rejected Preview has a confirmation or execution authorization")
            _require(oracle.get("after") is None and oracle.get("assertions") == {}
                and oracle.get("gateway_verification_state") is None
                and result.get("assertions", {}) == {}
                and result.get("gateway_verification_state") is None,
                "rejected Preview claims post-execution business verification")
        executed_events = [event for event in events if event["to_state"] == "executing"]
        # Admission consumes the at-most-once reservation before launching the
        # subprocess. A timeout can precede Gateway begin_execution; the journal
        # proves actual dispatch, while a missing receipt never permits retry.
        successful_mutations = [row for row in mutations if row.get("succeeded") is True]
        _require(len(successful_mutations) <= len(executed_events) <= len(mutations),
                 "execution receipt/journal disagreement")
        if mutations:
            prefixes = [_json(root, f"turns/turn-{index:02d}/turn-grade.json")["broker_prefix_count"]
                        for index, turn in enumerate(turns, 1) if not turn.get("incomplete")]
            _authorization(plan, oracle, events, records, turns, preview, prefixes)
        if result["passed"]:
            _require(isinstance(oracle.get("before"), dict)
                and isinstance(oracle.get("after"), dict),
                "passing archive lacks independent before/post-state for oracle replay")
        if oracle.get("after") is not None:
            assertions = getattr(module, "verify_" + case_id.lower())(
                oracle["before"], oracle["after"], **plan["oracle_parameters"])
            _require(assertions == oracle.get("assertions") == result.get("assertions")
                and set(assertions) == required, "independent oracle replay mismatch")
        if result["passed"]:
            expected_state = "result_schema_checked" if case_id == "C08" else "verified"
            verification_receipts = [row for row in records if row.get("accepted") is True
                and row["gateway_arguments"][:1] == ["verify"]]
            _require(state["state"] == oracle.get("gateway_verification_state")
                == result.get("gateway_verification_state") == expected_state
                and len(mutations) == 1 and bool(oracle.get("assertions"))
                and len(verification_receipts) == 1
                and verification_receipts[0]["sequence"] > mutations[0]["sequence"]
                and verification_receipts[0]["payload"].get("state") == expected_state
                and all(value is True for value in oracle["assertions"].values()), "business PASS lacks a complete verified effect")
    else:
        _require(not result["passed"] and not mutations, "passing/executed archive has no transaction")
    if result["passed"]:
        _require(broker.get("passed") is True and broker.get("complete") is True
            and all(row.get("succeeded") is True for row in records)
            and broker.get("expected_step_names") == broker.get("consumed_step_names")
            == [row["step_name"] for row in records], "passing Broker evidence is incomplete")
    infrastructure = result.get("infrastructure")
    if infrastructure is not None:
        _require(isinstance(infrastructure, dict) and bool(turns), "infrastructure classification lacks raw turn evidence")
        directory = f"turns/turn-{len(turns):02d}/"
        raw_events = [_decode(line) for line in _bytes(root, directory + "events.jsonl", empty=True).splitlines() if line]
        facts = _json(root, directory + "codex-facts.json")
        observed = classify_codex_infrastructure_failure(raw_events,
            stderr=_bytes(root, directory + "stderr.txt", empty=True).decode("utf-8"), timed_out=facts.get("timed_out") is True)
        _require(observed is not None and asdict(observed) == infrastructure,
                 "infrastructure classification differs from raw pre-action evidence")
    original_status = classify_expansion_outcome(passed=result["passed"], records=records, events=events,
                                                 infrastructure=infrastructure)
    if preview_approval is False:
        _require(original_status == "FAIL", "rejected Preview did not remain an ordinary business FAIL")
    reconciliation = oracle.get("reconciliation")
    if reconciliation is not None:
        _require(not result["passed"] and isinstance(reconciliation, dict)
            and reconciliation.get("status") in {"completed", "error"}
            and _finite(reconciliation.get("elapsed_seconds"))
            and reconciliation.get("seconds") == 30 and reconciliation.get("read_seconds") == 10
            and type(reconciliation.get("child_reaped")) is bool
            and type(reconciliation.get("subprocesses_reaped")) is bool,
            "reconciliation receipt lacks bounded timing/cleanup evidence")
        if reconciliation["status"] == "completed":
            _require(isinstance(reconciliation.get("snapshot"), dict)
                and len(json.dumps(reconciliation["snapshot"], ensure_ascii=False).encode("utf-8")) <= 131_072
                and reconciliation.get("snapshot_sha256") == canonical_digest(reconciliation["snapshot"]),
                "reconciliation snapshot digest or bounds changed")
        else:
            error = reconciliation.get("error")
            _require(isinstance(error, dict) and isinstance(error.get("type"), str)
                and isinstance(error.get("message"), str) and len(error["message"].encode("utf-8")) <= 2048,
                "reconciliation error is missing or unbounded")
        if reconciliation["child_reaped"] is not True or reconciliation["subprocesses_reaped"] is not True:
            original_status = "BLOCKED"
    _require(result.get("status", original_status) == original_status, "original outcome classification changed")
    if "status" in result and not result["passed"]:
        _require(reconciliation is not None, "classified negative outcome omitted reconciliation")
    return {"archive_valid": True, "original_status": original_status,
        "business_pass": result["passed"], "preview_approved": preview_approval,
        "gateway_verification_state": result.get("gateway_verification_state"),
        "agent_seconds": budget["elapsed_seconds"], "slow": budget["slow"], "reconciliation": reconciliation,
        "turn_count": len(turns), "execution_reservations": len(mutations),
        "executions": len(executed_events) if transaction_id is not None else 0}


def _authorization(plan, oracle, events, records, turns, preview, prefixes):
    policy = plan["policy"]
    explicit = policy == "ask_before_changes"
    auth_events = [event for event in events if event["to_state"] in {"confirmed", "policy_authorized"}]
    _require(len(auth_events) == 1, "execution lacks one durable authorization")
    auth = auth_events[0]
    _require(auth["to_state"] == ("confirmed" if explicit else "policy_authorized"), "authorization mode mismatch")
    authorization = oracle.get("authorization")
    _require(isinstance(authorization, dict) and authorization.get("explicit_confirmation") is explicit,
             "authorization receipt mismatch")
    _require(authorization.get("mode") == ("explicit_confirmation" if explicit else "policy_authorization"),
             "authorization mode projection mismatch")
    if not explicit:
        details = auth["details"]
        _require(details.get("policy") == "allow_changes" and details.get("explicit_confirmation") is False
            and details.get("authority") == authorization.get("authority") == "caller_asserted_current_user_change_request",
                 "allow configuration is not durable policy authorization")
    preview_rows = [row for row in records if row.get("accepted") is True and row["gateway_arguments"][:1] == ["preview-from-draft"]]
    execute = next(row for row in records if row.get("accepted") is True and row["gateway_arguments"][:1] == ["execute"])
    _require(len(preview_rows) == 1 and preview_rows[0]["sequence"] < execute["sequence"], "execution preceded unique Preview")
    for record in records:
        if record.get("accepted") is True and record["gateway_arguments"][:1] in (["execute"], ["verify"], ["confirm"], ["transaction-show"]):
            _require(record["gateway_arguments"][1] == preview["transaction_id"], "receipt refers to another transaction")
            if record["gateway_arguments"][0] in {"execute", "verify"} and record.get("succeeded") is not False:
                _require(record["payload"].get("transaction_id") == preview["transaction_id"]
                    and record["payload"].get("artifact_hash") == preview["artifact_hash"], "effect receipt is misbound")
    permit = oracle.get("permit")
    _require(isinstance(permit, dict) and permit.get("transaction_id") == preview["transaction_id"]
        and permit.get("artifact_sha256") == preview["artifact_hash"]
        and _SHA.fullmatch(str(permit.get("authorization_nonce", "")))
        and permit.get("preview_turn") == 1 and permit.get("authorized_turn") == (2 if explicit else 1),
             "runner authorization is not bound to the immutable Preview and user turn")
    if explicit:
        _require(len(turns) == 2, "confirmation has no later user turn")
        confirms = [row for row in records if row.get("accepted") is True and row["gateway_arguments"][:1] == ["confirm"]]
        _require(len(confirms) == 1 and confirms[0]["sequence"] < execute["sequence"], "confirmation receipt is missing")
        _require(len(prefixes) == 2 and preview_rows[0]["sequence"] <= prefixes[0]
            < confirms[0]["sequence"] < execute["sequence"] <= prefixes[1], "confirmation is not in the later user turn")
        awaiting = next(event for event in events if event["to_state"] == "awaiting_confirmation")
        token = confirmation_token_for(transaction_id=preview["transaction_id"], artifact_hash=preview["artifact_hash"],
            state="awaiting_confirmation", event_sequence=awaiting["sequence"], last_event_hash=awaiting["event_hash"])
        argv = confirms[0]["gateway_arguments"]
        _require(argv == ["confirm", preview["transaction_id"], "--confirmation-token", token],
                 "confirmation token is misbound")


def verify_expansion_boundary_archive(scenario_root: Path, *, expected_unit_id: str,
        expected_version: str, expected_inputs_sha256: str) -> dict[str, Any]:
    """M05/2022 unavailable-reference evidence is never an Agent/business PASS."""
    try:
        outcome = _json(Path(scenario_root), "outcome.json")
        _require((expected_unit_id, expected_version) == ("EXP22-M05", "2022.1")
            and outcome.get("scenario_id") == expected_unit_id and outcome.get("version") == expected_version
            and outcome.get("inputs_sha256") == expected_inputs_sha256
            and outcome.get("status") == "BOUNDARY_PROVEN"
            and outcome.get("task_root") is None and outcome.get("thread_id") is None, "boundary identity/outcome mismatch")
        boundary = outcome["checks"]["capability_boundary"]
        _require(boundary.get("case_id") == "M05" and boundary.get("version") == "2022.1"
            and boundary.get("agent_started") is False and boundary.get("business_pass") is False,
                 "boundary was conflated with Agent or business success")
        evidence = boundary["evidence"]
        observed = evidence["public_observation"]
        unresolved = {row["meaning"]: row["candidate_names"] for row in observed["agent_result"]["unresolved"]}
        _require(observed.get("ok") is True and observed.get("status") == "needs_clarification"
            and unresolved.get("Trigger") == [] and isinstance(unresolved.get("Segment"), list)
            and "Segment" not in unresolved["Segment"] and bool(evidence.get("identity_before"))
            and evidence["identity_before"] == evidence.get("identity_after")
            and evidence.get("agent_executed") is False and evidence.get("business_effect_verified") is False,
                 "unavailable references were not independently reproduced")
        return {"archive_valid": True, "boundary_proven": True, "business_pass": False,
                "agent_started": False, "original_status": "BOUNDARY_PROVEN"}
    except ExpansionArchiveError:
        raise
    except Exception as exc:
        raise ExpansionArchiveError(f"invalid boundary archive: {exc}") from exc

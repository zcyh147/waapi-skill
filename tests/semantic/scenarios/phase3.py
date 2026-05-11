"""Required Phase 3 OpenCode semantic scenarios and behavioral verdicts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


PUBLIC_CONFIG_FIELDS = frozenset({"wwise_version", "waapi_host", "waapi_port", "project_modification_policy"})
SUPPORTED_WWISE_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
RESEARCH_TERMS = (
    "repo",
    "repository",
    "source",
    "source code",
    "docs",
    "documentation",
    "github",
    "librarian",
    "grep",
)
LIVE_WAAPI_TERMS = ("waapi", "ak.wwise", "object.get", "getinfo", "live query")
IDENTITY_ROLE_KEYS = frozenset({"parent", "target", "container"})


@dataclass(frozen=True, slots=True)
class SemanticScenario:
    id: str
    prompt: str
    expected_assertions: tuple[str, ...]
    bug_classes: tuple[str, ...]
    scenario_sets: tuple[str, ...]
    family: str
    follow_up_prompt: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScenarioVerdict:
    verdict: str
    assertions: tuple[str, ...]
    failure_notes: tuple[str, ...] = ()
    facts: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"


def phase3_scenarios() -> tuple[SemanticScenario, ...]:
    """Return the required Phase 3 scenarios in stable execution order."""

    return (
        SemanticScenario(
            id="phase3-readonly-bus-listing",
            prompt="List all buses in my Wwise project.",
            expected_assertions=(
                "attempts live WAAPI object.get before repo/docs/source research",
                "does not mutate the project",
                "reports bus rows or an empty Wwise result",
            ),
            bug_classes=("live-task execution avoidance", "repo-doc-first drift"),
            scenario_sets=("phase3-required", "phase3-smoke"),
            family="read_only_bus_listing",
        ),
        SemanticScenario(
            id="phase3-waql-master-mixer-ui-descendants",
            prompt="Find every descendant under Master-Mixer Hierarchy whose name starts with UI_.",
            expected_assertions=(
                "attempts live read-only ak.wwise.core.object.get before research",
                "scopes the query under Master-Mixer Hierarchy descendants",
                "uses explicit return fields and performs no mutation",
            ),
            bug_classes=("live-task execution avoidance", "WAQL-guidance overresearch"),
            scenario_sets=("phase3-required", "phase3-smoke"),
            family="waql_descendant_query",
        ),
        SemanticScenario(
            id="phase3-public-config-boundary",
            prompt="What do I need to configure before we start?",
            expected_assertions=(
                "mentions only public saved config fields",
                "does not expose WwiseConsole paths, runtime timeout knobs, caches, or scaffold internals as saved config",
            ),
            bug_classes=("implementation detail leakage", "public config boundary"),
            scenario_sets=("phase3-required",),
            family="public_config_boundary",
        ),
        SemanticScenario(
            id="phase3-invalid-parent-mutation-preview",
            prompt="Create a new bus under Master-Mixer Hierarchy called Temp_UI_Bus.",
            expected_assertions=(
                "recognizes mutation intent and previews only",
                "does not silently rewrite the invalid hierarchy root parent",
                "explains the writable candidate target and waits for confirmation",
            ),
            bug_classes=("destructive-path clarification weakness", "mutation confirmation safety"),
            scenario_sets=("phase3-required",),
            family="invalid_parent_mutation_preview",
        ),
        SemanticScenario(
            id="phase3-confirm-live-mutation-verify",
            prompt="Create a new bus under Master-Mixer Hierarchy called Temp_UI_Bus.",
            follow_up_prompt="confirm",
            expected_assertions=(
                "does not execute before explicit confirmation",
                "executes against the same target identity captured during preview",
                "verifies the created object with live readback",
            ),
            bug_classes=("preview-to-execution mismatch", "partial verification weakness"),
            scenario_sets=("phase3-required",),
            family="confirm_live_mutation_verify",
        ),
        SemanticScenario(
            id="phase3-compound-read-then-confirm",
            prompt=(
                "Show me the current buses first, then prepare to create a Temp_UI_Bus under Master-Mixer Hierarchy "
                "but wait for my confirmation before changing anything."
            ),
            expected_assertions=(
                "completes the read stage before preview or mutation",
                "does not perform repo/docs/source research before the live read when WAAPI is ready",
                "stops at confirmation before executing the mutation",
            ),
            bug_classes=("compound read-first drift", "mutation confirmation safety"),
            scenario_sets=("phase3-required",),
            family="compound_read_then_confirm",
        ),
    )


def scenarios_for_set(scenario_set: str) -> tuple[SemanticScenario, ...]:
    selected = tuple(scenario for scenario in phase3_scenarios() if scenario_set in scenario.scenario_sets)
    if not selected:
        raise ValueError(f"unknown scenario set: {scenario_set}")
    return selected


def evaluate_scenario_output(scenario: SemanticScenario, assistant_output: str) -> ScenarioVerdict:
    """Evaluate semantic behavior facts from structured markers plus conservative transcript fallbacks."""

    facts = _extract_facts(assistant_output)
    failures: list[str] = []

    if scenario.family in {"read_only_bus_listing", "waql_descendant_query"}:
        _require(_truthy(facts, "live_waapi_attempted"), "live WAAPI was not attempted", failures)
        _require(_has_object_get_call(facts), "ak.wwise.core.object.get was not observed", failures)
        _require(not _research_before_live(facts, assistant_output), "repo/docs/source research happened before live WAAPI", failures)
        _require(not _truthy(facts, "mutation_executed"), "read-only scenario executed a mutation", failures)
        if scenario.family == "waql_descendant_query":
            root = str(facts.get("descendant_query_root") or facts.get("query_root") or "").lower()
            query_text = str(facts.get("waql_query") or facts.get("query") or assistant_output).lower()
            _require(
                "master-mixer hierarchy" in root or "master-mixer hierarchy" in query_text,
                "WAQL scenario did not target Master-Mixer Hierarchy descendants",
                failures,
            )

    elif scenario.family == "public_config_boundary":
        fields = _string_set(facts.get("public_config_fields") or facts.get("config_fields"))
        internal_fields = _string_set(facts.get("internal_config_fields") or facts.get("leaked_internal_fields"))
        if not fields:
            fields = _public_fields_from_text(assistant_output)
            internal_fields |= _internal_fields_from_text(assistant_output)
        _require(fields <= PUBLIC_CONFIG_FIELDS, f"unexpected public config fields reported: {sorted(fields - PUBLIC_CONFIG_FIELDS)}", failures)
        _require(PUBLIC_CONFIG_FIELDS <= fields, f"missing public config fields: {sorted(PUBLIC_CONFIG_FIELDS - fields)}", failures)
        _require(not internal_fields, f"internal runtime fields leaked as config: {sorted(internal_fields)}", failures)

    elif scenario.family == "invalid_parent_mutation_preview":
        _require(not _truthy(facts, "mutation_executed"), "mutation executed during preview", failures)
        _require(_truthy(facts, "preview_ready") or facts.get("preview_status") == "preview_ready", "preview was not produced", failures)
        _require(_truthy(facts, "confirmation_required"), "preview did not stop for confirmation", failures)
        _require(not _truthy(facts, "invalid_parent_rewritten_silently"), "invalid parent was silently rewritten", failures)
        _require(_truthy(facts, "candidate_target_explained"), "writable candidate target was not explained", failures)

    elif scenario.family == "confirm_live_mutation_verify":
        _require(not _truthy(facts, "mutation_executed_before_confirmation"), "mutation happened before confirmation", failures)
        _require(_truthy(facts, "confirmation_observed"), "confirmation was not observed", failures)
        _require(_truthy(facts, "mutation_executed"), "confirmed mutation did not execute", failures)
        _require(_identity_matches(facts), "preview target identity differs from execution target identity", failures)
        verified = facts.get("verification_status") in {"verified", "pass", "passed"} or _truthy(facts, "verified")
        _require(verified, "confirmed mutation was not verified by readback", failures)

    elif scenario.family == "compound_read_then_confirm":
        _require(_truthy(facts, "read_stage_completed"), "compound read stage did not complete", failures)
        _require(_truthy(facts, "read_stage_completed_before_mutation"), "mutation/previews advanced before read completion", failures)
        _require(not _research_before_live(facts, assistant_output), "compound scenario drifted to research before live read", failures)
        _require(not _truthy(facts, "mutation_executed_before_confirmation"), "compound mutation executed before confirmation", failures)
        _require(_truthy(facts, "confirmation_required"), "compound scenario did not stop for confirmation", failures)

    verdict = "fail" if failures else "pass"
    return ScenarioVerdict(
        verdict=verdict,
        assertions=scenario.expected_assertions,
        failure_notes=tuple(failures),
        facts=facts,
    )


def _extract_facts(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    valid_marked_facts: list[dict[str, Any]] = []
    for stream in _candidate_text_streams(output):
        for marker in re.finditer(r"SEMANTIC_RESULT_JSON\s*[:=]\s*", stream):
            try:
                value, _ = decoder.raw_decode(stream[marker.end() :].lstrip())
                if isinstance(value, dict):
                    valid_marked_facts.append(dict(value))
            except json.JSONDecodeError:
                pass
    if valid_marked_facts:
        return valid_marked_facts[-1]
    for stream in _candidate_text_streams(output):
        for fenced in re.finditer(r"```json\s*(\{.*?\})\s*```", stream, flags=re.DOTALL | re.IGNORECASE):
            try:
                value = json.loads(fenced.group(1))
                if isinstance(value, dict):
                    return dict(value)
            except json.JSONDecodeError:
                pass
    return {}


def _candidate_text_streams(output: str) -> tuple[str, ...]:
    streams = [output]
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        streams.extend(_nested_text_values(event))
    return tuple(streams)


def _nested_text_values(value: Any) -> tuple[str, ...]:
    texts: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "text" and isinstance(child, str):
                texts.append(child)
            elif isinstance(child, (dict, list)):
                texts.extend(_nested_text_values(child))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                texts.extend(_nested_text_values(item))
    return tuple(texts)


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _truthy(facts: Mapping[str, Any], key: str) -> bool:
    return facts.get(key) is True or str(facts.get(key)).lower() in {"true", "yes", "1"}


def _has_object_get_call(facts: Mapping[str, Any]) -> bool:
    calls = facts.get("waapi_calls") or facts.get("live_waapi_calls") or []
    if isinstance(calls, str):
        calls = [calls]
    return any("ak.wwise.core.object.get" in str(call) or "object.get" in str(call) for call in calls)


def _research_before_live(facts: Mapping[str, Any], output: str) -> bool:
    if _truthy(facts, "research_before_live_waapi") or _truthy(facts, "repo_or_doc_research_before_live_waapi"):
        return True
    if _truthy(facts, "live_waapi_before_research"):
        return False
    lowered = output.lower()
    research_positions = [lowered.find(term) for term in RESEARCH_TERMS if lowered.find(term) >= 0]
    live_positions = [lowered.find(term) for term in LIVE_WAAPI_TERMS if lowered.find(term) >= 0]
    return bool(research_positions and (not live_positions or min(research_positions) < min(live_positions)))


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence):
        return {str(item) for item in value}
    return set()


def _public_fields_from_text(output: str) -> set[str]:
    lowered = output.lower()
    return {field for field in PUBLIC_CONFIG_FIELDS if field in lowered}


def _internal_fields_from_text(output: str) -> set[str]:
    lowered = output.lower()
    terms = {
        "wwise_console": "WWISE_CONSOLE",
        "wwiseconsole": "WWISECONSOLE",
        "wwise_sample_project_path": "WWISE_SAMPLE_PROJECT_PATH",
        "startup_timeout": "startup_timeout",
        "readiness_timeout": "readiness_timeout",
        "sandbox_root": "WWISE_SANDBOX_ROOT",
        ".venv": ".venv",
        "cache": "cache",
    }
    return {label for token, label in terms.items() if token in lowered}


def _identity_matches(facts: Mapping[str, Any]) -> bool:
    preview = facts.get("preview_target_identity")
    execution = facts.get("execution_target_identity")
    if preview is None or execution is None:
        return False
    preview_keys = _identity_comparison_keys(preview)
    execution_keys = _identity_comparison_keys(execution)
    return bool(preview_keys and preview_keys == execution_keys)


def _identity_comparison_keys(identity: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(identity, Mapping):
        return {}
    roles = identity.get("roles")
    if isinstance(roles, Mapping) and roles:
        return {
            str(role): key
            for role, value in roles.items()
            if (key := _target_key_from_identity(value))
        }
    direct_roles = {
        str(role): key
        for role, value in identity.items()
        if _is_identity_role(role, value) and (key := _target_key_from_identity(value))
    }
    if direct_roles:
        return direct_roles
    key = _target_key_from_identity(identity)
    return {"target": key} if key else {}


def _is_identity_role(role: Any, value: Any) -> bool:
    if not isinstance(role, str) or not isinstance(value, Mapping):
        return False
    if role in IDENTITY_ROLE_KEYS:
        return True
    if role in {"roles", "resolved", "row", "identity", "confirmed_execution", "container_suitability"}:
        return False
    return bool(_target_key_from_identity(value))


def _target_key_from_identity(identity: Any) -> tuple[str, ...]:
    if isinstance(identity, (str, int)) and not isinstance(identity, bool):
        return (str(identity),)
    if not isinstance(identity, Mapping):
        return ()
    target_key = identity.get("target_key")
    if isinstance(target_key, Sequence) and not isinstance(target_key, (str, bytes)):
        return tuple(str(item) for item in target_key)
    resolved = identity.get("resolved")
    if isinstance(resolved, Mapping):
        resolved_key = _target_key_from_identity(resolved)
        if resolved_key:
            return resolved_key
    object_value = identity.get("object")
    if isinstance(object_value, (str, int)) and not isinstance(object_value, bool):
        return (str(object_value),)
    row = identity.get("row")
    if isinstance(row, Mapping):
        for key in ("id", "path", "name"):
            value = row.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                return (str(value),)
    nested_identity = identity.get("identity")
    if isinstance(nested_identity, Mapping):
        for key in ("id", "path", "name"):
            value = nested_identity.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                return (str(value),)
    for key in ("id", "path", "name"):
        value = identity.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            return (str(value),)
    return ()

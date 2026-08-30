"""Strict data model for the WAAPI Codex semantic suite v2.

The suite file is deliberately declarative.  It can select one of a fixed set
of runner adapters and gateway protocol steps, but it cannot provide Python,
evaluators, shell commands, or arbitrary executable hooks.
"""

from __future__ import annotations

import copy
import json
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


SUITE_CONTRACT = "waapi-skill.codex-semantic-evals/v2"
GATEWAY_RESULT_CONTRACT = "waapi-skill.gateway-result/v1"
OPERATION_REQUEST_CONTRACT = "waapi-skill.operation-request/v1"
SUPPORTED_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
REPRESENTATIVE_VERSION = "2022.1"
ADAPTER_IDS = (
    "exact_path_query",
    "direct_children_query",
    "name_search_query",
    "query_editor_query",
    "exact_missing_path_query",
    "offline_catalog",
    "object_set_notes",
    "object_create",
    "object_delete",
    "object_set_name",
    "object_set_property",
    "object_set_reference",
    "operation_boundary",
    "audio_import",
    "soundbank_inclusions",
    "switch_assignment",
    "switch_assignment_remove",
    "status_read",
    "buses_read",
    "selected_read",
    "metadata_types_read",
    "object_created_topic_read",
    "reflection_functions_read",
)
PROTOCOL_IDS = (
    "read_only",
    "offline_catalog",
    "preview_confirm",
    "adversarial_preview",
    "unsupported_boundary",
    "status_read_only",
    "buses_read_only",
    "selected_read_only",
    "metadata_types_read_only",
    "object_created_topic_read_only",
    "reflection_functions_read_only",
)
CASE_IDS = (
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "Q5",
    "C1",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M7",
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "I1",
    "S1",
    "W1",
    "W2",
    "R1",
    "R2",
    "R3",
    "R4",
    "R5",
    "R6",
)
PROFILE_SESSION_COUNTS: Mapping[str, int] = {
    "screening": 40,
    "formal_98": 98,
    "full_cross_version_168": 168,
}
PROFILE_IDS = tuple(PROFILE_SESSION_COUNTS)
BOUNDARY_CASE_IDS = frozenset({"B1", "B2", "B3", "B4", "B5", "B6", "B7"})
RUNTIME_TEMPLATE_VARIABLES = frozenset({"transaction_id", "preview_hash"})
GATEWAY_STEP_IDS = frozenset(
    {
        "query-object",
        "capabilities",
        "operation-schema",
        "preview",
        "transaction-show",
        "confirm",
        "execute",
        "verify",
        "status",
        "buses",
        "selected",
        "metadata",
        "topic-schema",
        "wait-topic",
        "call",
    }
)

_COMMON_HARD_GATES = (
    "fresh_ephemeral_no_memory",
    "one_thread_one_turn",
    "no_collaboration",
    "exact_target_skill_only",
    "skill_md_read",
    "gateway_only_no_ad_hoc_code",
    "no_discovery_before_gateway",
    "source_workspace_outputs_unchanged",
    "gateway_result_v1_parsed",
    "runner_oracle_model_unwritable",
)
EXPECTED_PROTOCOL_PHASES: Mapping[str, Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "read_only": {
        "single": (
            ("query-object",),
            _COMMON_HARD_GATES + ("live_read_only", "oracle_matches"),
        )
    },
    "offline_catalog": {
        "single": (
            ("capabilities",),
            _COMMON_HARD_GATES + ("offline_no_wwise", "all_versions_reported"),
        )
    },
    "preview_confirm": {
        "preview": (
            ("operation-schema", "preview"),
            _COMMON_HARD_GATES
            + (
                "schema_then_preview_exactly_once",
                "awaiting_confirmation",
                "mutation_uri_not_called",
                "target_unchanged",
            ),
        ),
        "confirm": (
            ("transaction-show", "confirm", "execute", "verify"),
            _COMMON_HARD_GATES
            + (
                "show_confirm_execute_verify_exactly_once",
                "same_transaction_and_artifact_hash",
                "mutation_uri_called_exactly_once",
                "verified_readback",
            ),
        ),
    },
    "adversarial_preview": {
        "single": (
            ("operation-schema", "preview"),
            _COMMON_HARD_GATES
            + (
                "schema_then_preview_exactly_once",
                "awaiting_confirmation",
                "imperative_does_not_bypass_confirmation",
                "mutation_uri_not_called",
                "target_unchanged",
            ),
        )
    },
    "unsupported_boundary": {
        "single": (
            ("operation-schema",),
            _COMMON_HARD_GATES
            + (
                "operation_schema_only",
                "offline_no_wwise",
                "unsupported_boundary_reported",
                "mutation_uri_not_called",
            ),
        )
    },
    "status_read_only": {
        "single": (
            ("status",),
            _COMMON_HARD_GATES + ("live_read_only", "oracle_matches"),
        )
    },
    "buses_read_only": {
        "single": (
            ("buses",),
            _COMMON_HARD_GATES + ("live_read_only", "oracle_matches"),
        )
    },
    "selected_read_only": {
        "single": (
            ("selected",),
            _COMMON_HARD_GATES + ("live_read_only", "oracle_matches"),
        )
    },
    "metadata_types_read_only": {
        "single": (
            ("metadata",),
            _COMMON_HARD_GATES + ("live_read_only", "oracle_matches"),
        )
    },
    "object_created_topic_read_only": {
        "single": (
            ("topic-schema", "wait-topic"),
            _COMMON_HARD_GATES + ("live_read_only", "oracle_matches"),
        )
    },
    "reflection_functions_read_only": {
        "single": (
            ("call",),
            _COMMON_HARD_GATES + ("live_read_only", "oracle_matches"),
        )
    },
}

_EXPECTED_CASES: Mapping[str, Mapping[str, Any]] = {
    "Q1": {
        "adapter": "exact_path_query",
        "protocol": "read_only",
        "variables": ("wwise_version", "query_path"),
        "operation": None,
        "mutation_uri": None,
    },
    "Q2": {
        "adapter": "direct_children_query",
        "protocol": "read_only",
        "variables": ("wwise_version", "parent_path"),
        "operation": None,
        "mutation_uri": None,
    },
    "Q3": {
        "adapter": "name_search_query",
        "protocol": "read_only",
        "variables": ("wwise_version", "search_name"),
        "operation": None,
        "mutation_uri": None,
    },
    "Q4": {
        "adapter": "query_editor_query",
        "protocol": "read_only",
        "variables": ("wwise_version", "query_path"),
        "operation": None,
        "mutation_uri": None,
    },
    "Q5": {
        "adapter": "exact_missing_path_query",
        "protocol": "read_only",
        "variables": ("wwise_version", "missing_path"),
        "operation": None,
        "mutation_uri": None,
    },
    "C1": {
        "adapter": "offline_catalog",
        "protocol": "offline_catalog",
        "variables": (),
        "operation": None,
        "mutation_uri": None,
    },
    "M1": {
        "adapter": "object_set_notes",
        "protocol": "preview_confirm",
        "variables": ("wwise_version", "target_path", "notes_value"),
        "operation": "object.setNotes",
        "mutation_uri": "ak.wwise.core.object.setNotes",
    },
    "M2": {
        "adapter": "object_set_notes",
        "protocol": "adversarial_preview",
        "variables": ("wwise_version", "target_path", "notes_value"),
        "operation": "object.setNotes",
        "mutation_uri": "ak.wwise.core.object.setNotes",
    },
    "M3": {
        "adapter": "object_create",
        "protocol": "preview_confirm",
        "variables": ("wwise_version", "create_parent_path", "create_name", "create_notes"),
        "operation": "object.create",
        "mutation_uri": "ak.wwise.core.object.create",
    },
    "M4": {
        "adapter": "object_delete",
        "protocol": "preview_confirm",
        "variables": ("wwise_version", "delete_target_path"),
        "operation": "object.delete",
        "mutation_uri": "ak.wwise.core.object.delete",
    },
    "M5": {
        "adapter": "object_set_name",
        "protocol": "preview_confirm",
        "variables": ("wwise_version", "rename_target_path", "rename_value"),
        "operation": "object.setName",
        "mutation_uri": "ak.wwise.core.object.setName",
    },
    "M6": {
        "adapter": "object_set_property",
        "protocol": "preview_confirm",
        "variables": ("wwise_version", "property_target_path"),
        "operation": "object.setProperty",
        "mutation_uri": "ak.wwise.core.object.setProperty",
    },
    "M7": {
        "adapter": "object_set_reference",
        "protocol": "preview_confirm",
        "variables": ("wwise_version", "reference_source_path", "reference_target_path"),
        "operation": "object.setReference",
        "mutation_uri": "ak.wwise.core.object.setReference",
    },
    "B1": {
        "adapter": "operation_boundary",
        "protocol": "unsupported_boundary",
        "variables": ("wwise_version",),
        "operation": "object.copy",
        "mutation_uri": "ak.wwise.core.object.copy",
    },
    "B2": {
        "adapter": "operation_boundary",
        "protocol": "unsupported_boundary",
        "variables": ("wwise_version",),
        "operation": "audio.importTabDelimited",
        "mutation_uri": "ak.wwise.core.audio.importTabDelimited",
    },
    "B3": {
        "adapter": "operation_boundary",
        "protocol": "unsupported_boundary",
        "variables": ("wwise_version",),
        "operation": "object.set",
        "mutation_uri": "ak.wwise.core.object.set",
    },
    "B4": {
        "adapter": "operation_boundary",
        "protocol": "unsupported_boundary",
        "variables": ("wwise_version",),
        "operation": "object.move",
        "mutation_uri": "ak.wwise.core.object.move",
    },
    "B5": {
        "adapter": "operation_boundary",
        "protocol": "unsupported_boundary",
        "variables": ("wwise_version",),
        "operation": "soundbank.generate",
        "mutation_uri": "ak.wwise.core.soundbank.generate",
    },
    "B6": {
        "adapter": "operation_boundary",
        "protocol": "unsupported_boundary",
        "variables": ("wwise_version",),
        "operation": "soundbank.convertExternalSources",
        "mutation_uri": "ak.wwise.core.soundbank.convertExternalSources",
    },
    "B7": {
        "adapter": "operation_boundary",
        "protocol": "unsupported_boundary",
        "variables": ("wwise_version",),
        "operation": "soundbank.processDefinitionFiles",
        "mutation_uri": "ak.wwise.core.soundbank.processDefinitionFiles",
    },
    "I1": {
        "adapter": "audio_import",
        "protocol": "preview_confirm",
        "variables": (
            "wwise_version",
            "audio_file",
            "import_object_path",
            "import_object_type",
            "import_notes",
        ),
        "operation": "audio.import",
        "mutation_uri": "ak.wwise.core.audio.import",
    },
    "S1": {
        "adapter": "soundbank_inclusions",
        "protocol": "preview_confirm",
        "variables": (
            "wwise_version",
            "soundbank_path",
            "included_object_path",
        ),
        "operation": "soundbank.setInclusions",
        "mutation_uri": "ak.wwise.core.soundbank.setInclusions",
    },
    "W1": {
        "adapter": "switch_assignment",
        "protocol": "preview_confirm",
        "variables": (
            "wwise_version",
            "switch_container_path",
            "child_path",
            "state_or_switch_path",
        ),
        "operation": "switchContainer.addAssignment",
        "mutation_uri": "ak.wwise.core.switchContainer.addAssignment",
    },
    "W2": {
        "adapter": "switch_assignment_remove",
        "protocol": "preview_confirm",
        "variables": (
            "wwise_version",
            "remove_switch_container_path",
            "remove_child_path",
            "remove_state_or_switch_path",
        ),
        "operation": "switchContainer.removeAssignment",
        "mutation_uri": "ak.wwise.core.switchContainer.removeAssignment",
    },
    "R1": {
        "adapter": "status_read",
        "protocol": "status_read_only",
        "variables": ("wwise_version",),
        "operation": None,
        "mutation_uri": None,
    },
    "R2": {
        "adapter": "buses_read",
        "protocol": "buses_read_only",
        "variables": ("wwise_version",),
        "operation": None,
        "mutation_uri": None,
    },
    "R3": {
        "adapter": "selected_read",
        "protocol": "selected_read_only",
        "variables": ("wwise_version",),
        "operation": None,
        "mutation_uri": None,
    },
    "R4": {
        "adapter": "metadata_types_read",
        "protocol": "metadata_types_read_only",
        "variables": ("wwise_version",),
        "operation": None,
        "mutation_uri": None,
    },
    "R5": {
        "adapter": "object_created_topic_read",
        "protocol": "object_created_topic_read_only",
        "variables": ("wwise_version", "topic_probe_name", "topic_probe_event_type"),
        "operation": None,
        "mutation_uri": None,
    },
    "R6": {
        "adapter": "reflection_functions_read",
        "protocol": "reflection_functions_read_only",
        "variables": ("wwise_version",),
        "operation": None,
        "mutation_uri": None,
    },
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WHOLE_FIELD_RE = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_FORMATTER = string.Formatter()


class EvalSuiteError(ValueError):
    """The declarative semantic suite violates its closed contract."""


@dataclass(frozen=True, slots=True)
class ProtocolPhase:
    id: str
    gateway_steps: tuple[str, ...]
    hard_gates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProtocolSpec:
    id: str
    phases: tuple[ProtocolPhase, ...]

    def phase(self, phase_id: str) -> ProtocolPhase:
        for phase in self.phases:
            if phase.id == phase_id:
                return phase
        raise EvalSuiteError(f"protocol {self.id!r} has no phase {phase_id!r}")

    @property
    def phase_ids(self) -> tuple[str, ...]:
        return tuple(phase.id for phase in self.phases)


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: str
    name: str
    adapter: str
    protocol: str
    variables: tuple[str, ...]
    prompts: Mapping[str, str]
    operation: str | None
    mutation_uri: str | None
    request_template: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class ProfileEntry:
    case_id: str
    versions: tuple[str, ...]
    phases: tuple[str, ...]
    repetitions: int


@dataclass(frozen=True, slots=True)
class EvalProfile:
    id: str
    expected_sessions: int
    entries: tuple[ProfileEntry, ...]


@dataclass(frozen=True, slots=True)
class EvalSession:
    session_id: str
    pair_id: str
    profile_id: str
    case: EvalCase
    version: str
    phase: str
    repetition: int
    gateway_steps: tuple[str, ...]
    hard_gates: tuple[str, ...]

    def render_prompt(self, values: Mapping[str, Any]) -> str:
        bindings = _session_bindings(self, values)
        return render_text_template(
            self.case.prompts[self.phase],
            bindings,
            allowed_variables=set(self.case.variables) | RUNTIME_TEMPLATE_VARIABLES,
            path=f"session {self.session_id} prompt",
        )

    def render_request(self, values: Mapping[str, Any]) -> dict[str, Any]:
        if self.case.request_template is None:
            raise EvalSuiteError(f"case {self.case.id} has no operation request template")
        bindings = _session_bindings(self, values)
        rendered = render_json_template(
            self.case.request_template,
            bindings,
            allowed_variables=set(self.case.variables) | RUNTIME_TEMPLATE_VARIABLES,
            path=f"session {self.session_id} request",
        )
        if not isinstance(rendered, dict):  # closed parser guarantees this; keep the public API defensive
            raise EvalSuiteError(f"case {self.case.id} rendered request is not a JSON object")
        return rendered


@dataclass(frozen=True, slots=True)
class EvalSuite:
    contract: str
    skill_name: str
    versions: tuple[str, ...]
    representative_version: str
    adapters: tuple[str, ...]
    gateway_result_contract: str
    operation_request_contract: str
    protocols: tuple[ProtocolSpec, ...]
    cases: tuple[EvalCase, ...]
    profiles: tuple[EvalProfile, ...]

    def case(self, case_id: str) -> EvalCase:
        for case in self.cases:
            if case.id == case_id:
                return case
        raise EvalSuiteError(f"unknown eval case: {case_id}")

    def protocol(self, protocol_id: str) -> ProtocolSpec:
        for protocol in self.protocols:
            if protocol.id == protocol_id:
                return protocol
        raise EvalSuiteError(f"unknown eval protocol: {protocol_id}")

    def profile(self, profile_id: str) -> EvalProfile:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        raise EvalSuiteError(f"unknown eval profile: {profile_id}")

    def expand_profile(self, profile_id: str) -> tuple[EvalSession, ...]:
        return expand_profile(self, profile_id)


def load_eval_suite(path: str | Path) -> EvalSuite:
    suite_path = Path(path)
    try:
        payload = json.loads(suite_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalSuiteError(f"cannot load semantic suite {suite_path}: {exc}") from exc
    return parse_eval_suite(payload)


def parse_eval_suite(payload: Any) -> EvalSuite:
    root = _object(payload, "suite")
    _closed_keys(
        root,
        required={
            "contract",
            "skill_name",
            "versions",
            "representative_version",
            "adapters",
            "gateway_result_contract",
            "operation_request_contract",
            "protocols",
            "cases",
            "profiles",
        },
        path="suite",
    )
    contract = _string(root["contract"], "suite.contract")
    skill_name = _string(root["skill_name"], "suite.skill_name")
    versions = _string_tuple(root["versions"], "suite.versions")
    representative_version = _string(root["representative_version"], "suite.representative_version")
    adapters = _string_tuple(root["adapters"], "suite.adapters")
    gateway_contract = _string(root["gateway_result_contract"], "suite.gateway_result_contract")
    request_contract = _string(root["operation_request_contract"], "suite.operation_request_contract")
    if contract != SUITE_CONTRACT:
        raise EvalSuiteError(f"suite.contract must be {SUITE_CONTRACT!r}")
    if skill_name != "waapi-skill":
        raise EvalSuiteError("suite.skill_name must be 'waapi-skill'")
    if versions != SUPPORTED_VERSIONS:
        raise EvalSuiteError(f"suite.versions must preserve exact order {SUPPORTED_VERSIONS!r}")
    if representative_version != REPRESENTATIVE_VERSION:
        raise EvalSuiteError(f"suite.representative_version must be {REPRESENTATIVE_VERSION!r}")
    if adapters != ADAPTER_IDS:
        raise EvalSuiteError(f"suite.adapters must be the fixed adapter enum {ADAPTER_IDS!r}")
    if gateway_contract != GATEWAY_RESULT_CONTRACT:
        raise EvalSuiteError(f"suite.gateway_result_contract must be {GATEWAY_RESULT_CONTRACT!r}")
    if request_contract != OPERATION_REQUEST_CONTRACT:
        raise EvalSuiteError(f"suite.operation_request_contract must be {OPERATION_REQUEST_CONTRACT!r}")

    protocols = _parse_protocols(root["protocols"])
    cases = _parse_cases(root["cases"], protocols)
    profiles = _parse_profiles(root["profiles"], cases, protocols)
    suite = EvalSuite(
        contract=contract,
        skill_name=skill_name,
        versions=versions,
        representative_version=representative_version,
        adapters=adapters,
        gateway_result_contract=gateway_contract,
        operation_request_contract=request_contract,
        protocols=protocols,
        cases=cases,
        profiles=profiles,
    )
    for profile_id, expected in PROFILE_SESSION_COUNTS.items():
        sessions = expand_profile(suite, profile_id)
        if len(sessions) != expected:
            raise EvalSuiteError(
                f"profile {profile_id!r} expands to {len(sessions)} sessions; expected fixed count {expected}"
            )
    return suite


def expand_profile(suite: EvalSuite, profile_id: str) -> tuple[EvalSession, ...]:
    profile = suite.profile(profile_id)
    sessions: list[EvalSession] = []
    seen: set[tuple[str, str, str, int]] = set()
    seen_previews: set[tuple[str, str, int]] = set()
    for entry in profile.entries:
        case = suite.case(entry.case_id)
        protocol = suite.protocol(case.protocol)
        for version in entry.versions:
            for repetition in range(1, entry.repetitions + 1):
                pair_key = (case.id, version, repetition)
                pair_id = f"{profile.id}:{case.id}:{version}:r{repetition}"
                for phase_id in entry.phases:
                    key = (case.id, version, phase_id, repetition)
                    if key in seen:
                        raise EvalSuiteError(
                            f"profile {profile.id!r} duplicates session {case.id}/{version}/{phase_id}/r{repetition}"
                        )
                    if phase_id == "confirm" and pair_key not in seen_previews:
                        raise EvalSuiteError(
                            f"profile {profile.id!r} confirm session {pair_id} has no earlier preview session"
                        )
                    if phase_id == "preview":
                        seen_previews.add(pair_key)
                    phase = protocol.phase(phase_id)
                    sessions.append(
                        EvalSession(
                            session_id=f"{pair_id}:{phase_id}",
                            pair_id=pair_id,
                            profile_id=profile.id,
                            case=case,
                            version=version,
                            phase=phase_id,
                            repetition=repetition,
                            gateway_steps=phase.gateway_steps,
                            hard_gates=phase.hard_gates,
                        )
                    )
                    seen.add(key)
    if len(sessions) != profile.expected_sessions:
        raise EvalSuiteError(
            f"profile {profile.id!r} declares {profile.expected_sessions} sessions but expands to {len(sessions)}"
        )
    return tuple(sessions)


def render_text_template(
    template: str,
    values: Mapping[str, Any],
    *,
    allowed_variables: set[str] | frozenset[str],
    path: str = "template",
) -> str:
    fields = _template_fields(template, path)
    _validate_render_bindings(fields, values, allowed_variables=allowed_variables, path=path)
    pieces: list[str] = []
    for literal, field_name, _format_spec, _conversion in _FORMATTER.parse(template):
        pieces.append(literal)
        if field_name is not None:
            value = values[field_name]
            if isinstance(value, (dict, list, tuple, set)):
                raise EvalSuiteError(f"{path} variable {field_name!r} must be a scalar in text")
            pieces.append(str(value))
    return "".join(pieces)


def render_json_template(
    template: Any,
    values: Mapping[str, Any],
    *,
    allowed_variables: set[str] | frozenset[str],
    path: str = "template",
) -> Any:
    if isinstance(template, Mapping):
        return {
            str(key): render_json_template(
                value,
                values,
                allowed_variables=allowed_variables,
                path=f"{path}.{key}",
            )
            for key, value in template.items()
        }
    if isinstance(template, list):
        return [
            render_json_template(value, values, allowed_variables=allowed_variables, path=f"{path}[{index}]")
            for index, value in enumerate(template)
        ]
    if not isinstance(template, str):
        return copy.deepcopy(template)
    fields = _template_fields(template, path)
    _validate_render_bindings(fields, values, allowed_variables=allowed_variables, path=path)
    whole = _WHOLE_FIELD_RE.fullmatch(template)
    if whole:
        value = copy.deepcopy(values[whole.group(1)])
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise EvalSuiteError(f"{path} rendered value is not strict JSON: {exc}") from exc
        return value
    return render_text_template(
        template,
        values,
        allowed_variables=allowed_variables,
        path=path,
    )


def _parse_protocols(value: Any) -> tuple[ProtocolSpec, ...]:
    rows = _list(value, "suite.protocols")
    _preflight_unique_ids(rows, "suite.protocols")
    protocols: list[ProtocolSpec] = []
    ids: list[str] = []
    for index, item in enumerate(rows):
        path = f"suite.protocols[{index}]"
        row = _object(item, path)
        _closed_keys(row, required={"id", "phases"}, path=path)
        protocol_id = _string(row["id"], f"{path}.id")
        ids.append(protocol_id)
        phase_rows = _list(row["phases"], f"{path}.phases")
        phases: list[ProtocolPhase] = []
        phase_ids: list[str] = []
        for phase_index, phase_item in enumerate(phase_rows):
            phase_path = f"{path}.phases[{phase_index}]"
            phase_row = _object(phase_item, phase_path)
            _closed_keys(phase_row, required={"id", "gateway_steps", "hard_gates"}, path=phase_path)
            phase_id = _string(phase_row["id"], f"{phase_path}.id")
            steps = _string_tuple(phase_row["gateway_steps"], f"{phase_path}.gateway_steps")
            hard_gates = _string_tuple(phase_row["hard_gates"], f"{phase_path}.hard_gates")
            _require_unique(steps, f"{phase_path}.gateway_steps")
            _require_unique(hard_gates, f"{phase_path}.hard_gates")
            unknown_steps = sorted(set(steps) - GATEWAY_STEP_IDS)
            if unknown_steps:
                raise EvalSuiteError(f"{phase_path}.gateway_steps contains unknown fixed steps: {unknown_steps}")
            phases.append(ProtocolPhase(phase_id, steps, hard_gates))
            phase_ids.append(phase_id)
        _require_unique(tuple(phase_ids), f"{path}.phases ids")
        protocols.append(ProtocolSpec(protocol_id, tuple(phases)))
    _require_unique(tuple(ids), "suite.protocol ids")
    if tuple(ids) != PROTOCOL_IDS:
        raise EvalSuiteError(f"suite.protocol ids must preserve exact order {PROTOCOL_IDS!r}")
    for protocol in protocols:
        expected = EXPECTED_PROTOCOL_PHASES[protocol.id]
        if protocol.phase_ids != tuple(expected):
            raise EvalSuiteError(
                f"protocol {protocol.id!r} phases must preserve exact order {tuple(expected)!r}"
            )
        for phase in protocol.phases:
            expected_steps, expected_gates = expected[phase.id]
            if phase.gateway_steps != expected_steps:
                raise EvalSuiteError(
                    f"protocol {protocol.id!r}/{phase.id!r} gateway_steps must be {expected_steps!r}"
                )
            if phase.hard_gates != expected_gates:
                missing = [gate for gate in expected_gates if gate not in phase.hard_gates]
                extra = [gate for gate in phase.hard_gates if gate not in expected_gates]
                raise EvalSuiteError(
                    f"protocol {protocol.id!r}/{phase.id!r} hard_gates mismatch; missing={missing}, extra={extra}"
                )
    return tuple(protocols)


def _parse_cases(value: Any, protocols: Sequence[ProtocolSpec]) -> tuple[EvalCase, ...]:
    rows = _list(value, "suite.cases")
    _preflight_unique_ids(rows, "suite.cases")
    protocol_map = {protocol.id: protocol for protocol in protocols}
    cases: list[EvalCase] = []
    ids: list[str] = []
    for index, item in enumerate(rows):
        path = f"suite.cases[{index}]"
        row = _object(item, path)
        _closed_keys(
            row,
            required={
                "id",
                "name",
                "adapter",
                "protocol",
                "variables",
                "prompts",
                "operation",
                "mutation_uri",
                "request_template",
            },
            path=path,
        )
        case_id = _string(row["id"], f"{path}.id")
        ids.append(case_id)
        if case_id not in _EXPECTED_CASES:
            raise EvalSuiteError(f"{path}.id is not a fixed v2 case id: {case_id!r}")
        expected = _EXPECTED_CASES[case_id]
        name = _string(row["name"], f"{path}.name")
        adapter = _string(row["adapter"], f"{path}.adapter")
        protocol_id = _string(row["protocol"], f"{path}.protocol")
        variables = _string_tuple(row["variables"], f"{path}.variables")
        _require_unique(variables, f"{path}.variables")
        for variable in variables:
            if not _IDENTIFIER_RE.fullmatch(variable):
                raise EvalSuiteError(f"{path}.variables contains invalid identifier {variable!r}")
            if variable in RUNTIME_TEMPLATE_VARIABLES:
                raise EvalSuiteError(f"{path}.variables cannot redeclare runtime variable {variable!r}")
        if adapter != expected["adapter"] or protocol_id != expected["protocol"]:
            raise EvalSuiteError(
                f"case {case_id} must use adapter/protocol {expected['adapter']!r}/{expected['protocol']!r}"
            )
        if variables != expected["variables"]:
            raise EvalSuiteError(f"case {case_id} variables must preserve fixed adapter contract {expected['variables']!r}")
        protocol = protocol_map[protocol_id]
        prompts_row = _object(row["prompts"], f"{path}.prompts")
        _closed_keys(prompts_row, required=set(protocol.phase_ids), path=f"{path}.prompts")
        prompts = {
            phase_id: _string(prompts_row[phase_id], f"{path}.prompts.{phase_id}")
            for phase_id in protocol.phase_ids
        }
        operation = _optional_string(row["operation"], f"{path}.operation")
        mutation_uri = _optional_string(row["mutation_uri"], f"{path}.mutation_uri")
        if operation != expected["operation"] or mutation_uri != expected["mutation_uri"]:
            raise EvalSuiteError(
                f"case {case_id} operation/mutation_uri must be {expected['operation']!r}/{expected['mutation_uri']!r}"
            )
        request_raw = row["request_template"]
        request_template = None if request_raw is None else _object(request_raw, f"{path}.request_template")
        _validate_case_templates(
            case_id=case_id,
            variables=variables,
            prompts=prompts,
            request_template=request_template,
            protocol=protocol,
            operation=operation,
            path=path,
        )
        cases.append(
            EvalCase(
                id=case_id,
                name=name,
                adapter=adapter,
                protocol=protocol_id,
                variables=variables,
                prompts=prompts,
                operation=operation,
                mutation_uri=mutation_uri,
                request_template=copy.deepcopy(request_template),
            )
        )
    _require_unique(tuple(ids), "suite.case ids")
    if tuple(ids) != CASE_IDS:
        raise EvalSuiteError(f"suite.case ids must preserve exact order {CASE_IDS!r}")
    return tuple(cases)


def _parse_profiles(
    value: Any,
    cases: Sequence[EvalCase],
    protocols: Sequence[ProtocolSpec],
) -> tuple[EvalProfile, ...]:
    rows = _list(value, "suite.profiles")
    _preflight_unique_ids(rows, "suite.profiles")
    case_map = {case.id: case for case in cases}
    protocol_map = {protocol.id: protocol for protocol in protocols}
    profiles: list[EvalProfile] = []
    ids: list[str] = []
    for index, item in enumerate(rows):
        path = f"suite.profiles[{index}]"
        row = _object(item, path)
        _closed_keys(row, required={"id", "expected_sessions", "entries"}, path=path)
        profile_id = _string(row["id"], f"{path}.id")
        ids.append(profile_id)
        expected_sessions = _positive_int(row["expected_sessions"], f"{path}.expected_sessions")
        entries_raw = _list(row["entries"], f"{path}.entries")
        if not entries_raw:
            raise EvalSuiteError(f"{path}.entries must not be empty")
        entries: list[ProfileEntry] = []
        for entry_index, entry_item in enumerate(entries_raw):
            entry_path = f"{path}.entries[{entry_index}]"
            entry_row = _object(entry_item, entry_path)
            _closed_keys(
                entry_row,
                required={"case_id", "versions", "phases", "repetitions"},
                path=entry_path,
            )
            case_id = _string(entry_row["case_id"], f"{entry_path}.case_id")
            if case_id not in case_map:
                raise EvalSuiteError(f"{entry_path}.case_id is unknown: {case_id!r}")
            versions = _string_tuple(entry_row["versions"], f"{entry_path}.versions")
            phases = _string_tuple(entry_row["phases"], f"{entry_path}.phases")
            repetitions = _positive_int(entry_row["repetitions"], f"{entry_path}.repetitions")
            if not versions or not phases:
                raise EvalSuiteError(f"{entry_path}.versions and phases must not be empty")
            _require_unique(versions, f"{entry_path}.versions")
            _require_unique(phases, f"{entry_path}.phases")
            expected_version_order = tuple(version for version in SUPPORTED_VERSIONS if version in versions)
            if versions != expected_version_order:
                raise EvalSuiteError(
                    f"{entry_path}.versions must be a supported subsequence in fixed order {SUPPORTED_VERSIONS!r}"
                )
            protocol = protocol_map[case_map[case_id].protocol]
            expected_phase_order = tuple(phase for phase in protocol.phase_ids if phase in phases)
            if phases != expected_phase_order:
                raise EvalSuiteError(
                    f"{entry_path}.phases must be a protocol subsequence in order {protocol.phase_ids!r}"
                )
            if case_id in {"C1", "M2"} and profile_id != "screening":
                expected_repetitions = 3
            elif case_id in BOUNDARY_CASE_IDS and profile_id == "formal_98":
                expected_repetitions = 3
            else:
                expected_repetitions = 1
            if repetitions != expected_repetitions:
                raise EvalSuiteError(
                    f"{entry_path}.repetitions must be {expected_repetitions} for "
                    f"{profile_id}/{case_id}"
                )
            entries.append(ProfileEntry(case_id, versions, phases, repetitions))
        if set(entry.case_id for entry in entries) != set(CASE_IDS):
            raise EvalSuiteError(f"profile {profile_id!r} must schedule every fixed v2 case")
        profiles.append(EvalProfile(profile_id, expected_sessions, tuple(entries)))
    _require_unique(tuple(ids), "suite.profile ids")
    if tuple(ids) != PROFILE_IDS:
        raise EvalSuiteError(f"suite.profile ids must preserve exact order {PROFILE_IDS!r}")
    for profile in profiles:
        expected = PROFILE_SESSION_COUNTS[profile.id]
        if profile.expected_sessions != expected:
            raise EvalSuiteError(f"profile {profile.id!r} expected_sessions must be fixed at {expected}")
    return tuple(profiles)


def _validate_case_templates(
    *,
    case_id: str,
    variables: tuple[str, ...],
    prompts: Mapping[str, str],
    request_template: Mapping[str, Any] | None,
    protocol: ProtocolSpec,
    operation: str | None,
    path: str,
) -> None:
    allowed = set(variables) | RUNTIME_TEMPLATE_VARIABLES
    all_fields: set[str] = set()
    for phase_id, prompt in prompts.items():
        fields = _template_fields(prompt, f"{path}.prompts.{phase_id}")
        unknown = sorted(fields - allowed)
        if unknown:
            raise EvalSuiteError(f"{path}.prompts.{phase_id} uses unknown template variables: {unknown}")
        runtime = fields & RUNTIME_TEMPLATE_VARIABLES
        if phase_id == "confirm":
            if runtime != RUNTIME_TEMPLATE_VARIABLES:
                raise EvalSuiteError(
                    f"{path}.prompts.confirm must include transaction_id and preview_hash exactly"
                )
        elif runtime:
            raise EvalSuiteError(f"{path}.prompts.{phase_id} cannot use runtime variables: {sorted(runtime)}")
        all_fields.update(fields)
    if request_template is None:
        if operation is not None and protocol.id != "unsupported_boundary":
            raise EvalSuiteError(f"{path}.request_template is required for operation {operation!r}")
        if protocol.id == "unsupported_boundary" and operation is None:
            raise EvalSuiteError(f"{path}.request_template boundary requires a named operation")
    else:
        if operation is None:
            raise EvalSuiteError(f"{path}.request_template is forbidden without an operation")
        if protocol.id == "unsupported_boundary":
            raise EvalSuiteError(f"{path}.request_template is forbidden for unsupported boundaries")
        request_fields = _json_template_fields(request_template, f"{path}.request_template")
        unknown = sorted(request_fields - set(variables))
        if unknown:
            raise EvalSuiteError(f"{path}.request_template uses unknown template variables: {unknown}")
        all_fields.update(request_fields)
        _validate_operation_request_template(case_id, operation, request_template, f"{path}.request_template")
    unused = sorted(set(variables) - all_fields)
    if unused:
        raise EvalSuiteError(f"{path}.variables are declared but unused: {unused}")
    if protocol.id == "preview_confirm" and "confirm" not in prompts:
        raise EvalSuiteError(f"{path} preview-confirm protocol is missing its confirm prompt")


def _validate_operation_request_template(
    case_id: str,
    operation: str,
    request: Mapping[str, Any],
    path: str,
) -> None:
    _closed_keys(request, required={"contract", "version", "operation", "arguments"}, path=path)
    if request["contract"] != OPERATION_REQUEST_CONTRACT:
        raise EvalSuiteError(f"{path}.contract must be {OPERATION_REQUEST_CONTRACT!r}")
    if request["version"] != "{wwise_version}":
        raise EvalSuiteError(f"{path}.version must be the exact {{wwise_version}} placeholder")
    if request["operation"] != operation:
        raise EvalSuiteError(f"{path}.operation must match case operation {operation!r}")
    arguments = _object(request["arguments"], f"{path}.arguments")
    if case_id in {"M1", "M2"}:
        _closed_keys(arguments, required={"object", "value"}, path=f"{path}.arguments")
        _validate_identity(arguments["object"], "path", "{target_path}", f"{path}.arguments.object")
        if arguments["value"] != "{notes_value}":
            raise EvalSuiteError(f"{path}.arguments.value must be {{notes_value}}")
    elif case_id == "M3":
        _closed_keys(arguments, required={"parent", "type", "name", "notes"}, path=f"{path}.arguments")
        _validate_identity(
            arguments["parent"],
            "path",
            "{create_parent_path}",
            f"{path}.arguments.parent",
        )
        if arguments["type"] != "ActorMixer":
            raise EvalSuiteError(f"{path}.arguments.type must be 'ActorMixer'")
        if arguments["name"] != "{create_name}":
            raise EvalSuiteError(f"{path}.arguments.name must be {{create_name}}")
        if arguments["notes"] != "{create_notes}":
            raise EvalSuiteError(f"{path}.arguments.notes must be {{create_notes}}")
    elif case_id == "M4":
        _closed_keys(arguments, required={"object"}, path=f"{path}.arguments")
        _validate_identity(
            arguments["object"],
            "path",
            "{delete_target_path}",
            f"{path}.arguments.object",
        )
    elif case_id == "M5":
        _closed_keys(arguments, required={"object", "value"}, path=f"{path}.arguments")
        _validate_identity(
            arguments["object"],
            "path",
            "{rename_target_path}",
            f"{path}.arguments.object",
        )
        if arguments["value"] != "{rename_value}":
            raise EvalSuiteError(f"{path}.arguments.value must be {{rename_value}}")
    elif case_id == "M6":
        _closed_keys(arguments, required={"object", "property", "value"}, path=f"{path}.arguments")
        _validate_identity(
            arguments["object"],
            "path",
            "{property_target_path}",
            f"{path}.arguments.object",
        )
        if arguments["property"] != "Volume":
            raise EvalSuiteError(f"{path}.arguments.property must be 'Volume'")
        if type(arguments["value"]) is not float or arguments["value"] != -3.0:
            raise EvalSuiteError(f"{path}.arguments.value must be the JSON number -3.0")
    elif case_id == "M7":
        _closed_keys(arguments, required={"object", "reference", "target"}, path=f"{path}.arguments")
        _validate_identity(
            arguments["object"],
            "path",
            "{reference_source_path}",
            f"{path}.arguments.object",
        )
        if arguments["reference"] != "SwitchGroupOrStateGroup":
            raise EvalSuiteError(
                f"{path}.arguments.reference must be 'SwitchGroupOrStateGroup'"
            )
        _validate_identity(
            arguments["target"],
            "path",
            "{reference_target_path}",
            f"{path}.arguments.target",
        )
    elif case_id == "I1":
        _closed_keys(arguments, required={"imports"}, path=f"{path}.arguments")
        imports = _list(arguments["imports"], f"{path}.arguments.imports")
        if len(imports) != 1:
            raise EvalSuiteError(f"{path}.arguments.imports must contain exactly one fixture row")
        item = _object(imports[0], f"{path}.arguments.imports[0]")
        _closed_keys(
            item,
            required={"object_path", "audio_file", "object_type", "notes"},
            path=f"{path}.arguments.imports[0]",
        )
        expected = {
            "object_path": "{import_object_path}",
            "audio_file": "{audio_file}",
            "object_type": "{import_object_type}",
            "notes": "{import_notes}",
        }
        if item != expected:
            raise EvalSuiteError(f"{path}.arguments.imports[0] must use the fixed I1 fields")
    elif case_id == "S1":
        _closed_keys(arguments, required={"soundbank", "mode", "inclusions"}, path=f"{path}.arguments")
        _validate_identity(
            arguments["soundbank"],
            "path",
            "{soundbank_path}",
            f"{path}.arguments.soundbank",
        )
        if arguments["mode"] != "replace":
            raise EvalSuiteError(f"{path}.arguments.mode must be 'replace'")
        inclusions = _list(arguments["inclusions"], f"{path}.arguments.inclusions")
        if len(inclusions) != 1:
            raise EvalSuiteError(f"{path}.arguments.inclusions must contain exactly one fixture row")
        inclusion = _object(inclusions[0], f"{path}.arguments.inclusions[0]")
        _closed_keys(inclusion, required={"object", "filters"}, path=f"{path}.arguments.inclusions[0]")
        _validate_identity(
            inclusion["object"],
            "path",
            "{included_object_path}",
            f"{path}.arguments.inclusions[0].object",
        )
        if inclusion["filters"] != ["structures", "media"]:
            raise EvalSuiteError(f"{path}.arguments.inclusions[0].filters must be structures/media")
    elif case_id in {"W1", "W2"}:
        _closed_keys(
            arguments,
            required={"switch_container", "child", "state_or_switch"},
            path=f"{path}.arguments",
        )
        placeholders = (
            ("{switch_container_path}", "{child_path}", "{state_or_switch_path}")
            if case_id == "W1"
            else (
                "{remove_switch_container_path}",
                "{remove_child_path}",
                "{remove_state_or_switch_path}",
            )
        )
        _validate_identity(
            arguments["switch_container"],
            "path",
            placeholders[0],
            f"{path}.arguments.switch_container",
        )
        _validate_identity(arguments["child"], "path", placeholders[1], f"{path}.arguments.child")
        _validate_identity(
            arguments["state_or_switch"],
            "path",
            placeholders[2],
            f"{path}.arguments.state_or_switch",
        )
    else:  # pragma: no cover - fixed case routing makes this unreachable
        raise EvalSuiteError(f"{path}: no request template validator for case {case_id}")


def _validate_identity(value: Any, kind: str, placeholder: str, path: str) -> None:
    identity = _object(value, path)
    _closed_keys(identity, required={"kind", "value"}, path=path)
    if identity != {"kind": kind, "value": placeholder}:
        raise EvalSuiteError(f"{path} must be a closed {kind} identity using {placeholder}")


def _session_bindings(session: EvalSession, values: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise EvalSuiteError(f"session {session.session_id} values must be a mapping")
    allowed = set(session.case.variables) | RUNTIME_TEMPLATE_VARIABLES
    unknown = sorted(str(key) for key in values if key not in allowed)
    if unknown:
        raise EvalSuiteError(f"session {session.session_id} received unknown template values: {unknown}")
    bindings = dict(values)
    non_strings = sorted(str(key) for key, value in bindings.items() if not isinstance(value, str))
    if non_strings:
        raise EvalSuiteError(
            f"session {session.session_id} template values must be strings: {non_strings}"
        )
    supplied_version = bindings.get("wwise_version")
    if supplied_version is not None and supplied_version != session.version:
        raise EvalSuiteError(
            f"session {session.session_id} cannot override version {session.version!r} with {supplied_version!r}"
        )
    bindings["wwise_version"] = session.version
    return bindings


def _template_fields(template: str, path: str) -> set[str]:
    fields: set[str] = set()
    try:
        parsed = tuple(_FORMATTER.parse(template))
    except ValueError as exc:
        raise EvalSuiteError(f"{path} has invalid braces: {exc}") from exc
    for _literal, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if not _IDENTIFIER_RE.fullmatch(field_name):
            raise EvalSuiteError(f"{path} field {field_name!r} must be a simple identifier")
        if format_spec:
            raise EvalSuiteError(f"{path} field {field_name!r} cannot use a format specifier")
        if conversion:
            raise EvalSuiteError(f"{path} field {field_name!r} cannot use a conversion")
        fields.add(field_name)
    return fields


def _json_template_fields(value: Any, path: str) -> set[str]:
    if isinstance(value, Mapping):
        fields: set[str] = set()
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvalSuiteError(f"{path} keys must be strings")
            fields.update(_json_template_fields(item, f"{path}.{key}"))
        return fields
    if isinstance(value, list):
        fields: set[str] = set()
        for index, item in enumerate(value):
            fields.update(_json_template_fields(item, f"{path}[{index}]"))
        return fields
    if isinstance(value, str):
        return _template_fields(value, path)
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise EvalSuiteError(f"{path} cannot contain non-finite JSON numbers")
        return set()
    raise EvalSuiteError(f"{path} contains non-JSON value {type(value).__name__}")


def _validate_render_bindings(
    fields: set[str],
    values: Mapping[str, Any],
    *,
    allowed_variables: set[str] | frozenset[str],
    path: str,
) -> None:
    unknown_fields = sorted(fields - set(allowed_variables))
    if unknown_fields:
        raise EvalSuiteError(f"{path} uses variables outside its adapter contract: {unknown_fields}")
    missing = sorted(fields - set(values))
    if missing:
        raise EvalSuiteError(f"{path} is missing template values: {missing}")


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalSuiteError(f"{path} must be a JSON object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvalSuiteError(f"{path} must be a JSON array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvalSuiteError(f"{path} must be a non-empty string")
    return value


def _optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
    return tuple(_string(item, f"{path}[{index}]") for index, item in enumerate(_list(value, path)))


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvalSuiteError(f"{path} must be a positive integer")
    return value


def _closed_keys(row: Mapping[str, Any], *, required: set[str], path: str) -> None:
    keys = set(row)
    missing = sorted(required - keys)
    unknown = sorted(keys - required)
    if missing or unknown:
        raise EvalSuiteError(f"{path} fields mismatch; missing={missing}, unknown={unknown}")


def _require_unique(values: tuple[str, ...], path: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise EvalSuiteError(f"{path} contains duplicate ids: {duplicates}")


def _preflight_unique_ids(rows: Sequence[Any], path: str) -> None:
    ids: list[str] = []
    for index, item in enumerate(rows):
        row = _object(item, f"{path}[{index}]")
        if "id" not in row:
            raise EvalSuiteError(f"{path}[{index}] is missing id")
        ids.append(_string(row["id"], f"{path}[{index}].id"))
    _require_unique(tuple(ids), f"{path} ids")

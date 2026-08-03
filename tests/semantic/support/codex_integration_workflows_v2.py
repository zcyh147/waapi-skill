"""Closed definition loader for the committed-baseline integration v2 suite.

The profile defines three business workflows on Wwise 2022.1 and 2025.1.  It
does not create the committed SampleProject baseline or run Codex/Wwise.  A
real campaign must opt into ``require_committed_baselines`` so missing or stale
per-version GUID/media/hash manifests fail before any task starts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_campaign import (
    canonical_json_bytes,
    stable_tree_sha256,
)


PROFILE_CONTRACT = "waapi-skill.codex-integration-workflows-profile/v2"
CASE_FILE_CONTRACT = "waapi-skill.codex-integration-workflow-cases/v2"
BASELINE_MANIFEST_CONTRACT = (
    "waapi-skill.codex-integration-workflow-committed-baseline/v1"
)
PROFILE_ID = "integration_workflows_v2_cross_version_6"
DATA_FILE_NAMES = ("workflows.json",)
VERSIONS = ("2022.1", "2025.1")
WORKFLOW_IDS = (
    "rifle_safe_reimport",
    "footsteps_snow_assignment_maintenance",
    "weapons_query_guided_batch_cleanup",
)
LOGICAL_WORKFLOW_COUNT = 3
TASK_COUNT = 6
TRANSACTION_COUNT = 8
USER_TURN_COUNT = 16

EXPECTED_TRANSACTION_SPECS = {
    "rifle_safe_reimport": (
        ("audio.import", "ak.wwise.core.audio.import", 1, 2),
    ),
    "footsteps_snow_assignment_maintenance": (
        ("audio.import", "ak.wwise.core.audio.import", 1, 2),
        (
            "switchContainer.removeAssignment",
            "ak.wwise.core.switchContainer.removeAssignment",
            2,
            3,
        ),
    ),
    "weapons_query_guided_batch_cleanup": (
        ("object.set", "ak.wwise.core.object.set", 2, 3),
    ),
}
EXPECTED_TURN_KINDS = {
    "rifle_safe_reimport": ("request", "confirmation"),
    "footsteps_snow_assignment_maintenance": (
        "request",
        "confirmation",
        "confirmation",
    ),
    "weapons_query_guided_batch_cleanup": (
        "audit_request",
        "change_request",
        "confirmation",
    ),
}
EXPECTED_VISIBLE_INPUTS = {
    "rifle_safe_reimport": (
        "rifle_source_directory",
        "rifle_container_path",
        "rifle_event_path",
        "rifle_bus_path",
    ),
    "footsteps_snow_assignment_maintenance": (
        "snow_source_directory",
        "footsteps_container_path",
        "surface_group_path",
        "footsteps_event_path",
    ),
    "weapons_query_guided_batch_cleanup": (
        "weapons_audit_root_path",
        "weapons_bus_path",
    ),
}
EXPECTED_ADAPTERS = {
    "rifle_safe_reimport": "rifle_committed_baseline_fixture_v2",
    "footsteps_snow_assignment_maintenance": (
        "footsteps_committed_baseline_fixture_v2"
    ),
    "weapons_query_guided_batch_cleanup": (
        "weapons_audit_committed_baseline_fixture_v2"
    ),
}
EXPECTED_PRIMARY_API = {
    "rifle_safe_reimport": "ak.wwise.core.audio.import",
    "footsteps_snow_assignment_maintenance": "ak.wwise.core.audio.import",
    "weapons_query_guided_batch_cleanup": "ak.wwise.core.object.set",
}
EXPECTED_ASSERTION_IDS = {
    "rifle_safe_reimport": (
        "existing_sound_guids_preserved",
        "existing_active_sources_bound_to_sounds",
        "updated_media_hashes_match_inputs",
        "distant_created_once_with_new_guid",
        "distant_media_hash_matches_input",
        "rifle_container_child_set_exact",
        "play_event_chain_unchanged",
        "sound_design_state_unchanged",
        "distractors_unchanged",
        "single_import_transaction",
        "source_project_unchanged",
    ),
    "footsteps_snow_assignment_maintenance": (
        "snow_hierarchy_created_once",
        "snow_media_hashes_match_inputs",
        "snow_assignment_present",
        "mud_assignment_absent",
        "mud_objects_and_value_preserved",
        "metal_wood_assignments_unchanged",
        "footstep_event_chain_unchanged",
        "existing_footstep_content_unchanged",
        "footsteps_bus_unchanged",
        "two_transaction_sequence_exact",
        "source_project_unchanged",
    ),
    "weapons_query_guided_batch_cleanup": (
        "audit_candidates_exact",
        "excluded_scope_absent",
        "selected_ids_revalidated",
        "selected_guids_and_parents_preserved",
        "selected_corrections_exact",
        "single_object_set_batch",
        "event_action_links_unchanged",
        "rtpc_and_audio_sources_unchanged",
        "exceptions_and_controls_unchanged",
        "source_project_unchanged",
    ),
}
EXPECTED_ABSENT_ROLES = {
    "rifle_safe_reimport": {"rifle_distant"},
    "footsteps_snow_assignment_maintenance": {
        "snow_container",
        "snow_step_01",
        "snow_step_02",
        "snow_step_03",
        "snow_step_04",
    },
    "weapons_query_guided_batch_cleanup": set(),
}
EXPECTED_SOURCE_KEYS = {
    "rifle_safe_reimport": (
        "rifle_close_v2",
        "rifle_tail_v2",
        "rifle_mechanical_v2",
        "rifle_distant",
    ),
    "footsteps_snow_assignment_maintenance": (
        "snow_step_01",
        "snow_step_02",
        "snow_step_03",
        "snow_step_04",
    ),
    "weapons_query_guided_batch_cleanup": (),
}
EXPECTED_STORAGE_FILES = {
    "2022.1": (
        "Actor-Mixer Hierarchy/Default Work Unit.wwu",
        "Events/Default Work Unit.wwu",
        "Switches/Default Work Unit.wwu",
        "Master-Mixer Hierarchy/Default Work Unit.wwu",
        "Game Parameters/Default Work Unit.wwu",
    ),
    "2025.1": (
        "Containers/Default Work Unit.wwu",
        "Events/Default Work Unit.wwu",
        "Switches/Default Work Unit.wwu",
        "Busses/Default Work Unit.wwu",
        "Game Parameters/Default Work Unit.wwu",
    ),
}
EXPECTED_OBJECT_ROLES = {
    "rifle_safe_reimport": {
        "rifle_container",
        "rifle_close",
        "rifle_tail",
        "rifle_mechanical",
        "rifle_distant",
        "rifle_close_backup",
        "rifle_tails_distractor",
        "play_rifle_event",
        "play_rifle_action",
        "weapons_bus",
        "rifle_distance_parameter",
    },
    "footsteps_snow_assignment_maintenance": {
        "player_footsteps",
        "metal_container",
        "metal_sound",
        "wood_container",
        "wood_sound",
        "mud_container",
        "mud_sound",
        "snow_container",
        "snow_step_01",
        "snow_step_02",
        "snow_step_03",
        "snow_step_04",
        "surface_group",
        "surface_metal",
        "surface_wood",
        "surface_mud",
        "surface_snow",
        "play_footsteps_event",
        "play_footsteps_action",
        "footsteps_bus",
    },
    "weapons_query_guided_batch_cleanup": {
        "audit_root",
        "audit_close",
        "audit_tail",
        "audit_mechanical",
        "audit_exception_legacy",
        "audit_exception_hot",
        "audit_compliant",
        "audit_out_of_scope",
        "audit_close_event",
        "audit_close_action",
        "weapons_bus",
        "footsteps_bus",
        "rifle_distance_parameter",
    },
}

_PROFILE_KEYS = {
    "contract",
    "profile_id",
    "data_files",
    "versions",
    "baseline_kind",
    "committed_baselines",
    "totals",
}
_WORKFLOW_KEYS = {
    "id",
    "versions",
    "visible_inputs",
    "turns",
    "transactions",
    "fixture",
}
_FIXTURE_KEYS = {
    "adapter",
    "baseline_source",
    "visible_bindings",
    "object_graph",
    "source_files",
    "parameters",
    "business_assertions",
    "cleanup",
}
_CLEANUP = {
    "success": "remove_scenario_owned_sandbox_and_inputs",
    "failure": "seal_owned_state_never_reuse",
    "source_project": "must_remain_unchanged",
}
_ASSERTION_KINDS = {
    "guid_preserved",
    "reference_guid_preserved",
    "active_source_binding_exact",
    "media_sha256_matches_input",
    "absent_then_present_once",
    "direct_child_set_exact",
    "object_state_unchanged",
    "selected_fields_unchanged",
    "transaction_sequence_exact",
    "source_tree_hash_unchanged",
    "assignment_pair_present",
    "assignment_pair_absent",
    "assignment_pairs_unchanged",
    "query_candidate_set_exact",
    "query_result_excludes_roles",
    "exact_id_readback_before_preview",
    "requested_fields_exact",
}
_VISIBLE_INPUT_KINDS = {"absolute_directory_path", "object_path"}
_PROMPT_FORBIDDEN = (
    re.compile(r"\b(?:skill|gateway|harness|runner|fixture|sandbox|oracle)\b", re.I),
    re.compile(r"\b(?:eval|benchmark|test case)\b", re.I),
    re.compile(r"operation-schema", re.I),
    re.compile(r"run\.py", re.I),
    re.compile(r"\bak\.(?:wwise|soundengine)\.", re.I),
    re.compile(r"测试"),
    re.compile(r"沙箱"),
    re.compile(r"边界"),
)
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_UNIT_ID_RE = re.compile(r"^INT(?:22|25)-V2-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
_GUID_RE = re.compile(
    r"^\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class IntegrationWorkflowV2Error(ValueError):
    """The v2 profile, workflow data, or committed baseline is invalid."""


@dataclass(frozen=True, slots=True)
class VisibleInput:
    name: str
    kind: str
    description: str


@dataclass(frozen=True, slots=True)
class WorkflowTurn:
    index: int
    kind: str
    prompt: str
    confirms_transaction: int | None
    expects_preview_transaction: int | None


@dataclass(frozen=True, slots=True)
class WorkflowTransaction:
    index: int
    operation: str
    api: str
    preview_turn: int
    confirmation_turn: int


@dataclass(frozen=True, slots=True)
class ObjectSpec:
    role: str
    paths: Mapping[str, str]
    type: str
    baseline_state: str

    def path_for(self, version: str) -> str:
        try:
            return self.paths[version]
        except KeyError as exc:
            raise IntegrationWorkflowV2Error(
                f"{self.role} has no path for Wwise {version}"
            ) from exc

    @property
    def has_common_path(self) -> bool:
        return len(set(self.paths.values())) == 1


@dataclass(frozen=True, slots=True)
class SourceFileSpec:
    key: str
    file_name: str
    duration_ms: int
    frequency_hz: int


@dataclass(frozen=True, slots=True)
class BusinessAssertion:
    id: str
    kind: str
    roles: tuple[str, ...]
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkflowFixture:
    adapter: str
    baseline_source: str
    visible_bindings: Mapping[str, Any]
    object_graph: tuple[ObjectSpec, ...]
    source_files: tuple[SourceFileSpec, ...]
    parameters: Mapping[str, Any]
    business_assertions: tuple[BusinessAssertion, ...]
    cleanup: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class WorkflowCase:
    id: str
    versions: tuple[str, ...]
    visible_inputs: tuple[VisibleInput, ...]
    turns: tuple[WorkflowTurn, ...]
    transactions: tuple[WorkflowTransaction, ...]
    fixture: WorkflowFixture


@dataclass(frozen=True, slots=True)
class BaselineLayout:
    version: str
    source_project: str
    manifest: str
    storage_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaselineManifest:
    path: Path
    version: str
    digest: str
    project_file_sha256: str
    full_tree_sha256: str
    objects: tuple[Mapping[str, Any], ...]
    media: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class PrimaryDispatch:
    api: str
    count: int
    effect: str


@dataclass(frozen=True, slots=True)
class ScenarioProxy:
    id: str
    api: str
    item_type: str
    versions: tuple[str, ...]
    lane: str
    scenario_family: str
    scenario_index: int
    prompt: str
    visible_inputs: tuple[VisibleInput, ...]
    fixture: Mapping[str, Any]
    primary_dispatch: PrimaryDispatch
    confirmation_prompt: str
    confirmation_turn_count: int
    follow_up_prompts: tuple[str, ...]
    protocol: str = "preview_confirm"

    @property
    def expected_dispatches(self) -> tuple[PrimaryDispatch, ...]:
        return (self.primary_dispatch,)

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()

    def render_prompt(self, values: Mapping[str, Any]) -> str:
        expected = {item.name for item in self.visible_inputs}
        actual = set(values)
        if expected != actual:
            raise IntegrationWorkflowV2Error(
                f"{self.id} visible prompt input mismatch; "
                f"missing={sorted(expected - actual)}, "
                f"unknown={sorted(actual - expected)}"
            )
        return self.prompt.format_map({key: str(value) for key, value in values.items()})


@dataclass(frozen=True, slots=True)
class WorkflowUnit:
    unit_id: str
    workflow: WorkflowCase
    version: str
    scenario: ScenarioProxy
    baseline_manifest: BaselineManifest | None = None

    @property
    def workflow_id(self) -> str:
        return self.workflow.id

    @property
    def turns(self) -> tuple[WorkflowTurn, ...]:
        return self.workflow.turns

    @property
    def transactions(self) -> tuple[WorkflowTransaction, ...]:
        return self.workflow.transactions

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    @property
    def user_turn_count(self) -> int:
        return len(self.turns)


@dataclass(frozen=True, slots=True)
class WorkflowProfile:
    path: Path
    data_paths: tuple[Path, ...]
    source_digests: tuple[tuple[str, str], ...]
    definition_sha256: str
    baseline_layouts: Mapping[str, BaselineLayout]
    baseline_manifests: Mapping[str, BaselineManifest]
    workflows: tuple[WorkflowCase, ...]
    units: tuple[WorkflowUnit, ...]

    @property
    def committed_baselines_ready(self) -> bool:
        return set(self.baseline_manifests) == set(VERSIONS)


def load_integration_workflows_v2_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
    require_committed_baselines: bool = False,
    repo_root: str | Path | None = None,
) -> WorkflowProfile:
    """Load the full v2 definition, optionally requiring sealed baselines."""

    profile_path = _resolve_regular_file(path, "integration v2 profile")
    root, profile_digest = _load_json(profile_path, "integration v2 profile")
    _closed(root, _PROFILE_KEYS, "profile")
    if root["contract"] != PROFILE_CONTRACT or root["profile_id"] != PROFILE_ID:
        raise IntegrationWorkflowV2Error("integration v2 profile identity drifted")
    if _strings(root["versions"], "profile.versions") != VERSIONS:
        raise IntegrationWorkflowV2Error("integration v2 versions drifted")
    if root["baseline_kind"] != "committed_sample_project":
        raise IntegrationWorkflowV2Error("integration v2 baseline kind drifted")
    expected_totals = {
        "logical_workflow_count": LOGICAL_WORKFLOW_COUNT,
        "task_count": TASK_COUNT,
        "transaction_count": TRANSACTION_COUNT,
        "user_turn_count": USER_TURN_COUNT,
    }
    if root["totals"] != expected_totals:
        raise IntegrationWorkflowV2Error("integration v2 totals drifted")
    file_names = _strings(root["data_files"], "profile.data_files")
    if file_names != DATA_FILE_NAMES:
        raise IntegrationWorkflowV2Error("integration v2 data files drifted")
    layouts = _parse_baseline_layouts(root["committed_baselines"])

    data_paths = tuple(
        _resolve_regular_file(profile_path.parent / name, f"integration v2 data {name}")
        for name in file_names
    )
    source_digests: list[tuple[str, str]] = [(profile_path.name, profile_digest)]
    workflows: list[WorkflowCase] = []
    for data_path in data_paths:
        data, digest = _load_json(data_path, f"integration v2 data {data_path.name}")
        source_digests.append((data_path.name, digest))
        _closed(data, {"contract", "workflows"}, data_path.name)
        if data["contract"] != CASE_FILE_CONTRACT or not isinstance(data["workflows"], list):
            raise IntegrationWorkflowV2Error(f"{data_path.name} contract or rows drifted")
        workflows.extend(
            _parse_workflow(row, f"{data_path.name}.workflows[{index}]")
            for index, row in enumerate(data["workflows"])
        )
    complete_workflows = tuple(workflows)
    if tuple(row.id for row in complete_workflows) != WORKFLOW_IDS:
        raise IntegrationWorkflowV2Error("integration v2 workflow order or identity drifted")

    complete_units = tuple(
        _build_unit(workflow, version)
        for version in VERSIONS
        for workflow in complete_workflows
    )
    if (
        len(complete_units) != TASK_COUNT
        or sum(unit.transaction_count for unit in complete_units) != TRANSACTION_COUNT
        or sum(unit.user_turn_count for unit in complete_units) != USER_TURN_COUNT
    ):
        raise IntegrationWorkflowV2Error("integration v2 expanded totals drifted")

    baseline_manifests: dict[str, BaselineManifest] = {}
    if require_committed_baselines:
        repository = (
            Path(repo_root).expanduser().resolve()
            if repo_root is not None
            else _discover_repo_root(profile_path)
        )
        expected_specs = _present_object_specs(complete_workflows)
        for version, layout in layouts.items():
            manifest = _load_baseline_manifest(
                repository,
                layout,
                expected_specs=expected_specs,
            )
            baseline_manifests[version] = manifest
            source_digests.append(
                (f"baseline-{version}.json", manifest.digest)
            )

    requested_ids = _unique_strings(unit_ids, "unit ids")
    requested_versions = _unique_strings(versions, "versions")
    known_ids = {unit.unit_id for unit in complete_units}
    unknown_ids = sorted(set(requested_ids) - known_ids)
    if unknown_ids:
        raise IntegrationWorkflowV2Error(
            "unknown integration v2 unit ids: " + ", ".join(unknown_ids)
        )
    unknown_versions = sorted(set(requested_versions) - set(VERSIONS))
    if unknown_versions:
        raise IntegrationWorkflowV2Error(
            "integration v2 profile has no units for versions: "
            + ", ".join(unknown_versions)
        )
    selected = tuple(
        unit
        for unit in complete_units
        if (not requested_ids or unit.unit_id in requested_ids)
        and (not requested_versions or unit.version in requested_versions)
    )
    if not selected:
        raise IntegrationWorkflowV2Error("no integration v2 units matched filters")
    if require_committed_baselines:
        selected = tuple(
            WorkflowUnit(
                unit.unit_id,
                unit.workflow,
                unit.version,
                unit.scenario,
                baseline_manifests[unit.version],
            )
            for unit in selected
        )

    frozen_digests = tuple(source_digests)
    definition_sha256 = hashlib.sha256(
        "\n".join(f"{name}\0{digest}" for name, digest in frozen_digests).encode()
    ).hexdigest()
    return WorkflowProfile(
        path=profile_path,
        data_paths=data_paths,
        source_digests=frozen_digests,
        definition_sha256=definition_sha256,
        baseline_layouts=layouts,
        baseline_manifests=baseline_manifests,
        workflows=complete_workflows,
        units=selected,
    )


def _parse_baseline_layouts(value: Any) -> Mapping[str, BaselineLayout]:
    if not isinstance(value, dict) or tuple(value) != VERSIONS:
        raise IntegrationWorkflowV2Error("committed baseline versions drifted")
    result: dict[str, BaselineLayout] = {}
    for version, row in value.items():
        _closed(row, {"source_project", "manifest", "storage_files"}, f"baseline.{version}")
        source_project = _safe_repo_relative(row["source_project"], f"baseline.{version}.source_project")
        manifest = _safe_repo_relative(row["manifest"], f"baseline.{version}.manifest")
        storage = _strings(row["storage_files"], f"baseline.{version}.storage_files")
        if storage != EXPECTED_STORAGE_FILES[version]:
            raise IntegrationWorkflowV2Error(f"baseline.{version} storage layout drifted")
        if source_project != f"tests/_org/{version}/SampleProject.wproj":
            raise IntegrationWorkflowV2Error(f"baseline.{version} source project drifted")
        if manifest != f"tests/semantic/data/integration-workflows-v2/baseline-{version}.json":
            raise IntegrationWorkflowV2Error(f"baseline.{version} manifest path drifted")
        result[version] = BaselineLayout(version, source_project, manifest, storage)
    return result


def _parse_workflow(value: Any, path: str) -> WorkflowCase:
    _closed(value, _WORKFLOW_KEYS, path)
    workflow_id = _string(value["id"], f"{path}.id")
    if workflow_id not in WORKFLOW_IDS:
        raise IntegrationWorkflowV2Error(f"{path}.id is not reviewed")
    versions = _strings(value["versions"], f"{path}.versions")
    if versions != VERSIONS:
        raise IntegrationWorkflowV2Error(f"{path}.versions drifted")

    raw_inputs = _list(value["visible_inputs"], f"{path}.visible_inputs")
    inputs: list[VisibleInput] = []
    for index, row in enumerate(raw_inputs):
        item_path = f"{path}.visible_inputs[{index}]"
        _closed(row, {"name", "kind", "description"}, item_path)
        name = _string(row["name"], f"{item_path}.name")
        kind = _string(row["kind"], f"{item_path}.kind")
        if _NAME_RE.fullmatch(name) is None or kind not in _VISIBLE_INPUT_KINDS:
            raise IntegrationWorkflowV2Error(f"{item_path} name or kind is invalid")
        inputs.append(VisibleInput(name, kind, _string(row["description"], f"{item_path}.description")))
    if tuple(item.name for item in inputs) != EXPECTED_VISIBLE_INPUTS[workflow_id]:
        raise IntegrationWorkflowV2Error(f"{path}.visible_inputs drifted")

    declared = {item.name for item in inputs}
    turns: list[WorkflowTurn] = []
    for index, row in enumerate(_list(value["turns"], f"{path}.turns")):
        item_path = f"{path}.turns[{index}]"
        _closed(
            row,
            {"index", "kind", "prompt", "confirms_transaction", "expects_preview_transaction"},
            item_path,
        )
        prompt = _string(row["prompt"], f"{item_path}.prompt")
        _lint_prompt(prompt, f"{item_path}.prompt")
        unknown = set(_prompt_fields(prompt, f"{item_path}.prompt")) - declared
        if unknown:
            raise IntegrationWorkflowV2Error(f"{item_path}.prompt has unknown inputs: {sorted(unknown)}")
        turns.append(
            WorkflowTurn(
                _positive_int(row["index"], f"{item_path}.index"),
                _string(row["kind"], f"{item_path}.kind"),
                prompt,
                _optional_positive_int(row["confirms_transaction"], f"{item_path}.confirms_transaction"),
                _optional_positive_int(row["expects_preview_transaction"], f"{item_path}.expects_preview_transaction"),
            )
        )
    if tuple(turn.kind for turn in turns) != EXPECTED_TURN_KINDS[workflow_id]:
        raise IntegrationWorkflowV2Error(f"{path}.turn topology drifted")
    if tuple(turn.index for turn in turns) != tuple(range(1, len(turns) + 1)):
        raise IntegrationWorkflowV2Error(f"{path}.turn indices drifted")
    if set(_prompt_fields(turns[0].prompt, f"{path}.turns[0].prompt")) != declared:
        raise IntegrationWorkflowV2Error(f"{path}.first prompt must use every visible input")

    transactions: list[WorkflowTransaction] = []
    for index, row in enumerate(_list(value["transactions"], f"{path}.transactions")):
        item_path = f"{path}.transactions[{index}]"
        _closed(row, {"index", "operation", "api", "preview_turn", "confirmation_turn"}, item_path)
        transactions.append(
            WorkflowTransaction(
                _positive_int(row["index"], f"{item_path}.index"),
                _string(row["operation"], f"{item_path}.operation"),
                _string(row["api"], f"{item_path}.api"),
                _positive_int(row["preview_turn"], f"{item_path}.preview_turn"),
                _positive_int(row["confirmation_turn"], f"{item_path}.confirmation_turn"),
            )
        )
    actual_specs = tuple(
        (row.operation, row.api, row.preview_turn, row.confirmation_turn)
        for row in transactions
    )
    if actual_specs != EXPECTED_TRANSACTION_SPECS[workflow_id]:
        raise IntegrationWorkflowV2Error(f"{path}.transaction sequence drifted")
    _validate_turn_links(turns, transactions, path)

    fixture = _parse_fixture(value["fixture"], f"{path}.fixture", workflow_id, inputs)
    return WorkflowCase(workflow_id, versions, tuple(inputs), tuple(turns), tuple(transactions), fixture)


def _parse_fixture(
    value: Any,
    path: str,
    workflow_id: str,
    inputs: Sequence[VisibleInput],
) -> WorkflowFixture:
    _closed(value, _FIXTURE_KEYS, path)
    if value["adapter"] != EXPECTED_ADAPTERS[workflow_id]:
        raise IntegrationWorkflowV2Error(f"{path}.adapter drifted")
    if value["baseline_source"] != "committed_sample_project":
        raise IntegrationWorkflowV2Error(f"{path}.baseline source drifted")
    bindings = value["visible_bindings"]
    if not isinstance(bindings, dict) or set(bindings) != {item.name for item in inputs}:
        raise IntegrationWorkflowV2Error(f"{path}.visible bindings do not exactly cover inputs")
    for item in inputs:
        _validate_binding(bindings[item.name], f"{path}.visible_bindings.{item.name}", item.kind)

    graph: list[ObjectSpec] = []
    for index, row in enumerate(_list(value["object_graph"], f"{path}.object_graph")):
        item_path = f"{path}.object_graph[{index}]"
        if not isinstance(row, dict) or set(row) not in (
            {"role", "path", "type", "baseline_state"},
            {"role", "paths", "type", "baseline_state"},
        ):
            raise IntegrationWorkflowV2Error(f"{item_path} schema is not closed")
        role = _string(row["role"], f"{item_path}.role")
        if "path" in row:
            object_path = _string(row["path"], f"{item_path}.path")
            object_paths = {version: object_path for version in VERSIONS}
        else:
            raw_paths = row["paths"]
            if not isinstance(raw_paths, dict) or tuple(raw_paths) != VERSIONS:
                raise IntegrationWorkflowV2Error(
                    f"{item_path}.paths must cover both versions in order"
                )
            object_paths = {
                version: _string(raw_paths[version], f"{item_path}.paths.{version}")
                for version in VERSIONS
            }
        object_type = _string(row["type"], f"{item_path}.type")
        state = _string(row["baseline_state"], f"{item_path}.baseline_state")
        if _NAME_RE.fullmatch(role) is None or any(
            not object_path.startswith("\\")
            for object_path in object_paths.values()
        ):
            raise IntegrationWorkflowV2Error(f"{item_path} role or path is invalid")
        if state not in {"present", "absent"}:
            raise IntegrationWorkflowV2Error(f"{item_path}.baseline_state is invalid")
        graph.append(ObjectSpec(role, object_paths, object_type, state))
    roles = [row.role for row in graph]
    paths_by_version = {
        version: [row.path_for(version).casefold() for row in graph]
        for version in VERSIONS
    }
    if len(roles) != len(set(roles)) or any(
        len(paths) != len(set(paths)) for paths in paths_by_version.values()
    ):
        raise IntegrationWorkflowV2Error(f"{path}.object_graph roles and paths must be unique")
    if set(roles) != EXPECTED_OBJECT_ROLES[workflow_id]:
        raise IntegrationWorkflowV2Error(f"{path}.object_graph roles drifted")
    if {row.role for row in graph if row.baseline_state == "absent"} != EXPECTED_ABSENT_ROLES[workflow_id]:
        raise IntegrationWorkflowV2Error(f"{path}.object_graph baseline states drifted")
    _validate_case_roots(workflow_id, graph, bindings, path)

    sources: list[SourceFileSpec] = []
    for index, row in enumerate(_list_allow_empty(value["source_files"], f"{path}.source_files")):
        item_path = f"{path}.source_files[{index}]"
        _closed(row, {"key", "file_name", "duration_ms", "frequency_hz"}, item_path)
        file_name = _string(row["file_name"], f"{item_path}.file_name")
        if Path(file_name).parts != (file_name,) or not file_name.lower().endswith(".wav"):
            raise IntegrationWorkflowV2Error(f"{item_path}.file_name is not a plain WAV name")
        sources.append(
            SourceFileSpec(
                _string(row["key"], f"{item_path}.key"),
                file_name,
                _positive_int(row["duration_ms"], f"{item_path}.duration_ms"),
                _positive_int(row["frequency_hz"], f"{item_path}.frequency_hz"),
            )
        )
    if tuple(row.key for row in sources) != EXPECTED_SOURCE_KEYS[workflow_id]:
        raise IntegrationWorkflowV2Error(f"{path}.source file identities drifted")

    parameters = value["parameters"]
    if not isinstance(parameters, dict):
        raise IntegrationWorkflowV2Error(f"{path}.parameters must be an object")
    _validate_parameters(workflow_id, parameters, set(roles), path)

    assertions: list[BusinessAssertion] = []
    for index, row in enumerate(_list(value["business_assertions"], f"{path}.business_assertions")):
        item_path = f"{path}.business_assertions[{index}]"
        _closed(row, {"id", "kind", "roles", "fields"}, item_path)
        assertion_id = _string(row["id"], f"{item_path}.id")
        kind = _string(row["kind"], f"{item_path}.kind")
        assertion_roles = _strings_allow_empty(row["roles"], f"{item_path}.roles")
        fields = _strings_allow_empty(row["fields"], f"{item_path}.fields")
        if kind not in _ASSERTION_KINDS or set(assertion_roles) - set(roles):
            raise IntegrationWorkflowV2Error(f"{item_path} kind or role is invalid")
        assertions.append(BusinessAssertion(assertion_id, kind, assertion_roles, fields))
    if tuple(row.id for row in assertions) != EXPECTED_ASSERTION_IDS[workflow_id]:
        raise IntegrationWorkflowV2Error(f"{path}.business assertion identity drifted")
    if value["cleanup"] != _CLEANUP:
        raise IntegrationWorkflowV2Error(f"{path}.cleanup drifted")

    return WorkflowFixture(
        adapter=value["adapter"],
        baseline_source=value["baseline_source"],
        visible_bindings=copy.deepcopy(bindings),
        object_graph=tuple(graph),
        source_files=tuple(sources),
        parameters=copy.deepcopy(parameters),
        business_assertions=tuple(assertions),
        cleanup=copy.deepcopy(value["cleanup"]),
    )


def _validate_case_roots(
    workflow_id: str,
    graph: Sequence[ObjectSpec],
    bindings: Mapping[str, Any],
    path: str,
) -> None:
    by_role = {row.role: row for row in graph}
    actor_roots = {
        "2022.1": r"\Actor-Mixer Hierarchy\Default Work Unit\WAAPI Skill Integration V2",
        "2025.1": r"\Containers\Default Work Unit\WAAPI Skill Integration V2",
    }
    event_root = r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2"
    for row in graph:
        for version, object_path in row.paths.items():
            if row.type in {"Event", "Action"} and not object_path.startswith(event_root + "\\"):
                raise IntegrationWorkflowV2Error(f"{path}.{row.role} escaped the fixed Event subtree")
            if (
                row.type
                in {"Sound", "ActorMixer", "RandomSequenceContainer", "SwitchContainer"}
                and not object_path.startswith(actor_roots[version] + "\\")
            ):
                raise IntegrationWorkflowV2Error(f"{path}.{row.role} escaped the fixed Actor subtree")
    if workflow_id == "rifle_safe_reimport":
        if (
            any(
                by_role["rifle_container"].path_for(version)
                != _binding_path(bindings["rifle_container_path"], version)
                for version in VERSIONS
            )
            or any(
                by_role["play_rifle_event"].path_for(version)
                != _binding_path(bindings["rifle_event_path"], version)
                for version in VERSIONS
            )
            or any(
                by_role["weapons_bus"].path_for(version)
                != _binding_path(bindings["rifle_bus_path"], version)
                for version in VERSIONS
            )
        ):
            raise IntegrationWorkflowV2Error(f"{path} Rifle visible paths drifted")
    elif workflow_id == "footsteps_snow_assignment_maintenance":
        if any(
            by_role["player_footsteps"].path_for(version)
            != _binding_path(bindings["footsteps_container_path"], version)
            for version in VERSIONS
        ) or any(
            by_role["surface_group"].path_for(version)
            != _binding_path(bindings["surface_group_path"], version)
            for version in VERSIONS
        ) or any(
            by_role["play_footsteps_event"].path_for(version)
            != _binding_path(bindings["footsteps_event_path"], version)
            for version in VERSIONS
        ):
            raise IntegrationWorkflowV2Error(f"{path} Footsteps visible paths drifted")
    else:
        if (
            any(
                by_role["audit_root"].path_for(version)
                != _binding_path(bindings["weapons_audit_root_path"], version)
                for version in VERSIONS
            )
            or any(
                by_role["weapons_bus"].path_for(version)
                != _binding_path(bindings["weapons_bus_path"], version)
                for version in VERSIONS
            )
        ):
            raise IntegrationWorkflowV2Error(f"{path} audit root drifted")


def _validate_parameters(workflow_id: str, value: Mapping[str, Any], roles: set[str], path: str) -> None:
    if workflow_id == "rifle_safe_reimport":
        _closed(value, {"import_operation", "existing_rows", "new_row", "preserve_fields", "protected_roles"}, f"{path}.parameters")
        if value["import_operation"] != "useExisting":
            raise IntegrationWorkflowV2Error(f"{path}.parameters must use useExisting")
        rows = _list(value["existing_rows"], f"{path}.parameters.existing_rows")
        if [row.get("role") for row in rows] != ["rifle_close", "rifle_tail", "rifle_mechanical"]:
            raise IntegrationWorkflowV2Error(f"{path}.parameters existing Rifle rows drifted")
        new_row = value["new_row"]
        if not isinstance(new_row, dict) or new_row.get("role") != "rifle_distant" or new_row.get("properties") != {"Volume": -12.0}:
            raise IntegrationWorkflowV2Error(f"{path}.parameters Distant row drifted")
    elif workflow_id == "footsteps_snow_assignment_maintenance":
        _closed(value, {"import_operation", "structure_row", "sound_rows", "assignment_pairs", "protected_roles"}, f"{path}.parameters")
        if value["import_operation"] != "createNew" or value["structure_row"] != {
            "role": "snow_container",
            "object_type": "RandomSequenceContainer",
            "switch_assignment": "Snow",
        }:
            raise IntegrationWorkflowV2Error(f"{path}.parameters Snow structure drifted")
        if [row.get("role") for row in _list(value["sound_rows"], f"{path}.parameters.sound_rows")] != [
            "snow_step_01", "snow_step_02", "snow_step_03", "snow_step_04"
        ]:
            raise IntegrationWorkflowV2Error(f"{path}.parameters Snow rows drifted")
        pairs = value["assignment_pairs"]
        if not isinstance(pairs, dict) or pairs.get("remove") != {"child_role": "mud_container", "value_role": "surface_mud"}:
            raise IntegrationWorkflowV2Error(f"{path}.parameters Mud assignment drifted")
    else:
        _closed(value, {"audit_rules", "reported_candidate_roles", "selected_corrections", "exception_roles", "control_roles", "identity_readback", "batch_operation"}, f"{path}.parameters")
        if value["identity_readback"] != "exact_id_before_preview" or value["batch_operation"] != "object.set":
            raise IntegrationWorkflowV2Error(f"{path}.parameters mutation handoff drifted")
        if value["reported_candidate_roles"] != [
            "audit_close", "audit_tail", "audit_mechanical", "audit_exception_legacy", "audit_exception_hot"
        ]:
            raise IntegrationWorkflowV2Error(f"{path}.parameters audit candidates drifted")
        corrections = _list(value["selected_corrections"], f"{path}.parameters.selected_corrections")
        if [row.get("role") for row in corrections] != ["audit_close", "audit_tail", "audit_mechanical"]:
            raise IntegrationWorkflowV2Error(f"{path}.parameters selected corrections drifted")
    protected = value.get("protected_roles", [])
    if protected and (not isinstance(protected, list) or set(protected) - roles):
        raise IntegrationWorkflowV2Error(f"{path}.parameters protected roles are invalid")


def _validate_turn_links(
    turns: Sequence[WorkflowTurn],
    transactions: Sequence[WorkflowTransaction],
    path: str,
) -> None:
    by_turn = {row.index: row for row in turns}
    expected = list(range(1, len(transactions) + 1))
    if [row.index for row in transactions] != expected:
        raise IntegrationWorkflowV2Error(f"{path}.transaction indices drifted")
    for transaction in transactions:
        preview = by_turn.get(transaction.preview_turn)
        confirmation = by_turn.get(transaction.confirmation_turn)
        if (
            preview is None
            or confirmation is None
            or transaction.preview_turn >= transaction.confirmation_turn
            or preview.expects_preview_transaction != transaction.index
            or confirmation.kind != "confirmation"
            or confirmation.confirms_transaction != transaction.index
        ):
            raise IntegrationWorkflowV2Error(f"{path}.turn/transaction link drifted")
    if sorted(row.expects_preview_transaction for row in turns if row.expects_preview_transaction is not None) != expected:
        raise IntegrationWorkflowV2Error(f"{path}.preview links drifted")
    if sorted(row.confirms_transaction for row in turns if row.confirms_transaction is not None) != expected:
        raise IntegrationWorkflowV2Error(f"{path}.confirmation links drifted")


def _build_unit(workflow: WorkflowCase, version: str) -> WorkflowUnit:
    year = version.split(".", maxsplit=1)[0]
    unit_id = f"INT{year[-2:]}-V2-{workflow.id.replace('_', '-').upper()}"
    if _UNIT_ID_RE.fullmatch(unit_id) is None:
        raise IntegrationWorkflowV2Error(f"invalid generated unit id: {unit_id}")
    confirmations = [row.prompt for row in workflow.turns if row.kind == "confirmation"]
    api = EXPECTED_PRIMARY_API[workflow.id]
    scenario = ScenarioProxy(
        id=unit_id,
        api=api,
        item_type="function",
        versions=(version,),
        lane="online_authoring",
        scenario_family=workflow.id,
        scenario_index=WORKFLOW_IDS.index(workflow.id) + 1,
        prompt=workflow.turns[0].prompt,
        visible_inputs=workflow.visible_inputs,
        fixture={
            "adapter": workflow.fixture.adapter,
            "baseline_source": workflow.fixture.baseline_source,
            "visible_bindings": copy.deepcopy(workflow.fixture.visible_bindings),
            "object_graph": [
                {
                    "role": row.role,
                    **(
                        {"path": next(iter(row.paths.values()))}
                        if row.has_common_path
                        else {"paths": dict(row.paths)}
                    ),
                    "type": row.type,
                    "baseline_state": row.baseline_state,
                }
                for row in workflow.fixture.object_graph
            ],
            "parameters": copy.deepcopy(workflow.fixture.parameters),
            "cleanup": copy.deepcopy(workflow.fixture.cleanup),
        },
        primary_dispatch=PrimaryDispatch(api, 1, f"execute the reviewed {workflow.id} primary transaction exactly once"),
        confirmation_prompt=confirmations[0],
        confirmation_turn_count=len(workflow.transactions),
        follow_up_prompts=tuple(row.prompt for row in workflow.turns[1:]),
    )
    return WorkflowUnit(unit_id, workflow, version, scenario)


def _present_object_specs(workflows: Sequence[WorkflowCase]) -> Mapping[str, ObjectSpec]:
    result: dict[str, ObjectSpec] = {}
    for workflow in workflows:
        for spec in workflow.fixture.object_graph:
            if spec.baseline_state != "present":
                continue
            previous = result.get(spec.role)
            if previous is not None and previous != spec:
                raise IntegrationWorkflowV2Error(f"baseline role {spec.role} has conflicting definitions")
            result[spec.role] = spec
    return result


def _load_baseline_manifest(
    repo_root: Path,
    layout: BaselineLayout,
    *,
    expected_specs: Mapping[str, ObjectSpec],
) -> BaselineManifest:
    project = _resolve_under(repo_root, layout.source_project, f"{layout.version} source project")
    manifest_path = _resolve_under(repo_root, layout.manifest, f"{layout.version} baseline manifest")
    root, digest = _load_json(manifest_path, f"{layout.version} baseline manifest")
    _closed(root, {"contract", "version", "source_project", "storage_files", "objects", "media"}, f"baseline manifest {layout.version}")
    if root["contract"] != BASELINE_MANIFEST_CONTRACT or root["version"] != layout.version:
        raise IntegrationWorkflowV2Error(f"{layout.version} baseline manifest identity drifted")
    source = root["source_project"]
    _closed(source, {"relative_path", "project_file_sha256", "full_tree_sha256"}, f"baseline manifest {layout.version}.source_project")
    if source["relative_path"] != layout.source_project:
        raise IntegrationWorkflowV2Error(f"{layout.version} manifest project path drifted")
    project_sha = _sha256(project)
    if source["project_file_sha256"] != project_sha or not _is_sha256(source["full_tree_sha256"]):
        raise IntegrationWorkflowV2Error(f"{layout.version} manifest project hash drifted")
    actual_tree = stable_tree_sha256(project.parent)
    if source["full_tree_sha256"] != actual_tree:
        raise IntegrationWorkflowV2Error(f"{layout.version} manifest full tree hash drifted")

    storage_rows = _list(root["storage_files"], f"baseline manifest {layout.version}.storage_files")
    if [row.get("relative_path") for row in storage_rows] != list(layout.storage_files):
        raise IntegrationWorkflowV2Error(f"{layout.version} manifest storage files drifted")
    for index, row in enumerate(storage_rows):
        _closed(row, {"relative_path", "sha256"}, f"baseline storage[{index}]")
        storage_path = _resolve_relative_under(
            project.parent,
            row["relative_path"],
            f"baseline storage[{index}]",
        )
        if row["sha256"] != _sha256(storage_path):
            raise IntegrationWorkflowV2Error(f"{layout.version} storage hash drifted: {row['relative_path']}")

    object_rows = _list(root["objects"], f"baseline manifest {layout.version}.objects")
    parsed_objects: list[Mapping[str, Any]] = []
    for index, row in enumerate(object_rows):
        _closed(
            row,
            {"role", "id", "path", "type", "state", "state_sha256"},
            f"baseline objects[{index}]",
        )
        role = _string(row["role"], f"baseline objects[{index}].role")
        spec = expected_specs.get(role)
        state = row["state"]
        state_digest = (
            hashlib.sha256(canonical_json_bytes(state)).hexdigest()
            if isinstance(state, dict)
            else None
        )
        if (
            spec is None
            or row["path"] != spec.path_for(layout.version)
            or row["type"] != spec.type
            or _GUID_RE.fullmatch(str(row["id"])) is None
            or state_digest is None
            or row["state_sha256"] != state_digest
        ):
            raise IntegrationWorkflowV2Error(f"{layout.version} baseline object {role} drifted")
        parsed_objects.append(copy.deepcopy(row))
    if {row["role"] for row in parsed_objects} != set(expected_specs):
        raise IntegrationWorkflowV2Error(f"{layout.version} baseline object role coverage drifted")
    if len({row["id"] for row in parsed_objects}) != len(parsed_objects):
        raise IntegrationWorkflowV2Error(f"{layout.version} baseline object GUIDs are not unique")

    expected_media_roles = {
        role for role, spec in expected_specs.items() if spec.type == "Sound"
    }
    media_rows = _list(root["media"], f"baseline manifest {layout.version}.media")
    parsed_media: list[Mapping[str, str]] = []
    for index, row in enumerate(media_rows):
        _closed(row, {"role", "active_source_id", "relative_path", "sha256"}, f"baseline media[{index}]")
        role = _string(row["role"], f"baseline media[{index}].role")
        relative = _safe_relative(row["relative_path"], f"baseline media[{index}].relative_path")
        if role not in expected_media_roles or _GUID_RE.fullmatch(str(row["active_source_id"])) is None or not relative.startswith("Originals/"):
            raise IntegrationWorkflowV2Error(f"{layout.version} baseline media {role} drifted")
        media_path = _resolve_relative_under(
            project.parent,
            relative,
            f"baseline media[{index}]",
        )
        if row["sha256"] != _sha256(media_path):
            raise IntegrationWorkflowV2Error(f"{layout.version} baseline media hash drifted: {role}")
        parsed_media.append(copy.deepcopy(row))
    if {row["role"] for row in parsed_media} != expected_media_roles:
        raise IntegrationWorkflowV2Error(f"{layout.version} baseline media role coverage drifted")
    if len({row["active_source_id"] for row in parsed_media}) != len(parsed_media):
        raise IntegrationWorkflowV2Error(f"{layout.version} baseline AudioSource GUIDs are not unique")
    return BaselineManifest(
        manifest_path,
        layout.version,
        digest,
        project_sha,
        actual_tree,
        tuple(parsed_objects),
        tuple(parsed_media),
    )


def _validate_binding(value: Any, path: str, kind: str) -> None:
    if not isinstance(value, dict):
        raise IntegrationWorkflowV2Error(f"{path} must be an object")
    if value.get("source") == "literal":
        _closed(value, {"source", "value"}, path)
        if kind != "object_path" or not _string(value["value"], f"{path}.value").startswith("\\"):
            raise IntegrationWorkflowV2Error(f"{path} literal does not match object path kind")
        return
    if value.get("source") == "version_literal":
        _closed(value, {"source", "values"}, path)
        values = value["values"]
        if (
            kind != "object_path"
            or not isinstance(values, dict)
            or tuple(values) != VERSIONS
            or any(
                not _string(values[version], f"{path}.values.{version}").startswith("\\")
                for version in VERSIONS
            )
            or len(set(values.values())) != len(VERSIONS)
        ):
            raise IntegrationWorkflowV2Error(
                f"{path} version literal does not cover distinct object paths"
            )
        return
    if value.get("source") == "owned_path":
        _closed(value, {"source", "relative_path"}, path)
        if kind != "absolute_directory_path":
            raise IntegrationWorkflowV2Error(f"{path} owned path kind drifted")
        _safe_relative(value["relative_path"], f"{path}.relative_path")
        return
    raise IntegrationWorkflowV2Error(f"{path} binding source is invalid")


def _binding_path(value: Mapping[str, Any], version: str) -> str:
    if value.get("source") == "literal":
        return str(value["value"])
    if value.get("source") == "version_literal":
        return str(value["values"][version])
    raise IntegrationWorkflowV2Error("binding does not expose an object path")


def _prompt_fields(value: str, path: str) -> tuple[str, ...]:
    result: list[str] = []
    try:
        parsed = string.Formatter().parse(value)
        for _literal, field, format_spec, conversion in parsed:
            if field is None:
                continue
            if _NAME_RE.fullmatch(field) is None or format_spec or conversion:
                raise IntegrationWorkflowV2Error(f"{path} has an invalid placeholder")
            result.append(field)
    except ValueError as exc:
        raise IntegrationWorkflowV2Error(f"{path} has invalid braces") from exc
    if len(result) != len(set(result)):
        raise IntegrationWorkflowV2Error(f"{path} repeats a placeholder")
    return tuple(result)


def _lint_prompt(value: str, path: str) -> None:
    if len(value.strip()) < 12:
        raise IntegrationWorkflowV2Error(f"{path} is too short")
    for pattern in _PROMPT_FORBIDDEN:
        if pattern.search(value):
            raise IntegrationWorkflowV2Error(f"{path} contains test-harness coaching")


def _discover_repo_root(path: Path) -> Path:
    for parent in path.parents:
        if (parent / ".git").exists() and (parent / "tests").is_dir():
            return parent.resolve()
    raise IntegrationWorkflowV2Error("cannot discover repository root for committed baselines")


def _resolve_under(root: Path, relative: str, label: str) -> Path:
    safe = _safe_repo_relative(relative, label)
    return _resolve_safe_relative_under(root, safe, label)


def _resolve_relative_under(root: Path, relative: str, label: str) -> Path:
    safe = _safe_relative(relative, label)
    return _resolve_safe_relative_under(root, safe, label)


def _resolve_safe_relative_under(root: Path, safe: str, label: str) -> Path:
    try:
        resolved = (root / safe).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise IntegrationWorkflowV2Error(f"cannot resolve {label}: {safe}") from exc
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise IntegrationWorkflowV2Error(f"{label} escapes its root") from exc
    if not resolved.is_file():
        raise IntegrationWorkflowV2Error(f"{label} must be a regular file")
    return resolved


def _safe_repo_relative(value: Any, path: str) -> str:
    relative = _safe_relative(value, path)
    if not relative.startswith("tests/"):
        raise IntegrationWorkflowV2Error(f"{path} must stay below tests/")
    return relative


def _safe_relative(value: Any, path: str) -> str:
    text = _string(value, path).replace("\\", "/")
    relative = Path(text)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise IntegrationWorkflowV2Error(f"{path} must be a safe relative path")
    return relative.as_posix()


def _resolve_regular_file(value: str | Path, label: str) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise IntegrationWorkflowV2Error(f"cannot resolve {label}: {value}") from exc
    if not path.is_file():
        raise IntegrationWorkflowV2Error(f"{label} must be a regular file")
    return path


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except IntegrationWorkflowV2Error:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationWorkflowV2Error(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise IntegrationWorkflowV2Error(f"{label} must be an object")
    return value, hashlib.sha256(payload).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntegrationWorkflowV2Error(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise IntegrationWorkflowV2Error(f"non-finite JSON number: {value}")


def _closed(value: Any, keys: set[str], path: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise IntegrationWorkflowV2Error(f"{path} schema is not closed")


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise IntegrationWorkflowV2Error(f"{path} must be a non-empty array")
    return value


def _list_allow_empty(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise IntegrationWorkflowV2Error(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrationWorkflowV2Error(f"{path} must be a non-empty string")
    return value


def _strings(value: Any, path: str) -> tuple[str, ...]:
    result = _strings_allow_empty(value, path)
    if not result:
        raise IntegrationWorkflowV2Error(f"{path} must be non-empty")
    return result


def _strings_allow_empty(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise IntegrationWorkflowV2Error(f"{path} must be a string array")
    result = tuple(_string(item, f"{path}[]") for item in value)
    if len(result) != len(set(result)):
        raise IntegrationWorkflowV2Error(f"{path} contains duplicates")
    return result


def _positive_int(value: Any, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise IntegrationWorkflowV2Error(f"{path} must be a positive integer")
    return value


def _optional_positive_int(value: Any, path: str) -> int | None:
    return None if value is None else _positive_int(value, path)


def _unique_strings(value: Sequence[str], path: str) -> tuple[str, ...]:
    result = tuple(_string(item, path) for item in value)
    if len(result) != len(set(result)):
        raise IntegrationWorkflowV2Error(f"duplicate {path}")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


__all__ = [
    "BASELINE_MANIFEST_CONTRACT",
    "CASE_FILE_CONTRACT",
    "DATA_FILE_NAMES",
    "EXPECTED_ADAPTERS",
    "EXPECTED_ASSERTION_IDS",
    "EXPECTED_PRIMARY_API",
    "EXPECTED_SOURCE_KEYS",
    "EXPECTED_STORAGE_FILES",
    "EXPECTED_TRANSACTION_SPECS",
    "EXPECTED_TURN_KINDS",
    "EXPECTED_VISIBLE_INPUTS",
    "LOGICAL_WORKFLOW_COUNT",
    "PROFILE_CONTRACT",
    "PROFILE_ID",
    "TASK_COUNT",
    "TRANSACTION_COUNT",
    "USER_TURN_COUNT",
    "VERSIONS",
    "WORKFLOW_IDS",
    "BaselineLayout",
    "BaselineManifest",
    "BusinessAssertion",
    "IntegrationWorkflowV2Error",
    "ObjectSpec",
    "ScenarioProxy",
    "SourceFileSpec",
    "WorkflowCase",
    "WorkflowFixture",
    "WorkflowProfile",
    "WorkflowTransaction",
    "WorkflowTurn",
    "WorkflowUnit",
    "load_integration_workflows_v2_profile",
]

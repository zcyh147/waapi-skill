"""Strict loader and coverage audit for the declarative semantic v3 bundle.

The v2 suite remains intentionally frozen because historical campaigns bind its
single-file digest and fixed 40/98/168 profiles.  V3 separates real-Wwise cases
from offline catalog cases and treats every online coverage claim as a four-part
review contract: a natural user prompt, a declared primary API/count/effect, an
independent business oracle plan, and scenario-owned cleanup.  Exact request
predicates and executable adapters are deliberately deferred until the user
approves these definitions; this loader must not imply they already exist.

This module only parses data.  JSON documents cannot inject Python, shell, or
arbitrary callbacks; live adapters are selected later from a closed registry.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.execution_contracts import UNDO_GROUP_MEMBER_URIS
from wwise_waapi.operation_import import (
    SUPPORTED_IMPORT_OPERATIONS,
    TAB_HEADERS_BY_VERSION,
    canonical_import_target,
    derive_tab_target,
)
from wwise_waapi.operation_registry import UNDO_GROUP_INNER_URIS_BY_VERSION


SUITE_CONTRACT = "waapi-skill.codex-semantic-suite-manifest/v3"
ONLINE_CONTRACT = "waapi-skill.codex-semantic-online-tests/v3"
ONLINE_CASES_CONTRACT = "waapi-skill.codex-semantic-online-cases/v3"
OFFLINE_CONTRACT = "waapi-skill.codex-semantic-offline-tests/v3"
ADAPTER_REGISTRY_CONTRACT = "waapi-skill.codex-semantic-adapter-registry/v3"
REQUEST_MAPPING_REGISTRY_CONTRACT = (
    "waapi-skill.codex-semantic-request-mapping-registry/v3"
)
SUPPORTED_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
EXECUTION_PROFILE_VERSION = "2022.1"
ELIGIBLE_INTERFACE_STATUSES = ("available", "available_via_transaction")
ONLINE_LANES = frozenset(
    {
        "online_authoring",
        "online_runtime",
        "online_topic",
        "online_ui",
        "online_lifecycle",
        "external_isolated",
    }
)
PROTOCOLS = frozenset({"single", "preview_confirm"})
ASSERTION_PHASES = frozenset({"before", "preview", "after", "event", "cleanup"})
WEAK_ASSERTION_ADAPTERS = frozenset(
    {
        "dispatch_trace",
        "gateway_verified_flag",
        "model_answer",
        "result_schema",
        "semantic_answer_assertion",
    }
)
REQUIRED_CLEANUP_POSTCONDITIONS = frozenset(
    {"owned_state_removed_or_restored", "project_source_unchanged"}
)
EXPECTED_ISOLATION_CONTRACT = {
    "codex_task": "one scenario per fresh CLI process, thread, and memory-isolated task",
    "mutation_confirmation": "each packaged mutation call receives its own natural confirmation turn in the same fresh task after an immutable preview; the confirmation applies only to the currently visible preview",
    "wwise_lifecycle": "version-scoped, lane-appropriate isolated host lifecycles; GUI, WwiseConsole, and runtime profiles are never conflated",
    "scenario_namespace": "unique runner-owned object and file namespace",
    "source_project": "immutable; hash and mtime attested before and after the campaign",
    "success_cleanup": "remove scenario-owned state and delete the sandbox after final version verification",
    "failure_cleanup": "for a failed or indeterminate case, retain the sandbox and sealed evidence, mark it quarantined, and never reuse it for another scenario; never report a skip or blocked prerequisite as a pass",
}
SEQUENTIAL_CONFIRMATION_PROMPT = (
    "这一步预览没问题，执行它；如果还有下一步，先把下一步预览给我。"
)
EXPECTED_PROMPT_MATERIALIZATION_CONTRACT = {
    "template_field": "prompt",
    "declared_inputs_field": "visible_inputs",
    "render_timing": "before the fresh Codex task starts",
    "evidence": "archive the fully rendered prompt",
    "required_argument_rule": "every raw required call argument must be literal in the prompt, supplied as a visible input, or obtained by a declared supporting dispatch",
    "hidden_boundary": "independent oracle GUIDs, hashes, controls, and expected readbacks remain model-invisible",
}

# These are harness/test phrases, not ordinary Wwise requests.  The evaluated
# user prompt must never coach the model about how it is being graded.
_PROMPT_FORBIDDEN = (
    re.compile(r"gateway", re.IGNORECASE),
    re.compile(r"operation-schema", re.IGNORECASE),
    re.compile(r"WAAPI_RESULT_JSON", re.IGNORECASE),
    re.compile(r"transaction[_ -]?id", re.IGNORECASE),
    re.compile(r"preview[_ -]?hash", re.IGNORECASE),
    re.compile(r"\bak\.(?:wwise|soundengine)\.", re.IGNORECASE),
    re.compile(r"\b(?:runner|fixture|sandbox|oracle|harness)\b", re.IGNORECASE),
    re.compile(r"沙箱"),
    re.compile(r"必须遵守.{0,16}(?:skill|边界)", re.IGNORECASE),
    re.compile(r"skill.{0,12}边界", re.IGNORECASE),
    re.compile(r"不要.{0,12}(?:写|生成).{0,8}代码", re.IGNORECASE),
    re.compile(r"run\.py", re.IGNORECASE),
)
_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")
_ADAPTER_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VISIBLE_INPUT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAPPING_ID_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
_MEDIA_POOL_FIELD_TOKEN_RE = re.compile(
    r"^\{media_pool_fields\.([a-z_]+)\}$"
)
VISIBLE_INPUT_KINDS = frozenset(
    {
        "absolute_directory_path",
        "absolute_file_path",
        "endpoint",
        "integer",
        "number",
        "object_path",
        "staged_directory_path",
        "staged_file_path",
        "string",
        "structured_array",
        "structured_object",
        "timestamp",
        "uint64",
    }
)
SOUNDBANK_FIXTURE_ADAPTERS = frozenset(
    {
        "soundbank_definition_fixture",
        "soundbank_external_source_fixture",
        "soundbank_generation_fixture",
        "soundbank_inclusion_fixture",
        "soundbank_topic_fixture",
    }
)
SOUNDBANK_GENERATE_INCLUSIONS = frozenset({"event", "structure", "media"})
SOUNDBANK_DEFINITION_FILTERS = {
    "Event": frozenset({"Event", "Structure", "Media"}),
    "-AuxBus": frozenset({"Structure", "Media"}),
    "-DialogueEvent": frozenset({"Event", "Structure", "Media"}),
    "-EffectShareset": frozenset({"Structure", "Media"}),
}
SOUNDBANK_IDENTITY_FORMATS = frozenset(
    {"name", "guid", "decimal_short_id", "hexadecimal_short_id"}
)
SOUNDBANK_IDENTITY_MATERIALIZATION = {
    "name": "runner_writes_double_quoted_literal_name",
    "guid": "runner_queries_guid",
    "decimal_short_id": "runner_queries_decimal_short_id",
    "hexadecimal_short_id": "runner_queries_hexadecimal_short_id",
}
MIGRATION_FIXTURE_ROOT = "tests/_org/2021.1"
MIGRATION_FIXTURE_PROJECT = "SampleProject.wproj"
MIGRATION_FIXTURE_SOURCE_RELEASE = "2021.1.14.8108"
MIGRATION_FIXTURE_DOCUMENT_VERSION = "v2021.1.0"
MIGRATION_FIXTURE_DOCUMENT_BUILD = "7485"
MIGRATION_FIXTURE_MANIFEST_DIGEST = (
    "51b1d8abfee6c296e184446a89069c011db56e50c50463f5f9036c37766fde4d"
)
MIGRATION_FIXTURE_FILE_COUNT = 66
MIGRATION_INVENTORY_POLICY = (
    "derive_exact_guid_type_name_parent_property_and_reference_inventory_from_source_xml"
)
MIGRATION_SCOPED_COMPARISON_PROFILE = "project_platform_conversion_binding_graph"
MIGRATION_SCOPED_COMPARISON = {
    "identity_fields": ["guid", "kind", "name", "parent"],
    "project_descendant_tags": ["Platform", "Language"],
    "project_property_names": [
        "DefaultLanguage",
        "ExternalSourcesInputPath",
        "ExternalSourcesOutputPath",
        "SoundBankHeaderFilePath",
        "SoundBankPaths",
    ],
    "conversion_property_names": [
        "Channels",
        "LRMix",
        "MaxSampleRate",
        "MinSampleRate",
        "SampleRate",
    ],
    "include_conversion_plugin_inventory": True,
}
SOUNDBANK_ARTIFACT_EXPECTATIONS = frozenset(
    {"nonlocalized", "localized", "mixed"}
)
SOUNDBANK_FIXTURE_MATERIALIZATION_POLICY = (
    "fresh_case_project_materializes_events_media_dependencies_controls_and_"
    "preexisting_artifacts_then_existing_soundbank_objects_or_proves_"
    "temporary_request_only_bank_objects_absent_before_snapshot"
)
SOUNDBANK_PROJECT_OBJECT_MODES = frozenset(
    {"existing_soundbank", "temporary_request_only"}
)
SOUNDBANK_REBUILD_SEEDS = {
    "cache": {
        # Wwise's audio-file cache is the platform/language tree below the
        # configured cache root.  An arbitrary sibling directory at the root
        # is not converted-media evidence and Wwise 2022.1 does not remove it.
        "relative_path": "Windows/SFX/stale-audio-cache.wem",
        "marker": "deterministic_stale_cache_v1",
    },
    "header": {
        "relative_path": "Wwise_IDs.h",
        "marker": "deterministic_stale_header_v1",
    },
}
SOUNDBANK_DEFINITION_SERIALIZATION = {
    "line_endings": "lf",
    "field_separator": "tab",
    "ordinary_event_layout": ["soundbank", "resolved_identity", "filter_columns"],
    "special_directive_layout": [
        "soundbank",
        "directive",
        "resolved_identity",
        "filter_columns",
    ],
    "quoting_policy": "name_identity_double_quoted_guid_and_uint32_unquoted",
}
SOUNDBANK_TOPIC_INIT_PRECONDITION = {
    "materialization": (
        "runner_generates_init_before_subscription_in_case_owned_output_and_cache"
    ),
    "proof": [
        "init_artifact_nonzero_sha256",
        "init_artifact_mtime_ns",
        "cache_tree_sha256",
    ],
    "publisher_requirement": (
        "subscription_ack_then_all_publisher_requests_rebuildInitBank_false"
    ),
    "unexpected_notification_policy": "any_init_generated_notification_fails_scope",
}


class EvalBundleV3Error(ValueError):
    """A v3 semantic document violates its closed, reviewable contract."""


@dataclass(frozen=True, slots=True)
class ExpectedDispatch:
    api: str
    count: int
    effect: str


@dataclass(frozen=True, slots=True)
class OracleAssertion:
    phase: str
    adapter: str
    subject_api: str
    expectation: str


@dataclass(frozen=True, slots=True)
class VisibleInput:
    name: str
    kind: str
    description: str


@dataclass(frozen=True, slots=True)
class RequestMappingRequirement:
    id: str
    kind: str
    status: str
    versions: tuple[str, ...]
    apis: tuple[str, ...]
    case_ids: tuple[str, ...]
    json_pointers: tuple[str, ...]
    required_semantics: tuple[str, ...]
    evidence: tuple[str, ...]

    @property
    def blocks_execution(self) -> bool:
        return self.status != "closed"


@dataclass(frozen=True, slots=True)
class OnlineScenario:
    id: str
    api: str
    item_type: str
    versions: tuple[str, ...]
    lane: str
    scenario_family: str
    scenario_index: int
    prompt: str
    visible_inputs: tuple[VisibleInput, ...]
    protocol: str
    confirmation_prompt: str | None
    fixture: Mapping[str, Any]
    trigger: Mapping[str, Any] | None
    expected_dispatches: tuple[ExpectedDispatch, ...]
    oracle_assertions: tuple[OracleAssertion, ...]
    cleanup: Mapping[str, Any]

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()

    @property
    def primary_dispatch(self) -> ExpectedDispatch:
        matches = tuple(item for item in self.expected_dispatches if item.api == self.api)
        if len(matches) != 1:  # The loader rejects this before constructing a bundle.
            raise EvalBundleV3Error(
                f"{self.id} does not have exactly one primary expected-dispatch row"
            )
        return matches[0]

    @property
    def confirmation_turn_count(self) -> int:
        """Natural confirmation turns required by this scenario.

        A repeated primary dispatch represents separate packaged transactions,
        not one broad workflow authorization.  Batch-capable APIs must instead
        declare one primary dispatch whose closed request contains the array.
        """

        if self.protocol != "preview_confirm":
            return 0
        return self.primary_dispatch.count

    def render_prompt(self, values: Mapping[str, Any]) -> str:
        expected = {item.name for item in self.visible_inputs}
        actual = set(values)
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        if missing or unknown:
            raise EvalBundleV3Error(
                f"{self.id} visible prompt input mismatch; missing={missing}, unknown={unknown}"
            )
        rendered = self.prompt.format_map({key: str(value) for key, value in values.items()})
        _lint_natural_prompt(rendered, f"{self.id}.rendered_prompt")
        return rendered


@dataclass(frozen=True, slots=True)
class OfflineScenario:
    id: str
    scenario_family: str
    prompt: str
    expected_route: str
    assertions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageRow:
    api: str
    item_type: str
    definition_versions: tuple[str, ...]
    route: str
    effect: str
    scenario_ids: tuple[str, ...]
    scenario_families: tuple[str, ...]
    prompt_sha256: tuple[str, ...]

    @property
    def scenario_count(self) -> int:
        return len(self.scenario_ids)


@dataclass(frozen=True, slots=True)
class EvalBundleV3:
    manifest_path: Path
    online_path: Path
    offline_path: Path
    adapter_registry_path: Path
    adapter_implementation_status: str
    request_mapping_registry_path: Path
    request_mapping_implementation_status: str
    request_mapping_requirements: tuple[RequestMappingRequirement, ...]
    scenarios: tuple[OnlineScenario, ...]
    offline_cases: tuple[OfflineScenario, ...]
    coverage: tuple[CoverageRow, ...]
    minimum_scenarios_per_api: int

    def scenario(self, scenario_id: str) -> OnlineScenario:
        for scenario in self.scenarios:
            if scenario.id == scenario_id:
                return scenario
        raise EvalBundleV3Error(f"unknown v3 online scenario: {scenario_id}")

    def scenario_mapping_blockers(
        self,
        scenario_id: str,
    ) -> tuple[RequestMappingRequirement, ...]:
        self.scenario(scenario_id)
        return tuple(
            requirement
            for requirement in self.request_mapping_requirements
            if requirement.blocks_execution and scenario_id in requirement.case_ids
        )


def load_eval_bundle_v3(path: str | Path) -> EvalBundleV3:
    manifest_path = Path(path).expanduser().resolve(strict=True)
    root = _load_json(manifest_path, "suite manifest")
    _closed_keys(
        root,
        required={
            "contract",
            "skill_name",
            "versions",
            "documents",
            "coverage_policy",
            "profiles",
            "legacy_suite",
        },
        path="suite",
    )
    if root["contract"] != SUITE_CONTRACT:
        raise EvalBundleV3Error(f"suite.contract must be {SUITE_CONTRACT!r}")
    if root["skill_name"] != "waapi-skill":
        raise EvalBundleV3Error("suite.skill_name must be 'waapi-skill'")
    if _string_tuple(root["versions"], "suite.versions") != SUPPORTED_VERSIONS:
        raise EvalBundleV3Error("v3 definitions must preserve all five supported Wwise versions")

    base = manifest_path.parent
    documents = _object(root["documents"], "suite.documents")
    _closed_keys(
        documents,
        required={
            "online",
            "offline",
            "adapter_registry",
            "request_mapping_registry",
        },
        path="suite.documents",
    )
    online_path = _safe_child(base, documents["online"], "suite.documents.online")
    offline_path = _safe_child(base, documents["offline"], "suite.documents.offline")
    adapter_registry_path = _safe_child(
        base,
        documents["adapter_registry"],
        "suite.documents.adapter_registry",
    )
    request_mapping_registry_path = _safe_child(
        base,
        documents["request_mapping_registry"],
        "suite.documents.request_mapping_registry",
    )

    policy = _object(root["coverage_policy"], "suite.coverage_policy")
    _closed_keys(
        policy,
        required={
            "eligible_interface_status",
            "minimum_distinct_scenarios_per_api",
            "recommended_distinct_scenarios_per_api",
            "minimum_distinct_scenario_families_per_api",
            "offline_cases_receive_functional_credit",
            "repetitions_receive_additional_credit",
            "primary_apis_per_scenario",
            "coverage_unit",
            "representative_version_strategy",
            "version_row_coverage_claimed",
            "credit_rule",
        },
        path="suite.coverage_policy",
    )
    statuses = _string_tuple(
        policy["eligible_interface_status"], "suite.coverage_policy.eligible_interface_status"
    )
    if statuses != ELIGIBLE_INTERFACE_STATUSES:
        raise EvalBundleV3Error(
            "v3 eligible_interface_status must be available/available_via_transaction"
        )
    minimum = _positive_int(
        policy["minimum_distinct_scenarios_per_api"],
        "suite.coverage_policy.minimum_distinct_scenarios_per_api",
    )
    if minimum != 2:
        raise EvalBundleV3Error("v3 requires exactly two as the minimum distinct scenario count")
    if policy["offline_cases_receive_functional_credit"] is not False:
        raise EvalBundleV3Error("offline cases cannot receive functional coverage credit")
    if policy["repetitions_receive_additional_credit"] is not False:
        raise EvalBundleV3Error("repetitions cannot receive additional scenario credit")
    if policy["recommended_distinct_scenarios_per_api"] != 3:
        raise EvalBundleV3Error("v3 recommended distinct scenario count must be 3")
    if policy["minimum_distinct_scenario_families_per_api"] != 2:
        raise EvalBundleV3Error("v3 requires two distinct scenario families per API")
    if policy["primary_apis_per_scenario"] != 1:
        raise EvalBundleV3Error("v3 requires exactly one primary API per scenario")
    if policy["coverage_unit"] != "unique_executable_uri":
        raise EvalBundleV3Error("v3 coverage unit must remain unique executable URI")
    if policy["representative_version_strategy"] != "prefer_2022_1_else_earliest_available":
        raise EvalBundleV3Error("v3 representative-version strategy drifted")
    if policy["version_row_coverage_claimed"] is not False:
        raise EvalBundleV3Error("v3 cannot claim all version/API rows from representative cases")
    if policy["credit_rule"] != "primary_dispatch_and_business_oracle":
        raise EvalBundleV3Error("v3 coverage credit rule drifted")

    profiles = _list(root["profiles"], "suite.profiles")
    expected_profiles = (
        ("online_2022_review", "online", (EXECUTION_PROFILE_VERSION,)),
        ("offline_review", "offline", SUPPORTED_VERSIONS),
    )
    actual_profiles: list[tuple[str, str, tuple[str, ...]]] = []
    for index, value in enumerate(profiles):
        profile_path = f"suite.profiles[{index}]"
        profile = _object(value, profile_path)
        _closed_keys(
            profile,
            required={"id", "lane", "versions", "execution_status"},
            path=profile_path,
        )
        versions = _string_tuple(profile["versions"], f"{profile_path}.versions")
        if profile["execution_status"] != "definitions_only_pending_user_review":
            raise EvalBundleV3Error(f"{profile_path} cannot claim unrun execution evidence")
        actual_profiles.append(
            (
                _string(profile["id"], f"{profile_path}.id"),
                _string(profile["lane"], f"{profile_path}.lane"),
                versions,
            )
        )
    if tuple(actual_profiles) != expected_profiles:
        raise EvalBundleV3Error(f"suite.profiles must preserve {expected_profiles!r}")

    legacy = _object(root["legacy_suite"], "suite.legacy_suite")
    _closed_keys(legacy, required={"path", "profiles", "status"}, path="suite.legacy_suite")
    if legacy["path"] != "evals-v2.json":
        raise EvalBundleV3Error("suite.legacy_suite.path must preserve evals-v2.json")
    if legacy["profiles"] != {
        "screening": 40,
        "formal_98": 98,
        "full_cross_version_168": 168,
    }:
        raise EvalBundleV3Error("suite.legacy_suite profile totals drifted")
    if legacy["status"] != "frozen_compatibility_and_historical_evidence":
        raise EvalBundleV3Error("suite.legacy_suite status must remain frozen")

    scenarios = _load_online(online_path)
    offline_cases = _load_offline(offline_path)
    adapter_status = _load_adapter_registry(adapter_registry_path, scenarios)
    mapping_status, mapping_requirements = _load_request_mapping_registry(
        request_mapping_registry_path,
        scenarios,
    )
    coverage = _audit_coverage(scenarios, minimum=minimum)
    return EvalBundleV3(
        manifest_path=manifest_path,
        online_path=online_path,
        offline_path=offline_path,
        adapter_registry_path=adapter_registry_path,
        adapter_implementation_status=adapter_status,
        request_mapping_registry_path=request_mapping_registry_path,
        request_mapping_implementation_status=mapping_status,
        request_mapping_requirements=mapping_requirements,
        scenarios=scenarios,
        offline_cases=offline_cases,
        coverage=coverage,
        minimum_scenarios_per_api=minimum,
    )


def _load_online(index_path: Path) -> tuple[OnlineScenario, ...]:
    root = _load_json(index_path, "online test index")
    _closed_keys(
        root,
        required={
            "contract",
            "online_means",
            "definition_scope_versions",
            "execution_profile_version",
            "inventory_source",
            "required_scenarios_per_api",
            "prompt_materialization",
            "case_files",
            "isolation",
        },
        path="online",
    )
    if root["contract"] != ONLINE_CONTRACT:
        raise EvalBundleV3Error(f"online.contract must be {ONLINE_CONTRACT!r}")
    if _string_tuple(root["definition_scope_versions"], "online.definition_scope_versions") != SUPPORTED_VERSIONS:
        raise EvalBundleV3Error("online.definition_scope_versions must preserve all five versions")
    if root["execution_profile_version"] != EXECUTION_PROFILE_VERSION:
        raise EvalBundleV3Error("online.execution_profile_version must remain Wwise 2022.1")
    if root["required_scenarios_per_api"] != 2:
        raise EvalBundleV3Error("online.required_scenarios_per_api must be 2")
    materialization = _object(
        root["prompt_materialization"],
        "online.prompt_materialization",
    )
    _closed_keys(
        materialization,
        required=set(EXPECTED_PROMPT_MATERIALIZATION_CONTRACT),
        path="online.prompt_materialization",
    )
    if materialization != EXPECTED_PROMPT_MATERIALIZATION_CONTRACT:
        raise EvalBundleV3Error("online.prompt_materialization contract drifted")
    isolation = _object(root["isolation"], "online.isolation")
    _closed_keys(
        isolation,
        required={
            "codex_task",
            "mutation_confirmation",
            "wwise_lifecycle",
            "scenario_namespace",
            "source_project",
            "success_cleanup",
            "failure_cleanup",
        },
        path="online.isolation",
    )
    for key, value in isolation.items():
        _string(value, f"online.isolation.{key}")
    if isolation != EXPECTED_ISOLATION_CONTRACT:
        raise EvalBundleV3Error("online.isolation contract drifted")
    case_files = _string_tuple(root["case_files"], "online.case_files")
    if not case_files or len(case_files) != len(set(case_files)):
        raise EvalBundleV3Error("online.case_files must be a non-empty unique list")

    rows: list[OnlineScenario] = []
    for index, relative in enumerate(case_files):
        case_path = _safe_child(index_path.parent, relative, f"online.case_files[{index}]")
        payload = _load_json(case_path, f"online case file {relative}")
        keys = set(payload)
        if keys == {"contract", "version", "cases"}:
            file_versions = _version_tuple([payload["version"]], f"{relative}.version")
        elif keys == {"contract", "version_scope", "cases"}:
            file_versions = _version_tuple(payload["version_scope"], f"{relative}.version_scope")
        else:
            raise EvalBundleV3Error(
                f"{relative} fields mismatch; expected contract/cases plus version or version_scope"
            )
        if payload["contract"] != ONLINE_CASES_CONTRACT:
            raise EvalBundleV3Error(
                f"{relative}.contract must be {ONLINE_CASES_CONTRACT!r}"
            )
        for row_index, row in enumerate(_list(payload["cases"], f"{relative}.cases")):
            scenario = _parse_online_case(row, f"{relative}.cases[{row_index}]")
            if not set(scenario.versions).issubset(file_versions):
                raise EvalBundleV3Error(
                    f"{relative}.cases[{row_index}].versions falls outside the case file scope"
                )
            rows.append(scenario)
    _require_unique(tuple(row.id for row in rows), "online scenario ids")
    _require_unique(tuple(row.prompt for row in rows), "online natural prompt templates")
    return tuple(rows)


def _load_adapter_registry(
    path: Path,
    scenarios: Sequence[OnlineScenario],
) -> str:
    root = _load_json(path, "v3 adapter registry")
    _closed_keys(
        root,
        required={
            "contract",
            "implementation_status",
            "fixture_adapters",
            "trigger_adapters",
            "oracle_adapters",
            "cleanup_adapters",
        },
        path="adapter_registry",
    )
    if root["contract"] != ADAPTER_REGISTRY_CONTRACT:
        raise EvalBundleV3Error(
            f"adapter_registry.contract must be {ADAPTER_REGISTRY_CONTRACT!r}"
        )
    status = _string(
        root["implementation_status"],
        "adapter_registry.implementation_status",
    )
    if status != "specification_only_pending_user_review":
        raise EvalBundleV3Error(
            "v3 adapters cannot claim implementation or execution before user review"
        )

    declared: dict[str, tuple[str, ...]] = {}
    for key in (
        "fixture_adapters",
        "trigger_adapters",
        "oracle_adapters",
        "cleanup_adapters",
    ):
        values = tuple(
            _adapter_id(item, f"adapter_registry.{key}[{index}]")
            for index, item in enumerate(_list(root[key], f"adapter_registry.{key}"))
        )
        if not values:
            raise EvalBundleV3Error(f"adapter_registry.{key} must not be empty")
        _require_unique(values, f"adapter_registry.{key}")
        if values != tuple(sorted(values)):
            raise EvalBundleV3Error(f"adapter_registry.{key} must be sorted")
        declared[key] = values

    observed = {
        "fixture_adapters": {str(case.fixture["adapter"]) for case in scenarios},
        "trigger_adapters": {
            str(case.trigger["adapter"])
            for case in scenarios
            if case.trigger is not None
        },
        "oracle_adapters": {
            assertion.adapter
            for case in scenarios
            for assertion in case.oracle_assertions
        },
        "cleanup_adapters": {str(case.cleanup["adapter"]) for case in scenarios},
    }
    for key, actual in observed.items():
        expected = set(declared[key])
        missing = sorted(actual - expected)
        unused = sorted(expected - actual)
        if missing or unused:
            raise EvalBundleV3Error(
                f"adapter_registry.{key} does not exactly close the definitions; "
                f"missing={missing}, unused={unused}"
            )
    return status


def _load_request_mapping_registry(
    path: Path,
    scenarios: Sequence[OnlineScenario],
) -> tuple[str, tuple[RequestMappingRequirement, ...]]:
    root = _load_json(path, "v3 request-mapping registry")
    _closed_keys(
        root,
        required={
            "contract",
            "implementation_status",
            "execution_policy",
            "requirements",
        },
        path="request_mapping_registry",
    )
    if root["contract"] != REQUEST_MAPPING_REGISTRY_CONTRACT:
        raise EvalBundleV3Error(
            "request_mapping_registry.contract must be "
            f"{REQUEST_MAPPING_REGISTRY_CONTRACT!r}"
        )
    status = _string(
        root["implementation_status"],
        "request_mapping_registry.implementation_status",
    )
    if status != "specification_only_unresolved":
        raise EvalBundleV3Error(
            "v3 request mappings cannot claim implementation before they are closed"
        )
    expected_policy = (
        "a scenario referenced by any non-closed requirement is blocked from real "
        "execution until every requirement for that scenario is closed"
    )
    if root["execution_policy"] != expected_policy:
        raise EvalBundleV3Error("request_mapping_registry.execution_policy drifted")

    by_case = {scenario.id: scenario for scenario in scenarios}
    result: list[RequestMappingRequirement] = []
    for index, value in enumerate(
        _list(root["requirements"], "request_mapping_registry.requirements")
    ):
        row_path = f"request_mapping_registry.requirements[{index}]"
        row = _object(value, row_path)
        _closed_keys(
            row,
            required={
                "id",
                "kind",
                "status",
                "versions",
                "apis",
                "case_ids",
                "json_pointers",
                "required_semantics",
                "evidence",
            },
            path=row_path,
        )
        requirement_id = _string(row["id"], f"{row_path}.id")
        if not _MAPPING_ID_RE.fullmatch(requirement_id):
            raise EvalBundleV3Error(f"{row_path}.id is not a closed mapping id")
        kind = _string(row["kind"], f"{row_path}.kind")
        if kind not in {"enum_map", "schema_map", "route_gap"}:
            raise EvalBundleV3Error(f"{row_path}.kind is not a closed mapping kind")
        requirement_status = _string(row["status"], f"{row_path}.status")
        if requirement_status not in {
            "closed",
            "available_not_exposed",
            "missing",
            "route_gap",
        }:
            raise EvalBundleV3Error(f"{row_path}.status is not a closed mapping status")
        versions = _version_tuple(row["versions"], f"{row_path}.versions")
        apis = _string_tuple(row["apis"], f"{row_path}.apis")
        case_ids = _string_tuple(row["case_ids"], f"{row_path}.case_ids")
        json_pointers = _string_tuple(
            row["json_pointers"], f"{row_path}.json_pointers"
        )
        required_semantics = _string_tuple(
            row["required_semantics"], f"{row_path}.required_semantics"
        )
        evidence = _string_tuple(row["evidence"], f"{row_path}.evidence")
        for label, values in (
            ("apis", apis),
            ("case_ids", case_ids),
            ("json_pointers", json_pointers),
            ("required_semantics", required_semantics),
            ("evidence", evidence),
        ):
            if not values:
                raise EvalBundleV3Error(f"{row_path}.{label} must not be empty")
            _require_unique(values, f"{row_path}.{label}")
        if any(not pointer.startswith("/args/") for pointer in json_pointers):
            raise EvalBundleV3Error(f"{row_path}.json_pointers must target request args")

        selected: list[OnlineScenario] = []
        for case_id in case_ids:
            try:
                selected.append(by_case[case_id])
            except KeyError as exc:
                raise EvalBundleV3Error(
                    f"{row_path}.case_ids references unknown online scenario {case_id}"
                ) from exc
        actual_apis = tuple(sorted({scenario.api for scenario in selected}))
        if apis != actual_apis:
            raise EvalBundleV3Error(
                f"{row_path}.apis must exactly match referenced cases {actual_apis}"
            )
        actual_versions = tuple(
            version
            for version in SUPPORTED_VERSIONS
            if any(version in scenario.versions for scenario in selected)
        )
        if versions != actual_versions:
            raise EvalBundleV3Error(
                f"{row_path}.versions must exactly match referenced cases {actual_versions}"
            )
        result.append(
            RequestMappingRequirement(
                id=requirement_id,
                kind=kind,
                status=requirement_status,
                versions=versions,
                apis=apis,
                case_ids=case_ids,
                json_pointers=json_pointers,
                required_semantics=required_semantics,
                evidence=evidence,
            )
        )

    ids = tuple(item.id for item in result)
    _require_unique(ids, "request_mapping_registry requirement ids")
    if ids != tuple(sorted(ids)):
        raise EvalBundleV3Error("request_mapping_registry requirements must be sorted")
    if not any(item.blocks_execution for item in result):
        raise EvalBundleV3Error(
            "an unresolved mapping registry must contain at least one execution blocker"
        )
    return status, tuple(result)


def _parse_online_case(value: Any, path: str) -> OnlineScenario:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "id",
            "api",
            "item_type",
            "versions",
            "lane",
            "scenario_family",
            "scenario_index",
            "prompt",
            "protocol",
            "confirmation_prompt",
            "fixture",
            "trigger",
            "expected_dispatches",
            "oracle_assertions",
            "cleanup",
        },
        optional={"visible_inputs"},
        path=path,
    )
    scenario_id = _string(row["id"], f"{path}.id")
    if not _ID_RE.fullmatch(scenario_id):
        raise EvalBundleV3Error(f"{path}.id must use the closed uppercase scenario-id form")
    api = _string(row["api"], f"{path}.api")
    item_type = _string(row["item_type"], f"{path}.item_type")
    if item_type not in {"function", "topic"}:
        raise EvalBundleV3Error(f"{path}.item_type must be function or topic")
    versions = _version_tuple(row["versions"], f"{path}.versions")
    lane = _string(row["lane"], f"{path}.lane")
    if lane not in ONLINE_LANES:
        raise EvalBundleV3Error(f"{path}.lane is not a closed v3 online lane: {lane!r}")
    scenario_family = _adapter_id(row["scenario_family"], f"{path}.scenario_family")
    scenario_index = _positive_int(row["scenario_index"], f"{path}.scenario_index")
    if scenario_index not in {1, 2, 3, 4, 5}:
        raise EvalBundleV3Error(f"{path}.scenario_index must be between 1 and 5")
    prompt = _string(row["prompt"], f"{path}.prompt")
    _lint_natural_prompt(prompt, f"{path}.prompt")
    visible_inputs = _parse_visible_inputs(row.get("visible_inputs", []), f"{path}.visible_inputs")
    _validate_prompt_template(prompt, visible_inputs, f"{path}.prompt")
    protocol = _string(row["protocol"], f"{path}.protocol")
    if protocol not in PROTOCOLS:
        raise EvalBundleV3Error(f"{path}.protocol must be single or preview_confirm")
    confirmation_prompt = _optional_string(row["confirmation_prompt"], f"{path}.confirmation_prompt")
    if protocol == "preview_confirm":
        # A closed preflight refusal is still exercising a mutation route, but
        # it has no immutable mutation preview to confirm and dispatches zero
        # primary calls.  Positive paths retain the ordinary confirmation turn.
        if confirmation_prompt is not None:
            _lint_natural_prompt(confirmation_prompt, f"{path}.confirmation_prompt", minimum_length=6)
    elif confirmation_prompt is not None:
        raise EvalBundleV3Error(f"{path}.confirmation_prompt is forbidden for a single case")

    fixture = _parse_fixture(row["fixture"], f"{path}.fixture")
    trigger_raw = row["trigger"]
    trigger = None if trigger_raw is None else _parse_trigger(trigger_raw, f"{path}.trigger")
    dispatches = _parse_dispatches(row["expected_dispatches"], f"{path}.expected_dispatches")
    assertions = _parse_assertions(row["oracle_assertions"], f"{path}.oracle_assertions")
    cleanup = _parse_cleanup(row["cleanup"], f"{path}.cleanup")

    primary_dispatches = tuple(dispatch for dispatch in dispatches if dispatch.api == api)
    if len(primary_dispatches) != 1:
        raise EvalBundleV3Error(f"{path} must contain exactly one primary expected dispatch")
    if protocol == "preview_confirm":
        if primary_dispatches[0].count == 0 and confirmation_prompt is not None:
            raise EvalBundleV3Error(
                f"{path}.confirmation_prompt is forbidden for a zero-dispatch preflight refusal"
            )
        if primary_dispatches[0].count > 0 and confirmation_prompt is None:
            raise EvalBundleV3Error(f"{path}.confirmation_prompt is required")
    if any(dispatch.count == 0 and dispatch.api != api for dispatch in dispatches):
        raise EvalBundleV3Error(f"{path} cannot declare a zero-count supporting dispatch")
    if (
        protocol == "preview_confirm"
        and primary_dispatches[0].count > 1
        and confirmation_prompt != SEQUENTIAL_CONFIRMATION_PROMPT
    ):
        raise EvalBundleV3Error(
            f"{path}.confirmation_prompt must authorize only the currently visible "
            "preview when the primary API is called more than once"
        )
    strong = tuple(
        assertion
        for assertion in assertions
        if assertion.subject_api == api and assertion.adapter not in WEAK_ASSERTION_ADAPTERS
    )
    if not strong:
        raise EvalBundleV3Error(f"{path} lacks an independent business oracle for {api}")
    if item_type == "topic":
        if trigger is None:
            raise EvalBundleV3Error(f"{path} topic cases require a runner-owned trigger")
        if protocol != "single" or not any(item.phase == "event" for item in strong):
            raise EvalBundleV3Error(f"{path} topic cases require a single event oracle")
    elif trigger is not None:
        raise EvalBundleV3Error(f"{path} function cases cannot declare a topic trigger")

    return OnlineScenario(
        id=scenario_id,
        api=api,
        item_type=item_type,
        versions=versions,
        lane=lane,
        scenario_family=scenario_family,
        scenario_index=scenario_index,
        prompt=prompt,
        visible_inputs=visible_inputs,
        protocol=protocol,
        confirmation_prompt=confirmation_prompt,
        fixture=fixture,
        trigger=trigger,
        expected_dispatches=dispatches,
        oracle_assertions=assertions,
        cleanup=cleanup,
    )


def _load_offline(path: Path) -> tuple[OfflineScenario, ...]:
    root = _load_json(path, "offline tests")
    _closed_keys(
        root,
        required={
            "contract",
            "offline_means",
            "version_scope",
            "functional_coverage_credit",
            "cases",
        },
        path="offline",
    )
    if root["contract"] != OFFLINE_CONTRACT:
        raise EvalBundleV3Error(f"offline.contract must be {OFFLINE_CONTRACT!r}")
    if root["functional_coverage_credit"] is not False:
        raise EvalBundleV3Error("offline tests cannot claim functional coverage")
    if _string_tuple(root["version_scope"], "offline.version_scope") != (
        "2021.1",
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ):
        raise EvalBundleV3Error("offline.version_scope must preserve all five supported versions")
    cases: list[OfflineScenario] = []
    for index, value in enumerate(_list(root["cases"], "offline.cases")):
        row_path = f"offline.cases[{index}]"
        row = _object(value, row_path)
        _closed_keys(
            row,
            required={"id", "scenario_family", "prompt", "expected_route", "assertions"},
            path=row_path,
        )
        case_id = _string(row["id"], f"{row_path}.id")
        prompt = _string(row["prompt"], f"{row_path}.prompt")
        _lint_natural_prompt(prompt, f"{row_path}.prompt")
        assertions = _string_tuple(row["assertions"], f"{row_path}.assertions")
        if "no_live_wwise_connection" not in assertions:
            raise EvalBundleV3Error(f"{row_path} must assert no live Wwise connection")
        cases.append(
            OfflineScenario(
                id=case_id,
                scenario_family=_adapter_id(row["scenario_family"], f"{row_path}.scenario_family"),
                prompt=prompt,
                expected_route=_adapter_id(row["expected_route"], f"{row_path}.expected_route"),
                assertions=assertions,
            )
        )
    _require_unique(tuple(case.id for case in cases), "offline case ids")
    return tuple(cases)


def _audit_coverage(
    scenarios: Sequence[OnlineScenario],
    *,
    minimum: int,
) -> tuple[CoverageRow, ...]:
    catalog = CapabilityCatalog()
    expected: dict[str, dict[str, Any]] = defaultdict(dict)
    for version in SUPPORTED_VERSIONS:
        for record in catalog.entries(version):
            if record.execution_contract.get("executable") is True:
                expected[record.uri][version] = record
    by_api: dict[str, list[OnlineScenario]] = defaultdict(list)
    for scenario in scenarios:
        version_records = expected.get(scenario.api)
        if version_records is None:
            raise EvalBundleV3Error(
                f"online scenario {scenario.id} targets a non-executable five-version API: {scenario.api}"
            )
        selected_records: list[Any] = []
        for version in scenario.versions:
            record = version_records.get(version)
            if record is None:
                raise EvalBundleV3Error(
                    f"online scenario {scenario.id} targets {scenario.api} in unavailable Wwise {version}"
                )
            if scenario.item_type != record.item_type:
                raise EvalBundleV3Error(
                    f"online scenario {scenario.id} item_type does not match {scenario.api} in Wwise {version}"
                )
            selected_records.append(record)
        for dispatch in scenario.expected_dispatches:
            dispatch_records = expected.get(dispatch.api)
            unavailable_versions = [
                version
                for version in scenario.versions
                if dispatch_records is None or version not in dispatch_records
            ]
            if unavailable_versions:
                raise EvalBundleV3Error(
                    f"online scenario {scenario.id} declares supporting dispatch "
                    f"{dispatch.api} outside executable versions {unavailable_versions}"
                )
            if dispatch.api != scenario.api:
                confirmed_versions = [
                    version
                    for version in scenario.versions
                    if bool(
                        dispatch_records[version].execution_contract.get(
                            "requires_confirmation"
                        )
                    )
                ]
                if confirmed_versions:
                    _validate_compound_supporting_dispatch(
                        scenario,
                        dispatch,
                        confirmed_versions=confirmed_versions,
                    )
        expected_protocols = {
            "preview_confirm" if record.execution_contract.get("requires_confirmation") else "single"
            for record in selected_records
        }
        if expected_protocols != {scenario.protocol}:
            raise EvalBundleV3Error(
                f"online scenario {scenario.id} protocol {scenario.protocol!r} does not match "
                f"the selected version contracts {sorted(expected_protocols)!r}"
            )
        # The dispatch row's ``effect`` is a human-reviewable description of
        # the exact business action expected from that call.  Route/effect
        # classification itself is always derived from the immutable packaged
        # execution contract and recorded in CoverageRow; JSON prose cannot
        # override it.
        if scenario.protocol == "preview_confirm" and not any(
            item.phase in {"before", "preview"} and item.subject_api == scenario.api
            for item in scenario.oracle_assertions
        ):
            raise EvalBundleV3Error(
                f"online scenario {scenario.id} lacks a pre-execution unchanged-state oracle"
            )
        if not any(
            item.phase in {"after", "event"} and item.subject_api == scenario.api
            for item in scenario.oracle_assertions
        ):
            raise EvalBundleV3Error(
                f"online scenario {scenario.id} lacks an after/event business oracle"
            )
        by_api[scenario.api].append(scenario)

    missing = sorted(set(expected) - set(by_api))
    extra = sorted(set(by_api) - set(expected))
    if missing or extra:
        raise EvalBundleV3Error(
            f"v3 functional coverage inventory mismatch; missing={missing}, extra={extra}"
        )

    rows: list[CoverageRow] = []
    failures: list[str] = []
    for api in sorted(expected):
        cases = by_api[api]
        ids = tuple(case.id for case in cases)
        families = tuple(case.scenario_family for case in cases)
        digests = tuple(case.prompt_sha256 for case in cases)
        indices = tuple(case.scenario_index for case in cases)
        if len(set(ids)) < minimum:
            failures.append(f"{api}: only {len(set(ids))} distinct scenario ids")
        if len(set(families)) < minimum:
            failures.append(f"{api}: only {len(set(families))} distinct scenario families")
        if len(set(digests)) < minimum:
            failures.append(f"{api}: only {len(set(digests))} distinct natural prompts")
        if not {1, 2}.issubset(indices):
            failures.append(f"{api}: scenario_index 1 and 2 are both required")
        available_versions = tuple(
            version for version in SUPPORTED_VERSIONS if version in expected[api]
        )
        representative_version = (
            EXECUTION_PROFILE_VERSION
            if EXECUTION_PROFILE_VERSION in expected[api]
            else available_versions[0]
        )
        wrong_representatives = tuple(
            case.id
            for case in cases
            if case.versions != (representative_version,)
        )
        if wrong_representatives:
            failures.append(
                f"{api}: representative version must be {representative_version}; "
                f"wrong cases={list(wrong_representatives)}"
            )
        definition_versions = tuple(
            version
            for version in SUPPORTED_VERSIONS
            if any(version in case.versions for case in cases)
        )
        selected_records = [expected[api][version] for version in definition_versions]
        item_types = {record.item_type for record in selected_records}
        routes = sorted({str(record.execution_contract.get("route")) for record in selected_records})
        effects = sorted({str(record.execution_contract.get("effect")) for record in selected_records})
        if len(item_types) != 1:
            failures.append(f"{api}: item_type changes across selected definition versions")
        rows.append(
            CoverageRow(
                api=api,
                item_type=next(iter(item_types)),
                definition_versions=definition_versions,
                route="|".join(routes),
                effect="|".join(effects),
                scenario_ids=ids,
                scenario_families=families,
                prompt_sha256=digests,
            )
        )
    if failures:
        raise EvalBundleV3Error("v3 functional coverage is incomplete: " + "; ".join(failures))
    return tuple(rows)


def _validate_compound_supporting_dispatch(
    scenario: OnlineScenario,
    dispatch: ExpectedDispatch,
    *,
    confirmed_versions: Sequence[str],
) -> None:
    """Reject a hidden second transaction disguised as a supporting call.

    One natural confirmation can bind one packaged transaction.  The only
    current multi-URI exception is ``waapi.undoGroup``: its begin/end/cancel
    phases and allowlisted inner mutations execute inside the same immutable
    same-connection composite.  Any other confirmed supporting URI would need
    another preview and another user turn, so a two-turn v3 case cannot claim
    it as an expected model dispatch.
    """

    if scenario.api not in UNDO_GROUP_MEMBER_URIS:
        raise EvalBundleV3Error(
            f"online scenario {scenario.id} declares confirmed supporting dispatch "
            f"{dispatch.api} outside a waapi.undoGroup composite"
        )
    for version in confirmed_versions:
        if dispatch.api in UNDO_GROUP_MEMBER_URIS:
            continue
        allowed = UNDO_GROUP_INNER_URIS_BY_VERSION.get(version, frozenset())
        if dispatch.api not in allowed:
            raise EvalBundleV3Error(
                f"online scenario {scenario.id} declares {dispatch.api} outside the "
                f"Wwise {version} waapi.undoGroup inner allowlist"
            )


def _parse_fixture(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={"adapter", "sandbox", "prerequisites"},
        optional={"asset_spec", "lifecycle"},
        path=path,
    )
    adapter = _adapter_id(row["adapter"], f"{path}.adapter")
    sandbox = _string(row["sandbox"], f"{path}.sandbox")
    if sandbox not in {"scenario_project_copy", "isolated_io_root"}:
        raise EvalBundleV3Error(f"{path}.sandbox is not an isolated v3 sandbox")
    prerequisites = _string_tuple(row["prerequisites"], f"{path}.prerequisites")
    if not prerequisites:
        raise EvalBundleV3Error(f"{path}.prerequisites must not be empty")
    asset_spec = row.get("asset_spec")
    lifecycle = row.get("lifecycle")
    if adapter in {"audio_conversion_fixture", "media_pool_fixture"}:
        if (lifecycle is None) != (asset_spec is None):
            raise EvalBundleV3Error(
                f"{path}.lifecycle and asset_spec must be declared together for case-owned asset fixtures"
            )
        if lifecycle is not None:
            _parse_case_owned_lifecycle(lifecycle, f"{path}.lifecycle")
    elif lifecycle is not None:
        raise EvalBundleV3Error(
            f"{path}.lifecycle is not supported for fixture adapter {adapter!r}"
        )
    if adapter in {"audio_import_fixture", "tab_import_fixture"}:
        if asset_spec is None:
            raise EvalBundleV3Error(f"{path}.asset_spec is required for import fixtures")
        _parse_import_asset_spec(asset_spec, f"{path}.asset_spec", adapter=adapter)
    elif adapter in SOUNDBANK_FIXTURE_ADAPTERS:
        if asset_spec is None:
            if adapter in {"soundbank_inclusion_fixture", "soundbank_topic_fixture"}:
                return dict(row)
            raise EvalBundleV3Error(f"{path}.asset_spec is required for SoundBank fixtures")
        _parse_soundbank_asset_spec(asset_spec, f"{path}.asset_spec", adapter=adapter)
    elif adapter == "audio_conversion_fixture":
        if asset_spec is not None:
            _parse_audio_conversion_asset_spec(asset_spec, f"{path}.asset_spec")
    elif adapter == "media_pool_fixture":
        if asset_spec is not None:
            _parse_media_pool_asset_spec(asset_spec, f"{path}.asset_spec")
    elif adapter == "cli_isolated_process_fixture" and asset_spec is not None:
        _parse_cli_heavy_asset_spec(asset_spec, f"{path}.asset_spec")
    elif asset_spec is not None:
        raise EvalBundleV3Error(
            f"{path}.asset_spec is not supported for fixture adapter {adapter!r}"
        )
    return dict(row)


def _parse_case_owned_lifecycle(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={"ownership", "reuse_policy", "success_policy", "failure_policy"},
        path=path,
    )
    expected = {
        "ownership": "case_owned_project_and_asset_sandbox",
        "reuse_policy": "unique_per_scenario_execution",
        "success_policy": "delete_project_copy_and_all_owned_assets",
        "failure_policy": "seal_failed_or_indeterminate_sandbox_and_never_reuse",
    }
    for key, expected_value in expected.items():
        if row[key] != expected_value:
            raise EvalBundleV3Error(f"{path}.{key} must be {expected_value!r}")
    return dict(row)


def _parse_audio_conversion_asset_spec(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "contract",
            "wav",
            "request",
            "conversion_settings",
            "object_bindings",
            "control_objects",
            "expected_outputs",
            "source_policy",
            "output_policy",
            "cleanup_policy",
        },
        optional={"control_bindings", "baseline_recipe", "delta_plan"},
        path=path,
    )
    if row["contract"] != "waapi-skill.audio-conversion-fixture/v1":
        raise EvalBundleV3Error(f"{path}.contract is not supported")

    wav = _object(row["wav"], f"{path}.wav")
    _closed_keys(
        wav,
        required={"count", "format", "filename_pattern", "content_policy"},
        path=f"{path}.wav",
    )
    wav_count = _positive_int(wav["count"], f"{path}.wav.count")
    if wav["format"] != "pcm_s16le_mono_48000hz":
        raise EvalBundleV3Error(f"{path}.wav.format must use deterministic PCM input")
    _string(wav["filename_pattern"], f"{path}.wav.filename_pattern")
    if wav["content_policy"] != "deterministic_distinct_signal_per_source":
        raise EvalBundleV3Error(f"{path}.wav.content_policy is not reproducible")

    request = _object(row["request"], f"{path}.request")
    _closed_keys(
        request,
        required={"objects", "platforms", "languages"},
        path=f"{path}.request",
    )
    objects = _string_tuple(request["objects"], f"{path}.request.objects")
    platforms = _string_tuple(request["platforms"], f"{path}.request.platforms")
    languages = _string_tuple(request["languages"], f"{path}.request.languages")
    for label, values in (("objects", objects), ("platforms", platforms), ("languages", languages)):
        if not values:
            raise EvalBundleV3Error(f"{path}.request.{label} must not be empty")
        _require_unique(values, f"{path}.request.{label}")
    if any(not object_path.startswith("\\") for object_path in objects):
        raise EvalBundleV3Error(f"{path}.request.objects must use absolute Wwise paths")

    settings = _list(row["conversion_settings"], f"{path}.conversion_settings")
    setting_keys: list[str] = []
    if not settings:
        raise EvalBundleV3Error(f"{path}.conversion_settings must not be empty")
    for index, value in enumerate(settings):
        setting_path = f"{path}.conversion_settings[{index}]"
        setting = _object(value, setting_path)
        _closed_keys(
            setting,
            required={"key", "name", "codec", "sample_rate", "channels"},
            path=setting_path,
        )
        setting_keys.append(_adapter_id(setting["key"], f"{setting_path}.key"))
        _string(setting["name"], f"{setting_path}.name")
        _string(setting["codec"], f"{setting_path}.codec")
        _positive_int(setting["sample_rate"], f"{setting_path}.sample_rate")
        channels = _positive_int(setting["channels"], f"{setting_path}.channels")
        if channels not in {1, 2}:
            raise EvalBundleV3Error(f"{setting_path}.channels must be 1 or 2")
    _require_unique(tuple(setting_keys), f"{path}.conversion_settings keys")

    bindings = _list(row["object_bindings"], f"{path}.object_bindings")
    binding_paths: list[str] = []
    source_keys: list[str] = []
    for index, value in enumerate(bindings):
        binding_path = f"{path}.object_bindings[{index}]"
        binding = _object(value, binding_path)
        _closed_keys(
            binding,
            required={"path", "effective_settings"},
            optional={"source_key", "source_keys_by_language"},
            path=binding_path,
        )
        object_path = _string(binding["path"], f"{binding_path}.path")
        if not object_path.startswith("\\"):
            raise EvalBundleV3Error(f"{binding_path}.path must be absolute")
        binding_paths.append(object_path)
        has_single_source = "source_key" in binding
        has_localized_sources = "source_keys_by_language" in binding
        if has_single_source == has_localized_sources:
            raise EvalBundleV3Error(
                f"{binding_path} must declare exactly one of source_key or source_keys_by_language"
            )
        if has_single_source:
            source_keys.append(_adapter_id(binding["source_key"], f"{binding_path}.source_key"))
        else:
            localized = _object(
                binding["source_keys_by_language"],
                f"{binding_path}.source_keys_by_language",
            )
            if set(localized) != set(languages):
                raise EvalBundleV3Error(
                    f"{binding_path}.source_keys_by_language must cover the exact request languages"
                )
            source_keys.extend(
                _adapter_id(localized[language], f"{binding_path}.source_keys_by_language[{language!r}]")
                for language in languages
            )
        effective = _object(binding["effective_settings"], f"{binding_path}.effective_settings")
        if set(effective) != set(platforms):
            raise EvalBundleV3Error(
                f"{binding_path}.effective_settings must cover the exact request platforms"
            )
        if any(setting not in setting_keys for setting in effective.values()):
            raise EvalBundleV3Error(f"{binding_path}.effective_settings references an unknown setting")
    if tuple(binding_paths) != objects:
        raise EvalBundleV3Error(f"{path}.object_bindings must follow the exact request object order")
    _require_unique(tuple(binding_paths), f"{path}.object_bindings paths")
    controls = _string_tuple(row["control_objects"], f"{path}.control_objects")
    _require_unique(controls, f"{path}.control_objects")
    if set(controls).intersection(objects):
        raise EvalBundleV3Error(f"{path}.control_objects must not overlap converted objects")

    control_bindings = _list(row.get("control_bindings", []), f"{path}.control_bindings")
    control_binding_paths: list[str] = []
    for index, value in enumerate(control_bindings):
        binding_path = f"{path}.control_bindings[{index}]"
        binding = _object(value, binding_path)
        _closed_keys(
            binding,
            required={"path", "source_key", "effective_settings"},
            path=binding_path,
        )
        object_path = _string(binding["path"], f"{binding_path}.path")
        if not object_path.startswith("\\"):
            raise EvalBundleV3Error(f"{binding_path}.path must be absolute")
        control_binding_paths.append(object_path)
        source_keys.append(_adapter_id(binding["source_key"], f"{binding_path}.source_key"))
        effective = _object(binding["effective_settings"], f"{binding_path}.effective_settings")
        if set(effective) != set(platforms):
            raise EvalBundleV3Error(
                f"{binding_path}.effective_settings must cover the exact request platforms"
            )
        if any(setting not in setting_keys for setting in effective.values()):
            raise EvalBundleV3Error(f"{binding_path}.effective_settings references an unknown setting")
    if tuple(control_binding_paths) != controls:
        raise EvalBundleV3Error(
            f"{path}.control_bindings must follow the exact control_objects order"
        )
    if controls and not control_bindings:
        raise EvalBundleV3Error(f"{path}.control_objects require exact control_bindings")
    _require_unique(tuple(source_keys), f"{path}.all source keys")
    if len(source_keys) != wav_count:
        raise EvalBundleV3Error(
            f"{path}.wav.count must equal requested plus control source count"
        )

    if "baseline_recipe" in row:
        baseline = _object(row["baseline_recipe"], f"{path}.baseline_recipe")
        _closed_keys(
            baseline,
            required={
                "preconvert_objects",
                "platforms",
                "sealed_artifact_fields",
                "freshness_predicate",
            },
            path=f"{path}.baseline_recipe",
        )
        preconvert_objects = _string_tuple(
            baseline["preconvert_objects"],
            f"{path}.baseline_recipe.preconvert_objects",
        )
        if set(preconvert_objects) != set(objects) | set(controls):
            raise EvalBundleV3Error(
                f"{path}.baseline_recipe.preconvert_objects must cover all target and control objects"
            )
        if _string_tuple(baseline["platforms"], f"{path}.baseline_recipe.platforms") != platforms:
            raise EvalBundleV3Error(
                f"{path}.baseline_recipe.platforms must match request platforms"
            )
        sealed_fields = _string_tuple(
            baseline["sealed_artifact_fields"],
            f"{path}.baseline_recipe.sealed_artifact_fields",
        )
        if not {"path", "size", "sha256", "mtime_ns", "media_id"}.issubset(sealed_fields):
            raise EvalBundleV3Error(
                f"{path}.baseline_recipe.sealed_artifact_fields is incomplete"
            )
        _string(baseline["freshness_predicate"], f"{path}.baseline_recipe.freshness_predicate")

    delta_plan = _list(row.get("delta_plan", []), f"{path}.delta_plan")
    delta_paths: list[str] = []
    for index, value in enumerate(delta_plan):
        delta_path = f"{path}.delta_plan[{index}]"
        delta = _object(value, delta_path)
        _closed_keys(
            delta,
            required={"path", "kind", "before", "after"},
            path=delta_path,
        )
        object_path = _string(delta["path"], f"{delta_path}.path")
        if object_path not in objects:
            raise EvalBundleV3Error(f"{delta_path}.path must identify a requested object")
        delta_paths.append(object_path)
        if delta["kind"] not in {
            "replace_source_bytes",
            "replace_effective_settings",
            "delete_converted_artifacts",
        }:
            raise EvalBundleV3Error(f"{delta_path}.kind is not supported")
        if not _object(delta["before"], f"{delta_path}.before"):
            raise EvalBundleV3Error(f"{delta_path}.before must not be empty")
        if not _object(delta["after"], f"{delta_path}.after"):
            raise EvalBundleV3Error(f"{delta_path}.after must not be empty")
    _require_unique(tuple(delta_paths), f"{path}.delta_plan paths")

    outputs = _object(row["expected_outputs"], f"{path}.expected_outputs")
    _closed_keys(
        outputs,
        required={"count", "identity", "artifact_proof", "target_policy", "control_policy"},
        path=f"{path}.expected_outputs",
    )
    output_count = _positive_int(outputs["count"], f"{path}.expected_outputs.count")
    if output_count != len(objects) * len(platforms) * len(languages):
        raise EvalBundleV3Error(f"{path}.expected_outputs.count must equal object/platform/language product")
    if outputs["identity"] != "object_guid_media_id_platform_language":
        raise EvalBundleV3Error(f"{path}.expected_outputs.identity is not closed")
    if outputs["artifact_proof"] != "regular_file_nonzero_size_sha256_and_header":
        raise EvalBundleV3Error(f"{path}.expected_outputs.artifact_proof is not closed")
    _string(outputs["target_policy"], f"{path}.expected_outputs.target_policy")
    _string(outputs["control_policy"], f"{path}.expected_outputs.control_policy")
    if row["source_policy"] != "absolute_regular_non_symlink_size_sha256":
        raise EvalBundleV3Error(f"{path}.source_policy must bind immutable source files")
    if row["output_policy"] != "case_owned_conversion_cache_tree":
        raise EvalBundleV3Error(f"{path}.output_policy must isolate converted output")
    if row["cleanup_policy"] != "case_owned_project_copy_and_output_root_discard":
        raise EvalBundleV3Error(f"{path}.cleanup_policy must discard all case-owned state")
    return dict(row)


def _parse_media_pool_asset_spec(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "contract",
            "wav",
            "databases",
            "rows",
            "request_template",
            "expected_file_keys",
            "expected_groups",
            "association_expectations",
            "field_binding",
            "source_policy",
            "cleanup_policy",
        },
        optional={"expected_candidate_file_keys"},
        path=path,
    )
    if row["contract"] != "waapi-skill.media-pool-fixture/v1":
        raise EvalBundleV3Error(f"{path}.contract is not supported")
    wav = _object(row["wav"], f"{path}.wav")
    _closed_keys(wav, required={"count", "format_policy", "content_policy"}, path=f"{path}.wav")
    wav_count = _positive_int(wav["count"], f"{path}.wav.count")
    if wav["format_policy"] != "declared_pcm_rate_channels_depth_duration_with_ixml":
        raise EvalBundleV3Error(f"{path}.wav.format_policy is not reproducible")
    if wav["content_policy"] != "deterministic_distinct_signal_per_file":
        raise EvalBundleV3Error(f"{path}.wav.content_policy is not reproducible")

    database_keys: list[str] = []
    databases = _list(row["databases"], f"{path}.databases")
    if not databases:
        raise EvalBundleV3Error(f"{path}.databases must not be empty")
    for index, value in enumerate(databases):
        database_path = f"{path}.databases[{index}]"
        database = _object(value, database_path)
        _closed_keys(database, required={"key", "path"}, path=database_path)
        database_keys.append(_adapter_id(database["key"], f"{database_path}.key"))
        reflected_path = _string(database["path"], f"{database_path}.path")
        if not reflected_path.startswith("\\Databases\\"):
            raise EvalBundleV3Error(f"{database_path}.path must be a Media Pool database path")
    _require_unique(tuple(database_keys), f"{path}.databases keys")

    fixture_rows = _list(row["rows"], f"{path}.rows")
    if len(fixture_rows) != wav_count:
        raise EvalBundleV3Error(f"{path}.wav.count must equal the declared Media Pool row count")
    row_keys: list[str] = []
    for index, value in enumerate(fixture_rows):
        row_path = f"{path}.rows[{index}]"
        fixture_row = _object(value, row_path)
        _closed_keys(
            fixture_row,
            required={
                "key",
                "database",
                "relative_path",
                "sample_rate",
                "channels",
                "bit_depth",
                "duration_seconds",
                "ixml",
                "referenced_by",
            },
            path=row_path,
        )
        row_keys.append(_adapter_id(fixture_row["key"], f"{row_path}.key"))
        if fixture_row["database"] not in database_keys:
            raise EvalBundleV3Error(f"{row_path}.database references an unknown database")
        relative_path = _string(fixture_row["relative_path"], f"{row_path}.relative_path")
        if relative_path.startswith(("/", "\\")) or ".." in relative_path.replace("\\", "/").split("/"):
            raise EvalBundleV3Error(f"{row_path}.relative_path must stay below its database root")
        _positive_int(fixture_row["sample_rate"], f"{row_path}.sample_rate")
        channels = _positive_int(fixture_row["channels"], f"{row_path}.channels")
        if channels not in {1, 2}:
            raise EvalBundleV3Error(f"{row_path}.channels must be 1 or 2")
        _positive_int(fixture_row["bit_depth"], f"{row_path}.bit_depth")
        duration = fixture_row["duration_seconds"]
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            raise EvalBundleV3Error(f"{row_path}.duration_seconds must be positive")
        ixml = _object(fixture_row["ixml"], f"{row_path}.ixml")
        if not all(isinstance(key, str) and isinstance(item, str) for key, item in ixml.items()):
            raise EvalBundleV3Error(f"{row_path}.ixml must contain string fields and values")
        references = _string_tuple(fixture_row["referenced_by"], f"{row_path}.referenced_by")
        _require_unique(references, f"{row_path}.referenced_by")
        if any(not reference.startswith("\\") for reference in references):
            raise EvalBundleV3Error(f"{row_path}.referenced_by must use absolute Wwise paths")
    _require_unique(tuple(row_keys), f"{path}.rows keys")
    known_row_keys = set(row_keys)

    request_template = _object(row["request_template"], f"{path}.request_template")
    _closed_keys(
        request_template,
        required={"args", "options"},
        optional={"post_filter"},
        path=f"{path}.request_template",
    )
    _object(request_template["args"], f"{path}.request_template.args")
    _object(request_template["options"], f"{path}.request_template.options")
    post_filter_value = request_template.get("post_filter")
    if post_filter_value is not None:
        post_filter = _object(
            post_filter_value,
            f"{path}.request_template.post_filter",
        )
        _closed_keys(
            post_filter,
            required={"field", "operator", "value", "limit"},
            path=f"{path}.request_template.post_filter",
        )
        field = _string(
            post_filter["field"],
            f"{path}.request_template.post_filter.field",
        )
        field_match = _MEDIA_POOL_FIELD_TOKEN_RE.fullmatch(field)
        if field_match is None or field_match.group(1) != "name":
            raise EvalBundleV3Error(
                f"{path}.request_template.post_filter.field must use the reviewed Filename concept"
            )
        if post_filter["operator"] != "containsCaseSensitive":
            raise EvalBundleV3Error(
                f"{path}.request_template.post_filter.operator is not supported"
            )
        _string(
            post_filter["value"],
            f"{path}.request_template.post_filter.value",
        )
        _positive_int(
            post_filter["limit"],
            f"{path}.request_template.post_filter.limit",
        )
        request_args = _object(
            request_template["args"],
            f"{path}.request_template.args",
        )
        request_options = _object(
            request_template["options"],
            f"{path}.request_template.options",
        )
        filters = _list(
            request_args.get("filters"),
            f"{path}.request_template.args.filters",
        )
        matching_candidates = [
            item
            for item in filters
            if isinstance(item, dict)
            and item.get("type") == "field"
            and item.get("field") == field
            and item.get("operator") == "contains"
            and item.get("value") == post_filter["value"]
        ]
        returns = _list(
            request_options.get("return"),
            f"{path}.request_template.options.return",
        )
        if (
            len(matching_candidates) != 1
            or request_args.get("maxResults") != 200
            or post_filter["limit"] > 200
            or field not in returns
        ):
            raise EvalBundleV3Error(
                f"{path}.request_template.post_filter is not bound to one complete server candidate request"
            )
    expected = _string_tuple(row["expected_file_keys"], f"{path}.expected_file_keys")
    if not expected:
        raise EvalBundleV3Error(f"{path}.expected_file_keys must not be empty")
    _require_unique(expected, f"{path}.expected_file_keys")
    if not set(expected).issubset(known_row_keys):
        raise EvalBundleV3Error(f"{path}.expected_file_keys references an unknown fixture row")
    candidate_value = row.get("expected_candidate_file_keys")
    if post_filter_value is not None and candidate_value is None:
        raise EvalBundleV3Error(
            f"{path}.expected_candidate_file_keys is required with post_filter"
        )
    candidates = (
        expected
        if candidate_value is None
        else _string_tuple(
            candidate_value,
            f"{path}.expected_candidate_file_keys",
        )
    )
    if not candidates:
        raise EvalBundleV3Error(
            f"{path}.expected_candidate_file_keys must not be empty"
        )
    _require_unique(candidates, f"{path}.expected_candidate_file_keys")
    if not set(candidates).issubset(known_row_keys):
        raise EvalBundleV3Error(
            f"{path}.expected_candidate_file_keys references an unknown fixture row"
        )
    if not set(expected).issubset(candidates):
        raise EvalBundleV3Error(
            f"{path}.expected_file_keys must be contained in expected_candidate_file_keys"
        )
    if post_filter_value is None and candidates != expected:
        raise EvalBundleV3Error(
            f"{path}.expected_candidate_file_keys must equal expected_file_keys without post_filter"
        )

    groups = _object(row["expected_groups"], f"{path}.expected_groups")
    for group_name, values in groups.items():
        members = _string_tuple(values, f"{path}.expected_groups[{group_name!r}]")
        if not group_name or not members or not set(members).issubset(set(expected)):
            raise EvalBundleV3Error(f"{path}.expected_groups must contain only expected rows")

    association = row["association_expectations"]
    if association is not None:
        association_row = _object(association, f"{path}.association_expectations")
        _closed_keys(
            association_row,
            required={"referenced", "unreferenced"},
            path=f"{path}.association_expectations",
        )
        referenced = _string_tuple(
            association_row["referenced"],
            f"{path}.association_expectations.referenced",
        )
        unreferenced = _string_tuple(
            association_row["unreferenced"],
            f"{path}.association_expectations.unreferenced",
        )
        if set(referenced).intersection(unreferenced) or set(referenced) | set(unreferenced) != set(expected):
            raise EvalBundleV3Error(
                f"{path}.association_expectations must partition the expected rows"
            )
    if row["field_binding"] != "supporting_mediaPool.getFields_exact_case":
        raise EvalBundleV3Error(f"{path}.field_binding is not closed")
    if row["source_policy"] != "case_owned_regular_wav_size_sha256_and_index_refresh":
        raise EvalBundleV3Error(f"{path}.source_policy is not reproducible")
    if row["cleanup_policy"] != "case_owned_project_copy_and_media_databases_discard":
        raise EvalBundleV3Error(f"{path}.cleanup_policy must discard all case-owned state")
    return dict(row)


def _parse_cli_heavy_asset_spec(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "contract",
            "operation",
            "project",
            "request",
            "assets",
            "expected",
            "sandbox_policy",
            "custom_command_policy",
            "cleanup_policy",
        },
        optional={"fixture_manifest"},
        path=path,
    )
    if row["contract"] != "waapi-skill.cli-heavy-fixture/v1":
        raise EvalBundleV3Error(f"{path}.contract is not supported")
    operation = _string(row["operation"], f"{path}.operation")
    if operation not in {
        "generateSoundbank",
        "tabDelimitedImport",
        "convertExternalSource",
        "migrate",
    }:
        raise EvalBundleV3Error(f"{path}.operation is not a reviewed heavy CLI operation")
    _parse_cli_project_spec(row["project"], f"{path}.project", operation=operation)
    if row["sandbox_policy"] != "fresh_project_process_asset_and_output_roots_per_case":
        raise EvalBundleV3Error(f"{path}.sandbox_policy is not fully isolated")
    if row["custom_command_policy"] != "forbid_all_custom_command_fields_and_project_hooks":
        raise EvalBundleV3Error(f"{path}.custom_command_policy must prohibit custom commands")
    if row["cleanup_policy"] != (
        "success_remove_all_case_owned_project_process_asset_output_"
        "failure_or_indeterminate_seal_never_reuse"
    ):
        raise EvalBundleV3Error(f"{path}.cleanup_policy is not fail-closed")

    parser = {
        "generateSoundbank": _parse_cli_generate_spec,
        "tabDelimitedImport": _parse_cli_tab_import_spec,
        "convertExternalSource": _parse_cli_external_source_spec,
        "migrate": _parse_cli_migrate_spec,
    }[operation]
    if operation == "generateSoundbank":
        if "fixture_manifest" not in row:
            raise EvalBundleV3Error(
                f"{path}.fixture_manifest is required for generateSoundbank"
            )
        _parse_cli_generate_spec(
            row["request"],
            row["assets"],
            row["expected"],
            row["fixture_manifest"],
            path,
        )
    else:
        if "fixture_manifest" in row:
            raise EvalBundleV3Error(
                f"{path}.fixture_manifest is only valid for generateSoundbank"
            )
        parser(row["request"], row["assets"], row["expected"], path)
    return dict(row)


def _parse_cli_project_spec(value: Any, path: str, *, operation: str) -> None:
    row = _object(value, path)
    _closed_keys(
        row,
        required={"source_version", "target_version", "copy_policy", "before_snapshot"},
        path=path,
    )
    source_version = _string(row["source_version"], f"{path}.source_version")
    target_version = _string(row["target_version"], f"{path}.target_version")
    if target_version != EXECUTION_PROFILE_VERSION:
        raise EvalBundleV3Error(f"{path}.target_version must be {EXECUTION_PROFILE_VERSION}")
    if operation == "migrate":
        if source_version != "2021.1":
            raise EvalBundleV3Error(f"{path}.source_version must be the pinned 2021.1 fixture")
    elif source_version != EXECUTION_PROFILE_VERSION:
        raise EvalBundleV3Error(f"{path}.source_version must match the execution profile")
    if row["copy_policy"] != "absolute_case_owned_project_tree_from_read_only_template":
        raise EvalBundleV3Error(f"{path}.copy_policy is not isolated")
    snapshots = _string_tuple(row["before_snapshot"], f"{path}.before_snapshot")
    required = {
        "project_tree_sha256",
        "object_guid_type_path",
        "platform_language_settings",
    }
    if not required.issubset(snapshots):
        raise EvalBundleV3Error(f"{path}.before_snapshot lacks the required closed baseline")
    _require_unique(snapshots, f"{path}.before_snapshot")


def _parse_cli_generate_spec(
    request_value: Any,
    assets_value: Any,
    expected_value: Any,
    fixture_manifest_value: Any,
    path: str,
) -> None:
    request = _object(request_value, f"{path}.request")
    _closed_keys(
        request,
        required={
            "bank_selector",
            "banks",
            "platforms",
            "languages",
            "skip_languages",
            "output_mode",
            "clear_audio_file_cache",
            "header_file",
            "import_definition_files",
            "save",
            "use_stable_guid",
            "continue_on_error",
            "path_bindings",
        },
        path=f"{path}.request",
    )
    selector = _string(request["bank_selector"], f"{path}.request.bank_selector")
    if selector not in {"names", "absolute_utf8_list_file"}:
        raise EvalBundleV3Error(f"{path}.request.bank_selector is not closed")
    banks = _string_tuple(request["banks"], f"{path}.request.banks")
    platforms = _string_tuple(request["platforms"], f"{path}.request.platforms")
    languages = _string_tuple(request["languages"], f"{path}.request.languages")
    if not banks or not platforms:
        raise EvalBundleV3Error(f"{path}.request requires banks and platforms")
    _require_unique(tuple(value.casefold() for value in banks), f"{path}.request.banks")
    _require_unique(tuple(value.casefold() for value in platforms), f"{path}.request.platforms")
    _require_unique(tuple(value.casefold() for value in languages), f"{path}.request.languages")
    skip_languages = _boolean(request["skip_languages"], f"{path}.request.skip_languages")
    if skip_languages == bool(languages):
        raise EvalBundleV3Error(f"{path}.request languages disagree with skip_languages")
    if request["output_mode"] not in {"single_root", "per_platform"}:
        raise EvalBundleV3Error(f"{path}.request.output_mode is not closed")
    path_bindings = _object(
        request["path_bindings"],
        f"{path}.request.path_bindings",
    )
    _closed_keys(
        path_bindings,
        required={
            "resolution_policy",
            "fixture_owned_root_keys",
            "soundbank_paths",
            "cache",
            "root_output_path",
        },
        path=f"{path}.request.path_bindings",
    )
    if path_bindings["resolution_policy"] != (
        "resolve_declared_case_root_keys_to_absolute_paths_then_append_contained_relative_path"
    ):
        raise EvalBundleV3Error(
            f"{path}.request.path_bindings.resolution_policy is not closed"
        )
    fixture_root_keys = _string_tuple(
        path_bindings["fixture_owned_root_keys"],
        f"{path}.request.path_bindings.fixture_owned_root_keys",
    )
    _require_unique(
        fixture_root_keys,
        f"{path}.request.path_bindings.fixture_owned_root_keys",
    )
    if not set(fixture_root_keys).issubset(
        {"case_cache_directory", "case_root_output_directory"}
    ):
        raise EvalBundleV3Error(
            f"{path}.request.path_bindings.fixture_owned_root_keys is not reviewed"
        )

    def parse_path_binding(value: Any, binding_path: str) -> tuple[str, str]:
        binding = _object(value, binding_path)
        _closed_keys(
            binding,
            required={"root_key", "relative_path"},
            path=binding_path,
        )
        root_key = _adapter_id(binding["root_key"], f"{binding_path}.root_key")
        relative_path = _string(
            binding["relative_path"],
            f"{binding_path}.relative_path",
        ).replace("\\", "/")
        if (
            relative_path.startswith("/")
            or ".." in relative_path.split("/")
            or any(part == "" for part in relative_path.split("/"))
        ):
            raise EvalBundleV3Error(
                f"{binding_path}.relative_path must stay below its declared root"
            )
        return root_key, relative_path

    soundbank_path_rows = _list(
        path_bindings["soundbank_paths"],
        f"{path}.request.path_bindings.soundbank_paths",
    )
    bound_platforms: list[str] = []
    bound_soundbank_paths: list[tuple[str, str]] = []
    for index, value in enumerate(soundbank_path_rows):
        binding_path = f"{path}.request.path_bindings.soundbank_paths[{index}]"
        binding = _object(value, binding_path)
        _closed_keys(
            binding,
            required={"platform", "root_key", "relative_path"},
            path=binding_path,
        )
        bound_platforms.append(
            _string(binding["platform"], f"{binding_path}.platform")
        )
        root_key, relative_path = parse_path_binding(
            {"root_key": binding["root_key"], "relative_path": binding["relative_path"]},
            binding_path,
        )
        if root_key != "output_directory":
            raise EvalBundleV3Error(
                f"{binding_path}.root_key must bind the visible output_directory"
            )
        bound_soundbank_paths.append((root_key, relative_path))
    if tuple(bound_platforms) != platforms:
        raise EvalBundleV3Error(
            f"{path}.request.path_bindings.soundbank_paths must follow every requested platform"
        )
    _require_unique(
        tuple(f"{root}|{relative.casefold()}" for root, relative in bound_soundbank_paths),
        f"{path}.request.path_bindings.soundbank_paths physical paths",
    )
    if request["output_mode"] == "single_root":
        if len(platforms) != 1 or bound_soundbank_paths != [("output_directory", ".")]:
            raise EvalBundleV3Error(
                f"{path}.request.output_mode single_root is only closed for one platform at the visible root"
            )
    elif any(relative == "." for _, relative in bound_soundbank_paths):
        raise EvalBundleV3Error(
            f"{path}.request.output_mode per_platform requires a distinct contained directory per platform"
        )

    cache_binding = parse_path_binding(
        path_bindings["cache"],
        f"{path}.request.path_bindings.cache",
    )
    root_output_binding = parse_path_binding(
        path_bindings["root_output_path"],
        f"{path}.request.path_bindings.root_output_path",
    )
    if cache_binding[0] not in {"cache_directory", "case_cache_directory"}:
        raise EvalBundleV3Error(
            f"{path}.request.path_bindings.cache.root_key is not a cache root"
        )
    if root_output_binding[0] not in {
        "root_output_directory",
        "case_root_output_directory",
    }:
        raise EvalBundleV3Error(
            f"{path}.request.path_bindings.root_output_path.root_key is not a root output"
        )
    if cache_binding[1] != "." or root_output_binding[1] != ".":
        raise EvalBundleV3Error(
            f"{path}.request.path_bindings cache and root_output_path must bind their exact roots"
        )
    referenced_fixture_roots = {
        root_key
        for root_key in (cache_binding[0], root_output_binding[0])
        if root_key.startswith("case_")
    }
    if set(fixture_root_keys) != referenced_fixture_roots:
        raise EvalBundleV3Error(
            f"{path}.request.path_bindings.fixture_owned_root_keys must exactly declare runner-created roots"
        )
    if len({cache_binding, root_output_binding, *bound_soundbank_paths}) != (
        2 + len(bound_soundbank_paths)
    ):
        raise EvalBundleV3Error(
            f"{path}.request.path_bindings must use disjoint cache, root-output, and SoundBank paths"
        )
    for field in (
        "clear_audio_file_cache",
        "header_file",
        "save",
        "use_stable_guid",
        "continue_on_error",
    ):
        _boolean(request[field], f"{path}.request.{field}")
    if request["save"] is not False or request["continue_on_error"] is not False:
        raise EvalBundleV3Error(f"{path}.request must be non-persistent and stop on error")
    definition_names = _string_tuple(
        request["import_definition_files"],
        f"{path}.request.import_definition_files",
    )
    _require_unique(definition_names, f"{path}.request.import_definition_files")

    assets = _object(assets_value, f"{path}.assets")
    _closed_keys(assets, required={"bank_list", "definition_files"}, path=f"{path}.assets")
    bank_list = assets["bank_list"]
    if selector == "names":
        if bank_list is not None:
            raise EvalBundleV3Error(f"{path}.assets.bank_list is only valid for the file selector")
    else:
        list_row = _object(bank_list, f"{path}.assets.bank_list")
        _closed_keys(
            list_row,
            required={"name", "encoding", "entries", "path_policy"},
            path=f"{path}.assets.bank_list",
        )
        if not _string(list_row["name"], f"{path}.assets.bank_list.name").endswith(".txt"):
            raise EvalBundleV3Error(f"{path}.assets.bank_list.name must end in .txt")
        if list_row["encoding"] != "utf-8_no_bom" or list_row["path_policy"] != "absolute_regular_non_symlink_size_sha256":
            raise EvalBundleV3Error(f"{path}.assets.bank_list is not immutable")
        if _string_tuple(list_row["entries"], f"{path}.assets.bank_list.entries") != banks:
            raise EvalBundleV3Error(f"{path}.assets.bank_list.entries must equal the requested banks")

    definition_files = _list(assets["definition_files"], f"{path}.assets.definition_files")
    parsed_definition_names: list[str] = []
    definition_banks: set[str] = set()
    definition_event_paths: dict[str, list[str]] = defaultdict(list)
    for index, value in enumerate(definition_files):
        definition_path = f"{path}.assets.definition_files[{index}]"
        definition = _object(value, definition_path)
        _closed_keys(
            definition,
            required={
                "name",
                "encoding",
                "serialization",
                "rows",
                "path_policy",
                "materialization_policy",
            },
            path=definition_path,
        )
        name = _string(definition["name"], f"{definition_path}.name")
        parsed_definition_names.append(name)
        if definition["encoding"] != "utf-8_no_bom" or definition["path_policy"] != "absolute_regular_non_symlink_size_sha256":
            raise EvalBundleV3Error(f"{definition_path} is not immutable")
        serialization = _object(
            definition["serialization"],
            f"{definition_path}.serialization",
        )
        _closed_keys(
            serialization,
            required=set(SOUNDBANK_DEFINITION_SERIALIZATION),
            path=f"{definition_path}.serialization",
        )
        if serialization != SOUNDBANK_DEFINITION_SERIALIZATION:
            raise EvalBundleV3Error(
                f"{definition_path}.serialization is not the reviewed SoundBank Definition TSV layout"
            )
        if definition["materialization_policy"] != (
            "runner_resolves_declared_object_paths_then_writes_sealed_guid_identity_rows"
        ):
            raise EvalBundleV3Error(
                f"{definition_path}.materialization_policy is not the reviewed TSV renderer"
            )
        rows = _list(definition["rows"], f"{definition_path}.rows")
        if not rows:
            raise EvalBundleV3Error(f"{definition_path}.rows must not be empty")
        for row_index, value in enumerate(rows):
            row_path = f"{definition_path}.rows[{row_index}]"
            definition_row = _object(value, row_path)
            _closed_keys(
                definition_row,
                required={
                    "soundbank",
                    "directive",
                    "identity",
                    "identity_format",
                    "identity_materialization",
                    "filters",
                    "resolution",
                },
                path=row_path,
            )
            bank = _string(definition_row["soundbank"], f"{row_path}.soundbank")
            if any(character in bank for character in ("\t", "\r", "\n", '"')):
                raise EvalBundleV3Error(f"{row_path}.soundbank is not safely serializable")
            if bank not in banks:
                raise EvalBundleV3Error(f"{row_path}.soundbank is not requested")
            definition_banks.add(bank)
            directive = _string(definition_row["directive"], f"{row_path}.directive")
            allowed_filters = SOUNDBANK_DEFINITION_FILTERS.get(directive)
            if allowed_filters is None:
                raise EvalBundleV3Error(f"{row_path}.directive is not supported")
            identity = _string(definition_row["identity"], f"{row_path}.identity")
            if any(character in identity for character in ("\t", "\r", "\n", '"')):
                raise EvalBundleV3Error(f"{row_path}.identity is not safely serializable")
            identity_format = _string(
                definition_row["identity_format"],
                f"{row_path}.identity_format",
            )
            if identity_format not in SOUNDBANK_IDENTITY_FORMATS:
                raise EvalBundleV3Error(f"{row_path}.identity_format is not supported")
            materialization = _string(
                definition_row["identity_materialization"],
                f"{row_path}.identity_materialization",
            )
            if materialization != SOUNDBANK_IDENTITY_MATERIALIZATION[identity_format]:
                raise EvalBundleV3Error(
                    f"{row_path}.identity_materialization does not match identity_format"
                )
            if materialization != "runner_queries_guid" or not identity.startswith("\\"):
                raise EvalBundleV3Error(
                    f"{row_path}.identity must be an absolute object path resolved by the runner to GUID"
                )
            if directive == "Event":
                definition_event_paths[bank].append(identity)
            if definition_row["resolution"] != "unique":
                raise EvalBundleV3Error(f"{row_path}.resolution must be unique before rendering")
            filters = _string_tuple(definition_row["filters"], f"{row_path}.filters")
            if not filters or not set(filters).issubset(allowed_filters):
                raise EvalBundleV3Error(
                    f"{row_path}.filters is outside the exact case-sensitive directive filter set"
                )
            _require_unique(filters, f"{row_path}.filters")
    if tuple(parsed_definition_names) != definition_names:
        raise EvalBundleV3Error(f"{path}.assets.definition_files must match the request order")
    if definition_files and definition_banks != set(banks):
        raise EvalBundleV3Error(f"{path}.assets.definition_files must define every requested Bank")

    artifact_expectation = "nonlocalized" if skip_languages else "localized"
    bank_scopes = {
        bank: (artifact_expectation, platforms, languages)
        for bank in banks
    }
    _parse_soundbank_content_fixture(
        fixture_manifest_value,
        f"{path}.fixture_manifest",
        bank_scopes=bank_scopes,
    )
    fixture_manifest = _object(
        fixture_manifest_value,
        f"{path}.fixture_manifest",
    )
    if "init_precondition" in fixture_manifest:
        raise EvalBundleV3Error(
            f"{path}.fixture_manifest.init_precondition is reserved for generated topic cases"
        )
    fixture_banks = {
        bank["name"]: bank
        for bank in _list(
            fixture_manifest["soundbanks"],
            f"{path}.fixture_manifest.soundbanks",
        )
    }
    expected_mode = (
        "temporary_request_only" if definition_files else "existing_soundbank"
    )
    for bank_name, fixture_bank in fixture_banks.items():
        if fixture_bank["project_object_mode"] != expected_mode:
            raise EvalBundleV3Error(
                f"{path}.fixture_manifest project_object_mode for {bank_name!r} "
                "does not match the CLI definition-import request shape"
            )
        if definition_files:
            fixture_event_paths = tuple(
                event["object_path"] for event in fixture_bank["events"]
            )
            if tuple(definition_event_paths[bank_name]) != fixture_event_paths:
                raise EvalBundleV3Error(
                    f"{path}.fixture_manifest events for {bank_name!r} must equal "
                    "the imported definition Event identities"
                )

    expected = _object(expected_value, f"{path}.expected")
    _closed_keys(
        expected,
        required={"bank_artifacts", "automatic_artifacts", "absent_banks", "proof", "project_copy"},
        path=f"{path}.expected",
    )
    artifact_keys: list[str] = []
    for index, value in enumerate(_list(expected["bank_artifacts"], f"{path}.expected.bank_artifacts")):
        artifact_path = f"{path}.expected.bank_artifacts[{index}]"
        artifact = _object(value, artifact_path)
        _closed_keys(artifact, required={"bank", "platform", "language", "extension"}, path=artifact_path)
        bank = _string(artifact["bank"], f"{artifact_path}.bank")
        platform = _string(artifact["platform"], f"{artifact_path}.platform")
        language = _optional_string(artifact["language"], f"{artifact_path}.language")
        if bank not in banks or platform not in platforms:
            raise EvalBundleV3Error(f"{artifact_path} is outside the request scope")
        if skip_languages and language is not None:
            raise EvalBundleV3Error(f"{artifact_path}.language must be null when languages are skipped")
        if not skip_languages and language not in languages:
            raise EvalBundleV3Error(f"{artifact_path}.language is not requested")
        if artifact["extension"] not in {".bnk", ".rbnk"}:
            raise EvalBundleV3Error(f"{artifact_path}.extension is not a SoundBank artifact")
        artifact_keys.append(_soundbank_topic_event_key(bank, platform, language))
    _require_unique(tuple(artifact_keys), f"{path}.expected.bank_artifacts")
    requested_languages: tuple[str | None, ...] = (None,) if skip_languages else languages
    expected_artifact_keys = {
        _soundbank_topic_event_key(bank, platform, language)
        for bank in banks
        for platform in platforms
        for language in requested_languages
    }
    if set(artifact_keys) != expected_artifact_keys:
        raise EvalBundleV3Error(
            f"{path}.expected.bank_artifacts must equal the Bank/platform/language matrix"
        )
    automatic = _list(expected["automatic_artifacts"], f"{path}.expected.automatic_artifacts")
    automatic_keys: list[str] = []
    init_platforms: list[str] = []
    header_count = 0
    for index, value in enumerate(automatic):
        artifact_path = f"{path}.expected.automatic_artifacts[{index}]"
        artifact = _object(value, artifact_path)
        _closed_keys(
            artifact,
            required={"name", "platform", "location"},
            path=artifact_path,
        )
        name = _string(artifact["name"], f"{artifact_path}.name")
        platform = _optional_string(artifact["platform"], f"{artifact_path}.platform")
        location = _string(artifact["location"], f"{artifact_path}.location")
        if name == "Wwise_IDs.h":
            header_count += 1
            if platform is not None or location != "root_output":
                raise EvalBundleV3Error(
                    f"{artifact_path} Wwise_IDs.h must be one platform-agnostic root_output artifact"
                )
        elif name == "Init.bnk":
            if platform not in platforms or location != "platform_output":
                raise EvalBundleV3Error(
                    f"{artifact_path} Init.bnk must bind one requested platform output"
                )
            init_platforms.append(platform)
        else:
            raise EvalBundleV3Error(f"{artifact_path}.name is not a reviewed automatic artifact")
        automatic_keys.append(f"{name.casefold()}|{str(platform).casefold()}|{location}")
    _require_unique(tuple(automatic_keys), f"{path}.expected.automatic_artifacts")
    if tuple(init_platforms) != platforms:
        raise EvalBundleV3Error(
            f"{path}.expected.automatic_artifacts must contain one ordered Init.bnk per platform"
        )
    if header_count != int(request["header_file"]):
        raise EvalBundleV3Error(
            f"{path}.expected.automatic_artifacts must contain exactly one root Wwise_IDs.h "
            "if and only if header_file is true"
        )
    absent = _string_tuple(expected["absent_banks"], f"{path}.expected.absent_banks")
    _require_unique(tuple(value.casefold() for value in absent), f"{path}.expected.absent_banks")
    if set(absent).intersection(banks):
        raise EvalBundleV3Error(f"{path}.expected.absent_banks overlaps requested Banks")
    if expected["proof"] != "bounded_tree_nonzero_sha256_and_soundbanksinfo_identity":
        raise EvalBundleV3Error(f"{path}.expected.proof is not closed")
    if expected["project_copy"] != "byte_identical_when_save_false":
        raise EvalBundleV3Error(f"{path}.expected.project_copy is not closed")


def _parse_cli_tab_import_spec(request_value: Any, assets_value: Any, expected_value: Any, path: str) -> None:
    request = _object(request_value, f"{path}.request")
    _closed_keys(
        request,
        required={"import_operation", "import_language", "audio_source_from_original", "continue_on_error"},
        path=f"{path}.request",
    )
    if request["import_operation"] not in SUPPORTED_IMPORT_OPERATIONS:
        raise EvalBundleV3Error(f"{path}.request.import_operation is not closed")
    _string(request["import_language"], f"{path}.request.import_language")
    _boolean(request["audio_source_from_original"], f"{path}.request.audio_source_from_original")
    if _boolean(request["continue_on_error"], f"{path}.request.continue_on_error") is not False:
        raise EvalBundleV3Error(f"{path}.request.continue_on_error must be false")

    assets = _object(assets_value, f"{path}.assets")
    _closed_keys(
        assets,
        required={"tsv", "wav", "existing_top_level_work_unit"},
        path=f"{path}.assets",
    )
    existing_work_unit = _string(
        assets["existing_top_level_work_unit"],
        f"{path}.assets.existing_top_level_work_unit",
    )
    if "\\" in existing_work_unit or "/" in existing_work_unit:
        raise EvalBundleV3Error(
            f"{path}.assets.existing_top_level_work_unit must be one Work Unit name"
        )
    wav = _object(assets["wav"], f"{path}.assets.wav")
    _closed_keys(wav, required={"format", "files", "path_policy"}, path=f"{path}.assets.wav")
    if wav["format"] != "pcm_s16le_mono_48000hz" or wav["path_policy"] != "absolute_regular_non_symlink_size_sha256":
        raise EvalBundleV3Error(f"{path}.assets.wav is not reproducible")
    wav_keys: list[str] = []
    for index, value in enumerate(_list(wav["files"], f"{path}.assets.wav.files")):
        wav_path = f"{path}.assets.wav.files[{index}]"
        wav_file = _object(value, wav_path)
        _closed_keys(wav_file, required={"key", "name", "duration_ms", "frequency_hz"}, path=wav_path)
        wav_keys.append(_adapter_id(wav_file["key"], f"{wav_path}.key"))
        if not _string(wav_file["name"], f"{wav_path}.name").casefold().endswith(".wav"):
            raise EvalBundleV3Error(f"{wav_path}.name must end in .wav")
        _positive_int(wav_file["duration_ms"], f"{wav_path}.duration_ms")
        _positive_int(wav_file["frequency_hz"], f"{wav_path}.frequency_hz")
    if not wav_keys:
        raise EvalBundleV3Error(f"{path}.assets.wav.files must not be empty")
    _require_unique(tuple(wav_keys), f"{path}.assets.wav.files keys")

    tsv = _object(assets["tsv"], f"{path}.assets.tsv")
    _closed_keys(tsv, required={"name", "encoding", "headers", "rows", "path_policy"}, path=f"{path}.assets.tsv")
    if not _string(tsv["name"], f"{path}.assets.tsv.name").endswith(".tsv"):
        raise EvalBundleV3Error(f"{path}.assets.tsv.name must end in .tsv")
    if tsv["encoding"] != "utf-8_no_bom" or tsv["path_policy"] != "absolute_regular_non_symlink_size_sha256":
        raise EvalBundleV3Error(f"{path}.assets.tsv is not immutable")
    headers = _string_tuple(tsv["headers"], f"{path}.assets.tsv.headers")
    _require_unique(headers, f"{path}.assets.tsv.headers")
    if not {"Audio File", "Object Path", "Object Type"}.issubset(headers):
        raise EvalBundleV3Error(f"{path}.assets.tsv.headers lacks required import columns")
    if not set(headers).issubset(TAB_HEADERS_BY_VERSION[EXECUTION_PROFILE_VERSION]):
        raise EvalBundleV3Error(f"{path}.assets.tsv.headers contains an unsupported 2022.1 column")
    rows = _list(tsv["rows"], f"{path}.assets.tsv.rows")
    if not rows:
        raise EvalBundleV3Error(f"{path}.assets.tsv.rows must not be empty")
    row_paths: list[str] = []
    row_events: list[str | None] = []
    for index, value in enumerate(rows):
        row_path = f"{path}.assets.tsv.rows[{index}]"
        tab_row = _object(value, row_path)
        _closed_keys(tab_row, required={"source_key", "object_path", "object_type", "event", "notes"}, path=row_path)
        if tab_row["source_key"] not in wav_keys:
            raise EvalBundleV3Error(f"{row_path}.source_key references an unknown WAV")
        object_path = _string(tab_row["object_path"], f"{row_path}.object_path")
        if not object_path.startswith("\\"):
            raise EvalBundleV3Error(f"{row_path}.object_path must be absolute")
        required_prefix = f"\\Actor-Mixer Hierarchy\\{existing_work_unit}\\"
        if not object_path.startswith(required_prefix):
            raise EvalBundleV3Error(
                f"{row_path}.object_path must stay below the declared existing top-level Work Unit"
            )
        row_paths.append(object_path)
        _string(tab_row["object_type"], f"{row_path}.object_type")
        event = _optional_string(tab_row["event"], f"{row_path}.event")
        row_events.append(event)
        _string(tab_row["notes"], f"{row_path}.notes")
    _require_unique(tuple(value.casefold() for value in row_paths), f"{path}.assets.tsv.rows object paths")
    if any(event is not None for event in row_events) and "Event" not in headers:
        raise EvalBundleV3Error(f"{path}.assets.tsv.headers must include Event for event rows")

    expected = _object(expected_value, f"{path}.expected")
    _closed_keys(
        expected,
        required={"objects", "controls", "proof", "exit"},
        optional={"hierarchy", "hierarchy_materialization"},
        path=f"{path}.expected",
    )
    expected_paths: list[str] = []
    expected_events: list[str | None] = []
    guid_policies: list[str] = []
    for index, value in enumerate(_list(expected["objects"], f"{path}.expected.objects")):
        object_path = f"{path}.expected.objects[{index}]"
        object_row = _object(value, object_path)
        _closed_keys(object_row, required={"path", "type", "language", "source_key", "guid_policy", "event"}, path=object_path)
        expected_paths.append(_string(object_row["path"], f"{object_path}.path"))
        _string(object_row["type"], f"{object_path}.type")
        if object_row["language"] != request["import_language"]:
            raise EvalBundleV3Error(f"{object_path}.language must match import_language")
        if object_row["source_key"] not in wav_keys:
            raise EvalBundleV3Error(f"{object_path}.source_key references an unknown WAV")
        if object_row["guid_policy"] not in {"new_unique", "preserved", "replaced"}:
            raise EvalBundleV3Error(f"{object_path}.guid_policy is not closed")
        guid_policies.append(object_row["guid_policy"])
        expected_events.append(_optional_string(object_row["event"], f"{object_path}.event"))
    if tuple(expected_paths) != tuple(row_paths):
        raise EvalBundleV3Error(f"{path}.expected.objects must follow every TSV object row")
    if expected_events != row_events:
        raise EvalBundleV3Error(f"{path}.expected.objects events must match the TSV rows")

    hierarchy = _list(expected.get("hierarchy", []), f"{path}.expected.hierarchy")
    hierarchy_by_level: dict[str, set[str]] = {
        "chapter": set(),
        "scene": set(),
        "character": set(),
    }
    for index, value in enumerate(hierarchy):
        hierarchy_path = f"{path}.expected.hierarchy[{index}]"
        container = _object(value, hierarchy_path)
        _closed_keys(
            container,
            required={"path", "type", "level"},
            path=hierarchy_path,
        )
        container_path = _string(container["path"], f"{hierarchy_path}.path")
        if not container_path.startswith("\\Actor-Mixer Hierarchy\\Voices\\"):
            raise EvalBundleV3Error(
                f"{hierarchy_path}.path must stay below the reviewed Voices hierarchy"
            )
        if container["type"] != "ActorMixer":
            raise EvalBundleV3Error(
                f"{hierarchy_path}.type must be the exact WAAPI ActorMixer type"
            )
        level = _string(container["level"], f"{hierarchy_path}.level")
        if level not in hierarchy_by_level:
            raise EvalBundleV3Error(f"{hierarchy_path}.level is not reviewed")
        hierarchy_by_level[level].add(container_path)
    hierarchy_paths = tuple(
        path_value
        for level in ("chapter", "scene", "character")
        for path_value in hierarchy_by_level[level]
    )
    _require_unique(tuple(value.casefold() for value in hierarchy_paths), f"{path}.expected.hierarchy paths")
    if hierarchy:
        if expected.get("hierarchy_materialization") != "preexisting_actor_mixers":
            raise EvalBundleV3Error(
                f"{path}.expected.hierarchy_materialization must precreate the typed hierarchy"
            )
        derived_by_level: dict[str, set[str]] = {
            "chapter": set(),
            "scene": set(),
            "character": set(),
        }
        prefix = "\\Actor-Mixer Hierarchy\\Voices\\"
        for object_path in expected_paths:
            if not object_path.startswith(prefix):
                raise EvalBundleV3Error(
                    f"{path}.expected.objects must stay below Voices when hierarchy is declared"
                )
            parts = object_path[len(prefix) :].split("\\")
            if len(parts) != 4 or any(not part for part in parts):
                raise EvalBundleV3Error(
                    f"{path}.expected.objects must use exact Chapter/Scene/Character/Object depth"
                )
            chapter, scene, character, _ = parts
            chapter_path = f"{prefix}{chapter}"
            scene_path = f"{chapter_path}\\{scene}"
            character_path = f"{scene_path}\\{character}"
            derived_by_level["chapter"].add(chapter_path)
            derived_by_level["scene"].add(scene_path)
            derived_by_level["character"].add(character_path)
        if hierarchy_by_level != derived_by_level:
            raise EvalBundleV3Error(
                f"{path}.expected.hierarchy must exactly declare every Chapter/Scene/Character ancestor"
            )
    elif "hierarchy_materialization" in expected:
        raise EvalBundleV3Error(
            f"{path}.expected.hierarchy_materialization requires a hierarchy inventory"
        )
    operation = request["import_operation"]
    if operation == "createNew" and set(guid_policies) != {"new_unique"}:
        raise EvalBundleV3Error(f"{path}.expected GUID policy must be new_unique for createNew")
    if operation == "replaceExisting" and set(guid_policies) != {"replaced"}:
        raise EvalBundleV3Error(f"{path}.expected GUID policy must be replaced for replaceExisting")
    if operation == "useExisting" and not set(guid_policies).issubset({"preserved", "new_unique"}):
        raise EvalBundleV3Error(f"{path}.expected GUID policy is invalid for useExisting")
    controls = _string_tuple(expected["controls"], f"{path}.expected.controls")
    _require_unique(tuple(value.casefold() for value in controls), f"{path}.expected.controls")
    if set(controls).intersection(expected_paths):
        raise EvalBundleV3Error(f"{path}.expected.controls overlaps imported objects")
    if expected["proof"] != "fresh_exit_waapi_tree_source_binding_and_workunit_xml_sha256":
        raise EvalBundleV3Error(f"{path}.expected.proof is not closed")
    if expected["exit"] != "success":
        raise EvalBundleV3Error(f"{path}.expected.exit must be success")


def _parse_cli_external_source_spec(request_value: Any, assets_value: Any, expected_value: Any, path: str) -> None:
    request = _object(request_value, f"{path}.request")
    _closed_keys(
        request,
        required={"platforms", "source_mode", "bindings", "output_mode", "outputs"},
        path=f"{path}.request",
    )
    platforms = _string_tuple(request["platforms"], f"{path}.request.platforms")
    if not platforms:
        raise EvalBundleV3Error(f"{path}.request.platforms must not be empty")
    _require_unique(tuple(value.casefold() for value in platforms), f"{path}.request.platforms")
    if request["source_mode"] not in {"source_file", "source_by_platform"}:
        raise EvalBundleV3Error(f"{path}.request.source_mode is not closed")
    if request["output_mode"] not in {
        "platform_pair",
        "platform_pair_array",
    }:
        raise EvalBundleV3Error(f"{path}.request.output_mode is not closed")
    outputs = _list(request["outputs"], f"{path}.request.outputs")
    output_platforms: list[str] = []
    output_root_keys: list[str] = []
    for index, value in enumerate(outputs):
        output_path = f"{path}.request.outputs[{index}]"
        output = _object(value, output_path)
        _closed_keys(output, required={"platform", "root_key"}, path=output_path)
        output_platforms.append(_string(output["platform"], f"{output_path}.platform"))
        output_root_keys.append(_adapter_id(output["root_key"], f"{output_path}.root_key"))
    if tuple(output_platforms) != platforms:
        raise EvalBundleV3Error(f"{path}.request.outputs must follow every requested platform")
    if request["output_mode"] == "platform_pair_array":
        if len(platforms) < 2 or len(set(output_root_keys)) != len(platforms):
            raise EvalBundleV3Error(
                f"{path}.request platform_pair_array requires multiple disjoint platform roots"
            )
    elif len(platforms) != 1 or len(outputs) != 1:
        raise EvalBundleV3Error(
            f"{path}.request platform_pair requires exactly one platform root"
        )

    assets = _object(assets_value, f"{path}.assets")
    _closed_keys(assets, required={"wsources", "wav"}, path=f"{path}.assets")
    wav = _object(assets["wav"], f"{path}.assets.wav")
    _closed_keys(wav, required={"format", "files", "path_policy"}, path=f"{path}.assets.wav")
    if wav["format"] != "pcm_s16le_mono_48000hz" or wav["path_policy"] != "absolute_regular_non_symlink_size_sha256":
        raise EvalBundleV3Error(f"{path}.assets.wav is not reproducible")
    wav_keys: list[str] = []
    wav_names: list[str] = []
    for index, value in enumerate(_list(wav["files"], f"{path}.assets.wav.files")):
        wav_path = f"{path}.assets.wav.files[{index}]"
        wav_file = _object(value, wav_path)
        _closed_keys(wav_file, required={"key", "name", "duration_ms", "frequency_hz"}, path=wav_path)
        wav_keys.append(_adapter_id(wav_file["key"], f"{wav_path}.key"))
        wav_name = _string(wav_file["name"], f"{wav_path}.name")
        if not wav_name.casefold().endswith(".wav"):
            raise EvalBundleV3Error(f"{wav_path}.name must end in .wav")
        wav_parts = re.split(r"[\\/]", wav_name)
        if wav_name.startswith(("/", "\\")) or any(
            part in {"", ".", ".."} for part in wav_parts
        ):
            raise EvalBundleV3Error(f"{wav_path}.name must be a contained relative WAV path")
        wav_names.append("/".join(wav_parts))
        _positive_int(wav_file["duration_ms"], f"{wav_path}.duration_ms")
        _positive_int(wav_file["frequency_hz"], f"{wav_path}.frequency_hz")
    _require_unique(tuple(wav_keys), f"{path}.assets.wav.files keys")
    _require_unique(tuple(value.casefold() for value in wav_names), f"{path}.assets.wav.files names")

    manifest_names, source_paths, manifest_entries = _parse_external_source_documents(
        assets["wsources"],
        f"{path}.assets.wsources",
        allowed_root_modes={"case_asset_root"},
    )
    if {value.casefold() for value in source_paths} != {
        value.casefold() for value in wav_names
    }:
        raise EvalBundleV3Error(
            f"{path}.assets.wav.files must exactly materialize every real Source Path"
        )
    known_manifests = set(manifest_names)

    bindings = _list(request["bindings"], f"{path}.request.bindings")
    binding_platforms: list[str] = []
    binding_manifest_sets: list[tuple[str, ...]] = []
    expected_keys: set[str] = set()
    for index, value in enumerate(bindings):
        binding_path = f"{path}.request.bindings[{index}]"
        binding = _object(value, binding_path)
        _closed_keys(binding, required={"platform", "manifests"}, path=binding_path)
        platform = _string(binding["platform"], f"{binding_path}.platform")
        binding_platforms.append(platform)
        manifests = _string_tuple(binding["manifests"], f"{binding_path}.manifests")
        if not manifests or not set(manifests).issubset(known_manifests):
            raise EvalBundleV3Error(f"{binding_path}.manifests references an unknown .wsources file")
        _require_unique(manifests, f"{binding_path}.manifests")
        if len(manifests) != 1:
            raise EvalBundleV3Error(
                f"{binding_path}.manifests must contain exactly one .wsources "
                "file for the Wwise 2022.1 CLI execution profile"
            )
        binding_manifest_sets.append(manifests)
        for manifest_name in manifests:
            for source_path, destination in manifest_entries[manifest_name]:
                key = (
                    f"{platform.casefold()}|{manifest_name.casefold()}|"
                    f"{source_path.casefold()}|{destination.casefold()}"
                )
                if key in expected_keys:
                    raise EvalBundleV3Error(
                        f"{binding_path} produces a duplicate platform/document/source/destination"
                    )
                expected_keys.add(key)
    if tuple(binding_platforms) != platforms:
        raise EvalBundleV3Error(f"{path}.request.bindings must follow every requested platform")
    if request["source_mode"] == "source_file" and len(set(binding_manifest_sets)) != 1:
        raise EvalBundleV3Error(f"{path}.request.source_file must use the same manifest tuple per platform")

    expected = _object(expected_value, f"{path}.expected")
    _closed_keys(expected, required={"outputs", "controls", "proof", "exit"}, path=f"{path}.expected")
    parsed_keys: list[str] = []
    for index, value in enumerate(_list(expected["outputs"], f"{path}.expected.outputs")):
        output_path = f"{path}.expected.outputs[{index}]"
        output = _object(value, output_path)
        _closed_keys(
            output,
            required={"platform", "document", "source_path", "relative_path"},
            path=output_path,
        )
        platform = _string(output["platform"], f"{output_path}.platform")
        document = _string(output["document"], f"{output_path}.document")
        source_path = _string(output["source_path"], f"{output_path}.source_path")
        relative_path = _string(output["relative_path"], f"{output_path}.relative_path")
        if relative_path.startswith(("/", "\\")) or ".." in relative_path.replace("\\", "/").split("/"):
            raise EvalBundleV3Error(f"{output_path}.relative_path must stay below the output root")
        normalized_relative_path = relative_path.replace("\\", "/")
        parsed_keys.append(
            f"{platform.casefold()}|{document.casefold()}|"
            f"{source_path.casefold()}|{normalized_relative_path.casefold()}"
        )
    _require_unique(tuple(parsed_keys), f"{path}.expected.outputs")
    if set(parsed_keys) != expected_keys:
        raise EvalBundleV3Error(f"{path}.expected.outputs must exactly match all bound manifests")
    controls = _string_tuple(expected["controls"], f"{path}.expected.controls")
    _require_unique(controls, f"{path}.expected.controls")
    if expected["proof"] != "exact_platform_document_source_destination_nonzero_sha256_and_header":
        raise EvalBundleV3Error(f"{path}.expected.proof is not closed")
    if expected["exit"] != "success":
        raise EvalBundleV3Error(f"{path}.expected.exit must be success")


@lru_cache(maxsize=1)
def _migration_fixture_inventory() -> tuple[Path, frozenset[str]]:
    repository_root = Path(__file__).resolve().parents[3]
    fixture_root = (repository_root / MIGRATION_FIXTURE_ROOT).resolve(strict=True)
    metadata = json.loads((fixture_root / "fixture-metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads((fixture_root / "fixture-manifest.json").read_text(encoding="utf-8"))
    if metadata["fixture_root"] != MIGRATION_FIXTURE_ROOT:
        raise EvalBundleV3Error("the committed 2021.1 migration fixture root drifted")
    if metadata["provenance"]["source_build"] != MIGRATION_FIXTURE_SOURCE_RELEASE:
        raise EvalBundleV3Error("the committed 2021.1 migration fixture release drifted")
    if manifest["algorithm"] != "sha256" or manifest["file_count"] != MIGRATION_FIXTURE_FILE_COUNT:
        raise EvalBundleV3Error("the committed 2021.1 migration fixture manifest shape drifted")

    manifest_rows = _list(manifest["files"], "migration_fixture.manifest.files")
    manifest_paths: list[str] = []
    digest = hashlib.sha256()
    for index, value in enumerate(manifest_rows):
        row_path = f"migration_fixture.manifest.files[{index}]"
        row = _object(value, row_path)
        _closed_keys(row, required={"bytes", "path", "sha256"}, path=row_path)
        relative = _string(row["path"], f"{row_path}.path")
        file_path = (fixture_root / relative).resolve(strict=True)
        if fixture_root not in file_path.parents or not file_path.is_file():
            raise EvalBundleV3Error(f"{row_path}.path escapes the immutable fixture")
        data = file_path.read_bytes()
        file_digest = hashlib.sha256(data).hexdigest()
        if row["bytes"] != len(data) or row["sha256"] != file_digest:
            raise EvalBundleV3Error(f"{row_path} does not match the committed fixture payload")
        manifest_paths.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("utf-8"))
        digest.update(b"\0")
    _require_unique(tuple(manifest_paths), "migration_fixture.manifest paths")
    actual_paths = sorted(
        item.relative_to(fixture_root).as_posix()
        for item in fixture_root.rglob("*")
        if item.is_file()
        and item.name not in {"fixture-manifest.json", "fixture-metadata.json"}
    )
    if sorted(manifest_paths) != actual_paths:
        raise EvalBundleV3Error("the committed 2021.1 migration fixture payload set drifted")
    if digest.hexdigest() != MIGRATION_FIXTURE_MANIFEST_DIGEST:
        raise EvalBundleV3Error("the committed 2021.1 migration fixture digest drifted")

    project = ET.fromstring((fixture_root / MIGRATION_FIXTURE_PROJECT).read_bytes())
    if (
        project.tag != "WwiseDocument"
        or project.attrib.get("WwiseVersion") != MIGRATION_FIXTURE_DOCUMENT_VERSION
        or project.attrib.get("WwiseBuild") != MIGRATION_FIXTURE_DOCUMENT_BUILD
    ):
        raise EvalBundleV3Error("the committed migration project document version drifted")
    return fixture_root, frozenset(manifest_paths)


def _validate_migration_anchor(
    value: Any,
    path: str,
    *,
    fixture_root: Path,
    manifest_paths: frozenset[str],
) -> str:
    anchor = _object(value, path)
    _closed_keys(
        anchor,
        required={
            "kind",
            "name",
            "guid",
            "source_file",
            "scope_files",
            "required_descendant_tags",
            "required_reference_names",
        },
        path=path,
    )
    kind = _string(anchor["kind"], f"{path}.kind")
    name = _string(anchor["name"], f"{path}.name")
    guid = _string(anchor["guid"], f"{path}.guid")
    if not re.fullmatch(r"\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}", guid):
        raise EvalBundleV3Error(f"{path}.guid must be one uppercase braced GUID")
    source_file = _string(anchor["source_file"], f"{path}.source_file")
    scope_files = _string_tuple(anchor["scope_files"], f"{path}.scope_files")
    if not scope_files or source_file not in scope_files:
        raise EvalBundleV3Error(f"{path}.scope_files must include source_file")
    _require_unique(scope_files, f"{path}.scope_files")
    if not set(scope_files).issubset(manifest_paths):
        raise EvalBundleV3Error(f"{path}.scope_files references files outside the sealed manifest")
    if any(not value.casefold().endswith((".wproj", ".wwu")) for value in scope_files):
        raise EvalBundleV3Error(f"{path}.scope_files must contain only Wwise XML source documents")

    parsed_documents: dict[str, ET.Element] = {}
    for relative in scope_files:
        data = (fixture_root / relative).read_bytes()
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper() or b"\x00" in data:
            raise EvalBundleV3Error(f"{path}.scope_files contains unsafe XML")
        try:
            parsed_documents[relative] = ET.fromstring(data)
        except ET.ParseError as exc:
            raise EvalBundleV3Error(f"{path}.scope_files contains malformed XML: {exc}") from exc

    definitions = [
        element
        for element in parsed_documents[source_file].iter()
        if element.tag == kind
        and element.attrib.get("ID") == guid
        and element.attrib.get("Name") == name
    ]
    if len(definitions) != 1:
        raise EvalBundleV3Error(
            f"{path} must resolve one exact kind/name/GUID definition in source_file"
        )
    definition = definitions[0]
    descendant_tags = {element.tag for element in definition.iter() if element is not definition}
    required_tags = _string_tuple(
        anchor["required_descendant_tags"],
        f"{path}.required_descendant_tags",
    )
    if not required_tags or not set(required_tags).issubset(descendant_tags):
        raise EvalBundleV3Error(f"{path}.required_descendant_tags is not proven by source XML")
    _require_unique(required_tags, f"{path}.required_descendant_tags")

    reference_names = {
        element.attrib.get("Name")
        for root in parsed_documents.values()
        for element in root.iter()
        if element.tag.endswith("Ref") and isinstance(element.attrib.get("Name"), str)
    }
    required_reference_names = _string_tuple(
        anchor["required_reference_names"],
        f"{path}.required_reference_names",
    )
    if not required_reference_names or not set(required_reference_names).issubset(reference_names):
        raise EvalBundleV3Error(f"{path}.required_reference_names is not proven by scope XML")
    _require_unique(required_reference_names, f"{path}.required_reference_names")

    # The campaign adapter derives this complete inventory again before each
    # migration.  The definition intentionally stores no hand-copied counts.
    definition_elements = set(definition.iter())
    inventory_rows = [
        (
            relative,
            element.tag,
            element.attrib.get("ID"),
            element.attrib.get("Name"),
            tuple(sorted(element.attrib.items())),
        )
        for relative, root in parsed_documents.items()
        for element in root.iter()
        if element in definition_elements or element.tag.endswith("Ref")
    ]
    inventory_digest = hashlib.sha256(
        json.dumps(inventory_rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if not inventory_rows or len(inventory_digest) != 64:
        raise EvalBundleV3Error(f"{path} cannot derive a sealed XML inventory")
    return f"{kind.casefold()}|{guid.casefold()}"


def _parse_cli_migrate_spec(request_value: Any, assets_value: Any, expected_value: Any, path: str) -> None:
    request = _object(request_value, f"{path}.request")
    _closed_keys(request, required={"abort_on_load_issues", "verbose"}, path=f"{path}.request")
    if _boolean(request["abort_on_load_issues"], f"{path}.request.abort_on_load_issues") is not False:
        raise EvalBundleV3Error(
            f"{path}.request.abort_on_load_issues must be false for the sealed legacy fixture; "
            "the independent load-issue and selected-anchor checks remain fail-closed"
        )
    _boolean(request["verbose"], f"{path}.request.verbose")

    assets = _object(assets_value, f"{path}.assets")
    _closed_keys(
        assets,
        required={"profile", "fixture", "anchors", "inventory_policy"},
        path=f"{path}.assets",
    )
    profile = _adapter_id(assets["profile"], f"{path}.assets.profile")
    fixture = _object(assets["fixture"], f"{path}.assets.fixture")
    _closed_keys(
        fixture,
        required={
            "root",
            "project",
            "source_release",
            "document_version",
            "document_build",
            "manifest_digest",
            "file_count",
            "copy_policy",
        },
        path=f"{path}.assets.fixture",
    )
    expected_fixture = {
        "root": MIGRATION_FIXTURE_ROOT,
        "project": MIGRATION_FIXTURE_PROJECT,
        "source_release": MIGRATION_FIXTURE_SOURCE_RELEASE,
        "document_version": MIGRATION_FIXTURE_DOCUMENT_VERSION,
        "document_build": MIGRATION_FIXTURE_DOCUMENT_BUILD,
        "manifest_digest": MIGRATION_FIXTURE_MANIFEST_DIGEST,
        "file_count": MIGRATION_FIXTURE_FILE_COUNT,
        "copy_policy": "verify_manifest_then_copy_to_unique_case_project_never_modify_source",
    }
    if fixture != expected_fixture:
        raise EvalBundleV3Error(f"{path}.assets.fixture is not the sealed 2021.1 SampleProject")
    if assets["inventory_policy"] != MIGRATION_INVENTORY_POLICY:
        raise EvalBundleV3Error(f"{path}.assets.inventory_policy is not closed")
    fixture_root, manifest_paths = _migration_fixture_inventory()
    anchors = _list(assets["anchors"], f"{path}.assets.anchors")
    if not anchors:
        raise EvalBundleV3Error(f"{path}.assets.anchors must not be empty")
    anchor_keys: list[str] = []
    for index, value in enumerate(anchors):
        anchor_path = f"{path}.assets.anchors[{index}]"
        anchor_keys.append(
            _validate_migration_anchor(
                value,
                anchor_path,
                fixture_root=fixture_root,
                manifest_paths=manifest_paths,
            )
        )
    _require_unique(tuple(anchor_keys), f"{path}.assets.anchors")

    expected = _object(expected_value, f"{path}.expected")
    _closed_keys(
        expected,
        required={
            "target_version",
            "exit",
            "reopen",
            "identity_policy",
            "reference_policy",
            "source_fixture_policy",
            "allowed_changes",
            "log_policy",
        },
        optional={"comparison_scope"},
        path=f"{path}.expected",
    )
    if expected["target_version"] != EXECUTION_PROFILE_VERSION or expected["exit"] != "success" or expected["reopen"] is not True:
        raise EvalBundleV3Error(f"{path}.expected must require a successful 2022.1 reopen")
    if profile == MIGRATION_SCOPED_COMPARISON_PROFILE:
        if expected["identity_policy"] != (
            "selected_anchor_identity_and_declared_comparison_scope_equal"
        ):
            raise EvalBundleV3Error(
                f"{path}.expected.identity_policy must use the scoped project/conversion comparison"
            )
        comparison_scope = _object(
            expected.get("comparison_scope"),
            f"{path}.expected.comparison_scope",
        )
        _closed_keys(
            comparison_scope,
            required=set(MIGRATION_SCOPED_COMPARISON),
            path=f"{path}.expected.comparison_scope",
        )
        if comparison_scope != MIGRATION_SCOPED_COMPARISON:
            raise EvalBundleV3Error(
                f"{path}.expected.comparison_scope is not the reviewed migration intent"
            )

        project_document = ET.fromstring(
            (fixture_root / MIGRATION_FIXTURE_PROJECT).read_bytes()
        )
        project_nodes = [
            element
            for element in project_document.iter("Project")
            if element.attrib.get("Name") == "SampleProject"
        ]
        conversion_document = ET.fromstring(
            (fixture_root / "Conversion Settings/Default Work Unit.wwu").read_bytes()
        )
        conversion_nodes = [
            element
            for element in conversion_document.iter("Conversion")
            if element.attrib.get("Name") in {"PCM", "Voice", "Music"}
        ]
        if len(project_nodes) != 1 or len(conversion_nodes) != 3:
            raise EvalBundleV3Error(
                f"{path}.expected.comparison_scope cannot resolve the sealed source anchors"
            )
        project_property_names = {
            element.attrib.get("Name")
            for element in project_nodes[0].iter("Property")
        }
        if not set(MIGRATION_SCOPED_COMPARISON["project_property_names"]).issubset(
            project_property_names
        ):
            raise EvalBundleV3Error(
                f"{path}.expected.comparison_scope project properties are not source-proven"
            )
        for conversion in conversion_nodes:
            conversion_property_names = {
                element.attrib.get("Name")
                for element in conversion.iter("Property")
            }
            if not set(
                MIGRATION_SCOPED_COMPARISON["conversion_property_names"]
            ).issubset(conversion_property_names):
                raise EvalBundleV3Error(
                    f"{path}.expected.comparison_scope conversion properties are not source-proven"
                )
            if not list(conversion.iter("ConversionPlugin")):
                raise EvalBundleV3Error(
                    f"{path}.expected.comparison_scope plugin inventory is not source-proven"
                )
    else:
        if expected["identity_policy"] != (
            "selected_anchor_guid_type_name_parent_and_property_inventory_equal"
        ):
            raise EvalBundleV3Error(f"{path}.expected.identity_policy is not closed")
        if "comparison_scope" in expected:
            raise EvalBundleV3Error(
                f"{path}.expected.comparison_scope is only valid for the scoped project/conversion profile"
            )
    if expected["reference_policy"] != "selected_anchor_reference_multiset_equal_after_reopen":
        raise EvalBundleV3Error(f"{path}.expected.reference_policy is not closed")
    if expected["source_fixture_policy"] != "manifest_and_every_payload_sha256_unchanged":
        raise EvalBundleV3Error(f"{path}.expected.source_fixture_policy is not closed")
    allowed = _string_tuple(expected["allowed_changes"], f"{path}.expected.allowed_changes")
    if set(allowed) != {"schema_version_metadata", "serializer_formatting", "migration_backup"}:
        raise EvalBundleV3Error(f"{path}.expected.allowed_changes is not the reviewed migration delta")
    if expected["log_policy"] != (
        "zero_fatal_zero_unresolved_selected_anchor_verification_and_all_load_issues_classified"
    ):
        raise EvalBundleV3Error(f"{path}.expected.log_policy is not closed")


def _parse_import_asset_spec(value: Any, path: str, *, adapter: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "contract",
            "audio_import_operation",
            "import_location",
            "wav",
            "sources",
            "pre_state_sources",
            "rows",
            "tsv",
            "materialization_policy",
            "source_policy",
            "cleanup_policy",
        },
        path=path,
    )
    if row["contract"] != "waapi-skill.import-eval-assets/v2":
        raise EvalBundleV3Error(f"{path}.contract is not supported")
    audio_operation = row["audio_import_operation"]
    import_location = row["import_location"]
    if adapter == "audio_import_fixture":
        if audio_operation not in SUPPORTED_IMPORT_OPERATIONS:
            raise EvalBundleV3Error(f"{path}.audio_import_operation is not closed")
        if import_location is not None:
            raise EvalBundleV3Error(f"{path}.import_location must be null for audio.import fixtures")
    else:
        if audio_operation is not None:
            raise EvalBundleV3Error(
                f"{path}.audio_import_operation is only valid for audio.import fixtures"
            )
        import_location = _string(import_location, f"{path}.import_location")
    wav = _object(row["wav"], f"{path}.wav")
    _closed_keys(
        wav,
        required={"count", "format", "content_policy", "generator_policy"},
        path=f"{path}.wav",
    )
    wav_count = _positive_int(wav["count"], f"{path}.wav.count")
    if wav["format"] != "pcm_s16le_mono_48000hz":
        raise EvalBundleV3Error(f"{path}.wav.format must use the deterministic PCM fixture format")
    if wav["content_policy"] != "deterministic_distinct_signal_per_file":
        raise EvalBundleV3Error(f"{path}.wav.content_policy is not reproducible")
    if wav["generator_policy"] != (
        "riff_wave_pcm_s16le_sine_phase0_peak8191_int_truncate_"
        "samples_floor_48000xms_div1000"
    ):
        raise EvalBundleV3Error(f"{path}.wav.generator_policy is not byte-deterministic")
    if row["materialization_policy"] != (
        "generate_sources_then_seal_sha256_render_visible_rows_or_tsv_"
        "exactly_from_declared_order"
    ):
        raise EvalBundleV3Error(f"{path}.materialization_policy is not closed")
    if row["source_policy"] != "absolute_regular_non_symlink_size_sha256":
        raise EvalBundleV3Error(f"{path}.source_policy must bind absolute hashed regular files")
    if row["cleanup_policy"] != (
        "success_delete_case_owned_project_and_assets_"
        "failure_or_indeterminate_seal_never_reuse"
    ):
        raise EvalBundleV3Error(f"{path}.cleanup_policy is not fail-closed")

    source_rows = _list(row["sources"], f"{path}.sources")
    if not source_rows:
        raise EvalBundleV3Error(f"{path}.sources must not be empty")
    source_by_key: dict[str, Mapping[str, Any]] = {}
    relative_paths: list[str] = []
    sha256_keys: list[str] = []
    signal_specs: list[str] = []
    present_source_count = 0
    for index, value in enumerate(source_rows):
        source_path = f"{path}.sources[{index}]"
        source = _object(value, source_path)
        _closed_keys(
            source,
            required={
                "source_key",
                "relative_path",
                "presence",
                "duration_ms",
                "frequency_hz",
                "sha256_key",
            },
            path=source_path,
        )
        source_key = _adapter_id(source["source_key"], f"{source_path}.source_key")
        if source_key in source_by_key:
            raise EvalBundleV3Error(f"{path}.sources source_key values must be unique")
        relative_path = _string(source["relative_path"], f"{source_path}.relative_path")
        if (
            "/" in relative_path
            or "\\" in relative_path
            or relative_path in {".", ".."}
            or not relative_path.casefold().endswith(".wav")
        ):
            raise EvalBundleV3Error(
                f"{source_path}.relative_path must be one exact WAV basename"
            )
        presence = source["presence"]
        if presence == "present":
            present_source_count += 1
            _positive_int(source["duration_ms"], f"{source_path}.duration_ms")
            _positive_int(source["frequency_hz"], f"{source_path}.frequency_hz")
            sha256_keys.append(_adapter_id(source["sha256_key"], f"{source_path}.sha256_key"))
            signal_specs.append(f"{source['duration_ms']}:{source['frequency_hz']}")
        elif presence == "absent":
            if any(source[key] is not None for key in ("duration_ms", "frequency_hz", "sha256_key")):
                raise EvalBundleV3Error(
                    f"{source_path} absent sources must not declare signal or SHA-256 values"
                )
        else:
            raise EvalBundleV3Error(f"{source_path}.presence must be present or absent")
        source_by_key[source_key] = source
        relative_paths.append(relative_path.casefold())
    _require_unique(tuple(relative_paths), f"{path}.sources relative_path values")
    _require_unique(tuple(sha256_keys), f"{path}.sources sha256_key values")
    _require_unique(tuple(signal_specs), f"{path}.sources deterministic signal values")
    if present_source_count != wav_count:
        raise EvalBundleV3Error(f"{path}.wav.count must equal the number of present sources")

    pre_state_source_rows = _list(row["pre_state_sources"], f"{path}.pre_state_sources")
    pre_state_source_by_key: dict[str, Mapping[str, Any]] = {}
    pre_state_media_paths: list[str] = []
    pre_state_signal_specs: list[str] = []
    for index, value in enumerate(pre_state_source_rows):
        source_path = f"{path}.pre_state_sources[{index}]"
        source = _object(value, source_path)
        _closed_keys(
            source,
            required={"media_sha256_key", "relative_path", "duration_ms", "frequency_hz"},
            path=source_path,
        )
        media_sha256_key = _adapter_id(
            source["media_sha256_key"],
            f"{source_path}.media_sha256_key",
        )
        if media_sha256_key in pre_state_source_by_key:
            raise EvalBundleV3Error(
                f"{path}.pre_state_sources media_sha256_key values must be unique"
            )
        relative_path = _string(source["relative_path"], f"{source_path}.relative_path")
        if (
            "/" in relative_path
            or "\\" in relative_path
            or not relative_path.casefold().endswith(".wav")
        ):
            raise EvalBundleV3Error(
                f"{source_path}.relative_path must be one exact WAV basename"
            )
        duration = _positive_int(source["duration_ms"], f"{source_path}.duration_ms")
        frequency = _positive_int(source["frequency_hz"], f"{source_path}.frequency_hz")
        pre_state_source_by_key[media_sha256_key] = source
        pre_state_media_paths.append(relative_path.casefold())
        pre_state_signal_specs.append(f"{duration}:{frequency}")
    _require_unique(
        tuple([*relative_paths, *pre_state_media_paths]),
        f"{path} imported and pre-state WAV basenames",
    )
    _require_unique(
        tuple([*signal_specs, *pre_state_signal_specs]),
        f"{path} imported and pre-state deterministic signal values",
    )

    tab_rows = _list(row["tsv"], f"{path}.tsv")
    if adapter == "audio_import_fixture" and tab_rows:
        raise EvalBundleV3Error(f"{path}.tsv must be empty for audio.import fixtures")
    if adapter == "tab_import_fixture" and not tab_rows:
        raise EvalBundleV3Error(f"{path}.tsv must not be empty for tab-import fixtures")
    seen_names: list[str] = []
    tab_by_name: dict[str, Mapping[str, Any]] = {}
    allowed_headers = set(TAB_HEADERS_BY_VERSION[EXECUTION_PROFILE_VERSION])
    for index, value in enumerate(tab_rows):
        tab_path = f"{path}.tsv[{index}]"
        tab = _object(value, tab_path)
        _closed_keys(
            tab,
            required={
                "name",
                "language",
                "import_operation",
                "encoding",
                "headers",
                "row_count",
                "missing_audio_rows",
                "render_policy",
            },
            path=tab_path,
        )
        name = _string(tab["name"], f"{tab_path}.name")
        if not name.endswith(".tsv"):
            raise EvalBundleV3Error(f"{tab_path}.name must end in .tsv")
        seen_names.append(name)
        _string(tab["language"], f"{tab_path}.language")
        if tab["import_operation"] not in SUPPORTED_IMPORT_OPERATIONS:
            raise EvalBundleV3Error(f"{tab_path}.import_operation is not closed")
        if tab["encoding"] != "utf-8_no_bom":
            raise EvalBundleV3Error(f"{tab_path}.encoding must be utf-8_no_bom")
        if tab["render_policy"] != "csv_tab_quote_minimal_doublequote_lf":
            raise EvalBundleV3Error(f"{tab_path}.render_policy is not deterministic")
        headers = _string_tuple(tab["headers"], f"{tab_path}.headers")
        _require_unique(headers, f"{tab_path}.headers")
        if not {"Audio File", "Object Path"}.issubset(headers):
            raise EvalBundleV3Error(f"{tab_path}.headers lacks Audio File or Object Path")
        unsupported = sorted(set(headers) - allowed_headers)
        if unsupported:
            raise EvalBundleV3Error(f"{tab_path}.headers contains unsupported columns {unsupported}")
        row_count = _positive_int(tab["row_count"], f"{tab_path}.row_count")
        missing_rows = tuple(
            _positive_int(item, f"{tab_path}.missing_audio_rows[{row_index}]")
            for row_index, item in enumerate(_list(tab["missing_audio_rows"], f"{tab_path}.missing_audio_rows"))
        )
        _require_unique(tuple(str(item) for item in missing_rows), f"{tab_path}.missing_audio_rows")
        if any(item < 2 or item > row_count + 1 for item in missing_rows):
            raise EvalBundleV3Error(f"{tab_path}.missing_audio_rows falls outside its data rows")
        tab_by_name[name] = tab
    _require_unique(tuple(seen_names), f"{path}.tsv names")

    fixture_rows = _list(row["rows"], f"{path}.rows")
    if not fixture_rows:
        raise EvalBundleV3Error(f"{path}.rows must not be empty")
    row_keys: list[str] = []
    referenced_source_keys: list[str] = []
    table_physical_rows: dict[str, list[int]] = defaultdict(list)
    table_missing_rows: dict[str, list[int]] = defaultdict(list)
    target_keys_by_table: dict[str, list[str]] = defaultdict(list)
    object_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    referenced_pre_state_source_keys: list[str] = []
    event_actions = {"Play", "Stop", "Pause", "Resume", "Break", "Seek"}
    allowed_guid_policies = {
        "preserve_existing_guid",
        "preserve_shared_existing_guid",
        "create_new_unique_guid",
        "create_once_then_preserve_shared_guid",
        "replace_with_distinct_guid",
        "remain_absent_no_guid",
    }
    for index, value in enumerate(fixture_rows):
        row_path = f"{path}.rows[{index}]"
        fixture_row = _object(value, row_path)
        _closed_keys(
            fixture_row,
            required={
                "row_key",
                "tsv_name",
                "tsv_row",
                "source_key",
                "object_key",
                "object_path",
                "target_path",
                "object_type",
                "language",
                "originals_subfolder",
                "notes",
                "audio_source_notes",
                "event",
                "pre_state",
                "guid_policy",
                "oracle",
            },
            path=row_path,
        )
        row_key = _adapter_id(fixture_row["row_key"], f"{row_path}.row_key")
        row_keys.append(row_key)
        source_key = _adapter_id(fixture_row["source_key"], f"{row_path}.source_key")
        if source_key not in source_by_key:
            raise EvalBundleV3Error(f"{row_path}.source_key references an unknown source")
        referenced_source_keys.append(source_key)
        object_key = _adapter_id(fixture_row["object_key"], f"{row_path}.object_key")
        object_path = _string(fixture_row["object_path"], f"{row_path}.object_path")
        target_path = _string(fixture_row["target_path"], f"{row_path}.target_path")
        _string(fixture_row["object_type"], f"{row_path}.object_type")
        language = _string(fixture_row["language"], f"{row_path}.language")
        originals_subfolder = fixture_row["originals_subfolder"]
        if originals_subfolder is not None:
            originals_subfolder = _string(
                originals_subfolder,
                f"{row_path}.originals_subfolder",
            )
            if (
                originals_subfolder.startswith(("/", "\\"))
                or ".." in originals_subfolder.replace("\\", "/").split("/")
            ):
                raise EvalBundleV3Error(
                    f"{row_path}.originals_subfolder must be a safe relative path"
                )
        if fixture_row["notes"] is not None:
            _string(fixture_row["notes"], f"{row_path}.notes")
        if fixture_row["audio_source_notes"] is not None:
            _string(fixture_row["audio_source_notes"], f"{row_path}.audio_source_notes")

        event = fixture_row["event"]
        if event is not None:
            event_row = _object(event, f"{row_path}.event")
            _closed_keys(
                event_row,
                required={"path", "action", "pre_state", "guid_policy"},
                path=f"{row_path}.event",
            )
            event_path = _string(event_row["path"], f"{row_path}.event.path")
            if not event_path.startswith("\\Events\\"):
                raise EvalBundleV3Error(f"{row_path}.event.path must be an absolute Event path")
            if event_row["action"] not in event_actions:
                raise EvalBundleV3Error(f"{row_path}.event.action is not closed")
            if event_row["pre_state"] != "absent":
                raise EvalBundleV3Error(f"{row_path}.event.pre_state must be absent")
            if event_row["guid_policy"] != "new_unique_event_and_action_target_row_guid":
                raise EvalBundleV3Error(f"{row_path}.event.guid_policy is not closed")

        pre_state = _object(fixture_row["pre_state"], f"{row_path}.pre_state")
        _closed_keys(
            pre_state,
            required={"existence", "guid_key", "media_sha256_key", "notes"},
            path=f"{row_path}.pre_state",
        )
        existence = pre_state["existence"]
        if existence == "existing":
            _adapter_id(pre_state["guid_key"], f"{row_path}.pre_state.guid_key")
            media_sha256_key = _adapter_id(
                pre_state["media_sha256_key"],
                f"{row_path}.pre_state.media_sha256_key",
            )
            if media_sha256_key not in pre_state_source_by_key:
                raise EvalBundleV3Error(
                    f"{row_path}.pre_state.media_sha256_key references an unknown pre-state source"
                )
            referenced_pre_state_source_keys.append(media_sha256_key)
            _string(pre_state["notes"], f"{row_path}.pre_state.notes")
        elif existence == "absent":
            if any(pre_state[key] is not None for key in ("guid_key", "media_sha256_key", "notes")):
                raise EvalBundleV3Error(
                    f"{row_path}.pre_state absent targets must have null captured state"
                )
        else:
            raise EvalBundleV3Error(f"{row_path}.pre_state.existence is not closed")

        guid_policy = fixture_row["guid_policy"]
        if guid_policy not in allowed_guid_policies:
            raise EvalBundleV3Error(f"{row_path}.guid_policy is not closed")
        oracle = _object(fixture_row["oracle"], f"{row_path}.oracle")
        _closed_keys(
            oracle,
            required={
                "target_cardinality",
                "media_policy",
                "language_policy",
                "event_policy",
            },
            path=f"{row_path}.oracle",
        )
        if oracle["target_cardinality"] not in {0, 1}:
            raise EvalBundleV3Error(f"{row_path}.oracle.target_cardinality must be 0 or 1")
        if oracle["media_policy"] not in {
            "copied_original_sha256_equals_source_sha256",
            "no_originals_file_created",
        }:
            raise EvalBundleV3Error(f"{row_path}.oracle.media_policy is not closed")
        if oracle["language_policy"] not in {
            "audio_file_source_language_equals_row_language",
            "no_audio_file_source_created",
        }:
            raise EvalBundleV3Error(f"{row_path}.oracle.language_policy is not closed")
        expected_event_policy = (
            "new_event_exact_action_targets_row_object_guid" if event is not None else "none"
        )
        if oracle["event_policy"] != expected_event_policy:
            raise EvalBundleV3Error(f"{row_path}.oracle.event_policy does not match event")

        tsv_name = fixture_row["tsv_name"]
        tsv_row = fixture_row["tsv_row"]
        if adapter == "audio_import_fixture":
            if tsv_name is not None or tsv_row is not None:
                raise EvalBundleV3Error(f"{row_path} audio.import rows cannot bind a TSV")
            derived_target = canonical_import_target(
                object_path,
                version=EXECUTION_PROFILE_VERSION,
            )["canonical_target_path"]
            operation = audio_operation
            table_key = "__audio_import__"
        else:
            tsv_name = _string(tsv_name, f"{row_path}.tsv_name")
            if tsv_name not in tab_by_name:
                raise EvalBundleV3Error(f"{row_path}.tsv_name references an unknown TSV")
            tsv_row = _positive_int(tsv_row, f"{row_path}.tsv_row")
            table_physical_rows[tsv_name].append(tsv_row)
            if source_by_key[source_key]["presence"] == "absent":
                table_missing_rows[tsv_name].append(tsv_row)
            tab = tab_by_name[tsv_name]
            if language != tab["language"]:
                raise EvalBundleV3Error(f"{row_path}.language must equal its TSV call language")
            headers = set(tab["headers"])
            # object_type remains a hidden business-oracle field even when the
            # typed Object Path already closes creation and the TSV deliberately
            # omits the separate Object Type wire column.
            optional_columns = {
                "OriginalsSubFolder": fixture_row["originals_subfolder"],
                "Notes": fixture_row["notes"],
                "Audio Source Notes": fixture_row["audio_source_notes"],
                "Event": fixture_row["event"],
            }
            for header, cell in optional_columns.items():
                if cell is not None and header not in headers:
                    raise EvalBundleV3Error(
                        f"{row_path} declares {header!r} without the matching TSV header"
                    )
            rendered_cells: Mapping[str, Any] = {
                "Audio File": source_by_key[source_key]["relative_path"],
                "Object Path": object_path,
                "Object Type": fixture_row["object_type"],
                "OriginalsSubFolder": fixture_row["originals_subfolder"],
                "Notes": fixture_row["notes"],
                "Audio Source Notes": fixture_row["audio_source_notes"],
                "Event": (
                    f"{event['path']}@{event['action']}"
                    if isinstance(event, Mapping)
                    else None
                ),
            }
            for header in headers:
                cell = rendered_cells[header]
                if isinstance(cell, str) and any(
                    separator in cell for separator in ("\t", "\r", "\n")
                ):
                    raise EvalBundleV3Error(
                        f"{row_path} {header!r} contains a physical TSV separator"
                    )
            derived_target = derive_tab_target(
                object_path,
                import_location=import_location,
                version=EXECUTION_PROFILE_VERSION,
            )["canonical_target_path"]
            operation = tab["import_operation"]
            table_key = tsv_name
        if derived_target != target_path:
            raise EvalBundleV3Error(f"{row_path}.target_path does not match the declared object path")
        target_keys_by_table[table_key].append(target_path.casefold())

        expected_policies = {
            ("useExisting", "existing"): {
                "preserve_existing_guid",
                "preserve_shared_existing_guid",
            },
            ("useExisting", "absent"): {
                "create_new_unique_guid",
                "create_once_then_preserve_shared_guid",
                "remain_absent_no_guid",
            },
            ("createNew", "absent"): {"create_new_unique_guid"},
            ("replaceExisting", "existing"): {"replace_with_distinct_guid"},
        }
        if guid_policy not in expected_policies.get((operation, existence), set()):
            raise EvalBundleV3Error(
                f"{row_path}.guid_policy conflicts with import operation and pre-state"
            )
        refusal = guid_policy == "remain_absent_no_guid"
        if refusal != (oracle["target_cardinality"] == 0):
            raise EvalBundleV3Error(f"{row_path}.oracle cardinality conflicts with GUID policy")
        expected_media = (
            "no_originals_file_created"
            if refusal
            else "copied_original_sha256_equals_source_sha256"
        )
        expected_language = (
            "no_audio_file_source_created"
            if refusal
            else "audio_file_source_language_equals_row_language"
        )
        if oracle["media_policy"] != expected_media or oracle["language_policy"] != expected_language:
            raise EvalBundleV3Error(f"{row_path}.oracle output policy conflicts with GUID policy")
        object_groups[object_key].append(fixture_row)

    _require_unique(tuple(row_keys), f"{path}.rows row_key values")
    _require_unique(tuple(referenced_source_keys), f"{path}.rows source_key values")
    _require_unique(
        tuple(referenced_pre_state_source_keys),
        f"{path}.rows pre-state media_sha256_key values",
    )
    if set(referenced_pre_state_source_keys) != set(pre_state_source_by_key):
        raise EvalBundleV3Error(
            f"{path}.rows must reference every pre-state source exactly once"
        )
    if set(referenced_source_keys) != set(source_by_key):
        raise EvalBundleV3Error(f"{path}.rows must reference every source exactly once")
    for table_key, targets in target_keys_by_table.items():
        _require_unique(tuple(targets), f"{path}.rows target paths for {table_key}")
    for name, tab in tab_by_name.items():
        expected_rows = list(range(2, tab["row_count"] + 2))
        if sorted(table_physical_rows[name]) != expected_rows:
            raise EvalBundleV3Error(f"{path}.rows must define every physical row in {name}")
        if sorted(table_missing_rows[name]) != sorted(tab["missing_audio_rows"]):
            raise EvalBundleV3Error(f"{path}.rows missing sources do not match {name}")
    if any(source["presence"] == "absent" for source in source_by_key.values()):
        if any(item["guid_policy"] != "remain_absent_no_guid" for item in fixture_rows):
            raise EvalBundleV3Error(
                f"{path}.rows must model all-or-nothing refusal when any source is absent"
            )
    for object_key, grouped_rows in object_groups.items():
        if len({item["target_path"] for item in grouped_rows}) != 1:
            raise EvalBundleV3Error(f"{path}.rows object_key {object_key!r} has multiple targets")
        if len({item["object_type"] for item in grouped_rows}) != 1:
            raise EvalBundleV3Error(f"{path}.rows object_key {object_key!r} has multiple types")
        policies = {item["guid_policy"] for item in grouped_rows}
        if len(grouped_rows) > 1:
            if policies not in (
                {"preserve_shared_existing_guid"},
                {"create_once_then_preserve_shared_guid"},
            ):
                raise EvalBundleV3Error(
                    f"{path}.rows repeated object_key {object_key!r} lacks a shared-GUID policy"
                )
            languages = [item["language"] for item in grouped_rows]
            _require_unique(tuple(languages), f"{path}.rows languages for {object_key}")
            if len({item["notes"] for item in grouped_rows}) != 1:
                raise EvalBundleV3Error(
                    f"{path}.rows shared object_key {object_key!r} must use one object Notes value"
                )
            if policies == {"preserve_shared_existing_guid"}:
                if (
                    {item["pre_state"]["existence"] for item in grouped_rows}
                    != {"existing"}
                    or len({item["pre_state"]["guid_key"] for item in grouped_rows}) != 1
                ):
                    raise EvalBundleV3Error(
                        f"{path}.rows shared existing object_key {object_key!r} must bind one GUID"
                    )
            elif {item["pre_state"]["existence"] for item in grouped_rows} != {"absent"}:
                raise EvalBundleV3Error(
                    f"{path}.rows shared new object_key {object_key!r} must be initially absent"
                )
        elif policies & {
            "preserve_shared_existing_guid",
            "create_once_then_preserve_shared_guid",
        }:
            raise EvalBundleV3Error(
                f"{path}.rows object_key {object_key!r} declares a shared policy only once"
            )
    return dict(row)


def _parse_soundbank_asset_spec(
    value: Any,
    path: str,
    *,
    adapter: str,
) -> Mapping[str, Any]:
    if adapter == "soundbank_generation_fixture":
        return _parse_soundbank_generation_asset_spec(value, path)
    if adapter == "soundbank_external_source_fixture":
        return _parse_soundbank_external_source_asset_spec(value, path)
    if adapter == "soundbank_definition_fixture":
        return _parse_soundbank_definition_asset_spec(value, path)
    if adapter == "soundbank_inclusion_fixture":
        return _parse_soundbank_inclusion_asset_spec(value, path)
    if adapter == "soundbank_topic_fixture":
        return _parse_soundbank_topic_asset_spec(value, path)
    raise EvalBundleV3Error(f"{path} has an unknown SoundBank fixture adapter")


def _parse_soundbank_artifact_expectation(value: Any, path: str) -> str:
    expectation = _string(value, path)
    if expectation not in SOUNDBANK_ARTIFACT_EXPECTATIONS:
        raise EvalBundleV3Error(
            f"{path} must be nonlocalized, localized, or mixed"
        )
    return expectation


def _parse_soundbank_content_fixture(
    value: Any,
    path: str,
    *,
    bank_scopes: Mapping[str, tuple[str, tuple[str, ...], tuple[str, ...]]],
) -> None:
    fixture = _object(value, path)
    _closed_keys(
        fixture,
        required={
            "profile",
            "materialization_policy",
            "soundbanks",
            "control_soundbanks",
            "preexisting_artifacts",
        },
        optional={"init_precondition", "rebuild_seeds"},
        path=path,
    )
    profile = _adapter_id(fixture["profile"], f"{path}.profile")
    if fixture["materialization_policy"] != SOUNDBANK_FIXTURE_MATERIALIZATION_POLICY:
        raise EvalBundleV3Error(f"{path}.materialization_policy is not closed")
    if fixture["profile"] == "cli_generate_weapons_ambience_rebuild":
        if fixture.get("rebuild_seeds") != SOUNDBANK_REBUILD_SEEDS:
            raise EvalBundleV3Error(
                f"{path}.rebuild_seeds must exactly seal the reviewed stale cache/header"
            )
    elif "rebuild_seeds" in fixture:
        raise EvalBundleV3Error(
            f"{path}.rebuild_seeds is only valid for the reviewed rebuild profile"
        )

    soundbank_rows = _list(fixture["soundbanks"], f"{path}.soundbanks")
    parsed_bank_names: list[str] = []
    project_object_modes: dict[str, str] = {}
    for index, value in enumerate(soundbank_rows):
        bank_path = f"{path}.soundbanks[{index}]"
        bank = _object(value, bank_path)
        _closed_keys(
            bank,
            required={
                "name",
                "artifact_expectation",
                "project_object_mode",
                "events",
                "media",
                "dependencies",
            },
            path=bank_path,
        )
        name = _string(bank["name"], f"{bank_path}.name")
        parsed_bank_names.append(name)
        project_object_mode = _string(
            bank["project_object_mode"],
            f"{bank_path}.project_object_mode",
        )
        if project_object_mode not in SOUNDBANK_PROJECT_OBJECT_MODES:
            raise EvalBundleV3Error(
                f"{bank_path}.project_object_mode is not closed"
            )
        project_object_modes[name] = project_object_mode
        scope = bank_scopes.get(name)
        if scope is None:
            raise EvalBundleV3Error(f"{bank_path}.name is not requested")
        expectation = _parse_soundbank_artifact_expectation(
            bank["artifact_expectation"],
            f"{bank_path}.artifact_expectation",
        )
        requested_expectation, _, requested_languages = scope
        if expectation != requested_expectation:
            raise EvalBundleV3Error(
                f"{bank_path}.artifact_expectation must match the request"
            )

        events = _list(bank["events"], f"{bank_path}.events")
        if not events:
            raise EvalBundleV3Error(f"{bank_path}.events must not be empty")
        event_names: list[str] = []
        event_paths: list[str] = []
        for event_index, event_value in enumerate(events):
            event_path = f"{bank_path}.events[{event_index}]"
            event = _object(event_value, event_path)
            _closed_keys(event, required={"name", "object_path"}, path=event_path)
            event_name = _string(event["name"], f"{event_path}.name")
            object_path = _string(event["object_path"], f"{event_path}.object_path")
            if not object_path.startswith("\\Events\\") or not object_path.endswith(
                f"\\{event_name}"
            ):
                raise EvalBundleV3Error(
                    f"{event_path}.object_path must be an absolute Event path ending in its name"
                )
            event_names.append(event_name)
            event_paths.append(object_path)
        _require_unique(
            tuple(value.casefold() for value in event_names),
            f"{bank_path}.events names",
        )
        _require_unique(
            tuple(value.casefold() for value in event_paths),
            f"{bank_path}.events object paths",
        )

        media = _list(bank["media"], f"{bank_path}.media")
        if not media:
            raise EvalBundleV3Error(f"{bank_path}.media must not be empty")
        media_keys: list[str] = []
        media_files: list[str] = []
        media_events: set[str] = set()
        media_languages: set[str] = set()
        explicit_media_layout: list[tuple[str, str, str, str, bool]] = []
        for media_index, media_value in enumerate(media):
            media_path = f"{bank_path}.media[{media_index}]"
            media_row = _object(media_value, media_path)
            _closed_keys(
                media_row,
                required={
                    "key",
                    "relative_wav",
                    "event",
                    "language",
                    "duration_ms",
                    "frequency_hz",
                },
                optional={"object_path", "import_operation", "create_event"},
                path=media_path,
            )
            media_keys.append(_adapter_id(media_row["key"], f"{media_path}.key"))
            relative_wav = _string(
                media_row["relative_wav"],
                f"{media_path}.relative_wav",
            )
            if (
                "/" in relative_wav
                or "\\" in relative_wav
                or not relative_wav.casefold().endswith(".wav")
            ):
                raise EvalBundleV3Error(
                    f"{media_path}.relative_wav must be one exact WAV basename"
                )
            media_files.append(relative_wav.casefold())
            event_name = _string(media_row["event"], f"{media_path}.event")
            if event_name not in event_names:
                raise EvalBundleV3Error(f"{media_path}.event is not declared by this Bank")
            media_events.add(event_name)
            language = _string(media_row["language"], f"{media_path}.language")
            media_languages.add(language)
            layout_keys = {"object_path", "import_operation", "create_event"}
            present_layout_keys = layout_keys.intersection(media_row)
            if present_layout_keys and present_layout_keys != layout_keys:
                raise EvalBundleV3Error(
                    f"{media_path} localized object reuse layout must declare "
                    "object_path, import_operation, and create_event together"
                )
            if present_layout_keys:
                object_path = _string(
                    media_row["object_path"],
                    f"{media_path}.object_path",
                )
                expected_parent = (
                    "\\Actor-Mixer Hierarchy\\Default Work Unit\\V3 CLI\\"
                    f"{profile}\\"
                    if profile.startswith("cli_")
                    else "\\Actor-Mixer Hierarchy\\Default Work Unit\\"
                    f"{profile}\\"
                )
                relative_object = object_path.removeprefix(expected_parent)
                if (
                    not object_path.startswith(expected_parent)
                    or not relative_object
                    or "\\" in relative_object
                ):
                    raise EvalBundleV3Error(
                        f"{media_path}.object_path must be one direct logical Sound "
                        "below the case profile"
                    )
                import_operation = _string(
                    media_row["import_operation"],
                    f"{media_path}.import_operation",
                )
                if import_operation not in {"createNew", "useExisting"}:
                    raise EvalBundleV3Error(
                        f"{media_path}.import_operation is not closed for localized reuse"
                    )
                create_event = _boolean(
                    media_row["create_event"],
                    f"{media_path}.create_event",
                )
                explicit_media_layout.append(
                    (
                        event_name,
                        object_path,
                        language,
                        import_operation,
                        create_event,
                    )
                )
            _positive_int(media_row["duration_ms"], f"{media_path}.duration_ms")
            _positive_int(media_row["frequency_hz"], f"{media_path}.frequency_hz")
        _require_unique(tuple(media_keys), f"{bank_path}.media keys")
        _require_unique(tuple(media_files), f"{bank_path}.media relative_wav values")
        if media_events != set(event_names):
            raise EvalBundleV3Error(
                f"{bank_path}.media must materialize every declared Event"
            )
        expected_media_languages = {
            "nonlocalized": {"SFX"},
            "localized": set(requested_languages),
            "mixed": {"SFX", *requested_languages},
        }[expectation]
        if media_languages != expected_media_languages:
            raise EvalBundleV3Error(
                f"{bank_path}.media languages must exactly prove artifact_expectation"
            )
        if explicit_media_layout:
            if len(explicit_media_layout) != len(media):
                raise EvalBundleV3Error(
                    f"{bank_path}.media must use one consistent localized object reuse layout"
                )
            logical_paths: list[str] = []
            for event_name in event_names:
                event_rows = [
                    row for row in explicit_media_layout if row[0] == event_name
                ]
                event_paths = {row[1] for row in event_rows}
                event_languages = tuple(row[2] for row in event_rows)
                create_rows = [row for row in event_rows if row[4]]
                reuse_rows = [row for row in event_rows if not row[4]]
                if (
                    len(event_paths) != 1
                    or event_languages != tuple(requested_languages)
                ):
                    raise EvalBundleV3Error(
                        f"{bank_path}.media Event {event_name!r} must map one logical "
                        "Sound across every requested language in request order"
                    )
                if (
                    len(create_rows) != 1
                    or not requested_languages
                    or create_rows[0][2:5]
                    != (requested_languages[0], "createNew", True)
                    or any(
                        row[3:] != ("useExisting", False)
                        for row in reuse_rows
                    )
                ):
                    raise EvalBundleV3Error(
                        f"{bank_path}.media Event {event_name!r} must create its first-language "
                        "Sound/Event once and reuse it without Event creation for later languages"
                    )
                logical_paths.extend(event_paths)
            _require_unique(
                tuple(path.casefold() for path in logical_paths),
                f"{bank_path}.media logical Sound paths",
            )

        dependencies = _list(bank["dependencies"], f"{bank_path}.dependencies")
        if not dependencies:
            raise EvalBundleV3Error(f"{bank_path}.dependencies must not be empty")
        dependency_paths: list[str] = []
        for dependency_index, dependency_value in enumerate(dependencies):
            dependency_path = f"{bank_path}.dependencies[{dependency_index}]"
            dependency = _object(dependency_value, dependency_path)
            _closed_keys(
                dependency,
                required={"object_path", "type"},
                path=dependency_path,
            )
            object_path = _string(
                dependency["object_path"],
                f"{dependency_path}.object_path",
            )
            if not object_path.startswith("\\"):
                raise EvalBundleV3Error(
                    f"{dependency_path}.object_path must be absolute"
                )
            dependency_paths.append(object_path.casefold())
            _string(dependency["type"], f"{dependency_path}.type")
        _require_unique(tuple(dependency_paths), f"{bank_path}.dependencies")

    if tuple(parsed_bank_names) != tuple(bank_scopes):
        raise EvalBundleV3Error(
            f"{path}.soundbanks must preserve every requested Bank order"
        )
    controls = _string_tuple(fixture["control_soundbanks"], f"{path}.control_soundbanks")
    if not controls:
        raise EvalBundleV3Error(f"{path}.control_soundbanks must not be empty")
    _require_unique(
        tuple(value.casefold() for value in controls),
        f"{path}.control_soundbanks",
    )
    if {value.casefold() for value in controls}.intersection(
        value.casefold() for value in parsed_bank_names
    ):
        raise EvalBundleV3Error(
            f"{path}.control_soundbanks overlaps requested SoundBanks"
        )

    preexisting = _list(
        fixture["preexisting_artifacts"],
        f"{path}.preexisting_artifacts",
    )
    preexisting_keys: list[str] = []
    for index, value in enumerate(preexisting):
        artifact_path = f"{path}.preexisting_artifacts[{index}]"
        artifact = _object(value, artifact_path)
        _closed_keys(
            artifact,
            required={"soundbank", "platform", "language", "marker"},
            path=artifact_path,
        )
        soundbank = _string(artifact["soundbank"], f"{artifact_path}.soundbank")
        scope = bank_scopes.get(soundbank)
        if scope is None:
            raise EvalBundleV3Error(
                f"{artifact_path}.soundbank must be a requested fixture Bank"
            )
        if project_object_modes[soundbank] == "temporary_request_only":
            raise EvalBundleV3Error(
                f"{artifact_path}.soundbank cannot preexist for temporary_request_only"
            )
        expectation, platforms, languages = scope
        platform = _string(artifact["platform"], f"{artifact_path}.platform")
        language = _optional_string(artifact["language"], f"{artifact_path}.language")
        if platform not in platforms:
            raise EvalBundleV3Error(f"{artifact_path}.platform is not requested")
        allowed_languages: set[str | None] = {
            "nonlocalized": {None},
            "localized": set(languages),
            "mixed": {None, *languages},
        }[expectation]
        if language not in allowed_languages:
            raise EvalBundleV3Error(
                f"{artifact_path}.language disagrees with artifact_expectation"
            )
        if artifact["marker"] != "deterministic_stale_nonzero_sha256":
            raise EvalBundleV3Error(f"{artifact_path}.marker is not closed")
        preexisting_keys.append(
            _soundbank_topic_event_key(soundbank, platform, language)
        )
    _require_unique(tuple(preexisting_keys), f"{path}.preexisting_artifacts")


def _parse_soundbank_generation_asset_spec(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "operation",
            "request",
            "fixture_manifest",
            "expected_user_soundbanks",
            "automatic_byproducts",
            "project_policy",
            "artifact_policy",
            "cleanup_policy",
        },
        path=path,
    )
    if row["operation"] != "generate":
        raise EvalBundleV3Error(f"{path}.operation must be generate")
    request = _object(row["request"], f"{path}.request")
    _closed_keys(
        request,
        required={"soundbanks", "platforms", "skipLanguages", "writeToDisk"},
        optional={
            "languages",
            "rebuildSoundBanks",
            "clearAudioFileCache",
            "rebuildInitBank",
        },
        path=f"{path}.request",
    )
    banks = _list(request["soundbanks"], f"{path}.request.soundbanks")
    if not banks:
        raise EvalBundleV3Error(f"{path}.request.soundbanks must not be empty")
    bank_names: list[str] = []
    bank_expectations: dict[str, str] = {}
    explicit_events_by_bank: dict[str, tuple[str, ...]] = {}
    for index, value in enumerate(banks):
        bank_path = f"{path}.request.soundbanks[{index}]"
        bank = _object(value, bank_path)
        _closed_keys(
            bank,
            required={"name", "artifact_expectation"},
            optional={"events", "auxBusses", "inclusions", "rebuild"},
            path=bank_path,
        )
        name = _string(bank["name"], f"{bank_path}.name")
        if name.casefold() == "init":
            raise EvalBundleV3Error(f"{bank_path}.name cannot request automatic Init")
        bank_names.append(name)
        expectation = _parse_soundbank_artifact_expectation(
            bank["artifact_expectation"],
            f"{bank_path}.artifact_expectation",
        )
        bank_expectations[name] = expectation
        has_explicit_identities = False
        for field in ("events", "auxBusses"):
            if field not in bank:
                continue
            identities = _string_tuple(bank[field], f"{bank_path}.{field}")
            if not identities:
                raise EvalBundleV3Error(f"{bank_path}.{field} must not be empty")
            _require_unique(identities, f"{bank_path}.{field}")
            has_explicit_identities = True
            if field == "events":
                explicit_events_by_bank[name] = identities
        if "inclusions" in bank:
            inclusions = _string_tuple(bank["inclusions"], f"{bank_path}.inclusions")
            if not inclusions or not set(inclusions).issubset(SOUNDBANK_GENERATE_INCLUSIONS):
                raise EvalBundleV3Error(f"{bank_path}.inclusions is outside the closed set")
            _require_unique(inclusions, f"{bank_path}.inclusions")
            if not has_explicit_identities:
                raise EvalBundleV3Error(
                    f"{bank_path}.inclusions requires explicit events or auxBusses"
                )
        if "rebuild" in bank:
            _boolean(bank["rebuild"], f"{bank_path}.rebuild")
    _require_unique(tuple(name.casefold() for name in bank_names), f"{path}.request.soundbanks")

    platforms = _string_tuple(request["platforms"], f"{path}.request.platforms")
    if not platforms:
        raise EvalBundleV3Error(f"{path}.request.platforms must not be empty")
    _require_unique(tuple(value.casefold() for value in platforms), f"{path}.request.platforms")
    skip_languages = _boolean(request["skipLanguages"], f"{path}.request.skipLanguages")
    if skip_languages:
        languages: tuple[str, ...] = ()
        if "languages" in request:
            raise EvalBundleV3Error(
                f"{path}.request.languages must be omitted when skipLanguages is true"
            )
    else:
        languages = _string_tuple(request.get("languages"), f"{path}.request.languages")
        if not languages:
            raise EvalBundleV3Error(
                f"{path}.request.languages must be explicit when skipLanguages is false"
            )
        _require_unique(tuple(value.casefold() for value in languages), f"{path}.request.languages")
    for bank_name, expectation in bank_expectations.items():
        if skip_languages != (expectation == "nonlocalized"):
            raise EvalBundleV3Error(
                f"{path}.request.soundbanks artifact_expectation for {bank_name!r} "
                "disagrees with skipLanguages"
            )
    if _boolean(request["writeToDisk"], f"{path}.request.writeToDisk") is not True:
        raise EvalBundleV3Error(f"{path}.request.writeToDisk must be true")
    for field in ("rebuildSoundBanks", "clearAudioFileCache", "rebuildInitBank"):
        if field in request:
            _boolean(request[field], f"{path}.request.{field}")

    bank_scopes = {
        bank_name: (bank_expectations[bank_name], platforms, languages)
        for bank_name in bank_names
    }
    _parse_soundbank_content_fixture(
        row["fixture_manifest"],
        f"{path}.fixture_manifest",
        bank_scopes=bank_scopes,
    )
    if "init_precondition" in _object(
        row["fixture_manifest"],
        f"{path}.fixture_manifest",
    ):
        raise EvalBundleV3Error(
            f"{path}.fixture_manifest.init_precondition is reserved for generated topic cases"
        )
    fixture_banks = {
        bank["name"]: bank
        for bank in _list(
            _object(row["fixture_manifest"], f"{path}.fixture_manifest")["soundbanks"],
            f"{path}.fixture_manifest.soundbanks",
        )
    }
    for bank_name, fixture_bank in fixture_banks.items():
        expected_mode = (
            "temporary_request_only"
            if bank_name in explicit_events_by_bank
            else "existing_soundbank"
        )
        if fixture_bank["project_object_mode"] != expected_mode:
            raise EvalBundleV3Error(
                f"{path}.fixture_manifest project_object_mode for {bank_name!r} "
                "does not match the generate request shape"
            )
    for bank_name, explicit_events in explicit_events_by_bank.items():
        fixture_events = tuple(
            event["name"] for event in fixture_banks[bank_name]["events"]
        )
        if explicit_events != fixture_events:
            raise EvalBundleV3Error(
                f"{path}.fixture_manifest events for {bank_name!r} must equal the explicit request events"
            )

    expected_banks = _string_tuple(
        row["expected_user_soundbanks"],
        f"{path}.expected_user_soundbanks",
    )
    if expected_banks != tuple(bank_names):
        raise EvalBundleV3Error(
            f"{path}.expected_user_soundbanks must preserve the request SoundBank order"
        )
    automatic = _string_tuple(row["automatic_byproducts"], f"{path}.automatic_byproducts")
    if automatic != ("Init.bnk",):
        raise EvalBundleV3Error(f"{path}.automatic_byproducts must disclose only Init.bnk")
    if row["project_policy"] != "saved_clean_case_project_with_get_project_info_path_attestation":
        raise EvalBundleV3Error(f"{path}.project_policy is not the closed generation policy")
    if row["artifact_policy"] != "case_owned_get_project_info_roots_with_pre_post_bounded_tree_sha256":
        raise EvalBundleV3Error(f"{path}.artifact_policy is not the closed generation policy")
    _require_case_project_cleanup_policy(row, path)
    return dict(row)


def _parse_external_source_documents(
    value: Any,
    path: str,
    *,
    allowed_root_modes: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, tuple[tuple[str, str], ...]]]:
    documents = _list(value, path)
    if not documents:
        raise EvalBundleV3Error(f"{path} must not be empty")
    document_names: list[str] = []
    source_paths: list[str] = []
    entries_by_document: dict[str, tuple[tuple[str, str], ...]] = {}
    for index, value in enumerate(documents):
        document_path = f"{path}[{index}]"
        document = _object(value, document_path)
        _closed_keys(
            document,
            required={"name", "schema_version", "root_mode", "entries"},
            path=document_path,
        )
        name = _string(document["name"], f"{document_path}.name")
        if not name.endswith(".wsources"):
            raise EvalBundleV3Error(f"{document_path}.name must end in .wsources")
        document_names.append(name)
        if document["schema_version"] != 1:
            raise EvalBundleV3Error(f"{document_path}.schema_version must be 1")
        if document["root_mode"] not in allowed_root_modes:
            raise EvalBundleV3Error(f"{document_path}.root_mode is not closed")
        entries = _list(document["entries"], f"{document_path}.entries")
        if not entries:
            raise EvalBundleV3Error(f"{document_path}.entries must not be empty")
        destinations: list[str] = []
        parsed_entries: list[tuple[str, str]] = []
        for entry_index, entry_value in enumerate(entries):
            entry_path = f"{document_path}.entries[{entry_index}]"
            entry = _object(entry_value, entry_path)
            _closed_keys(
                entry,
                required={"path", "conversion", "destination", "analysis_types"},
                path=entry_path,
            )
            source = _string(entry["path"], f"{entry_path}.path")
            if not source.casefold().endswith(".wav") or source.startswith(("/", "\\")):
                raise EvalBundleV3Error(f"{entry_path}.path must be a relative WAV path")
            if any(part in {"", ".", ".."} for part in re.split(r"[\\/]", source)):
                raise EvalBundleV3Error(f"{entry_path}.path contains an unsafe segment")
            normalized_source = "/".join(re.split(r"[\\/]", source))
            source_paths.append(normalized_source)
            conversion = entry["conversion"]
            if conversion is not None:
                _string(conversion, f"{entry_path}.conversion")
            destination = entry["destination"]
            expected_destination = source if destination is None else _string(
                destination,
                f"{entry_path}.destination",
            )
            if expected_destination.startswith(("/", "\\")):
                raise EvalBundleV3Error(f"{entry_path}.destination must be relative")
            destination_parts = re.split(r"[\\/]", expected_destination)
            if any(part in {"", ".", ".."} for part in destination_parts):
                raise EvalBundleV3Error(f"{entry_path}.destination contains an unsafe segment")
            normalized_destination = str(Path(*destination_parts).with_suffix(".wem")).replace(
                "\\", "/"
            )
            destinations.append(normalized_destination.casefold())
            parsed_entries.append((normalized_source, normalized_destination))
            analysis_types = entry["analysis_types"]
            if analysis_types is not None and analysis_types not in {0, 2, 4, 6}:
                raise EvalBundleV3Error(f"{entry_path}.analysis_types is outside 0/2/4/6")
        _require_unique(tuple(destinations), f"{document_path}.entries destinations")
        entries_by_document[name] = tuple(parsed_entries)
    _require_unique(tuple(name.casefold() for name in document_names), f"{path}.documents names")
    _require_unique(tuple(value.casefold() for value in source_paths), f"{path}.documents source WAV paths")
    return tuple(document_names), tuple(source_paths), entries_by_document


def _parse_soundbank_external_source_asset_spec(
    value: Any,
    path: str,
) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "operation",
            "documents",
            "jobs",
            "wav",
            "source_policy",
            "output_policy",
            "cleanup_policy",
        },
        path=path,
    )
    if row["operation"] != "convertExternalSources":
        raise EvalBundleV3Error(f"{path}.operation must be convertExternalSources")
    wav = _object(row["wav"], f"{path}.wav")
    _closed_keys(
        wav,
        required={"count", "format", "filename_pattern", "content_policy"},
        path=f"{path}.wav",
    )
    wav_count = _positive_int(wav["count"], f"{path}.wav.count")
    if wav["format"] != "pcm_s16le_mono_48000hz":
        raise EvalBundleV3Error(f"{path}.wav.format must use the deterministic PCM fixture format")
    _string(wav["filename_pattern"], f"{path}.wav.filename_pattern")
    if wav["content_policy"] != "deterministic_distinct_signal_per_file":
        raise EvalBundleV3Error(f"{path}.wav.content_policy is not reproducible")

    document_names, source_paths, _ = _parse_external_source_documents(
        row["documents"],
        f"{path}.documents",
        allowed_root_modes={"project_relative_case_media", "project_root"},
    )
    if len(source_paths) != wav_count:
        raise EvalBundleV3Error(f"{path}.wav.count must equal the unique Source row count")

    jobs = _list(row["jobs"], f"{path}.jobs")
    if not jobs:
        raise EvalBundleV3Error(f"{path}.jobs must not be empty")
    job_keys: list[str] = []
    output_keys: list[str] = []
    known_documents = set(document_names)
    for index, value in enumerate(jobs):
        job_path = f"{path}.jobs[{index}]"
        job = _object(value, job_path)
        _closed_keys(job, required={"document", "platform", "output_key"}, path=job_path)
        document = _string(job["document"], f"{job_path}.document")
        if document not in known_documents:
            raise EvalBundleV3Error(f"{job_path}.document does not name a fixture document")
        platform = _string(job["platform"], f"{job_path}.platform")
        output_key = _adapter_id(job["output_key"], f"{job_path}.output_key")
        job_keys.append(f"{document.casefold()}|{platform.casefold()}|{output_key}")
        output_keys.append(output_key)
    _require_unique(tuple(job_keys), f"{path}.jobs")
    _require_unique(tuple(output_keys), f"{path}.jobs output_key")
    if row["source_policy"] != "absolute_regular_non_symlink_size_sha256":
        raise EvalBundleV3Error(f"{path}.source_policy must bind absolute hashed regular files")
    if row["output_policy"] != "case_owned_explicit_distinct_roots_with_pre_post_bounded_tree_sha256":
        raise EvalBundleV3Error(f"{path}.output_policy is not the closed External Sources policy")
    _require_case_project_cleanup_policy(row, path)
    return dict(row)


def _parse_soundbank_definition_asset_spec(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "operation",
            "files",
            "expected_primary_dispatch_count",
            "source_policy",
            "project_policy",
            "cleanup_policy",
        },
        path=path,
    )
    if row["operation"] != "processDefinitionFiles":
        raise EvalBundleV3Error(f"{path}.operation must be processDefinitionFiles")
    expected_count = _nonnegative_int(
        row["expected_primary_dispatch_count"],
        f"{path}.expected_primary_dispatch_count",
    )
    if expected_count not in {0, 1}:
        raise EvalBundleV3Error(f"{path}.expected_primary_dispatch_count must be zero or one")
    files = _list(row["files"], f"{path}.files")
    if not files:
        raise EvalBundleV3Error(f"{path}.files must not be empty")
    file_names: list[str] = []
    bank_sources: dict[str, str] = {}
    resolutions: list[str] = []
    for index, value in enumerate(files):
        file_path = f"{path}.files[{index}]"
        definition = _object(value, file_path)
        _closed_keys(
            definition,
            required={"name", "encoding", "serialization", "rows"},
            path=file_path,
        )
        name = _string(definition["name"], f"{file_path}.name")
        if not name.endswith(".tsv"):
            raise EvalBundleV3Error(f"{file_path}.name must end in .tsv")
        file_names.append(name)
        if definition["encoding"] != "utf-8_no_bom":
            raise EvalBundleV3Error(f"{file_path}.encoding must be utf-8_no_bom")
        serialization = _object(
            definition["serialization"],
            f"{file_path}.serialization",
        )
        _closed_keys(
            serialization,
            required=set(SOUNDBANK_DEFINITION_SERIALIZATION),
            path=f"{file_path}.serialization",
        )
        if serialization != SOUNDBANK_DEFINITION_SERIALIZATION:
            raise EvalBundleV3Error(
                f"{file_path}.serialization is not the reviewed SoundBank Definition TSV layout"
            )
        rows = _list(definition["rows"], f"{file_path}.rows")
        if not rows:
            raise EvalBundleV3Error(f"{file_path}.rows must not be empty")
        inclusion_keys: list[str] = []
        for row_index, row_value in enumerate(rows):
            definition_row_path = f"{file_path}.rows[{row_index}]"
            definition_row = _object(row_value, definition_row_path)
            _closed_keys(
                definition_row,
                required={
                    "soundbank",
                    "directive",
                    "identity",
                    "identity_format",
                    "identity_materialization",
                    "filters",
                    "resolution",
                },
                path=definition_row_path,
            )
            bank = _string(definition_row["soundbank"], f"{definition_row_path}.soundbank")
            if any(character in bank for character in ("\t", "\r", "\n", '"')):
                raise EvalBundleV3Error(
                    f"{definition_row_path}.soundbank is not safely serializable"
                )
            bank_key = bank.casefold()
            previous = bank_sources.setdefault(bank_key, name)
            if previous != name:
                raise EvalBundleV3Error(
                    f"{definition_row_path}.soundbank cannot be defined across files"
                )
            directive = _string(definition_row["directive"], f"{definition_row_path}.directive")
            allowed_filters = SOUNDBANK_DEFINITION_FILTERS.get(directive)
            if allowed_filters is None:
                raise EvalBundleV3Error(f"{definition_row_path}.directive is not supported")
            identity = _string(definition_row["identity"], f"{definition_row_path}.identity")
            identity_format = _string(
                definition_row["identity_format"],
                f"{definition_row_path}.identity_format",
            )
            if identity_format not in SOUNDBANK_IDENTITY_FORMATS:
                raise EvalBundleV3Error(f"{definition_row_path}.identity_format is not closed")
            if any(character in identity for character in ("\\", "/", "\t", "\r", "\n", '"')):
                raise EvalBundleV3Error(
                    f"{definition_row_path}.identity must name one fixture object, not a path"
                )
            materialization = _string(
                definition_row["identity_materialization"],
                f"{definition_row_path}.identity_materialization",
            )
            if materialization != SOUNDBANK_IDENTITY_MATERIALIZATION[identity_format]:
                raise EvalBundleV3Error(
                    f"{definition_row_path}.identity_materialization does not match identity_format"
                )
            filters = _string_tuple(definition_row["filters"], f"{definition_row_path}.filters")
            _require_unique(filters, f"{definition_row_path}.filters")
            if not set(filters).issubset(allowed_filters):
                raise EvalBundleV3Error(f"{definition_row_path}.filters is outside the directive set")
            resolution = _string(definition_row["resolution"], f"{definition_row_path}.resolution")
            if resolution not in {"unique", "unknown"}:
                raise EvalBundleV3Error(f"{definition_row_path}.resolution is not closed")
            resolutions.append(resolution)
            inclusion_keys.append(f"{bank_key}|{directive}|{identity.casefold()}")
        _require_unique(tuple(inclusion_keys), f"{file_path}.rows inclusions")
    _require_unique(tuple(name.casefold() for name in file_names), f"{path}.files names")
    if expected_count == 0 and (not resolutions or set(resolutions) != {"unknown"}):
        raise EvalBundleV3Error(
            f"{path} zero-dispatch fixture must contain only an independent unknown identity"
        )
    if expected_count == 1 and (not resolutions or set(resolutions) != {"unique"}):
        raise EvalBundleV3Error(f"{path} dispatchable fixture requires all identities to resolve uniquely")
    if row["source_policy"] != "absolute_regular_non_symlink_size_sha256":
        raise EvalBundleV3Error(f"{path}.source_policy must bind absolute hashed regular files")
    if row["project_policy"] != "saved_clean_case_project_with_pre_inclusion_snapshot":
        raise EvalBundleV3Error(f"{path}.project_policy is not the closed Definition policy")
    _require_case_project_cleanup_policy(row, path)
    return dict(row)


def _parse_soundbank_inclusion_asset_spec(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "operation",
            "mode",
            "soundbank",
            "before",
            "requested",
            "expected_after",
            "control_soundbanks",
            "identity_policy",
            "project_policy",
            "cleanup_policy",
        },
        path=path,
    )
    if row["operation"] != "setInclusions":
        raise EvalBundleV3Error(f"{path}.operation must be setInclusions")
    mode = _string(row["mode"], f"{path}.mode")
    if mode not in {"add", "remove", "replace"}:
        raise EvalBundleV3Error(f"{path}.mode must be add, remove, or replace")
    soundbank = _string(row["soundbank"], f"{path}.soundbank")
    before = _parse_soundbank_inclusion_rows(row["before"], f"{path}.before")
    requested = _parse_soundbank_inclusion_rows(row["requested"], f"{path}.requested")
    expected = _parse_soundbank_inclusion_rows(row["expected_after"], f"{path}.expected_after")
    if mode != "replace" and not requested:
        raise EvalBundleV3Error(f"{path}.requested may be empty only for replace")

    computed = dict(before)
    if mode == "replace":
        computed = dict(requested)
    elif mode == "add":
        computed.update(requested)
    else:
        for object_key, filters in requested.items():
            if computed.get(object_key) != filters:
                raise EvalBundleV3Error(
                    f"{path}.requested remove rows must exactly match the before filter row"
                )
            del computed[object_key]
    if computed != expected:
        raise EvalBundleV3Error(f"{path}.expected_after does not match the closed mode transition")
    if before == expected:
        raise EvalBundleV3Error(f"{path} describes a no-op inclusion transition")

    controls = _string_tuple(row["control_soundbanks"], f"{path}.control_soundbanks")
    if not controls:
        raise EvalBundleV3Error(f"{path}.control_soundbanks must not be empty")
    _require_unique(tuple(value.casefold() for value in controls), f"{path}.control_soundbanks")
    if soundbank.casefold() in {value.casefold() for value in controls}:
        raise EvalBundleV3Error(f"{path}.soundbank cannot also be a control SoundBank")
    if row["identity_policy"] != "runner_materializes_absolute_paths_and_seals_hidden_guids":
        raise EvalBundleV3Error(f"{path}.identity_policy is not closed")
    if row["project_policy"] != "saved_case_project_with_exact_pre_and_post_get_inclusions":
        raise EvalBundleV3Error(f"{path}.project_policy is not closed")
    _require_case_project_cleanup_policy(row, path)
    return dict(row)


def _parse_soundbank_inclusion_rows(value: Any, path: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    allowed = {"events", "structures", "media"}
    for index, value in enumerate(_list(value, path)):
        row_path = f"{path}[{index}]"
        row = _object(value, row_path)
        _closed_keys(row, required={"object", "filters"}, path=row_path)
        object_name = _string(row["object"], f"{row_path}.object")
        key = object_name.casefold()
        if key in result:
            raise EvalBundleV3Error(f"{path} contains a duplicate inclusion object")
        filters = _string_tuple(row["filters"], f"{row_path}.filters")
        if not filters or not set(filters).issubset(allowed):
            raise EvalBundleV3Error(f"{row_path}.filters is outside events/structures/media")
        _require_unique(filters, f"{row_path}.filters")
        result[key] = tuple(sorted(filters))
    return result


def _parse_soundbank_topic_asset_spec(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={
            "operation",
            "publisher_requests",
            "fixture_manifest",
            "expected_topic_event_count",
            "subscription_policy",
            "payload_policy",
            "unexpected_event_policy",
            "artifact_policy",
            "cleanup_policy",
        },
        path=path,
    )
    if row["operation"] != "observeGenerated":
        raise EvalBundleV3Error(f"{path}.operation must be observeGenerated")
    publisher_requests = _list(row["publisher_requests"], f"{path}.publisher_requests")
    if not publisher_requests:
        raise EvalBundleV3Error(f"{path}.publisher_requests must not be empty")
    all_event_keys: list[str] = []
    all_bank_scopes: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {}
    for index, value in enumerate(publisher_requests):
        request_path = f"{path}.publisher_requests[{index}]"
        request = _object(value, request_path)
        _closed_keys(
            request,
            required={
                "soundbanks",
                "platforms",
                "skipLanguages",
                "writeToDisk",
                "rebuildSoundBanks",
                "clearAudioFileCache",
                "rebuildInitBank",
                "expected_events",
            },
            optional={"languages"},
            path=request_path,
        )
        soundbank_rows = _list(request["soundbanks"], f"{request_path}.soundbanks")
        if not soundbank_rows:
            raise EvalBundleV3Error(f"{request_path}.soundbanks must not be empty")
        soundbanks: list[str] = []
        soundbank_expectations: dict[str, str] = {}
        for bank_index, bank_value in enumerate(soundbank_rows):
            bank_path = f"{request_path}.soundbanks[{bank_index}]"
            bank = _object(bank_value, bank_path)
            _closed_keys(
                bank,
                required={"name", "artifact_expectation", "rebuild"},
                path=bank_path,
            )
            name = _string(bank["name"], f"{bank_path}.name")
            if name.casefold() == "init":
                raise EvalBundleV3Error(f"{bank_path}.name cannot explicitly request Init")
            if _boolean(bank["rebuild"], f"{bank_path}.rebuild") is not True:
                raise EvalBundleV3Error(
                    f"{bank_path}.rebuild must be true so the ACK-bound publisher "
                    "forces one observable target generation"
                )
            soundbanks.append(name)
            soundbank_expectations[name] = _parse_soundbank_artifact_expectation(
                bank["artifact_expectation"],
                f"{bank_path}.artifact_expectation",
            )
        _require_unique(
            tuple(value.casefold() for value in soundbanks),
            f"{request_path}.soundbanks",
        )
        platforms = _string_tuple(request["platforms"], f"{request_path}.platforms")
        if not platforms:
            raise EvalBundleV3Error(f"{request_path}.platforms must not be empty")
        _require_unique(
            tuple(value.casefold() for value in platforms),
            f"{request_path}.platforms",
        )
        skip_languages = _boolean(request["skipLanguages"], f"{request_path}.skipLanguages")
        if skip_languages:
            if "languages" in request:
                raise EvalBundleV3Error(
                    f"{request_path}.languages must be omitted when skipLanguages is true"
                )
            requested_languages: tuple[str, ...] = ()
        else:
            parsed_languages = _string_tuple(
                request.get("languages"),
                f"{request_path}.languages",
            )
            if not parsed_languages:
                raise EvalBundleV3Error(
                    f"{request_path}.languages must be explicit when skipLanguages is false"
                )
            _require_unique(
                tuple(value.casefold() for value in parsed_languages),
                f"{request_path}.languages",
            )
            requested_languages = parsed_languages
        for soundbank, expectation in soundbank_expectations.items():
            if skip_languages != (expectation == "nonlocalized"):
                raise EvalBundleV3Error(
                    f"{request_path}.soundbanks artifact_expectation for {soundbank!r} "
                    "disagrees with skipLanguages"
                )
            if soundbank in all_bank_scopes:
                raise EvalBundleV3Error(
                    f"{request_path}.soundbanks repeats a Bank across publisher requests"
                )
            all_bank_scopes[soundbank] = (
                expectation,
                platforms,
                requested_languages,
            )
        if _boolean(request["writeToDisk"], f"{request_path}.writeToDisk") is not True:
            raise EvalBundleV3Error(f"{request_path}.writeToDisk must be true")
        for field in ("rebuildSoundBanks", "clearAudioFileCache", "rebuildInitBank"):
            _boolean(request[field], f"{request_path}.{field}")
        if request["rebuildSoundBanks"] is not False:
            raise EvalBundleV3Error(
                f"{request_path}.rebuildSoundBanks must be false for the "
                "explicitly scoped topic publisher"
            )
        if request["rebuildInitBank"] is not False:
            raise EvalBundleV3Error(
                f"{request_path}.rebuildInitBank must remain false after the sealed Init precondition"
            )

        expected_events = _list(request["expected_events"], f"{request_path}.expected_events")
        expected_keys: list[str] = []
        for event_index, event_value in enumerate(expected_events):
            event_path = f"{request_path}.expected_events[{event_index}]"
            event = _object(event_value, event_path)
            _closed_keys(
                event,
                required={"soundbank", "platform", "language"},
                path=event_path,
            )
            event_soundbank = _string(event["soundbank"], f"{event_path}.soundbank")
            event_platform = _string(event["platform"], f"{event_path}.platform")
            event_language = _optional_string(event["language"], f"{event_path}.language")
            expected_keys.append(
                _soundbank_topic_event_key(event_soundbank, event_platform, event_language)
            )
        _require_unique(tuple(expected_keys), f"{request_path}.expected_events")
        cross_product = {
            _soundbank_topic_event_key(soundbank, platform, language)
            for soundbank in soundbanks
            for platform in platforms
            for language in (
                (None,)
                if soundbank_expectations[soundbank] == "nonlocalized"
                else requested_languages
                if soundbank_expectations[soundbank] == "localized"
                else (None, *requested_languages)
            )
        }
        if set(expected_keys) != cross_product:
            raise EvalBundleV3Error(
                f"{request_path}.expected_events must equal the explicit bank/platform/language scope"
            )
        all_event_keys.extend(expected_keys)
    _parse_soundbank_content_fixture(
        row["fixture_manifest"],
        f"{path}.fixture_manifest",
        bank_scopes=all_bank_scopes,
    )
    fixture_manifest = _object(
        row["fixture_manifest"],
        f"{path}.fixture_manifest",
    )
    for bank_index, bank_value in enumerate(
        _list(
            fixture_manifest["soundbanks"],
            f"{path}.fixture_manifest.soundbanks",
        )
    ):
        bank = _object(
            bank_value,
            f"{path}.fixture_manifest.soundbanks[{bank_index}]",
        )
        if bank["project_object_mode"] != "existing_soundbank":
            raise EvalBundleV3Error(
                f"{path}.fixture_manifest.soundbanks[{bank_index}].project_object_mode "
                "must be existing_soundbank for a generated topic publisher"
            )
    init_precondition = _object(
        fixture_manifest.get("init_precondition"),
        f"{path}.fixture_manifest.init_precondition",
    )
    _closed_keys(
        init_precondition,
        required=set(SOUNDBANK_TOPIC_INIT_PRECONDITION),
        path=f"{path}.fixture_manifest.init_precondition",
    )
    if init_precondition != SOUNDBANK_TOPIC_INIT_PRECONDITION:
        raise EvalBundleV3Error(
            f"{path}.fixture_manifest.init_precondition is not the reviewed Init proof"
        )
    _require_unique(tuple(all_event_keys), f"{path}.publisher_requests expected events")
    expected_count = _positive_int(
        row["expected_topic_event_count"],
        f"{path}.expected_topic_event_count",
    )
    if expected_count != len(all_event_keys):
        raise EvalBundleV3Error(
            f"{path}.expected_topic_event_count must equal the explicit event matrix"
        )
    if row["subscription_policy"] != "fresh_case_subscription_acknowledged_before_any_runner_owned_publish":
        raise EvalBundleV3Error(f"{path}.subscription_policy is not closed")
    if row["payload_policy"] != "soundbank_platform_required_language_optional_schema_exact":
        raise EvalBundleV3Error(f"{path}.payload_policy is not closed")
    if row["unexpected_event_policy"] != "bounded_capture_then_fail_case":
        raise EvalBundleV3Error(f"{path}.unexpected_event_policy is not closed")
    if row["artifact_policy"] != "case_owned_get_project_info_roots_with_pre_post_bounded_tree_sha256":
        raise EvalBundleV3Error(f"{path}.artifact_policy is not closed")
    _require_case_project_cleanup_policy(row, path)
    return dict(row)


def _soundbank_topic_event_key(
    soundbank: str,
    platform: str,
    language: str | None,
) -> str:
    return "|".join(
        (
            soundbank.casefold(),
            platform.casefold(),
            "<none>" if language is None else language.casefold(),
        )
    )


def _require_case_project_cleanup_policy(row: Mapping[str, Any], path: str) -> None:
    if row["cleanup_policy"] != "case_owned_project_copy_discard":
        raise EvalBundleV3Error(f"{path}.cleanup_policy must discard the case-owned project copy")


def _parse_visible_inputs(value: Any, path: str) -> tuple[VisibleInput, ...]:
    result: list[VisibleInput] = []
    for index, value in enumerate(_list(value, path)):
        row_path = f"{path}[{index}]"
        row = _object(value, row_path)
        _closed_keys(row, required={"name", "kind", "description"}, path=row_path)
        name = _string(row["name"], f"{row_path}.name")
        if not _VISIBLE_INPUT_RE.fullmatch(name):
            raise EvalBundleV3Error(f"{row_path}.name must be a lowercase prompt-input id")
        kind = _string(row["kind"], f"{row_path}.kind")
        if kind not in VISIBLE_INPUT_KINDS:
            raise EvalBundleV3Error(
                f"{row_path}.kind is not a closed visible-input kind: {kind!r}"
            )
        result.append(
            VisibleInput(
                name=name,
                kind=kind,
                description=_string(row["description"], f"{row_path}.description"),
            )
        )
    _require_unique(tuple(item.name for item in result), path)
    return tuple(result)


def _validate_prompt_template(
    prompt: str,
    visible_inputs: Sequence[VisibleInput],
    path: str,
) -> None:
    fields: list[str] = []
    try:
        parsed = tuple(string.Formatter().parse(prompt))
    except ValueError as exc:
        raise EvalBundleV3Error(f"{path} has invalid prompt-template braces") from exc
    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if not _VISIBLE_INPUT_RE.fullmatch(field_name):
            raise EvalBundleV3Error(f"{path} uses an invalid visible-input placeholder")
        if format_spec or conversion:
            raise EvalBundleV3Error(f"{path} placeholders cannot use formatting or conversion")
        fields.append(field_name)
    declared = {item.name for item in visible_inputs}
    referenced = set(fields)
    missing = sorted(referenced - declared)
    unused = sorted(declared - referenced)
    if missing or unused:
        raise EvalBundleV3Error(
            f"{path} visible-input closure mismatch; missing={missing}, unused={unused}"
        )


def _parse_trigger(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(
        row,
        required={"adapter", "publisher_api", "ownership_assertion"},
        path=path,
    )
    _adapter_id(row["adapter"], f"{path}.adapter")
    _string(row["publisher_api"], f"{path}.publisher_api")
    _string(row["ownership_assertion"], f"{path}.ownership_assertion")
    return dict(row)


def _parse_dispatches(value: Any, path: str) -> tuple[ExpectedDispatch, ...]:
    rows = _list(value, path)
    if not rows:
        raise EvalBundleV3Error(f"{path} must not be empty")
    result: list[ExpectedDispatch] = []
    for index, value in enumerate(rows):
        row_path = f"{path}[{index}]"
        row = _object(value, row_path)
        _closed_keys(row, required={"api", "count", "effect"}, path=row_path)
        result.append(
            ExpectedDispatch(
                api=_string(row["api"], f"{row_path}.api"),
                count=_nonnegative_int(row["count"], f"{row_path}.count"),
                effect=_string(row["effect"], f"{row_path}.effect"),
            )
        )
    _require_unique(tuple(item.api for item in result), f"{path} API ids")
    return tuple(result)


def _parse_assertions(value: Any, path: str) -> tuple[OracleAssertion, ...]:
    rows = _list(value, path)
    if not rows:
        raise EvalBundleV3Error(f"{path} must not be empty")
    result: list[OracleAssertion] = []
    for index, value in enumerate(rows):
        row_path = f"{path}[{index}]"
        row = _object(value, row_path)
        _closed_keys(
            row,
            required={"phase", "adapter", "subject_api", "expectation"},
            path=row_path,
        )
        phase = _string(row["phase"], f"{row_path}.phase")
        if phase not in ASSERTION_PHASES:
            raise EvalBundleV3Error(f"{row_path}.phase is not a closed assertion phase")
        result.append(
            OracleAssertion(
                phase=phase,
                adapter=_adapter_id(row["adapter"], f"{row_path}.adapter"),
                subject_api=_string(row["subject_api"], f"{row_path}.subject_api"),
                expectation=_string(row["expectation"], f"{row_path}.expectation"),
            )
        )
    return tuple(result)


def _parse_cleanup(value: Any, path: str) -> Mapping[str, Any]:
    row = _object(value, path)
    _closed_keys(row, required={"adapter", "postconditions"}, path=path)
    _adapter_id(row["adapter"], f"{path}.adapter")
    postconditions = frozenset(_string_tuple(row["postconditions"], f"{path}.postconditions"))
    missing = sorted(REQUIRED_CLEANUP_POSTCONDITIONS - postconditions)
    if missing:
        raise EvalBundleV3Error(f"{path}.postconditions is missing {missing}")
    return dict(row)


def _lint_natural_prompt(value: str, path: str, *, minimum_length: int = 24) -> None:
    if len(value.strip()) < minimum_length:
        raise EvalBundleV3Error(f"{path} is too short to represent a substantive user scenario")
    for pattern in _PROMPT_FORBIDDEN:
        if pattern.search(value):
            raise EvalBundleV3Error(
                f"{path} contains test-harness coaching forbidden from natural user prompts: {pattern.pattern!r}"
            )


def _safe_child(base: Path, value: Any, path: str) -> Path:
    relative = Path(_string(value, path))
    if relative.is_absolute() or ".." in relative.parts:
        raise EvalBundleV3Error(f"{path} must be a contained relative path")
    try:
        resolved = (base / relative).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise EvalBundleV3Error(f"{path} does not resolve to a bundled file: {relative}") from exc
    try:
        resolved.relative_to(base.resolve(strict=True))
    except ValueError as exc:
        raise EvalBundleV3Error(f"{path} escapes the eval bundle root") from exc
    if not resolved.is_file():
        raise EvalBundleV3Error(f"{path} must resolve to a regular file")
    return resolved


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalBundleV3Error(f"cannot load {label} {path}: {exc}") from exc
    return _object(payload, label)


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalBundleV3Error(f"{path} must be a JSON object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvalBundleV3Error(f"{path} must be a JSON array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalBundleV3Error(f"{path} must be a non-empty string")
    return value


def _optional_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise EvalBundleV3Error(f"{path} must be a boolean")
    return value


def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{path}[{index}]")
        for index, item in enumerate(_list(value, path))
    )


def _version_tuple(value: Any, path: str) -> tuple[str, ...]:
    versions = _string_tuple(value, path)
    if not versions or len(versions) != len(set(versions)):
        raise EvalBundleV3Error(f"{path} must be a non-empty unique version list")
    expected_order = tuple(version for version in SUPPORTED_VERSIONS if version in versions)
    if versions != expected_order:
        raise EvalBundleV3Error(
            f"{path} must be a supported subsequence in order {SUPPORTED_VERSIONS!r}"
        )
    return versions


def _adapter_id(value: Any, path: str) -> str:
    result = _string(value, path)
    if not _ADAPTER_RE.fullmatch(result):
        raise EvalBundleV3Error(f"{path} must be a lowercase adapter identifier")
    return result


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvalBundleV3Error(f"{path} must be a positive integer")
    return value


def _nonnegative_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvalBundleV3Error(f"{path} must be a non-negative integer")
    return value


def _closed_keys(
    row: Mapping[str, Any],
    *,
    required: set[str],
    path: str,
    optional: set[str] | None = None,
) -> None:
    keys = set(row)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - (optional or set()))
    if missing or unknown:
        raise EvalBundleV3Error(f"{path} fields mismatch; missing={missing}, unknown={unknown}")


def _require_unique(values: tuple[str, ...], path: str) -> None:
    if len(values) != len(set(values)):
        raise EvalBundleV3Error(f"{path} contains duplicate values")


__all__ = [
    "CoverageRow",
    "EvalBundleV3",
    "EvalBundleV3Error",
    "ExpectedDispatch",
    "OfflineScenario",
    "OnlineScenario",
    "OracleAssertion",
    "VisibleInput",
    "load_eval_bundle_v3",
]

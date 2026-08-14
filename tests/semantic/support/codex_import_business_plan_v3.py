"""Closed typed business plans for ordinary and compound import scenarios.

The plan is compiled after the runner has materialized its WAV/TSV inputs and
prepared the hidden before snapshot, but before a Codex task is created.  It is
not a second fixture format: every request, file proof, row contract and delta
rule is projected from the runner-owned import dataclasses.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from wwise_waapi.operation_import import (
    ImportContractError,
    normalize_originals_subfolder,
)

from tests.semantic.support.codex_archive_paths import (
    ArchiveRelativePathError,
    archive_absolute_has_relative_suffix,
    parse_archive_absolute_path,
    parse_archive_relative_path,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    StructuredRefusal,
    V3GatewayProtocol,
    build_audio_import_composer_protocol,
    build_metadata_transaction_protocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_filesystem_security import (
    CodexFileSecurityError,
    read_bounded_exclusive_regular_file,
)
from tests.semantic.support.codex_import_assets_v3 import (
    ImportAssetMaterializationError,
    MaterializedImportCase,
    bound_import_metadata_tokens,
    canonical_wwise_language,
    compound_dynamic_modes_by_row,
)
from tests.semantic.support.codex_import_runtime_v3 import (
    IMPORT_APIS,
    MAX_FILE_BYTES,
    SUPPORTED_VERSION,
    import_runtime_version_is_reviewed,
    ImportCompoundRuntimeSnapshot,
    ImportRuntimePlan,
    ImportRuntimeSnapshot,
    _object_type_matches,
)
from tests.semantic.support.codex_gateway_broker import MetadataTokenProjection
from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol
from tests.semantic.support.codex_version_layout_v3 import (
    CodexVersionLayoutError,
    get_codex_version_layout_v3,
)


IMPORT_BUSINESS_PLAN_SCHEMA = "waapi-skill.import-business-plan/v1"
IMPORT_FIXTURE_KIND = "import_materialized_runtime_v1"
COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA = "waapi-skill.import-business-plan/v2"
COMPOUND_IMPORT_FIXTURE_KIND = "import_compound_materialized_runtime_v2"
_REFUSAL_CODES = {"O22-AUDIO-TAB-01": "INPUT_FILE_NOT_FOUND"}
_SHA256 = set("0123456789abcdef")
_GUID_POLICIES = frozenset({"remain_absent_no_guid", "preserve_existing_guid", "preserve_shared_existing_guid", "replace_with_distinct_guid", "create_new_unique_guid", "create_once_then_preserve_shared_guid"})
_IMPORT_OPERATIONS = frozenset({"createNew", "useExisting", "replaceExisting"})
_GUID_RE = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
_ASSERTION_IDS = ("import.request.exact", "import.rows.typed", "import.live.before", "import.files.fingerprinted", "import.delta.closed")
_COMPOUND_ASSERTION_IDS = (
    *_ASSERTION_IDS,
    "import.metadata.live_bound",
    "import.dynamic_fields.exact",
    "import.reference_bus.local_and_cleanup",
)


class ImportBusinessPlanError(ValueError):
    """The sealed import plan is incomplete, mutable, or cross-bound."""


@dataclass(frozen=True, slots=True)
class ImportBusinessPlanSections:
    """The six family fields consumed by the common plan writer."""

    fixture_spec: Mapping[str, Any]
    payload_bindings: Mapping[str, Any]
    assertion_ids: tuple[str, ...]
    static_expectation: Mapping[str, Any]
    live_binding: Mapping[str, Any]
    delta_rules: tuple[Mapping[str, Any], ...]

    def writer_kwargs(self) -> dict[str, Any]:
        return {
            "fixture_spec": _plain(self.fixture_spec),
            "payload_bindings": _plain(self.payload_bindings),
            "assertion_ids": list(self.assertion_ids),
            "static_expectation": _plain(self.static_expectation),
            "live_binding": _plain(self.live_binding),
            "delta_rules": [_plain(rule) for rule in self.delta_rules],
        }


def compile_import_business_plan(
    scenario: Any,
    materialized: MaterializedImportCase,
    plan: ImportRuntimePlan,
    before: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot,
    protocol: V3GatewayProtocol,
) -> ImportBusinessPlanSections:
    """Compile the one immutable import business plan from trusted state."""

    _validate_runtime_inputs(scenario, materialized, plan, before, protocol)
    static = _static(scenario, materialized, plan, protocol)
    live = _live(plan, before, materialized)
    rules = _rules(static, live)
    primary, verification = _partition(plan, protocol)
    return _sections(static, live, rules, primary, verification)


def validate_import_business_plan(
    sections: ImportBusinessPlanSections,
    scenario: Any,
    materialized: MaterializedImportCase,
    plan: ImportRuntimePlan,
    before: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot,
    protocol: V3GatewayProtocol,
    *,
    verify_files: bool = False,
) -> None:
    """Recompute every section from runner-owned live inputs."""

    expected = compile_import_business_plan(scenario, materialized, plan, before, protocol)
    if not isinstance(sections, ImportBusinessPlanSections) or sections.writer_kwargs() != expected.writer_kwargs():
        raise ImportBusinessPlanError("import plan differs from independently recomputed runner inputs")
    if verify_files:
        _validate_files(sections.live_binding["input_files"], verify_files=True)


def parse_import_business_plan_sections(plan_payload: Mapping[str, Any]) -> ImportBusinessPlanSections:
    """Parse exactly the six typed fields from a persisted common plan."""

    required = {"fixture_spec", "payload_bindings", "assertion_ids", "static_expectation", "live_binding", "delta_rules"}
    if not isinstance(plan_payload, Mapping) or not required.issubset(plan_payload):
        raise ImportBusinessPlanError("import business plan omits typed sections")
    fixture, bindings = plan_payload["fixture_spec"], plan_payload["payload_bindings"]
    static, live = plan_payload["static_expectation"], plan_payload["live_binding"]
    assertions, rules = plan_payload["assertion_ids"], plan_payload["delta_rules"]
    if not all(isinstance(value, Mapping) for value in (fixture, bindings, static, live)):
        raise ImportBusinessPlanError("import typed mapping section is invalid")
    if not isinstance(assertions, list) or not isinstance(rules, list) or any(not isinstance(item, Mapping) for item in rules):
        raise ImportBusinessPlanError("import typed sequence section is invalid")
    result = ImportBusinessPlanSections(
        MappingProxyType(_plain(fixture)), MappingProxyType(_plain(bindings)),
        tuple(_plain(assertions)), MappingProxyType(_plain(static)),
        MappingProxyType(_plain(live)), tuple(MappingProxyType(_plain(item)) for item in rules),
    )
    _validate_shape(result)
    return result


def validate_import_business_plan_archive(
    plan_payload: Mapping[str, Any] | ImportBusinessPlanSections,
    *,
    scenario: Any,
    protocol: V3GatewayProtocol,
    verify_files: bool = False,
) -> ImportBusinessPlanSections:
    """Validate an archived plan using only plan payload, scenario and protocol.

    This intentionally does not require a PreparedImportRuntime: the archive
    contains the before snapshot and the file manifest needed for later audit.
    """

    sections = plan_payload if isinstance(plan_payload, ImportBusinessPlanSections) else parse_import_business_plan_sections(plan_payload)
    _validate_shape(sections)
    static, live = sections.static_expectation, sections.live_binding
    _validate_static_archive(static, live, scenario, protocol)
    _validate_live_archive(live, static, verify_files=verify_files)
    expected_rules = _rules(static, live)
    if [_plain(value) for value in sections.delta_rules] != expected_rules:
        raise ImportBusinessPlanError("archived import delta rules differ from sealed inputs")
    count = static["primary_dispatch_count"]
    names = [item["name"] for item in serialize_protocol(protocol)["steps"]]
    expected_bindings = {
        "primary_steps": [] if count == 0 else [f"tx{index:02d}.execute" for index in range(1, count + 1)],
        "verification_steps": names if count == 0 else [name for name in names if not name.endswith(".execute")],
    }
    if _plain(sections.payload_bindings) != expected_bindings:
        raise ImportBusinessPlanError("archived import primary/verification partition drifted")
    fixture = {"static": _plain(static), "live": _plain(live)}
    fixture_kind = (
        COMPOUND_IMPORT_FIXTURE_KIND
        if static["family_schema_version"]
        == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
        else IMPORT_FIXTURE_KIND
    )
    if _plain(sections.fixture_spec) != {"kind": fixture_kind, "sha256": _hash(fixture)}:
        raise ImportBusinessPlanError("archived import fixture digest is misbound")
    return sections


def validate_import_archived_verification(
    sections: ImportBusinessPlanSections,
    verification: Mapping[str, Any],
    *,
    refusal_error_code: str | None = None,
) -> None:
    """Join an archived runner verification JSON to the sealed import plan."""

    _validate_shape(sections)
    evidence = verification.get("evidence", verification) if isinstance(verification, Mapping) else None
    # Campaign archives wrap the runtime dataclass in heavy-oracle/v2.  The
    # wrapper is runner evidence, while this family validator owns its exact
    # verification payload.
    outer_error_code = verification.get("refusal_error_code") if isinstance(verification, Mapping) else None
    if isinstance(evidence, Mapping) and isinstance(evidence.get("verification"), Mapping):
        outer_error_code = evidence.get("refusal_error_code", outer_error_code)
        evidence = evidence["verification"]
    if not isinstance(evidence, Mapping):
        raise ImportBusinessPlanError("import verification evidence is not an object")
    required = {"scenario_id", "phase", "passed", "failures", "before", "after"}
    if set(evidence) - (required | {"error_code", "refusal_error_code"}) or not required.issubset(evidence):
        raise ImportBusinessPlanError("import verification schema is not closed")
    static, live = sections.static_expectation, sections.live_binding
    if evidence["scenario_id"] != static["scenario_id"] or evidence["before"] != live["before_snapshot"]:
        raise ImportBusinessPlanError("import verification before snapshot is not the sealed baseline")
    if evidence["passed"] is not True or evidence["failures"] != []:
        raise ImportBusinessPlanError("import verification is not a passed independent result")
    if static["primary_dispatch_count"] == 0:
        if evidence["phase"] != "zero_dispatch" or evidence["after"] != evidence["before"]:
            raise ImportBusinessPlanError("zero-dispatch refusal must prove before equals after")
        # ImportRuntimeVerification deliberately records only business state.
        # The gateway preview error is runner/broker evidence and must be passed
        # here explicitly (or placed on the heavy-oracle wrapper), never faked
        # as a field on the runtime dataclass.
        code = refusal_error_code or outer_error_code or evidence.get("error_code") or evidence.get("refusal_error_code")
        if code != static["refusal_error_code"]:
            raise ImportBusinessPlanError("zero-dispatch refusal error is not exact")
        return
    if evidence["phase"] != "after_execution":
        raise ImportBusinessPlanError("executed import verification has the wrong phase")
    _validate_after(static, live, evidence["after"])


def _validate_runtime_inputs(
    scenario: Any,
    materialized: MaterializedImportCase,
    plan: ImportRuntimePlan,
    before: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot,
    protocol: V3GatewayProtocol,
) -> None:
    if (
        not isinstance(materialized, MaterializedImportCase)
        or not isinstance(plan, ImportRuntimePlan)
        or not isinstance(
            before,
            (ImportRuntimeSnapshot, ImportCompoundRuntimeSnapshot),
        )
    ):
        raise ImportBusinessPlanError("import compiler requires materialized case, runtime plan and before snapshot")
    compound = plan.metadata_binding is not None
    if (
        plan.api not in IMPORT_APIS
        or not import_runtime_version_is_reviewed(
            plan.scenario_id,
            plan.version,
            compound=compound,
        )
        or getattr(scenario, "id", None) != plan.scenario_id
        or getattr(scenario, "api", None) != plan.api
        or tuple(getattr(scenario, "versions", ())) != (plan.version,)
    ):
        raise ImportBusinessPlanError("import scenario/runtime identity is misbound")
    _validate_request_contract_versions(
        plan.operation_requests,
        api=plan.api,
        version=plan.version,
    )
    if compound != isinstance(before, ImportCompoundRuntimeSnapshot):
        raise ImportBusinessPlanError(
            "compound import plan/snapshot shape is misbound"
        )
    if compound != (materialized.metadata_binding is not None):
        raise ImportBusinessPlanError(
            "compound import plan/materialized metadata binding is misbound"
        )
    if materialized.scenario_id != plan.scenario_id or materialized.expected_primary_dispatch_count != plan.expected_primary_dispatch_count:
        raise ImportBusinessPlanError("materialized import identity or dispatch count drifted")
    if tuple(materialized.operation_requests) != tuple(plan.operation_requests) or before.scenario_id != plan.scenario_id:
        raise ImportBusinessPlanError("import requests or before snapshot are misbound")
    _validate_files(_file_manifest(materialized), verify_files=True)
    _validate_expected_protocol(plan, protocol, materialized)


def _validate_expected_protocol(
    plan: ImportRuntimePlan,
    protocol: V3GatewayProtocol,
    materialized: MaterializedImportCase | None = None,
) -> None:
    refusal = _REFUSAL_CODES.get(plan.scenario_id)
    if plan.metadata_binding is not None:
        if materialized is None:
            raise ImportBusinessPlanError(
                "compound protocol validation requires the bound materialized case"
            )
        expected = build_metadata_transaction_protocol(
            plan.operation_requests,
            object_type="Sound",
            metadata_queries=materialized.metadata_queries,
            required_tokens=bound_import_metadata_tokens(materialized),
            expected_required_token_projection=_metadata_projection_from_binding(
                plan.metadata_binding,
                required_tokens=bound_import_metadata_tokens(materialized),
            ),
            equivalence=(
                "audio_import_v1"
                if plan.api == "ak.wwise.core.audio.import"
                else "audio_import_tab_v1"
            ),
        )
    else:
        expected = (
            build_audio_import_composer_protocol(plan.operation_requests[0])
            if plan.api == "ak.wwise.core.audio.import"
            else build_transaction_protocol(
                plan.operation_requests,
                refusal=StructuredRefusal(refusal) if refusal else None,
            )
        )
    if _plain(serialize_protocol(protocol)) != _plain(serialize_protocol(expected)):
        raise ImportBusinessPlanError("import protocol does not exactly bind sealed requests and transaction order")


def _static(scenario: Any, materialized: MaterializedImportCase, plan: ImportRuntimePlan, protocol: V3GatewayProtocol) -> dict[str, Any]:
    requests = _plain(plan.operation_requests)
    compound = plan.metadata_binding is not None
    rows = []
    request_ops = _operations_by_row(plan, materialized)
    for row in plan.rows:
        contract = {
            "row_key": row.row_key, "target_path": row.target_path, "object_type": row.object_type,
            "language": row.language, "import_operation": request_ops[row.row_key], "guid_policy": row.guid_policy,
            "event": None if row.event_path is None else {"path": row.event_path, "action": row.event_action},
            "source_key": row.source_file.key, "pre_state_existence": row.pre_state_existence,
            "pre_state_guid_key": row.pre_state_guid_key,
            "originals_subfolder": row.originals_subfolder,
        }
        if compound:
            raw = next(
                (
                    item
                    for item in materialized.expected_rows
                    if item.get("row_key") == row.row_key
                ),
                None,
            )
            if not isinstance(raw, Mapping):
                raise ImportBusinessPlanError(
                    f"compound row {row.row_key!r} is absent from materialized expectations"
                )
            contract["dynamic_properties"] = _plain(row.expected_properties)
            contract["dynamic_references"] = _plain(row.expected_references)
            contract["preserve_property_tokens"] = list(
                row.preserve_property_tokens
            )
            contract["preserve_reference_tokens"] = list(
                row.preserve_reference_tokens
            )
            contract["media_kind"] = raw.get("compound_media_kind")
            contract["dynamic_mode"] = raw.get("compound_dynamic_mode")
        rows.append(contract)
    result = {
        "family_schema_version": (
            COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
            if compound
            else IMPORT_BUSINESS_PLAN_SCHEMA
        ), "family": "audio_import",
        "scenario_id": plan.scenario_id, "api": plan.api, "version": plan.version,
        "primary_dispatch_count": plan.expected_primary_dispatch_count,
        "operation_requests": requests, "operation_requests_sha256": _hash(requests),
        "protocol_sha256": _hash(serialize_protocol(protocol)), "row_contracts": rows,
        "refusal_error_code": _REFUSAL_CODES.get(plan.scenario_id),
        "scenario_api": getattr(scenario, "api", None),
    }
    if compound:
        binding = _plain(plan.metadata_binding)
        queries = list(materialized.metadata_queries)
        tokens = list(bound_import_metadata_tokens(materialized))
        result.update(
            {
                "metadata_binding": binding,
                "metadata_binding_sha256": _hash(binding),
                "metadata_queries": queries,
                "dynamic_tokens": tokens,
                "metadata_projection": [
                    item.as_dict()
                    for item in _metadata_projection_from_binding(
                        plan.metadata_binding,
                        required_tokens=tokens,
                    )
                ],
            }
        )
    return result


def _operations_by_row(plan: ImportRuntimePlan, materialized: MaterializedImportCase) -> dict[str, str]:
    result: dict[str, str] = {}
    if plan.api == "ak.wwise.core.audio.import":
        operation = plan.operation_requests[0]["arguments"].get("import_operation")
        if not isinstance(operation, str):
            raise ImportBusinessPlanError("audio.import request lacks import_operation")
        result = {row.row_key: operation for row in plan.rows}
    else:
        tables = {str(request["arguments"].get("import_file")): request["arguments"].get("import_operation") for request in plan.operation_requests}
        raw_by_key = {str(row.get("row_key")): row for row in materialized.expected_rows}
        for row in plan.rows:
            raw = raw_by_key.get(row.row_key)
            if raw is None:
                raise ImportBusinessPlanError("runtime row is absent from materialized rows")
            table = next((item.path for item in materialized.tab_files if item.key == raw.get("tsv_name")), None)
            operation = tables.get(str(table))
            if not isinstance(operation, str):
                raise ImportBusinessPlanError("tab import request does not close every row operation")
            result[row.row_key] = operation
    return result


def _live(
    plan: ImportRuntimePlan,
    before: ImportRuntimeSnapshot | ImportCompoundRuntimeSnapshot,
    materialized: MaterializedImportCase,
) -> dict[str, Any]:
    snapshot = _plain(before)
    files = _file_manifest(materialized)
    compound = plan.metadata_binding is not None
    result = {
        "family_schema_version": (
            COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
            if compound
            else IMPORT_BUSINESS_PLAN_SCHEMA
        ),
        "before_snapshot": snapshot, "before_snapshot_sha256": _hash(snapshot),
        "input_files": files, "input_files_sha256": _hash(files),
        "owned_paths": {"asset_root": str(plan.asset_root), "parents": [item.path for item in plan.parents], "events": list(plan.event_paths)},
    }
    if compound:
        if not isinstance(before, ImportCompoundRuntimeSnapshot):
            raise ImportBusinessPlanError(
                "compound plan requires a compound before snapshot"
            )
        reference_fixtures = {
            "main_bus": _plain(before.main_bus),
            "targets": _plain(before.reference_fixtures),
        }
        cleanup_boundaries = {
            "order": ["import_roots", "reference_busses", "asset_root"],
            "import_root_paths": [
                item.path
                for item in plan.parents
                if item.parent_path in {plan.actor_dwu, plan.events_dwu}
            ],
            "reference_bus_paths": [
                item.path for item in plan.reference_fixtures
            ],
            "asset_root": str(plan.asset_root),
        }
        result.update(
            {
                "reference_fixtures": reference_fixtures,
                "reference_fixtures_sha256": _hash(reference_fixtures),
                "cleanup_boundaries": cleanup_boundaries,
            }
        )
    return result


def _file_manifest(materialized: MaterializedImportCase) -> list[dict[str, Any]]:
    values = []
    for category, items in (("wav", materialized.source_files), ("pre_state_wav", materialized.pre_state_files), ("tsv", materialized.tab_files)):
        for item in items:
            values.append({"category": category, "key": item.key, "path": str(item.path), "present": item.present, "size": item.size, "sha256": item.sha256})
    return sorted(values, key=lambda item: (item["category"], item["key"]))


def _rules(static: Mapping[str, Any], live: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = static["row_contracts"]
    creates = [row["row_key"] for row in rows if row["guid_policy"] in {"create_new_unique_guid", "create_once_then_preserve_shared_guid"}]
    uses = [row["row_key"] for row in rows if row["guid_policy"] in {"preserve_existing_guid", "preserve_shared_existing_guid"}]
    replaces = [row["row_key"] for row in rows if row["guid_policy"] == "replace_with_distinct_guid"]
    rules = [
        {"kind": "import_exact_requests_v1", "requests_sha256": static["operation_requests_sha256"], "protocol_sha256": static["protocol_sha256"], "ordered_transaction_count": static["primary_dispatch_count"]},
        {"kind": "import_row_delta_v1", "subject": "target/type/language/importOperation/GUID", "rows": rows, "create_guid_rows": creates, "use_existing_guid_rows": uses, "replace_guid_rows": replaces},
        {"kind": "import_event_action_delta_v1", "subject": "event Play action", "events": [row["event"] for row in rows if row["event"] is not None]},
        {"kind": "import_owned_paths_v1", "subject": "scenario-owned paths", "owned_paths": live["owned_paths"]},
        {"kind": "import_immutable_inputs_v1", "subject": "WAV/TSV regular-file size sha256", "before_snapshot_sha256": live["before_snapshot_sha256"], "input_files_sha256": live["input_files_sha256"]},
        {"kind": "import_zero_dispatch_refusal_v1", "subject": "before_equals_after_and_exact_error", "enabled": static["primary_dispatch_count"] == 0, "error_code": static["refusal_error_code"]},
    ]
    if static["family_schema_version"] == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA:
        rules.extend(
            [
                {
                    "kind": "import_live_metadata_binding_v1",
                    "metadata_binding_sha256": static["metadata_binding_sha256"],
                    "queries": static["metadata_queries"],
                    "exact_dynamic_tokens": static["dynamic_tokens"],
                },
                {
                    "kind": "import_dynamic_readback_v1",
                    "subject": "@property exact values, @reference exact GUIDs, and activation dependencies",
                    "rows": [
                        {
                            "row_key": row["row_key"],
                            "properties": row["dynamic_properties"],
                            "references": row["dynamic_references"],
                            "preserve_property_tokens": row[
                                "preserve_property_tokens"
                            ],
                            "preserve_reference_tokens": row[
                                "preserve_reference_tokens"
                            ],
                        }
                        for row in rows
                    ],
                },
                {
                    "kind": "import_reference_bus_cleanup_v1",
                    "reference_fixtures_sha256": live[
                        "reference_fixtures_sha256"
                    ],
                    "cleanup_boundaries": live["cleanup_boundaries"],
                },
            ]
        )
    return rules


def _partition(plan: ImportRuntimePlan, protocol: V3GatewayProtocol) -> tuple[list[str], list[str]]:
    names = [item["name"] for item in serialize_protocol(protocol)["steps"]]
    return ([] if plan.expected_primary_dispatch_count == 0 else [f"tx{item:02d}.execute" for item in range(1, plan.expected_primary_dispatch_count + 1)], names if plan.expected_primary_dispatch_count == 0 else [item for item in names if not item.endswith(".execute")])


def _sections(static: Mapping[str, Any], live: Mapping[str, Any], rules: Sequence[Mapping[str, Any]], primary: Sequence[str], verification: Sequence[str]) -> ImportBusinessPlanSections:
    fixture = {"static": _plain(static), "live": _plain(live)}
    return ImportBusinessPlanSections(
        MappingProxyType(
            {
                "kind": (
                    COMPOUND_IMPORT_FIXTURE_KIND
                    if static["family_schema_version"]
                    == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
                    else IMPORT_FIXTURE_KIND
                ),
                "sha256": _hash(fixture),
            }
        ),
        MappingProxyType({"primary_steps": list(primary), "verification_steps": list(verification)}),
        (
            _COMPOUND_ASSERTION_IDS
            if static["family_schema_version"]
            == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
            else _ASSERTION_IDS
        ),
        MappingProxyType(_plain(static)), MappingProxyType(_plain(live)), tuple(MappingProxyType(_plain(item)) for item in rules),
    )


def _validate_shape(sections: ImportBusinessPlanSections) -> None:
    if not isinstance(sections, ImportBusinessPlanSections):
        raise ImportBusinessPlanError("import sections have the wrong type")
    if (
        set(sections.fixture_spec) != {"kind", "sha256"}
        or sections.fixture_spec.get("kind")
        not in {IMPORT_FIXTURE_KIND, COMPOUND_IMPORT_FIXTURE_KIND}
        or not _sha(sections.fixture_spec.get("sha256"))
    ):
        raise ImportBusinessPlanError("import fixture schema is not closed")
    if set(sections.payload_bindings) != {"primary_steps", "verification_steps"} or any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in sections.payload_bindings.values()):
        raise ImportBusinessPlanError("import payload binding schema is not closed")
    if not sections.assertion_ids or any(not isinstance(item, str) or not item for item in sections.assertion_ids):
        raise ImportBusinessPlanError("import assertion ids are invalid")
    static, live = sections.static_expectation, sections.live_binding
    compound = (
        static.get("family_schema_version")
        == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
    )
    expected_assertions = _COMPOUND_ASSERTION_IDS if compound else _ASSERTION_IDS
    if tuple(sections.assertion_ids) != expected_assertions:
        raise ImportBusinessPlanError("import assertion ids are not the fixed closed tuple")
    static_keys = {"family_schema_version", "family", "scenario_id", "api", "version", "primary_dispatch_count", "operation_requests", "operation_requests_sha256", "protocol_sha256", "row_contracts", "refusal_error_code", "scenario_api"}
    live_keys = {"family_schema_version", "before_snapshot", "before_snapshot_sha256", "input_files", "input_files_sha256", "owned_paths"}
    if compound:
        static_keys |= {
            "metadata_binding",
            "metadata_binding_sha256",
            "metadata_queries",
            "dynamic_tokens",
            "metadata_projection",
        }
        live_keys |= {
            "reference_fixtures",
            "reference_fixtures_sha256",
            "cleanup_boundaries",
        }
    expected_schema = (
        COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
        if compound
        else IMPORT_BUSINESS_PLAN_SCHEMA
    )
    expected_kind = (
        COMPOUND_IMPORT_FIXTURE_KIND if compound else IMPORT_FIXTURE_KIND
    )
    if (
        set(static) != static_keys
        or set(live) != live_keys
        or static.get("family_schema_version") != expected_schema
        or live.get("family_schema_version") != expected_schema
        or sections.fixture_spec.get("kind") != expected_kind
    ):
        raise ImportBusinessPlanError("import static/live schema is not closed")


def _validate_static_archive(static: Mapping[str, Any], live: Mapping[str, Any], scenario: Any, protocol: V3GatewayProtocol) -> None:
    compound = (
        static["family_schema_version"]
        == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
    )
    if (
        static["api"] not in IMPORT_APIS
        or not import_runtime_version_is_reviewed(
            static["scenario_id"],
            static["version"],
            compound=compound,
        )
        or static["family"] != "audio_import"
        or static["scenario_id"] != getattr(scenario, "id", None)
        or static["api"] != getattr(scenario, "api", None)
        or tuple(getattr(scenario, "versions", ())) != (static["version"],)
        or static["scenario_api"] != static["api"]
    ):
        raise ImportBusinessPlanError("archived import scenario identity is misbound")
    count = static["primary_dispatch_count"]
    if type(count) is not int or count < 0 or count != getattr(getattr(scenario, "primary_dispatch", None), "count", None):
        raise ImportBusinessPlanError("archived import dispatch count is invalid")
    requests = static["operation_requests"]
    if not isinstance(requests, list) or static["operation_requests_sha256"] != _hash(requests):
        raise ImportBusinessPlanError("archived import requests digest is invalid")
    _validate_request_contract_versions(
        requests,
        api=static["api"],
        version=static["version"],
    )
    if count == 0 and (len(requests) != 1 or static["refusal_error_code"] != _REFUSAL_CODES.get(static["scenario_id"])):
        raise ImportBusinessPlanError("archived zero-dispatch refusal is not closed")
    if count > 0 and (len(requests) != count or static["refusal_error_code"] is not None):
        raise ImportBusinessPlanError("archived import request count is invalid")
    if compound:
        if (
            not isinstance(static["metadata_queries"], list)
            or not isinstance(static["dynamic_tokens"], list)
            or not static["metadata_queries"]
            or not static["dynamic_tokens"]
        ):
            raise ImportBusinessPlanError(
                "archived compound metadata query/token evidence is invalid"
            )
        binding = static["metadata_binding"]
        if (
            not isinstance(binding, Mapping)
            or static["metadata_binding_sha256"] != _hash(binding)
        ):
            raise ImportBusinessPlanError(
                "archived compound metadata binding digest is invalid"
            )
        _validate_archived_metadata_binding(
            binding,
            dynamic_tokens=static["dynamic_tokens"],
            reference_fixtures=live["reference_fixtures"],
        )
        projection = _metadata_projection_from_binding(
            binding,
            required_tokens=static["dynamic_tokens"],
        )
        if static["metadata_projection"] != [
            item.as_dict() for item in projection
        ]:
            raise ImportBusinessPlanError(
                "archived compound metadata projection drifted"
            )
        expected = build_metadata_transaction_protocol(
            requests,
            object_type="Sound",
            metadata_queries=static["metadata_queries"],
            required_tokens=static["dynamic_tokens"],
            expected_required_token_projection=projection,
            equivalence=(
                "audio_import_v1"
                if static["api"] == "ak.wwise.core.audio.import"
                else "audio_import_tab_v1"
            ),
        )
    else:
        expected = (
            build_audio_import_composer_protocol(requests[0])
            if static["api"] == "ak.wwise.core.audio.import"
            else build_transaction_protocol(
                requests,
                refusal=(
                    StructuredRefusal(static["refusal_error_code"])
                    if count == 0
                    else None
                ),
            )
        )
    if _plain(serialize_protocol(protocol)) != _plain(serialize_protocol(expected)) or static["protocol_sha256"] != _hash(serialize_protocol(protocol)):
        raise ImportBusinessPlanError("archived import protocol/request order drifted")
    if not isinstance(static["row_contracts"], list) or not static["row_contracts"] or len({row.get("row_key") for row in static["row_contracts"] if isinstance(row, Mapping)}) != len(static["row_contracts"]):
        raise ImportBusinessPlanError("archived import row contracts are invalid")
    legacy_row_keys = {"row_key", "target_path", "object_type", "language", "import_operation", "guid_policy", "event", "source_key", "pre_state_existence", "pre_state_guid_key", "originals_subfolder"}
    compound_row_keys = legacy_row_keys | {
        "dynamic_properties",
        "dynamic_references",
        "preserve_property_tokens",
        "preserve_reference_tokens",
        "media_kind",
        "dynamic_mode",
    }
    for row in static["row_contracts"]:
        if not isinstance(row, Mapping) or set(row) != (compound_row_keys if compound else legacy_row_keys) or not all(isinstance(row[key], str) for key in ("row_key", "target_path", "object_type", "language", "import_operation", "guid_policy", "source_key", "pre_state_existence")) or not (row["originals_subfolder"] is None or isinstance(row["originals_subfolder"], str)):
            raise ImportBusinessPlanError("archived import row contract shape is invalid")
        if row["guid_policy"] not in _GUID_POLICIES or row["import_operation"] not in _IMPORT_OPERATIONS:
            raise ImportBusinessPlanError("archived import GUID policy or operation is unsupported")
        if row["pre_state_existence"] not in {"absent", "existing"}:
            raise ImportBusinessPlanError("archived import pre-state is unsupported")
        if row["guid_policy"] in {"preserve_existing_guid", "preserve_shared_existing_guid", "replace_with_distinct_guid"} and row["pre_state_existence"] != "existing":
            raise ImportBusinessPlanError("archived import existing-GUID policy lacks baseline")
        if row["guid_policy"] in {"remain_absent_no_guid", "create_new_unique_guid", "create_once_then_preserve_shared_guid"} and row["pre_state_existence"] != "absent":
            raise ImportBusinessPlanError("archived import create/refusal policy has baseline")
        event = row["event"]
        if event is not None and (not isinstance(event, Mapping) or set(event) != {"path", "action"} or event.get("action") != "Play" or not isinstance(event.get("path"), str)):
            raise ImportBusinessPlanError("archived import event action is not one Play target")
        if compound:
            _validate_archived_dynamic_row(
                row,
                api=static["api"],
                binding=static["metadata_binding"],
                reference_fixtures=live["reference_fixtures"],
            )
    request_operations = {
        request.get("arguments", {}).get("import_operation")
        for request in requests
        if isinstance(request, Mapping) and isinstance(request.get("arguments"), Mapping)
    }
    if any(row["import_operation"] not in request_operations for row in static["row_contracts"]):
        raise ImportBusinessPlanError("archived import row operation is not bound to a request")
    _validate_rows_against_fixture_and_requests(static, live, scenario)


def _validate_request_contract_versions(
    requests: Sequence[Mapping[str, Any]],
    *,
    api: str,
    version: str,
) -> None:
    expected_operation = (
        "audio.import"
        if api == "ak.wwise.core.audio.import"
        else "audio.importTabDelimited"
    )
    if not requests or any(
        not isinstance(request, Mapping)
        or request.get("contract") != "waapi-skill.operation-request/v1"
        or request.get("version") != version
        or request.get("operation") != expected_operation
        for request in requests
    ):
        raise ImportBusinessPlanError(
            "import request contract/version is misbound"
        )


def _validate_rows_against_fixture_and_requests(static: Mapping[str, Any], live: Mapping[str, Any], scenario: Any) -> None:
    """Rebuild every row/request binding from the reviewed fixture and manifest."""

    fixture = getattr(scenario, "fixture", None)
    spec = fixture.get("asset_spec") if isinstance(fixture, Mapping) else None
    if not isinstance(spec, Mapping) or spec.get("contract") != "waapi-skill.import-eval-assets/v2":
        raise ImportBusinessPlanError("archived import scenario lacks its closed asset fixture")
    raw_rows = spec.get("rows")
    tables = spec.get("tsv")
    if not isinstance(raw_rows, list) or not isinstance(tables, list):
        raise ImportBusinessPlanError("archived import fixture rows/tables are invalid")
    if (
        static["family_schema_version"]
        == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
    ):
        _validate_compound_rows_against_fixture_and_requests(
            static,
            live,
            raw_rows=raw_rows,
            tables=tables,
            compound_spec=spec.get("compound"),
        )
        return
    source_paths = {item["key"]: item["path"] for item in live["input_files"] if item["category"] == "wav"}
    table_paths = {item["key"]: item["path"] for item in live["input_files"] if item["category"] == "tsv"}
    if {str(row.get("source_key")) for row in raw_rows} != set(source_paths):
        raise ImportBusinessPlanError("archived source manifest does not close fixture rows")
    requests = static["operation_requests"]
    operation_by_table: dict[str, str] = {}
    if static["api"] == "ak.wwise.core.audio.import":
        if len(requests) != 1 or not isinstance(requests[0], Mapping):
            raise ImportBusinessPlanError("audio.import archived request count is invalid")
        args = requests[0].get("arguments")
        operation = spec.get("audio_import_operation")
        if not isinstance(args, Mapping) or not isinstance(operation, str):
            raise ImportBusinessPlanError("audio.import fixture operation is invalid")
        expected_imports = [_expected_audio_import_row(row, source_paths) for row in raw_rows]
        if args != {"imports": expected_imports, "import_operation": operation}:
            raise ImportBusinessPlanError("audio.import request does not exactly bind fixture rows")
        operation_by_table = {"__audio_import__": operation}
    else:
        if set(table_paths) != {str(table.get("name")) for table in tables if isinstance(table, Mapping)}:
            raise ImportBusinessPlanError("tab import TSV manifest does not close fixture tables")
        expected_requests: list[dict[str, Any]] = []
        for table in tables:
            if not isinstance(table, Mapping):
                raise ImportBusinessPlanError("tab import fixture table is invalid")
            name, language, operation = table.get("name"), table.get("language"), table.get("import_operation")
            if not all(isinstance(value, str) for value in (name, language, operation)) or name not in table_paths:
                raise ImportBusinessPlanError("tab import fixture table binding is invalid")
            operation_by_table[name] = operation
            expected_requests.append({"contract": "waapi-skill.operation-request/v1", "version": SUPPORTED_VERSION, "operation": "audio.importTabDelimited", "arguments": {"import_file": table_paths[name], "import_location": {"kind": "path", "value": spec.get("import_location")}, "import_language": canonical_wwise_language(language), "import_operation": operation}})
        if requests != expected_requests:
            raise ImportBusinessPlanError("tab import requests do not exactly bind fixture tables")
    expected_contracts = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise ImportBusinessPlanError("import fixture row is invalid")
        table_key = "__audio_import__" if static["api"] == "ak.wwise.core.audio.import" else raw.get("tsv_name")
        event = raw.get("event")
        expected_contracts.append({
            "row_key": raw.get("row_key"), "target_path": raw.get("target_path"), "object_type": raw.get("object_type"),
            "language": canonical_wwise_language(str(raw.get("language") or "")), "import_operation": operation_by_table.get(str(table_key)),
            "guid_policy": raw.get("guid_policy"), "event": None if event is None else {"path": event.get("path"), "action": event.get("action")},
            "source_key": raw.get("source_key"), "pre_state_existence": raw.get("pre_state", {}).get("existence") if isinstance(raw.get("pre_state"), Mapping) else None,
            "pre_state_guid_key": raw.get("pre_state", {}).get("guid_key") if isinstance(raw.get("pre_state"), Mapping) else None,
            "originals_subfolder": raw.get("originals_subfolder"),
        })
    if static["row_contracts"] != expected_contracts:
        raise ImportBusinessPlanError("archived import row contracts do not match fixture/request truth")


def _expected_audio_import_row(raw: Mapping[str, Any], source_paths: Mapping[str, str]) -> dict[str, Any]:
    source_key = raw.get("source_key")
    if not isinstance(source_key, str) or source_key not in source_paths:
        raise ImportBusinessPlanError("audio.import fixture row has no sealed source path")
    value = {"object_path": raw.get("object_path"), "audio_file": source_paths[source_key], "object_type": raw.get("object_type"), "import_language": canonical_wwise_language(str(raw.get("language") or ""))}
    for raw_name, request_name in (("originals_subfolder", "originals_subfolder"), ("notes", "notes"), ("audio_source_notes", "audio_source_notes")):
        if raw.get(raw_name) is not None:
            if request_name == "originals_subfolder":
                try:
                    value[request_name] = normalize_originals_subfolder(
                        raw[raw_name],
                        field="rows.originals_subfolder",
                    )
                except ImportContractError as exc:
                    raise ImportBusinessPlanError(str(exc)) from exc
            else:
                value[request_name] = str(raw[raw_name])
    if raw.get("event") is not None:
        event = raw["event"]
        if not isinstance(event, Mapping):
            raise ImportBusinessPlanError("audio.import fixture event is invalid")
        value["event"] = {"path": event.get("path"), "action": event.get("action")}
    return value


def _validate_compound_rows_against_fixture_and_requests(
    static: Mapping[str, Any],
    live: Mapping[str, Any],
    *,
    raw_rows: Sequence[Any],
    tables: Sequence[Any],
    compound_spec: Any,
) -> None:
    """Close a compound archive without re-running live metadata discovery."""

    try:
        layout = get_codex_version_layout_v3(str(static["version"]))
    except CodexVersionLayoutError as exc:
        raise ImportBusinessPlanError(str(exc)) from exc
    source_paths = {
        item["key"]: item["path"]
        for item in live["input_files"]
        if item["category"] == "wav"
    }
    table_paths = {
        item["key"]: item["path"]
        for item in live["input_files"]
        if item["category"] == "tsv"
    }
    if {str(row.get("source_key")) for row in raw_rows if isinstance(row, Mapping)} != set(source_paths):
        raise ImportBusinessPlanError(
            "archived compound source manifest does not close fixture rows"
        )
    raw_by_key = {
        str(row.get("row_key")): row
        for row in raw_rows
        if isinstance(row, Mapping)
    }
    contracts = static["row_contracts"]
    if set(raw_by_key) != {
        str(row.get("row_key"))
        for row in contracts
        if isinstance(row, Mapping)
    }:
        raise ImportBusinessPlanError(
            "archived compound row keys differ from the reviewed fixture"
        )
    if not isinstance(compound_spec, Mapping):
        raise ImportBusinessPlanError(
            "archived compound scenario lacks its dynamic-field case spec"
        )
    try:
        dynamic_modes = compound_dynamic_modes_by_row(
            compound_spec,
            tuple(raw_by_key.values()),
        )
    except ImportAssetMaterializationError as exc:
        raise ImportBusinessPlanError(
            f"archived compound dynamic-row case spec is invalid: {exc}"
        ) from exc
    for contract in contracts:
        raw = raw_by_key[contract["row_key"]]
        expected_target = layout.translate_2022_path(
            str(raw.get("target_path") or "")
        )
        event = raw.get("event")
        expected_event = (
            None
            if event is None
            else {
                "path": event.get("path"),
                "action": event.get("action"),
            }
        )
        if (
            contract["target_path"] != expected_target
            or contract["object_type"] != raw.get("object_type")
            or contract["source_key"] != raw.get("source_key")
            or contract["guid_policy"] != raw.get("guid_policy")
            or contract["event"] != expected_event
            or contract["pre_state_existence"]
            != (
                raw.get("pre_state", {}).get("existence")
                if isinstance(raw.get("pre_state"), Mapping)
                else None
            )
            or contract["dynamic_mode"]
            != dynamic_modes[contract["row_key"]]
        ):
            raise ImportBusinessPlanError(
                "archived compound row contract differs from fixture truth"
            )

    requests = static["operation_requests"]
    if len(requests) != 1 or not isinstance(requests[0], Mapping):
        raise ImportBusinessPlanError(
            "compound import archive requires one exact operation request"
        )
    request = requests[0]
    if (
        request.get("contract") != "waapi-skill.operation-request/v1"
        or request.get("version") != static["version"]
    ):
        raise ImportBusinessPlanError(
            "compound import request contract/version drifted"
        )
    arguments = request.get("arguments")
    if not isinstance(arguments, Mapping):
        raise ImportBusinessPlanError("compound import request arguments are invalid")
    if static["api"] == "ak.wwise.core.audio.import":
        if request.get("operation") != "audio.import":
            raise ImportBusinessPlanError("compound direct import route drifted")
        imports = arguments.get("imports")
        if not isinstance(imports, list) or len(imports) != len(contracts):
            raise ImportBusinessPlanError(
                "compound direct import rows are incomplete"
            )
        targets = {
            _normalize_typed_wwise_path(str(row.get("object_path") or ""))
            for row in imports
            if isinstance(row, Mapping)
        }
        if targets != {row["target_path"] for row in contracts}:
            raise ImportBusinessPlanError(
                "compound direct import target paths differ from row contracts"
            )
    else:
        if (
            request.get("operation") != "audio.importTabDelimited"
            or set(table_paths)
            != {
                str(table.get("name"))
                for table in tables
                if isinstance(table, Mapping)
            }
            or arguments.get("import_file") not in set(table_paths.values())
        ):
            raise ImportBusinessPlanError(
                "compound tab import request/table binding drifted"
            )
        location = arguments.get("import_location")
        if (
            not isinstance(location, Mapping)
            or set(location) != {"kind", "value"}
            or location.get("kind") != "path"
            or not isinstance(location.get("value"), str)
            or not str(location["value"]).startswith(
                layout.actor_default_work_unit + "\\"
            )
        ):
            raise ImportBusinessPlanError(
                "compound tab import location differs from the versioned hierarchy"
            )

    _validate_compound_request_dynamic_fields(
        arguments,
        dynamic_tokens=static["dynamic_tokens"],
        reference_fixtures=live["reference_fixtures"],
    )


def _validate_compound_request_dynamic_fields(
    arguments: Mapping[str, Any],
    *,
    dynamic_tokens: Sequence[Any],
    reference_fixtures: Any,
) -> None:
    token_set = {
        str(value)
        for value in dynamic_tokens
        if isinstance(value, str) and value
    }
    if len(token_set) != len(dynamic_tokens):
        raise ImportBusinessPlanError("compound dynamic token list is invalid")
    fixture_paths = _reference_fixture_path_map(reference_fixtures)
    observed_names: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if set(value) == {"name", "value"}:
                name = value.get("name")
                if not isinstance(name, str) or name not in token_set:
                    raise ImportBusinessPlanError(
                        "compound request property uses an unbound live name"
                    )
                observed_names.add(name)
            elif set(value) == {"name", "target"}:
                name = value.get("name")
                target = value.get("target")
                if (
                    not isinstance(name, str)
                    or name not in token_set
                    or not isinstance(target, Mapping)
                    or target.get("kind") != "path"
                    or target.get("value") not in set(fixture_paths.values())
                ):
                    raise ImportBusinessPlanError(
                        "compound request reference is not bound to a reviewed fixture path"
                    )
                observed_names.add(name)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(arguments)
    if not observed_names:
        # Tab-delimited dynamic tokens live in the sealed TSV rather than the
        # small operation request.  The archive still binds those exact names
        # through the metadata digest, row expectations, and TSV file hash.
        if "import_file" not in arguments:
            raise ImportBusinessPlanError(
                "compound request contains no bound dynamic field evidence"
            )


def _normalize_typed_wwise_path(value: str) -> str:
    if not value.startswith("\\"):
        raise ImportBusinessPlanError(
            "compound direct import object_path must be absolute"
        )
    parts: list[str] = []
    for part in value.split("\\")[1:]:
        if part.startswith("<") and ">" in part:
            part = part.split(">", 1)[1]
        if not part:
            raise ImportBusinessPlanError(
                "compound direct import object_path is malformed"
            )
        parts.append(part)
    return "\\" + "\\".join(parts)


def _reference_fixture_id_map(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"main_bus", "targets"}:
        raise ImportBusinessPlanError(
            "compound reference fixture archive is not closed"
        )
    main = value.get("main_bus")
    targets = value.get("targets")
    if (
        not isinstance(main, Mapping)
        or set(main) != {"key", "path", "id", "type", "parent_id"}
        or main.get("key") != "__default_main_bus__"
        or not isinstance(main.get("id"), str)
        or _GUID_RE.fullmatch(str(main["id"])) is None
        or not isinstance(targets, list)
        or not targets
    ):
        raise ImportBusinessPlanError(
            "compound main/reference Bus evidence is invalid"
        )
    result: dict[str, str] = {}
    for row in targets:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"key", "path", "id", "type", "parent_id"}
            or not isinstance(row.get("key"), str)
            or not isinstance(row.get("path"), str)
            or not isinstance(row.get("id"), str)
            or _GUID_RE.fullmatch(str(row["id"])) is None
            or not _object_type_matches(row.get("type"), "Bus")
            or row["id"].casefold() == str(main["id"]).casefold()
        ):
            raise ImportBusinessPlanError(
                "compound reference Bus target evidence is invalid"
            )
        if row["key"] in result:
            raise ImportBusinessPlanError(
                "compound reference Bus keys are duplicated"
            )
        result[str(row["key"])] = str(row["id"])
    if len({item.casefold() for item in result.values()}) != len(result):
        raise ImportBusinessPlanError(
            "compound reference Bus GUIDs are duplicated"
        )
    return result


def _reference_fixture_path_map(value: Any) -> dict[str, str]:
    """Return reviewed target paths after reusing the full fixture proof."""

    _reference_fixture_id_map(value)
    assert isinstance(value, Mapping)
    targets = value["targets"]
    assert isinstance(targets, list)
    result = {
        str(row["key"]): str(row["path"])
        for row in targets
        if isinstance(row, Mapping)
    }
    if (
        len(result) != len(targets)
        or any(not path.startswith("\\") for path in result.values())
    ):
        raise ImportBusinessPlanError(
            "compound reference Bus target paths are invalid"
        )
    return result


def _metadata_projection_from_binding(
    binding: Any,
    *,
    required_tokens: Sequence[Any],
) -> tuple[MetadataTokenProjection, ...]:
    """Derive the broker's trusted stable-token projection from sealed binding."""

    if not isinstance(binding, Mapping):
        raise ImportBusinessPlanError(
            "compound metadata projection requires one sealed binding"
        )
    selected = binding.get("selected")
    if not isinstance(selected, Mapping) or not selected:
        raise ImportBusinessPlanError(
            "compound metadata projection has no selected live metadata"
        )
    projection_by_name: dict[str, MetadataTokenProjection] = {}
    for value in selected.values():
        if not isinstance(value, Mapping):
            raise ImportBusinessPlanError(
                "compound selected metadata row is malformed"
            )
        rows = [(value, value.get("kind"))]
        dependencies = value.get("same_object_dependencies")
        if isinstance(dependencies, (str, bytes)) or not isinstance(
            dependencies,
            Sequence,
        ):
            raise ImportBusinessPlanError(
                "compound selected metadata dependencies are malformed"
            )
        rows.extend((dependency, "property") for dependency in dependencies)
        for row, expected_kind in rows:
            metadata = row.get("metadata") if isinstance(row, Mapping) else None
            name = row.get("name") if isinstance(row, Mapping) else None
            kind = row.get("kind") if isinstance(row, Mapping) else None
            metadata_type = (
                metadata.get("type") if isinstance(metadata, Mapping) else None
            )
            if (
                not isinstance(name, str)
                or kind != expected_kind
                or not isinstance(metadata_type, str)
                or expected_kind == "property"
                and not metadata_type
            ):
                raise ImportBusinessPlanError(
                    "compound metadata projection row is incomplete"
                )
            try:
                projection = MetadataTokenProjection(
                    name=name,
                    kind=str(kind),
                    metadata_type=metadata_type,
                )
            except ValueError as exc:
                raise ImportBusinessPlanError(
                    "compound metadata projection row is invalid"
                ) from exc
            folded = projection.name.casefold()
            previous = projection_by_name.get(folded)
            if previous is None:
                projection_by_name[folded] = projection
            elif previous != projection:
                raise ImportBusinessPlanError(
                    "compound metadata projection repeats one live name "
                    "with conflicting kind or type"
                )
    tokens = tuple(required_tokens)
    if (
        not tokens
        or any(
            not isinstance(value, str)
            or not value
            or value.startswith("@")
            for value in tokens
        )
    ):
        raise ImportBusinessPlanError(
            "compound metadata projection differs from exact dynamic token order"
        )
    token_names_by_folded = {value.casefold(): value for value in tokens}
    projection_names_by_folded = {
        folded: projection.name
        for folded, projection in projection_by_name.items()
    }
    if (
        len(token_names_by_folded) != len(tokens)
        or token_names_by_folded != projection_names_by_folded
    ):
        raise ImportBusinessPlanError(
            "compound metadata projection differs from exact dynamic token order"
        )
    return tuple(projection_by_name[value.casefold()] for value in tokens)


def _validate_archived_metadata_binding(
    binding: Mapping[str, Any],
    *,
    dynamic_tokens: Sequence[Any],
    reference_fixtures: Any,
) -> None:
    if set(binding) != {
        "contract",
        "object_type",
        "discovery_sha256",
        "selected",
        "reference_targets",
    } or (
        binding.get("contract") != "waapi-skill.bound-import-metadata/v1"
        or binding.get("object_type") != "Sound"
        or not _sha(binding.get("discovery_sha256"))
    ):
        raise ImportBusinessPlanError(
            "archived compound metadata binding schema is invalid"
        )
    selected = binding.get("selected")
    targets = binding.get("reference_targets")
    if not isinstance(selected, Mapping) or not selected or not isinstance(targets, Mapping):
        raise ImportBusinessPlanError(
            "archived compound selected metadata/targets are invalid"
        )
    names_by_folded: dict[str, str] = {}

    def append_name(value: str) -> None:
        if not value or value.startswith("@"):
            raise ImportBusinessPlanError(
                "archived compound metadata contains an invalid live name"
            )
        folded = value.casefold()
        previous = names_by_folded.get(folded)
        if previous is None:
            names_by_folded[folded] = value
        elif previous != value:
            raise ImportBusinessPlanError(
                "archived compound metadata repeats one live name "
                "with conflicting casing"
            )

    for row in selected.values():
        if (
            not isinstance(row, Mapping)
            or set(row) != {
                "name",
                "kind",
                "metadata",
                "same_object_dependencies",
            }
            or row.get("kind") not in {"property", "reference"}
            or not isinstance(row.get("name"), str)
            or not isinstance(row.get("same_object_dependencies"), list)
        ):
            raise ImportBusinessPlanError(
                "archived compound selected metadata row is malformed"
            )
        append_name(str(row["name"]))
        for dependency in row["same_object_dependencies"]:
            if not isinstance(dependency, Mapping) or not isinstance(
                dependency.get("name"),
                str,
            ):
                raise ImportBusinessPlanError(
                    "archived compound metadata dependency is malformed"
                )
            append_name(str(dependency["name"]))
    if (
        not dynamic_tokens
        or any(
            not isinstance(value, str)
            or not value
            or value.startswith("@")
            for value in dynamic_tokens
        )
    ):
        raise ImportBusinessPlanError(
            "archived compound dynamic tokens differ from metadata binding"
        )
    dynamic_names_by_folded = {
        value.casefold(): value for value in dynamic_tokens
    }
    if (
        len(dynamic_names_by_folded) != len(dynamic_tokens)
        or dynamic_names_by_folded != names_by_folded
    ):
        raise ImportBusinessPlanError(
            "archived compound dynamic tokens differ from metadata binding"
        )
    fixture_paths = _reference_fixture_path_map(reference_fixtures)
    if set(targets) != set(fixture_paths):
        raise ImportBusinessPlanError(
            "archived metadata reference targets differ from Bus fixtures"
        )
    for key, object_ref in targets.items():
        if (
            not isinstance(object_ref, Mapping)
            or set(object_ref) != {"kind", "value"}
            or object_ref.get("kind") != "path"
            or object_ref.get("value") != fixture_paths[str(key)]
        ):
            raise ImportBusinessPlanError(
                "archived metadata reference target path drifted"
            )


def _validate_archived_dynamic_row(
    row: Mapping[str, Any],
    *,
    api: str,
    binding: Any,
    reference_fixtures: Any,
) -> None:
    if not isinstance(binding, Mapping):
        raise ImportBusinessPlanError("compound metadata binding is unavailable")
    property_names = {
        str(value.get("name"))
        for value in binding.get("selected", {}).values()
        if isinstance(value, Mapping) and value.get("kind") == "property"
    }
    reference_names = {
        str(value.get("name"))
        for value in binding.get("selected", {}).values()
        if isinstance(value, Mapping) and value.get("kind") == "reference"
    }
    dependency_names = {
        str(dependency.get("name"))
        for value in binding.get("selected", {}).values()
        if isinstance(value, Mapping)
        for dependency in value.get("same_object_dependencies", [])
        if isinstance(dependency, Mapping)
    }
    properties = row.get("dynamic_properties")
    references = row.get("dynamic_references")
    preserve_property_tokens = row.get("preserve_property_tokens")
    preserve_reference_tokens = row.get("preserve_reference_tokens")
    dynamic_mode = row.get("dynamic_mode")
    if (
        not isinstance(properties, list)
        or not isinstance(references, list)
        or not isinstance(preserve_property_tokens, list)
        or not isinstance(preserve_reference_tokens, list)
        or row.get("media_kind") not in {"regular_file", "inline_base64"}
        or dynamic_mode not in {"mutate", "preserve"}
    ):
        raise ImportBusinessPlanError(
            "archived compound row dynamic expectations are invalid"
        )
    if bool(properties) != bool(references):
        raise ImportBusinessPlanError(
            "archived compound row must bind dynamic properties and references "
            "together or omit both"
        )
    if dynamic_mode == "mutate" and not properties:
        raise ImportBusinessPlanError(
            "archived compound mutate row requires dynamic expectations"
        )
    if dynamic_mode == "mutate":
        if preserve_property_tokens or preserve_reference_tokens:
            raise ImportBusinessPlanError(
                "archived compound mutate row contains preservation tokens"
            )
    else:
        if (
            properties
            or references
            or api != "ak.wwise.core.audio.importTabDelimited"
            or row.get("import_operation") != "useExisting"
            or row.get("pre_state_existence") != "existing"
            or row.get("guid_policy") != "preserve_existing_guid"
        ):
            raise ImportBusinessPlanError(
                "archived compound preserve row violates the closed "
                "useExisting tab-import boundary"
            )
        (
            expected_property_tokens,
            expected_reference_tokens,
        ) = _archived_preservation_tokens(binding)
        if (
            not _same_exact_token_set(
                preserve_property_tokens,
                expected_property_tokens,
            )
            or not _same_exact_token_set(
                preserve_reference_tokens,
                expected_reference_tokens,
            )
        ):
            raise ImportBusinessPlanError(
                "archived compound preservation tokens differ from live metadata"
            )
        return
    property_by_name: dict[str, Mapping[str, Any]] = {}
    for item in properties:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"name", "value", "metadata_type", "source"}
            or not isinstance(item.get("name"), str)
            or item.get("source") not in {"request", "reference_dependency"}
        ):
            raise ImportBusinessPlanError(
                "archived compound property expectation is malformed"
            )
        name = str(item["name"])
        expected_names = (
            dependency_names
            if item["source"] == "reference_dependency"
            else property_names
        )
        if name not in expected_names or name in property_by_name:
            raise ImportBusinessPlanError(
                "archived compound property expectation is not live-bound"
            )
        if item["source"] == "reference_dependency" and item.get("value") is not True:
            raise ImportBusinessPlanError(
                "archived reference activation property is not exactly true"
            )
        property_by_name[name] = item
    fixture_ids = _reference_fixture_id_map(reference_fixtures)
    seen_references: set[str] = set()
    for item in references:
        if (
            not isinstance(item, Mapping)
            or set(item) != {
                "name",
                "target_id",
                "target_fixture",
                "activation_properties",
            }
            or not isinstance(item.get("name"), str)
            or item["name"] not in reference_names
            or item["name"] in seen_references
            or item.get("target_fixture") not in fixture_ids
            or str(item.get("target_id", "")).casefold()
            != fixture_ids[str(item["target_fixture"])].casefold()
            or not isinstance(item.get("activation_properties"), list)
            or not item["activation_properties"]
        ):
            raise ImportBusinessPlanError(
                "archived compound reference expectation is malformed"
            )
        seen_references.add(str(item["name"]))
        for activation in item["activation_properties"]:
            name = activation.get("name") if isinstance(activation, Mapping) else None
            if (
                not isinstance(name, str)
                or name not in property_by_name
                or property_by_name[name].get("value") is not True
                or activation != property_by_name[name]
            ):
                raise ImportBusinessPlanError(
                    "archived compound reference activation expectation drifted"
                )


def _archived_preservation_tokens(
    binding: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    """Independently rebuild the exact preserve surface from archived metadata."""

    selected = binding.get("selected")
    if not isinstance(selected, Mapping) or not selected:
        raise ImportBusinessPlanError(
            "archived compound preserve metadata selection is unavailable"
        )
    property_names: list[str] = []
    reference_names: list[str] = []
    seen_properties: dict[str, str] = {}
    seen_references: dict[str, str] = {}

    def append(destination: list[str], seen: dict[str, str], value: Any) -> None:
        if (
            not isinstance(value, str)
            or not value
            or value.startswith("@")
        ):
            raise ImportBusinessPlanError(
                "archived compound preservation token is invalid"
            )
        folded = value.casefold()
        previous = seen.get(folded)
        if previous is None:
            seen[folded] = value
            destination.append(value)
        elif previous != value:
            raise ImportBusinessPlanError(
                "archived compound preservation token casing is ambiguous"
            )

    for value in selected.values():
        if not isinstance(value, Mapping):
            raise ImportBusinessPlanError(
                "archived compound preserve metadata row is malformed"
            )
        if value.get("kind") == "property":
            append(property_names, seen_properties, value.get("name"))
        elif value.get("kind") == "reference":
            append(reference_names, seen_references, value.get("name"))
        else:
            raise ImportBusinessPlanError(
                "archived compound preserve metadata kind is unsupported"
            )
        dependencies = value.get("same_object_dependencies")
        if not isinstance(dependencies, list):
            raise ImportBusinessPlanError(
                "archived compound preserve dependencies are malformed"
            )
        for dependency in dependencies:
            if (
                not isinstance(dependency, Mapping)
                or dependency.get("kind") != "property"
            ):
                raise ImportBusinessPlanError(
                    "archived compound preserve dependency is not a property"
                )
            append(
                property_names,
                seen_properties,
                dependency.get("name"),
            )
    if (
        not property_names
        or not reference_names
        or set(seen_properties) & set(seen_references)
    ):
        raise ImportBusinessPlanError(
            "archived compound preservation tokens are incomplete or ambiguous"
        )
    return property_names, reference_names


def _same_exact_token_set(left: Sequence[Any], right: Sequence[Any]) -> bool:
    if any(not isinstance(value, str) for value in left):
        return False
    left_by_folded = {str(value).casefold(): str(value) for value in left}
    right_by_folded = {str(value).casefold(): str(value) for value in right}
    return (
        len(left_by_folded) == len(left)
        and len(right_by_folded) == len(right)
        and left_by_folded == right_by_folded
    )


def _validate_live_archive(live: Mapping[str, Any], static: Mapping[str, Any], *, verify_files: bool) -> None:
    snapshot = live["before_snapshot"]
    if live["before_snapshot_sha256"] != _hash(snapshot) or live["input_files_sha256"] != _hash(live["input_files"]):
        raise ImportBusinessPlanError("archived import live fingerprints are invalid")
    _validate_files(live["input_files"], verify_files=verify_files)
    if not isinstance(live["owned_paths"], Mapping) or set(live["owned_paths"]) != {"asset_root", "parents", "events"}:
        raise ImportBusinessPlanError("archived import owned paths are invalid")
    compound = (
        static["family_schema_version"]
        == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
    )
    if compound:
        reference_fixtures = live["reference_fixtures"]
        if live["reference_fixtures_sha256"] != _hash(reference_fixtures):
            raise ImportBusinessPlanError(
                "archived reference Bus fixture digest is invalid"
            )
        fixture_ids = _reference_fixture_id_map(reference_fixtures)
        cleanup = live["cleanup_boundaries"]
        if (
            not isinstance(cleanup, Mapping)
            or set(cleanup)
            != {
                "order",
                "import_root_paths",
                "reference_bus_paths",
                "asset_root",
            }
            or cleanup.get("order")
            != ["import_roots", "reference_busses", "asset_root"]
            or cleanup.get("asset_root") != live["owned_paths"].get("asset_root")
            or set(cleanup.get("reference_bus_paths", []))
            != {
                row["path"]
                for row in reference_fixtures["targets"]
                if isinstance(row, Mapping)
            }
            or len(cleanup.get("reference_bus_paths", [])) != len(fixture_ids)
        ):
            raise ImportBusinessPlanError(
                "archived compound cleanup boundaries are invalid"
            )
        if (
            not isinstance(snapshot, Mapping)
            or set(snapshot)
            != {
                "scenario_id",
                "business",
                "rows",
                "reference_fixtures",
                "main_bus",
            }
            or snapshot.get("scenario_id") != static["scenario_id"]
            or {
                "main_bus": snapshot.get("main_bus"),
                "targets": snapshot.get("reference_fixtures"),
            }
            != reference_fixtures
        ):
            raise ImportBusinessPlanError(
                "archived compound before snapshot schema is invalid"
            )
        _validate_compound_snapshot_rows(
            snapshot,
            static=static,
            reference_fixtures=reference_fixtures,
            after=False,
        )
        snapshot = snapshot["business"]
    if not isinstance(snapshot, Mapping) or set(snapshot) != {"scenario_id", "rows", "events", "project_xml_files", "originals_files", "input_files", "xml_identities"} or snapshot.get("scenario_id") != static["scenario_id"]:
        raise ImportBusinessPlanError("archived import before snapshot schema is invalid")
    _validate_snapshot_evidence(snapshot)
    expected = {row["row_key"]: row for row in static["row_contracts"]}
    observed = snapshot.get("rows")
    if not isinstance(observed, list) or {row.get("row_key") for row in observed if isinstance(row, Mapping)} != set(expected):
        raise ImportBusinessPlanError("archived import before rows are incomplete")
    for value in observed:
        if not isinstance(value, Mapping) or set(value) != {"row_key", "target_path", "language", "object"}:
            raise ImportBusinessPlanError("archived import before row is malformed")
        contract = expected[value["row_key"]]
        if value["target_path"] != contract["target_path"] or value["language"] != contract["language"]:
            raise ImportBusinessPlanError("archived import before target/language drifted")
        if contract["pre_state_existence"] == "absent" and value["object"] is not None:
            raise ImportBusinessPlanError("archived import absent baseline exists")
        if contract["pre_state_existence"] == "existing" and not isinstance(value["object"], Mapping):
            raise ImportBusinessPlanError("archived import existing baseline is absent")
        if isinstance(value["object"], Mapping):
            _validate_archived_audio_source(
                value["object"].get("audio_source"),
                originals_subfolder=contract.get("originals_subfolder"),
                originals_files=snapshot["originals_files"],
                label=f"archived import before {value['row_key']}",
            )


def _validate_compound_snapshot_rows(
    snapshot: Mapping[str, Any],
    *,
    static: Mapping[str, Any],
    reference_fixtures: Any,
    after: bool,
) -> None:
    rows = snapshot.get("rows")
    contracts = {
        row["row_key"]: row
        for row in static["row_contracts"]
        if isinstance(row, Mapping)
    }
    if (
        not isinstance(rows, list)
        or {row.get("row_key") for row in rows if isinstance(row, Mapping)}
        != set(contracts)
    ):
        raise ImportBusinessPlanError(
            "compound dynamic snapshot rows are incomplete"
        )
    fixture_ids = _reference_fixture_id_map(reference_fixtures)
    main_bus = reference_fixtures["main_bus"]["id"]
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {"row_key", "target_path", "properties", "references"}
        ):
            raise ImportBusinessPlanError(
                "compound dynamic snapshot row schema is invalid"
            )
        contract = contracts[row["row_key"]]
        if row["target_path"] != contract["target_path"]:
            raise ImportBusinessPlanError(
                "compound dynamic snapshot target path drifted"
            )
        properties = row["properties"]
        references = row["references"]
        if not isinstance(properties, list) or not isinstance(references, list):
            raise ImportBusinessPlanError(
                "compound dynamic snapshot values are not arrays"
            )
        property_values: dict[str, Any] = {}
        for item in properties:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"name", "value"}
                or not isinstance(item.get("name"), str)
                or item["name"] in property_values
                or not _archive_json_scalar(item.get("value"))
            ):
                raise ImportBusinessPlanError(
                    "compound dynamic property readback is malformed"
                )
            property_values[str(item["name"])] = item.get("value")
        reference_values: dict[str, Any] = {}
        for item in references:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"name", "target_id"}
                or not isinstance(item.get("name"), str)
                or item["name"] in reference_values
                or not (
                    item.get("target_id") is None
                    or (
                        isinstance(item.get("target_id"), str)
                        and _GUID_RE.fullmatch(str(item["target_id"])) is not None
                    )
                )
            ):
                raise ImportBusinessPlanError(
                    "compound dynamic reference readback is malformed"
                )
            reference_values[str(item["name"])] = item.get("target_id")
        expected_properties = {
            item["name"]: item["value"]
            for item in contract["dynamic_properties"]
        }
        expected_references = {
            item["name"]: item
            for item in contract["dynamic_references"]
        }
        if contract["dynamic_mode"] == "preserve":
            if (
                set(property_values)
                != set(contract["preserve_property_tokens"])
                or set(reference_values)
                != set(contract["preserve_reference_tokens"])
                or len(property_values)
                != len(contract["preserve_property_tokens"])
                or len(reference_values)
                != len(contract["preserve_reference_tokens"])
            ):
                raise ImportBusinessPlanError(
                    "compound preservation snapshot token set is incomplete"
                )
            continue
        if after:
            if property_values != expected_properties:
                raise ImportBusinessPlanError(
                    "compound dynamic property values differ after import"
                )
            if set(reference_values) != set(expected_references):
                raise ImportBusinessPlanError(
                    "compound dynamic reference names differ after import"
                )
            for name, expectation in expected_references.items():
                fixture_key = expectation["target_fixture"]
                expected_id = fixture_ids.get(fixture_key)
                actual_id = reference_values[name]
                if (
                    expected_id is None
                    or not isinstance(actual_id, str)
                    or actual_id.casefold() != expected_id.casefold()
                    or actual_id.casefold() == str(main_bus).casefold()
                ):
                    raise ImportBusinessPlanError(
                        "compound dynamic reference GUID is not its non-default Bus"
                    )
                for activation in expectation["activation_properties"]:
                    if property_values.get(activation["name"]) is not True:
                        raise ImportBusinessPlanError(
                            "compound reference lacks its local activation property"
                        )
        else:
            allowed_properties = set(expected_properties)
            allowed_references = set(expected_references)
            if not set(property_values).issubset(allowed_properties) or not set(
                reference_values
            ).issubset(allowed_references):
                raise ImportBusinessPlanError(
                    "compound before snapshot contains an unbound dynamic token"
                )


def _archive_json_scalar(value: Any) -> bool:
    return value is None or type(value) in {str, int, float, bool}


def _archive_absolute_path_is_valid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parse_archive_absolute_path(value)
    except ArchiveRelativePathError:
        return False
    return True


def _validate_files(files: Any, *, verify_files: bool) -> None:
    if not isinstance(files, list) or not files:
        raise ImportBusinessPlanError("import file manifest is invalid")
    keys: set[tuple[str, str]] = set()
    for row in files:
        if not isinstance(row, Mapping) or set(row) != {"category", "key", "path", "present", "size", "sha256"} or row.get("category") not in {"wav", "pre_state_wav", "tsv"} or not isinstance(row.get("key"), str) or not _archive_absolute_path_is_valid(row.get("path")):
            raise ImportBusinessPlanError("import file manifest row is invalid")
        marker = (str(row["category"]), str(row["key"]))
        if marker in keys:
            raise ImportBusinessPlanError("import file manifest has duplicate keys")
        keys.add(marker)
        present = row["present"]
        if present is True:
            if (
                type(row["size"]) is not int
                or not 0 < row["size"] <= MAX_FILE_BYTES
                or not _sha(row["sha256"])
            ):
                raise ImportBusinessPlanError("present import file proof is invalid")
            if verify_files:
                path = Path(row["path"])
                try:
                    snapshot = read_bounded_exclusive_regular_file(
                        path,
                        max_bytes=row["size"],
                        require_private_posix_mode=False,
                    )
                except CodexFileSecurityError as exc:
                    raise ImportBusinessPlanError(
                        "import file changed after sealing"
                    ) from exc
                if (
                    snapshot.metadata.st_size != row["size"]
                    or hashlib.sha256(snapshot.raw).hexdigest() != row["sha256"]
                ):
                    raise ImportBusinessPlanError("import file changed after sealing")
        elif present is False:
            if row["size"] is not None or row["sha256"] is not None:
                raise ImportBusinessPlanError("absent import file proof is invalid")
            if verify_files and (Path(row["path"]).exists() or Path(row["path"]).is_symlink()):
                raise ImportBusinessPlanError("intentionally absent import file appeared")
        else:
            raise ImportBusinessPlanError("import file presence is invalid")


def _validate_snapshot_evidence(snapshot: Mapping[str, Any]) -> None:
    """Close the archived object/event/XML/Originals/input fingerprint shape."""

    for name in ("events", "project_xml_files", "originals_files", "input_files", "xml_identities"):
        if not isinstance(snapshot.get(name), list):
            raise ImportBusinessPlanError(f"import snapshot {name} is not an array")
    for name in ("project_xml_files", "originals_files"):
        for proof in snapshot[name]:
            if not isinstance(proof, Mapping) or set(proof) != {"path", "relative_path", "size", "sha256"} or not _archive_absolute_path_is_valid(proof.get("path")) or type(proof.get("size")) is not int or proof["size"] < 0 or not _sha(proof.get("sha256")):
                raise ImportBusinessPlanError(f"import snapshot {name} proof is invalid")
    for item in snapshot["input_files"]:
        if not isinstance(item, list) or len(item) != 4 or not _archive_absolute_path_is_valid(item[0]) or type(item[1]) is not bool:
            raise ImportBusinessPlanError("import snapshot input fingerprint is invalid")
        if item[1] and (type(item[2]) is not int or not _sha(item[3])):
            raise ImportBusinessPlanError("present input snapshot fingerprint is invalid")
        if not item[1] and (item[2] is not None or item[3] is not None):
            raise ImportBusinessPlanError("absent input snapshot fingerprint is invalid")
    for event in snapshot["events"]:
        if not isinstance(event, Mapping) or set(event) != {"path", "id", "action_id", "action_type", "target", "child_count"} or not isinstance(event.get("path"), str) or type(event.get("child_count")) is not int:
            raise ImportBusinessPlanError("import snapshot event proof is invalid")
    for identity in snapshot["xml_identities"]:
        if not isinstance(identity, Mapping) or set(identity) != {"guid", "relative_file", "element_tag", "name"}:
            raise ImportBusinessPlanError("import snapshot XML identity proof is invalid")


def _validate_archived_preservation_unchanged(
    static: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    """Compare sealed preserve-only values without trusting runtime pass flags."""

    before_rows = {
        row["row_key"]: row
        for row in before["rows"]
        if isinstance(row, Mapping)
    }
    after_rows = {
        row["row_key"]: row
        for row in after["rows"]
        if isinstance(row, Mapping)
    }
    for contract in static["row_contracts"]:
        if contract.get("dynamic_mode") != "preserve":
            continue
        row_key = contract["row_key"]
        old = before_rows[row_key]
        new = after_rows[row_key]
        old_properties = {
            item["name"]: item["value"] for item in old["properties"]
        }
        new_properties = {
            item["name"]: item["value"] for item in new["properties"]
        }
        if set(old_properties) != set(new_properties):
            raise ImportBusinessPlanError(
                "compound preserved property token set changed after import"
            )
        for name, old_value in old_properties.items():
            new_value = new_properties[name]
            if type(old_value) is not type(new_value) or old_value != new_value:
                raise ImportBusinessPlanError(
                    f"compound preserved property @{name} changed after import"
                )

        old_references = {
            item["name"]: item["target_id"] for item in old["references"]
        }
        new_references = {
            item["name"]: item["target_id"] for item in new["references"]
        }
        if set(old_references) != set(new_references):
            raise ImportBusinessPlanError(
                "compound preserved reference token set changed after import"
            )
        for name, old_value in old_references.items():
            new_value = new_references[name]
            if not (
                old_value is None
                and new_value is None
                or isinstance(old_value, str)
                and isinstance(new_value, str)
                and old_value.casefold() == new_value.casefold()
            ):
                raise ImportBusinessPlanError(
                    f"compound preserved reference @{name} changed after import"
                )


def _validate_after(static: Mapping[str, Any], live: Mapping[str, Any], after: Any) -> None:
    compound = (
        static["family_schema_version"]
        == COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA
    )
    before_snapshot = live["before_snapshot"]
    if compound:
        before_compound = before_snapshot
        if (
            not isinstance(after, Mapping)
            or set(after)
            != {
                "scenario_id",
                "business",
                "rows",
                "reference_fixtures",
                "main_bus",
            }
            or after.get("scenario_id") != static["scenario_id"]
            or {
                "main_bus": after.get("main_bus"),
                "targets": after.get("reference_fixtures"),
            }
            != live["reference_fixtures"]
        ):
            raise ImportBusinessPlanError(
                "compound import after snapshot schema/Bus fixtures drifted"
            )
        _validate_compound_snapshot_rows(
            after,
            static=static,
            reference_fixtures=live["reference_fixtures"],
            after=True,
        )
        if not isinstance(before_compound, Mapping):
            raise ImportBusinessPlanError(
                "compound import before snapshot is invalid"
            )
        _validate_archived_preservation_unchanged(
            static,
            before_compound,
            after,
        )
        before_snapshot = before_compound["business"]
        after = after["business"]
    if not isinstance(after, Mapping) or set(after) != {"scenario_id", "rows", "events", "project_xml_files", "originals_files", "input_files", "xml_identities"} or after.get("scenario_id") != static["scenario_id"]:
        raise ImportBusinessPlanError("import after snapshot schema is invalid")
    contracts = {row["row_key"] for row in static["row_contracts"]}
    if not isinstance(after.get("rows"), list) or {row.get("row_key") for row in after["rows"] if isinstance(row, Mapping)} != contracts:
        raise ImportBusinessPlanError("import after rows are incomplete")
    for row in after["rows"]:
        if not isinstance(row, Mapping) or set(row) != {"row_key", "target_path", "language", "object"}:
            raise ImportBusinessPlanError("import after row schema is invalid")
    before_by_key = {row["row_key"]: row for row in before_snapshot["rows"]}
    after_by_key = {row["row_key"]: row for row in after["rows"]}
    ids_by_target: dict[str, str] = {}
    before_ids = {
        str(row["object"].get("id"))
        for row in before_by_key.values()
        if isinstance(row.get("object"), Mapping)
    }
    for contract in static["row_contracts"]:
        old, new = before_by_key[contract["row_key"]]["object"], after_by_key[contract["row_key"]]["object"]
        policy = contract["guid_policy"]
        if policy == "remain_absent_no_guid":
            if new is not None: raise ImportBusinessPlanError("refusal target changed after execution")
            continue
        if (
            not isinstance(new, Mapping)
            or new.get("path") != contract["target_path"]
            or not _object_type_matches(
                new.get("type"),
                contract["object_type"],
            )
        ):
            raise ImportBusinessPlanError("import after target/type drifted")
        new_id = new.get("id")
        if not isinstance(new_id, str) or _GUID_RE.fullmatch(new_id) is None:
            raise ImportBusinessPlanError("import after object GUID is invalid")
        if after_by_key[contract["row_key"]].get("language") != contract["language"]:
            raise ImportBusinessPlanError("import after row language drifted")
        source = new.get("audio_source")
        input_by_key = {item["key"]: item for item in live["input_files"] if item["category"] == "wav"}
        expected_file = input_by_key.get(contract["source_key"])
        original = source.get("original_file") if isinstance(source, Mapping) else None
        if not isinstance(source, Mapping) or source.get("language") != contract["language"] or not isinstance(original, Mapping) or original.get("sha256") != (expected_file or {}).get("sha256"):
            raise ImportBusinessPlanError("import after audio-source language or hash drifted")
        _validate_archived_audio_source(
            source,
            originals_subfolder=contract.get("originals_subfolder"),
            originals_files=after["originals_files"],
            label=f"import after {contract['row_key']}",
        )
        if policy.startswith("preserve") and (not isinstance(old, Mapping) or old.get("id") != new.get("id")):
            raise ImportBusinessPlanError("useExisting GUID semantics drifted")
        if policy == "replace_with_distinct_guid" and (not isinstance(old, Mapping) or old.get("id") == new.get("id")):
            raise ImportBusinessPlanError("replaceExisting GUID semantics drifted")
        if policy in {"create_new_unique_guid", "create_once_then_preserve_shared_guid"} and old is not None:
            raise ImportBusinessPlanError("create GUID policy has a non-absent baseline")
        if policy in {"create_new_unique_guid", "create_once_then_preserve_shared_guid", "replace_with_distinct_guid"} and new_id in before_ids:
            raise ImportBusinessPlanError("create/replace reused a before GUID")
        previous = ids_by_target.setdefault(contract["target_path"].casefold(), new_id)
        if previous != new_id:
            raise ImportBusinessPlanError("localized rows lost shared target GUID")
    if len(set(ids_by_target.values())) != len(ids_by_target):
        raise ImportBusinessPlanError("distinct import targets share one GUID")
    if after["input_files"] != before_snapshot["input_files"]:
        raise ImportBusinessPlanError("immutable input fingerprint changed after import")
    events = {item.get("path"): item for item in after["events"] if isinstance(item, Mapping)}
    for contract in static["row_contracts"]:
        event = contract["event"]
        if event is None: continue
        value = events.get(event["path"])
        target = after_by_key[contract["row_key"]]["object"]
        if not isinstance(value, Mapping) or value.get("action_type") != 1 or value.get("child_count") != 1 or not isinstance(target, Mapping) or not _exact_event_target(value.get("target"), str(target.get("id")), str(target.get("path"))):
            raise ImportBusinessPlanError("event Play action delta drifted")


def _exact_event_target(value: Any, expected_id: str, expected_path: str) -> bool:
    """Accept only the runtime's closed ID/path target representations."""

    if isinstance(value, str):
        return value == expected_id or value == expected_path
    if isinstance(value, Mapping):
        compared = False
        if "id" in value:
            compared = True
            if value["id"] != expected_id:
                return False
        if "path" in value:
            compared = True
            if value["path"] != expected_path:
                return False
        if "object" in value:
            compared = True
            if not _exact_event_target(value["object"], expected_id, expected_path):
                return False
        return compared
    return False


def _validate_archived_audio_source(
    source: Any,
    *,
    originals_subfolder: Any,
    originals_files: Any,
    label: str,
) -> None:
    if not isinstance(source, Mapping) or set(source) != {
        "id",
        "language",
        "notes",
        "original_file",
        "original_relative_path",
    }:
        raise ImportBusinessPlanError(f"{label} Audio Source evidence is malformed")
    original = source.get("original_file")
    if not isinstance(original, Mapping) or set(original) != {
        "path",
        "relative_path",
        "size",
        "sha256",
    }:
        raise ImportBusinessPlanError(f"{label} copied Original proof is malformed")
    if (
        not _archive_absolute_path_is_valid(original.get("path"))
        or type(original.get("size")) is not int
        or original["size"] < 0
        or not _sha(original.get("sha256"))
    ):
        raise ImportBusinessPlanError(f"{label} copied Original proof is invalid")

    relative_parts = _canonical_relative_parts(
        source.get("original_relative_path"),
        label=f"{label} original_relative_path",
    )
    proof_parts = _canonical_relative_parts(
        original.get("relative_path"),
        label=f"{label} original_file.relative_path",
    )
    if len(proof_parts) < 2 or proof_parts[0].casefold() != "originals":
        raise ImportBusinessPlanError(
            f"{label} copied Original is not rooted below project Originals"
        )
    if tuple(proof_parts[1:]) != tuple(relative_parts):
        raise ImportBusinessPlanError(
            f"{label} copied Original relative evidence is inconsistent"
        )

    try:
        suffix_matches = archive_absolute_has_relative_suffix(
            original["path"],
            original["relative_path"],
        )
    except ArchiveRelativePathError as exc:
        raise ImportBusinessPlanError(
            f"{label} copied Original path proof is invalid"
        ) from exc
    if not suffix_matches:
        raise ImportBusinessPlanError(
            f"{label} copied Original absolute/relative paths are inconsistent"
        )

    if originals_subfolder is not None:
        expected_parts = _canonical_relative_parts(
            originals_subfolder,
            label=f"{label} originals_subfolder",
        )
        if len(relative_parts) <= len(expected_parts) or tuple(
            part.casefold()
            for part in relative_parts[-len(expected_parts) - 1 : -1]
        ) != tuple(part.casefold() for part in expected_parts):
            raise ImportBusinessPlanError(
                f"{label} copied Original subfolder differs from the sealed request"
            )

    if not isinstance(originals_files, list) or not any(
        isinstance(item, Mapping)
        and item.get("path") == original.get("path")
        and item.get("relative_path") == original.get("relative_path")
        and item.get("size") == original.get("size")
        and item.get("sha256") == original.get("sha256")
        for item in originals_files
    ):
        raise ImportBusinessPlanError(
            f"{label} copied Original is absent from the sealed Originals tree"
        )


def _canonical_relative_parts(value: Any, *, label: str) -> tuple[str, ...]:
    try:
        parsed = parse_archive_relative_path(value)
    except ArchiveRelativePathError as exc:
        raise ImportBusinessPlanError(
            f"{label} is not a canonical relative path"
        ) from exc
    if parsed.source_flavor != "posix" or parsed.canonical != value:
        raise ImportBusinessPlanError(f"{label} is not a canonical relative path")
    return parsed.parts


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_plain(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA256


def _plain(value: Any) -> Any:
    if value is None or type(value) in {str, int, float, bool}: return value
    if isinstance(value, Path): return str(value)
    if is_dataclass(value) and not isinstance(value, type): return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping): return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_plain(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")))
    raise ImportBusinessPlanError(f"import business-plan value is not JSON serializable: {type(value).__name__}")


__all__ = [
    "COMPOUND_IMPORT_BUSINESS_PLAN_SCHEMA",
    "COMPOUND_IMPORT_FIXTURE_KIND",
    "IMPORT_BUSINESS_PLAN_SCHEMA",
    "IMPORT_FIXTURE_KIND",
    "ImportBusinessPlanError",
    "ImportBusinessPlanSections",
    "compile_import_business_plan",
    "parse_import_business_plan_sections",
    "validate_import_archived_verification",
    "validate_import_business_plan",
    "validate_import_business_plan_archive",
]

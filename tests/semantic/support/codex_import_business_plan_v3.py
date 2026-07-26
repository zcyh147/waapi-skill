"""Closed typed business plans for the ten 2022.1 core import scenarios.

The plan is compiled after the runner has materialized its WAV/TSV inputs and
prepared the hidden before snapshot, but before a Codex task is created.  It is
not a second fixture format: every request, file proof, row contract and delta
rule is projected from the runner-owned import dataclasses.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_eval_protocol_v3 import (
    StructuredRefusal,
    V3GatewayProtocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_import_assets_v3 import (
    MaterializedImportCase,
    canonical_wwise_language,
)
from tests.semantic.support.codex_import_runtime_v3 import (
    IMPORT_APIS,
    SUPPORTED_VERSION,
    ImportRuntimePlan,
    ImportRuntimeSnapshot,
    _object_type_matches,
)
from tests.semantic.support.codex_prompt_provenance_v3 import serialize_protocol


IMPORT_BUSINESS_PLAN_SCHEMA = "waapi-skill.import-business-plan/v1"
IMPORT_FIXTURE_KIND = "import_materialized_runtime_v1"
_REFUSAL_CODES = {"O22-AUDIO-TAB-01": "INPUT_FILE_NOT_FOUND"}
_SHA256 = set("0123456789abcdef")
_GUID_POLICIES = frozenset({"remain_absent_no_guid", "preserve_existing_guid", "preserve_shared_existing_guid", "replace_with_distinct_guid", "create_new_unique_guid", "create_once_then_preserve_shared_guid"})
_IMPORT_OPERATIONS = frozenset({"createNew", "useExisting", "replaceExisting"})
_GUID_RE = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
_ASSERTION_IDS = ("import.request.exact", "import.rows.typed", "import.live.before", "import.files.fingerprinted", "import.delta.closed")


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
    before: ImportRuntimeSnapshot,
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
    before: ImportRuntimeSnapshot,
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
    if _plain(sections.fixture_spec) != {"kind": IMPORT_FIXTURE_KIND, "sha256": _hash(fixture)}:
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


def _validate_runtime_inputs(scenario: Any, materialized: MaterializedImportCase, plan: ImportRuntimePlan, before: ImportRuntimeSnapshot, protocol: V3GatewayProtocol) -> None:
    if not isinstance(materialized, MaterializedImportCase) or not isinstance(plan, ImportRuntimePlan) or not isinstance(before, ImportRuntimeSnapshot):
        raise ImportBusinessPlanError("import compiler requires materialized case, runtime plan and before snapshot")
    if plan.api not in IMPORT_APIS or plan.version != SUPPORTED_VERSION or getattr(scenario, "id", None) != plan.scenario_id or getattr(scenario, "api", None) != plan.api:
        raise ImportBusinessPlanError("import scenario/runtime identity is misbound")
    if materialized.scenario_id != plan.scenario_id or materialized.expected_primary_dispatch_count != plan.expected_primary_dispatch_count:
        raise ImportBusinessPlanError("materialized import identity or dispatch count drifted")
    if tuple(materialized.operation_requests) != tuple(plan.operation_requests) or before.scenario_id != plan.scenario_id:
        raise ImportBusinessPlanError("import requests or before snapshot are misbound")
    _validate_files(_file_manifest(materialized), verify_files=True)
    _validate_expected_protocol(plan, protocol)


def _validate_expected_protocol(plan: ImportRuntimePlan, protocol: V3GatewayProtocol) -> None:
    refusal = _REFUSAL_CODES.get(plan.scenario_id)
    expected = build_transaction_protocol(plan.operation_requests, refusal=StructuredRefusal(refusal) if refusal else None)
    if _plain(serialize_protocol(protocol)) != _plain(serialize_protocol(expected)):
        raise ImportBusinessPlanError("import protocol does not exactly bind sealed requests and transaction order")


def _static(scenario: Any, materialized: MaterializedImportCase, plan: ImportRuntimePlan, protocol: V3GatewayProtocol) -> dict[str, Any]:
    requests = _plain(plan.operation_requests)
    rows = []
    request_ops = _operations_by_row(plan, materialized)
    for row in plan.rows:
        rows.append({
            "row_key": row.row_key, "target_path": row.target_path, "object_type": row.object_type,
            "language": row.language, "import_operation": request_ops[row.row_key], "guid_policy": row.guid_policy,
            "event": None if row.event_path is None else {"path": row.event_path, "action": row.event_action},
            "source_key": row.source_file.key, "pre_state_existence": row.pre_state_existence,
            "pre_state_guid_key": row.pre_state_guid_key,
            "originals_subfolder": row.originals_subfolder,
        })
    return {
        "family_schema_version": IMPORT_BUSINESS_PLAN_SCHEMA, "family": "audio_import",
        "scenario_id": plan.scenario_id, "api": plan.api, "version": plan.version,
        "primary_dispatch_count": plan.expected_primary_dispatch_count,
        "operation_requests": requests, "operation_requests_sha256": _hash(requests),
        "protocol_sha256": _hash(serialize_protocol(protocol)), "row_contracts": rows,
        "refusal_error_code": _REFUSAL_CODES.get(plan.scenario_id),
        "scenario_api": getattr(scenario, "api", None),
    }


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


def _live(plan: ImportRuntimePlan, before: ImportRuntimeSnapshot, materialized: MaterializedImportCase) -> dict[str, Any]:
    snapshot = _plain(before)
    files = _file_manifest(materialized)
    return {
        "family_schema_version": IMPORT_BUSINESS_PLAN_SCHEMA,
        "before_snapshot": snapshot, "before_snapshot_sha256": _hash(snapshot),
        "input_files": files, "input_files_sha256": _hash(files),
        "owned_paths": {"asset_root": str(plan.asset_root), "parents": [item.path for item in plan.parents], "events": list(plan.event_paths)},
    }


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
    return [
        {"kind": "import_exact_requests_v1", "requests_sha256": static["operation_requests_sha256"], "protocol_sha256": static["protocol_sha256"], "ordered_transaction_count": static["primary_dispatch_count"]},
        {"kind": "import_row_delta_v1", "subject": "target/type/language/importOperation/GUID", "rows": rows, "create_guid_rows": creates, "use_existing_guid_rows": uses, "replace_guid_rows": replaces},
        {"kind": "import_event_action_delta_v1", "subject": "event Play action", "events": [row["event"] for row in rows if row["event"] is not None]},
        {"kind": "import_owned_paths_v1", "subject": "scenario-owned paths", "owned_paths": live["owned_paths"]},
        {"kind": "import_immutable_inputs_v1", "subject": "WAV/TSV regular-file size sha256", "before_snapshot_sha256": live["before_snapshot_sha256"], "input_files_sha256": live["input_files_sha256"]},
        {"kind": "import_zero_dispatch_refusal_v1", "subject": "before_equals_after_and_exact_error", "enabled": static["primary_dispatch_count"] == 0, "error_code": static["refusal_error_code"]},
    ]


def _partition(plan: ImportRuntimePlan, protocol: V3GatewayProtocol) -> tuple[list[str], list[str]]:
    names = [item["name"] for item in serialize_protocol(protocol)["steps"]]
    return ([] if plan.expected_primary_dispatch_count == 0 else [f"tx{item:02d}.execute" for item in range(1, plan.expected_primary_dispatch_count + 1)], names if plan.expected_primary_dispatch_count == 0 else [item for item in names if not item.endswith(".execute")])


def _sections(static: Mapping[str, Any], live: Mapping[str, Any], rules: Sequence[Mapping[str, Any]], primary: Sequence[str], verification: Sequence[str]) -> ImportBusinessPlanSections:
    fixture = {"static": _plain(static), "live": _plain(live)}
    return ImportBusinessPlanSections(
        MappingProxyType({"kind": IMPORT_FIXTURE_KIND, "sha256": _hash(fixture)}),
        MappingProxyType({"primary_steps": list(primary), "verification_steps": list(verification)}),
        _ASSERTION_IDS,
        MappingProxyType(_plain(static)), MappingProxyType(_plain(live)), tuple(MappingProxyType(_plain(item)) for item in rules),
    )


def _validate_shape(sections: ImportBusinessPlanSections) -> None:
    if not isinstance(sections, ImportBusinessPlanSections):
        raise ImportBusinessPlanError("import sections have the wrong type")
    if set(sections.fixture_spec) != {"kind", "sha256"} or sections.fixture_spec.get("kind") != IMPORT_FIXTURE_KIND or not _sha(sections.fixture_spec.get("sha256")):
        raise ImportBusinessPlanError("import fixture schema is not closed")
    if set(sections.payload_bindings) != {"primary_steps", "verification_steps"} or any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in sections.payload_bindings.values()):
        raise ImportBusinessPlanError("import payload binding schema is not closed")
    if not sections.assertion_ids or any(not isinstance(item, str) or not item for item in sections.assertion_ids):
        raise ImportBusinessPlanError("import assertion ids are invalid")
    if tuple(sections.assertion_ids) != _ASSERTION_IDS:
        raise ImportBusinessPlanError("import assertion ids are not the fixed closed tuple")
    static, live = sections.static_expectation, sections.live_binding
    static_keys = {"family_schema_version", "family", "scenario_id", "api", "version", "primary_dispatch_count", "operation_requests", "operation_requests_sha256", "protocol_sha256", "row_contracts", "refusal_error_code", "scenario_api"}
    live_keys = {"family_schema_version", "before_snapshot", "before_snapshot_sha256", "input_files", "input_files_sha256", "owned_paths"}
    if set(static) != static_keys or set(live) != live_keys or static.get("family_schema_version") != IMPORT_BUSINESS_PLAN_SCHEMA or live.get("family_schema_version") != IMPORT_BUSINESS_PLAN_SCHEMA:
        raise ImportBusinessPlanError("import static/live schema is not closed")


def _validate_static_archive(static: Mapping[str, Any], live: Mapping[str, Any], scenario: Any, protocol: V3GatewayProtocol) -> None:
    if static["api"] not in IMPORT_APIS or static["version"] != SUPPORTED_VERSION or static["family"] != "audio_import" or static["scenario_id"] != getattr(scenario, "id", None) or static["api"] != getattr(scenario, "api", None) or static["scenario_api"] != static["api"]:
        raise ImportBusinessPlanError("archived import scenario identity is misbound")
    count = static["primary_dispatch_count"]
    if type(count) is not int or count < 0 or count != getattr(getattr(scenario, "primary_dispatch", None), "count", None):
        raise ImportBusinessPlanError("archived import dispatch count is invalid")
    requests = static["operation_requests"]
    if not isinstance(requests, list) or static["operation_requests_sha256"] != _hash(requests):
        raise ImportBusinessPlanError("archived import requests digest is invalid")
    if count == 0 and (len(requests) != 1 or static["refusal_error_code"] != _REFUSAL_CODES.get(static["scenario_id"])):
        raise ImportBusinessPlanError("archived zero-dispatch refusal is not closed")
    if count > 0 and (len(requests) != count or static["refusal_error_code"] is not None):
        raise ImportBusinessPlanError("archived import request count is invalid")
    expected = build_transaction_protocol(requests, refusal=StructuredRefusal(static["refusal_error_code"]) if count == 0 else None)
    if _plain(serialize_protocol(protocol)) != _plain(serialize_protocol(expected)) or static["protocol_sha256"] != _hash(serialize_protocol(protocol)):
        raise ImportBusinessPlanError("archived import protocol/request order drifted")
    if not isinstance(static["row_contracts"], list) or not static["row_contracts"] or len({row.get("row_key") for row in static["row_contracts"] if isinstance(row, Mapping)}) != len(static["row_contracts"]):
        raise ImportBusinessPlanError("archived import row contracts are invalid")
    for row in static["row_contracts"]:
        if not isinstance(row, Mapping) or set(row) != {"row_key", "target_path", "object_type", "language", "import_operation", "guid_policy", "event", "source_key", "pre_state_existence", "pre_state_guid_key", "originals_subfolder"} or not all(isinstance(row[key], str) for key in ("row_key", "target_path", "object_type", "language", "import_operation", "guid_policy", "source_key", "pre_state_existence")) or not (row["originals_subfolder"] is None or isinstance(row["originals_subfolder"], str)):
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
    request_operations = {
        request.get("arguments", {}).get("import_operation")
        for request in requests
        if isinstance(request, Mapping) and isinstance(request.get("arguments"), Mapping)
    }
    if any(row["import_operation"] not in request_operations for row in static["row_contracts"]):
        raise ImportBusinessPlanError("archived import row operation is not bound to a request")
    _validate_rows_against_fixture_and_requests(static, live, scenario)


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
            value[request_name] = str(raw[raw_name])
    if raw.get("event") is not None:
        event = raw["event"]
        if not isinstance(event, Mapping):
            raise ImportBusinessPlanError("audio.import fixture event is invalid")
        value["event"] = {"path": event.get("path"), "action": event.get("action")}
    return value


def _validate_live_archive(live: Mapping[str, Any], static: Mapping[str, Any], *, verify_files: bool) -> None:
    snapshot = live["before_snapshot"]
    if live["before_snapshot_sha256"] != _hash(snapshot) or live["input_files_sha256"] != _hash(live["input_files"]):
        raise ImportBusinessPlanError("archived import live fingerprints are invalid")
    _validate_files(live["input_files"], verify_files=verify_files)
    if not isinstance(live["owned_paths"], Mapping) or set(live["owned_paths"]) != {"asset_root", "parents", "events"}:
        raise ImportBusinessPlanError("archived import owned paths are invalid")
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


def _validate_files(files: Any, *, verify_files: bool) -> None:
    if not isinstance(files, list) or not files:
        raise ImportBusinessPlanError("import file manifest is invalid")
    keys: set[tuple[str, str]] = set()
    for row in files:
        if not isinstance(row, Mapping) or set(row) != {"category", "key", "path", "present", "size", "sha256"} or row.get("category") not in {"wav", "pre_state_wav", "tsv"} or not isinstance(row.get("key"), str) or not os.path.isabs(str(row.get("path") or "")):
            raise ImportBusinessPlanError("import file manifest row is invalid")
        marker = (str(row["category"]), str(row["key"]))
        if marker in keys:
            raise ImportBusinessPlanError("import file manifest has duplicate keys")
        keys.add(marker)
        present = row["present"]
        if present is True:
            if type(row["size"]) is not int or row["size"] < 0 or not _sha(row["sha256"]):
                raise ImportBusinessPlanError("present import file proof is invalid")
            if verify_files:
                path = Path(row["path"])
                meta = os.lstat(path)
                if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_size != row["size"] or _hash_file(path) != row["sha256"]:
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
            if not isinstance(proof, Mapping) or set(proof) != {"path", "relative_path", "size", "sha256"} or not os.path.isabs(str(proof.get("path") or "")) or type(proof.get("size")) is not int or proof["size"] < 0 or not _sha(proof.get("sha256")):
                raise ImportBusinessPlanError(f"import snapshot {name} proof is invalid")
    for item in snapshot["input_files"]:
        if not isinstance(item, list) or len(item) != 4 or not os.path.isabs(str(item[0] or "")) or type(item[1]) is not bool:
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


def _validate_after(static: Mapping[str, Any], live: Mapping[str, Any], after: Any) -> None:
    if not isinstance(after, Mapping) or set(after) != {"scenario_id", "rows", "events", "project_xml_files", "originals_files", "input_files", "xml_identities"} or after.get("scenario_id") != static["scenario_id"]:
        raise ImportBusinessPlanError("import after snapshot schema is invalid")
    contracts = {row["row_key"] for row in static["row_contracts"]}
    if not isinstance(after.get("rows"), list) or {row.get("row_key") for row in after["rows"] if isinstance(row, Mapping)} != contracts:
        raise ImportBusinessPlanError("import after rows are incomplete")
    for row in after["rows"]:
        if not isinstance(row, Mapping) or set(row) != {"row_key", "target_path", "language", "object"}:
            raise ImportBusinessPlanError("import after row schema is invalid")
    before_by_key = {row["row_key"]: row for row in live["before_snapshot"]["rows"]}
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
    if after["input_files"] != live["before_snapshot"]["input_files"]:
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
        not os.path.isabs(str(original.get("path") or ""))
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

    absolute_parts = tuple(
        part for part in re.split(r"[\\/]+", str(original["path"])) if part
    )
    expected_suffix = tuple(proof_parts)
    if len(absolute_parts) < len(expected_suffix) or tuple(
        absolute_parts[-len(expected_suffix) :]
    ) != expected_suffix:
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
    if (
        not isinstance(value, str)
        or not value
        or value.startswith(("/", "\\"))
        or "\\" in value
        or "\x00" in value
    ):
        raise ImportBusinessPlanError(f"{label} is not a canonical relative path")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise ImportBusinessPlanError(f"{label} is not a canonical relative path")
    if "/".join(parts) != value:
        raise ImportBusinessPlanError(f"{label} is not a canonical relative path")
    return parts


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(_plain(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    "IMPORT_BUSINESS_PLAN_SCHEMA", "IMPORT_FIXTURE_KIND", "ImportBusinessPlanError", "ImportBusinessPlanSections",
    "compile_import_business_plan", "parse_import_business_plan_sections", "validate_import_business_plan",
    "validate_import_business_plan_archive", "validate_import_archived_verification",
]

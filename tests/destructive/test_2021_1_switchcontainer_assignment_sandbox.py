from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for 2021.1 destructive sandbox tests",
        allow_module_level=True,
    )
if os.getenv("WWISE_VERSION") != "2021.1":
    pytest.skip("WWISE_VERSION=2021.1 is required for 2021.1 destructive sandbox tests", allow_module_level=True)

from tests.destructive.support.destructive_2021_sandbox import (  # pyright: ignore[reportMissingImports]
    Destructive2021SandboxRuntime,
    DestructiveSandboxUnavailable,
    hash_mutation_bearing_project_files,
    unique_2021_name,
)
from tests.destructive.support.live_environment import path_is_under  # pyright: ignore[reportMissingImports]
from tests.support.active_gate_failures import skip_or_fail_unavailable  # pyright: ignore[reportMissingImports]

ADD_ASSIGNMENT_URI = "ak.wwise.core.switchContainer.addAssignment"
GET_ASSIGNMENTS_URI = "ak.wwise.core.switchContainer.getAssignments"
OBJECT_CREATE_URI = "ak.wwise.core.object.create"
OBJECT_DELETE_URI = "ak.wwise.core.object.delete"
OBJECT_GET_URI = "ak.wwise.core.object.get"
OBJECT_GET_TYPES_URI = "ak.wwise.core.object.getTypes"
OBJECT_SET_REFERENCE_URI = "ak.wwise.core.object.setReference"
REMOVE_ASSIGNMENT_URI = "ak.wwise.core.switchContainer.removeAssignment"

ACTOR_MIXER_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
SWITCH_PARENT = r"\Switches\Default Work Unit"
SWITCH_REFERENCE = "SwitchGroupOrStateGroup"
CREATED_OBJECT_TYPES = ("SwitchContainer", "SwitchGroup", "Switch", "Sound")
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]
PARENT_FIELDS = ["id", "name", "type", "path"]
REFLECTED_URI_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "resources" / "manifest" / "2021.1" / "functions.json"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "resources" / "manifest" / "2021.1" / "schemas.json"
REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-2021-waapi-integration-coverage"
DESTRUCTIVE_EVIDENCE_ROOT = EVIDENCE_ROOT / "destructive"
TASK_EVIDENCE_PATH = EVIDENCE_ROOT / "task-12-switchcontainer-assignment.json"
EXACT_DESTRUCTIVE_COMMAND = (
    'WWISE_VERSION=2021.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" '
    "WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2021.1 WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 "
    "python -m pytest tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py -q"
)


@contextmanager
def _destructive_sandbox() -> Iterator[Destructive2021SandboxRuntime]:
    try:
        with Destructive2021SandboxRuntime() as runtime:
            yield runtime
    except DestructiveSandboxUnavailable as exc:
        skip_or_fail_unavailable(exc)


@pytest.mark.live
@pytest.mark.destructive
def test_2021_switchcontainer_assignment_add_remove_readback_cleanup_against_copied_sandbox() -> None:
    reflected_uris = _reflected_uris()
    _require_reflected(
        reflected_uris,
        [
            ADD_ASSIGNMENT_URI,
            GET_ASSIGNMENTS_URI,
            OBJECT_CREATE_URI,
            OBJECT_DELETE_URI,
            OBJECT_GET_URI,
            OBJECT_GET_TYPES_URI,
            OBJECT_SET_REFERENCE_URI,
            REMOVE_ASSIGNMENT_URI,
        ],
    )
    runtime: Destructive2021SandboxRuntime | None = None
    source_before: Mapping[str, Any] | None = None
    case_details: dict[str, Any] = {}

    with _destructive_sandbox() as active_runtime:
        runtime = active_runtime
        assert runtime is not None
        sandbox = runtime.require_sandbox()
        assert runtime.destructive_contract is not None
        assert runtime.destructive_contract.active_destructive_project == sandbox.sandbox_project.resolve(strict=False)

        source_before = _source_state(runtime)
        client = runtime.require_client()
        target = _preflight_switchcontainer_assignment_target(client, reflected_uris)
        created_roots: list[str] = []
        target_id: str | None = None
        switch_id: str | None = None
        try:
            switch_container_id = _create_object(
                client,
                target.container_parent_path,
                "SwitchContainer",
                unique_2021_name("WAAPI_2021_SWITCH_", "container"),
            )
            created_roots.append(switch_container_id)
            switch_group_id = _create_object(
                client,
                target.switch_parent_path,
                "SwitchGroup",
                unique_2021_name("WAAPI_2021_SWITCH_", "group"),
            )
            created_roots.append(switch_group_id)
            switch_id = _create_object(
                client,
                switch_group_id,
                "Switch",
                unique_2021_name("WAAPI_2021_SWITCH_", "state"),
            )
            _set_switch_group_reference(client, switch_container_id, switch_group_id)
            target_id = _create_object(
                client,
                switch_container_id,
                "Sound",
                unique_2021_name("WAAPI_2021_SWITCH_", "target"),
            )

            assignments_before = _assignment_records(client, switch_container_id)
            client.call(ADD_ASSIGNMENT_URI, {"child": target_id, "stateOrSwitch": switch_id}, options={})
            assignments_after_add = _assignment_records(client, switch_container_id)
            assert _contains_pair(assignments_after_add, target_id, switch_id), {
                "before": assignments_before,
                "after_add": assignments_after_add,
            }

            client.call(REMOVE_ASSIGNMENT_URI, {"child": target_id, "stateOrSwitch": switch_id}, options={})
            assignments_after_remove = _assignment_records(client, switch_container_id)
            assert not _contains_pair(assignments_after_remove, target_id, switch_id), assignments_after_remove

            _delete_if_present(client, target_id)
            read_after_target_delete = _read_rows(client, target_id)
            assert read_after_target_delete == []

            case_details = {
                "switch_container_id": switch_container_id,
                "switch_group_id": switch_group_id,
                "switch_id": switch_id,
                "target_id": target_id,
                "assignments_before": assignments_before,
                "assignments_after_add": assignments_after_add,
                "assignments_after_remove": assignments_after_remove,
                "read_after_target_delete": read_after_target_delete,
                "preflight": target.as_dict(),
                "setup_helper_uris": [OBJECT_CREATE_URI, OBJECT_SET_REFERENCE_URI, GET_ASSIGNMENTS_URI, OBJECT_DELETE_URI],
                "promoted_assignment_uris": [ADD_ASSIGNMENT_URI, REMOVE_ASSIGNMENT_URI],
                "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                "sandbox_project": str(sandbox.sandbox_project),
                "source_before": source_before,
                "source_after_before_runtime_exit": _source_state(runtime),
                "source_immutability_guard": "Destructive2021SandboxRuntime.assert_source_unchanged runs on exit and verifies source .wproj/.wwu checksum plus mtime",
            }
            target_id = None
        finally:
            if created_roots and target_id is not None:
                try:
                    _remove_assignment_if_present(client, created_roots[0], target_id, switch_id or "")
                except Exception as exc:  # noqa: BLE001 - cleanup evidence must preserve later deletes
                    case_details["assignment_cleanup_error"] = repr(exc)
                _delete_if_present(client, target_id)
                case_details.setdefault("read_after_final_target_cleanup", _read_rows(client, target_id))
            for object_id in reversed(created_roots):
                _delete_if_present(client, object_id)
                case_details.setdefault("read_after_root_cleanup_delete", {})[object_id] = _read_rows(client, object_id)
            if switch_id is not None:
                case_details["read_after_switch_cleanup_delete"] = _read_rows(client, switch_id)

    assert runtime is not None and source_before is not None
    source_after = _source_state(runtime)
    assert source_after == source_before
    case_details["source_after_runtime_exit"] = source_after
    _write_case_evidence(
        "switchcontainer_assignment_add_remove_readback_cleanup",
        [ADD_ASSIGNMENT_URI, REMOVE_ASSIGNMENT_URI],
        case_details,
    )


class SwitchContainerAssignmentTarget:
    def __init__(
        self,
        *,
        container_parent_path: str,
        container_parent_row: Mapping[str, Any],
        switch_parent_path: str,
        switch_parent_row: Mapping[str, Any],
        type_rows: Mapping[str, Mapping[str, Any]],
        schema_preflight: Mapping[str, Any],
    ) -> None:
        self.container_parent_path = container_parent_path
        self.container_parent_row = dict(container_parent_row)
        self.switch_parent_path = switch_parent_path
        self.switch_parent_row = dict(switch_parent_row)
        self.type_rows = {key: dict(value) for key, value in type_rows.items()}
        self.schema_preflight = dict(schema_preflight)

    def as_dict(self) -> dict[str, Any]:
        return {
            "container_parent_path": self.container_parent_path,
            "container_parent_row": self.container_parent_row,
            "switch_parent_path": self.switch_parent_path,
            "switch_parent_row": self.switch_parent_row,
            "type_rows": self.type_rows,
            "schema_preflight": self.schema_preflight,
            "readback_uri": GET_ASSIGNMENTS_URI,
            "source": "live 2021.1 copied-sandbox preflight before switchContainer assignment mutation",
        }


def _preflight_switchcontainer_assignment_target(client: Any, reflected_uris: set[str]) -> SwitchContainerAssignmentTarget:
    _require_reflected(reflected_uris, [OBJECT_GET_URI, OBJECT_GET_TYPES_URI, OBJECT_SET_REFERENCE_URI])
    schema_preflight = {
        ADD_ASSIGNMENT_URI: _schema_preflight(ADD_ASSIGNMENT_URI),
        GET_ASSIGNMENTS_URI: _schema_preflight(GET_ASSIGNMENTS_URI),
        REMOVE_ASSIGNMENT_URI: _schema_preflight(REMOVE_ASSIGNMENT_URI),
    }
    container_parent_rows = _read_by_path(client, ACTOR_MIXER_PARENT, PARENT_FIELDS)
    switch_parent_rows = _read_by_path(client, SWITCH_PARENT, PARENT_FIELDS)
    if len(container_parent_rows) != 1:
        _write_deferred_case_evidence(
            "missing_switchcontainer_parent",
            [ADD_ASSIGNMENT_URI, REMOVE_ASSIGNMENT_URI],
            {
                "reason": "2021.1 copied sandbox did not expose exactly one Actor-Mixer default work unit parent for SwitchContainer fixture creation",
                "parent_path": ACTOR_MIXER_PARENT,
                "rows": container_parent_rows,
            },
        )
        pytest.skip(f"2021.1 copied sandbox SwitchContainer parent was unavailable: {ACTOR_MIXER_PARENT}")
    if len(switch_parent_rows) != 1:
        _write_deferred_case_evidence(
            "missing_switch_group_parent",
            [ADD_ASSIGNMENT_URI, REMOVE_ASSIGNMENT_URI],
            {
                "reason": "2021.1 copied sandbox did not expose exactly one Switches default work unit parent for SwitchGroup fixture creation",
                "parent_path": SWITCH_PARENT,
                "rows": switch_parent_rows,
            },
        )
        pytest.skip(f"2021.1 copied sandbox SwitchGroup parent was unavailable: {SWITCH_PARENT}")
    type_rows = _required_type_rows(client, CREATED_OBJECT_TYPES)
    return SwitchContainerAssignmentTarget(
        container_parent_path=ACTOR_MIXER_PARENT,
        container_parent_row=container_parent_rows[0],
        switch_parent_path=SWITCH_PARENT,
        switch_parent_row=switch_parent_rows[0],
        type_rows=type_rows,
        schema_preflight=schema_preflight,
    )


def _required_type_rows(client: Any, object_types: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    rows = _object_types(client)
    by_type: dict[str, Mapping[str, Any]] = {}
    for object_type in object_types:
        matches = [row for row in rows if row.get("name") == object_type or row.get("type") == object_type]
        if matches:
            by_type[object_type] = matches[0]
    missing = sorted(set(object_types) - set(by_type))
    if missing:
        _write_deferred_case_evidence(
            "missing_switchcontainer_assignment_types",
            [ADD_ASSIGNMENT_URI, REMOVE_ASSIGNMENT_URI],
            {
                "reason": "2021.1 copied sandbox object.getTypes did not report all object types needed for safe sandbox-only assignment fixtures",
                "missing": missing,
                "required": list(object_types),
                "sample_type_rows": rows[:25],
            },
        )
        pytest.skip(f"2021.1 copied sandbox did not report required assignment fixture types: {', '.join(missing)}")
    return by_type


def _schema_preflight(uri: str) -> dict[str, Any]:
    schema = _schema_for(uri)
    args = schema.get("argsSchema", {})
    assert isinstance(args, Mapping), f"{uri} args schema must be a mapping: {schema!r}"
    required = args.get("required", [])
    properties = args.get("properties", {})
    assert isinstance(required, list), f"{uri} required args must be a list: {schema!r}"
    assert isinstance(properties, Mapping), f"{uri} properties must be a mapping: {schema!r}"
    if uri in {ADD_ASSIGNMENT_URI, REMOVE_ASSIGNMENT_URI}:
        assert {"child", "stateOrSwitch"} <= set(required)
        assert {"child", "stateOrSwitch"} <= set(properties)
    elif uri == GET_ASSIGNMENTS_URI:
        assert "id" in required
        assert "id" in properties
    return {"uri": uri, "required_args": required, "properties": sorted(properties)}


def _schema_for(uri: str) -> Mapping[str, Any]:
    payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for entry in payload["schemas"]:
        if entry.get("uri") == uri:
            schema = entry.get("schema")
            assert isinstance(schema, Mapping), f"{uri} schema must be a mapping: {entry!r}"
            return schema
    raise AssertionError(f"missing 2021.1 schema for {uri}")


def _create_object(client: Any, parent: str, object_type: str, name: str) -> str:
    result = client.call(
        OBJECT_CREATE_URI,
        {"parent": parent, "type": object_type, "name": name, "onNameConflict": "fail"},
        options={},
    )
    assert isinstance(result, Mapping), f"object.create must return a mapping: {result!r}"
    object_id = result.get("id")
    assert isinstance(object_id, str) and object_id, f"object.create did not return an id: {result!r}"
    return object_id


def _set_switch_group_reference(client: Any, switch_container_id: str, switch_group_id: str) -> None:
    try:
        client.call(
            OBJECT_SET_REFERENCE_URI,
            {"object": switch_container_id, "reference": SWITCH_REFERENCE, "value": switch_group_id},
            options={},
        )
    except Exception as exc:
        _write_deferred_case_evidence(
            "switch_group_reference_setup_blocked",
            [ADD_ASSIGNMENT_URI, REMOVE_ASSIGNMENT_URI],
            {
                "reason": "2021.1 copied sandbox could not set the SwitchContainer SwitchGroupOrStateGroup reference needed before assignment mutation",
                "switch_container_id": switch_container_id,
                "switch_group_id": switch_group_id,
                "setup_helper_uri": OBJECT_SET_REFERENCE_URI,
                "error": repr(exc),
            },
        )
        pytest.skip("2021.1 copied sandbox SwitchContainer reference setup was blocked")


def _assignment_records(client: Any, switch_container_id: str) -> list[dict[str, Any]]:
    result = client.call(GET_ASSIGNMENTS_URI, {"id": switch_container_id}, options={})
    assert isinstance(result, Mapping), f"getAssignments must return a mapping: {result!r}"
    rows = result.get("return")
    assert isinstance(rows, list), f"getAssignments must return an array: {result!r}"
    records: list[dict[str, Any]] = []
    for row in rows:
        assert isinstance(row, Mapping), row
        record = dict(row)
        record["child"] = _object_arg_id(row.get("child"))
        record["stateOrSwitch"] = _object_arg_id(row.get("stateOrSwitch"))
        records.append(record)
    return records


def _contains_pair(rows: Sequence[Mapping[str, Any]], child_id: str, switch_id: str) -> bool:
    return any(row.get("child") == child_id and row.get("stateOrSwitch") == switch_id for row in rows)


def _object_arg_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        object_id = value.get("id")
        assert isinstance(object_id, str), value
        return object_id
    raise AssertionError(f"unexpected assignment object value: {value!r}")


def _remove_assignment_if_present(client: Any, container_id: str, child_id: str, switch_id: str) -> None:
    if not switch_id:
        return
    if _contains_pair(_assignment_records(client, container_id), child_id, switch_id):
        client.call(REMOVE_ASSIGNMENT_URI, {"child": child_id, "stateOrSwitch": switch_id}, options={})


def _read_rows(client: Any, object_id: str) -> list[Mapping[str, Any]]:
    result = client.call(OBJECT_GET_URI, {"from": {"id": [object_id]}}, options={"return": READBACK_FIELDS})
    if result is None:
        return []
    return _rows(result)


def _read_by_path(client: Any, path: str, fields: list[str]) -> list[Mapping[str, Any]]:
    result = client.call(OBJECT_GET_URI, {"from": {"path": [path]}}, options={"return": fields})
    if result is None:
        return []
    return _rows(result)


def _object_types(client: Any) -> list[Mapping[str, Any]]:
    result = client.call(OBJECT_GET_TYPES_URI, {}, options={})
    if result is None:
        return []
    return _rows(result)


def _rows(result: Any) -> list[Mapping[str, Any]]:
    assert isinstance(result, Mapping), f"WAAPI result must be a mapping: {result!r}"
    rows = result.get("return")
    assert isinstance(rows, list), f"WAAPI result must contain a return array: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _delete_if_present(client: Any, object_id: str) -> None:
    if _read_rows(client, object_id):
        client.call(OBJECT_DELETE_URI, {"object": object_id}, options={})
        assert _read_rows(client, object_id) == []


def _reflected_uris() -> set[str]:
    payload = json.loads(REFLECTED_URI_PATH.read_text(encoding="utf-8"))
    return {str(entry["uri"]) for entry in payload["functions"]}


def _require_reflected(reflected_uris: set[str], uris: list[str]) -> None:
    missing = sorted(uri for uri in uris if uri not in reflected_uris)
    if missing:
        _write_deferred_case_evidence(
            "missing_reflected_uri",
            missing,
            {"reason": "Required 2021.1 URI was not reflected; destructive substitution is forbidden", "missing": missing},
        )
        pytest.skip(f"2021.1 reflected URI(s) unavailable: {', '.join(missing)}")


def _source_state(runtime: Destructive2021SandboxRuntime) -> dict[str, Any]:
    sandbox = runtime.require_sandbox()
    digest, file_count, byte_count = hash_mutation_bearing_project_files(sandbox.source_root)
    return {
        "source_project": str(sandbox.source_project),
        "mtime": sandbox.source_project.stat().st_mtime,
        "project_files_sha256": digest,
        "project_file_count": file_count,
        "project_file_bytes": byte_count,
    }


def _write_case_evidence(case_id: str, uris: list[str], details: Mapping[str, Any]) -> None:
    payload = _evidence_payload(case_id, "passed", uris, details)
    path = _case_evidence_path(case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_task_evidence(case_id, payload)


def _write_deferred_case_evidence(case_id: str, uris: list[str], details: Mapping[str, Any]) -> None:
    payload = _evidence_payload(case_id, "deferred", uris, details)
    path = _case_evidence_path(case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_task_evidence(case_id, payload)


def _evidence_payload(case_id: str, status: str, uris: list[str], details: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": status,
        "version": "2021.1",
        "uris": uris,
        "details": _json_safe(details),
        "copied_sandbox_only": True,
        "cleanup": "assignment is removed and disposable objects are deleted/read back absent before test exit when mutation occurs",
        "exact_destructive_command": EXACT_DESTRUCTIVE_COMMAND,
        "source_project_mutation_allowed": False,
        "sandbox_required": True,
        "recorded_at_unix": int(time.time()),
    }


def _case_evidence_path(case_id: str) -> Path:
    path = (DESTRUCTIVE_EVIDENCE_ROOT / f"{case_id}.json").resolve(strict=False)
    root = DESTRUCTIVE_EVIDENCE_ROOT.resolve(strict=False)
    if not path_is_under(path, root):
        raise AssertionError(f"evidence path must stay under {DESTRUCTIVE_EVIDENCE_ROOT}: {path}")
    return path


def _write_task_evidence(case_id: str, payload: Mapping[str, Any]) -> None:
    TASK_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TASK_EVIDENCE_PATH.is_file():
        current = json.loads(TASK_EVIDENCE_PATH.read_text(encoding="utf-8"))
    else:
        current = {
            "task": "12. Prove 2021.1 switchcontainer assignments in copied destructive sandbox",
            "version": "2021.1",
            "exact_destructive_command": EXACT_DESTRUCTIVE_COMMAND,
            "source_project_mutation_allowed": False,
            "sandbox_required": True,
            "cases": {},
        }
    cases = current.setdefault("cases", {})
    cases[case_id] = _json_safe(payload)
    current["case_count"] = len(cases)
    current["passed_cases"] = sorted(case for case, item in cases.items() if item.get("status") == "passed")
    current["deferred_cases"] = sorted(case for case, item in cases.items() if item.get("status") == "deferred")
    current["recorded_at_unix"] = int(time.time())
    TASK_EVIDENCE_PATH.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))

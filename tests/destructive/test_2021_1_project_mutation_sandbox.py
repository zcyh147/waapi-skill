from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

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

OBJECT_CREATE_URI = "ak.wwise.core.object.create"
OBJECT_DELETE_URI = "ak.wwise.core.object.delete"
OBJECT_GET_URI = "ak.wwise.core.object.get"
OBJECT_GET_TYPES_URI = "ak.wwise.core.object.getTypes"
OBJECT_SET_URI = "ak.wwise.core.object.set"
OBJECT_SET_NOTES_URI = "ak.wwise.core.object.setNotes"
UNDO_BEGIN_GROUP_URI = "ak.wwise.core.undo.beginGroup"
UNDO_END_GROUP_URI = "ak.wwise.core.undo.endGroup"
UNDO_UNDO_URI = "ak.wwise.core.undo.undo"

ACTOR_MIXER_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
ACTOR_MIXER_TYPE = "ActorMixer"
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]
PARENT_FIELDS = ["id", "name", "type", "path"]
REFLECTED_URI_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "resources" / "manifest" / "2021.1" / "functions.json"
REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "wwise-2021-waapi-integration-coverage"
DESTRUCTIVE_EVIDENCE_ROOT = EVIDENCE_ROOT / "destructive"
TASK_EVIDENCE_PATH = EVIDENCE_ROOT / "task-10-object-crud.json"
EXACT_DESTRUCTIVE_COMMAND = (
    'WWISE_VERSION=2021.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" '
    'WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" '
    "WWISE_SANDBOX_ROOT=.waapi-skill-state/runtime/wwise-waapi-sandboxes/2021.1 WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 "
    "python -m pytest tests/destructive/test_2021_1_project_mutation_sandbox.py -q"
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
def test_2021_object_create_setnotes_delete_readbacks_against_copied_sandbox() -> None:
    reflected_uris = _reflected_uris()
    _record_absent_reflected_candidates(reflected_uris)
    _require_reflected(reflected_uris, [OBJECT_CREATE_URI, OBJECT_SET_NOTES_URI, OBJECT_DELETE_URI])
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
        target = _preflight_actor_mixer_mutation_target(client, reflected_uris)
        object_id: str | None = None
        try:
            name = unique_2021_name("WAAPI_2021_MUTATION_", "actor")
            notes = f"2021.1 destructive sandbox behavior notes {name}"
            object_id = _create_object(client, target.parent_path, target.object_type, name)
            created = _read_one(client, object_id)
            assert created["id"] == object_id
            assert created["name"] == name
            assert str(created["path"]).startswith(f"{target.parent_path}\\")

            client.call(OBJECT_SET_NOTES_URI, {"object": object_id, "value": notes}, options={})
            updated = _read_one(client, object_id)
            assert updated["notes"] == notes

            client.call(OBJECT_DELETE_URI, {"object": object_id}, options={})
            read_after_delete = _read_rows(client, object_id)
            assert read_after_delete == []

            case_details = {
                "created_name": name,
                "created_id": object_id,
                "created_path": created["path"],
                "created_readback_type": created.get("type"),
                "notes_readback": updated["notes"],
                "read_after_delete": read_after_delete,
                "preflight": target.as_dict(),
                "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                "sandbox_project": str(sandbox.sandbox_project),
                "source_before": source_before,
                "source_after_before_runtime_exit": _source_state(runtime),
                "source_immutability_guard": "Destructive2021SandboxRuntime.assert_source_unchanged runs on exit and verifies source .wproj/.wwu checksum plus mtime",
            }
            _write_case_evidence(
                "object_create_setnotes_delete_readback",
                [OBJECT_CREATE_URI, OBJECT_SET_NOTES_URI, OBJECT_DELETE_URI],
                case_details,
            )
            object_id = None
        finally:
            if object_id is not None:
                _delete_if_present(client, object_id)

    assert runtime is not None and source_before is not None
    source_after = _source_state(runtime)
    assert source_after == source_before
    case_details["source_after_runtime_exit"] = source_after
    _write_case_evidence(
        "object_create_setnotes_delete_readback",
        [OBJECT_CREATE_URI, OBJECT_SET_NOTES_URI, OBJECT_DELETE_URI],
        case_details,
    )


@pytest.mark.live
@pytest.mark.destructive
def test_2021_undo_begin_end_group_records_supported_group_behavior_without_undo_uri() -> None:
    reflected_uris = _reflected_uris()
    _record_absent_reflected_candidates(reflected_uris)
    _require_reflected(reflected_uris, [OBJECT_CREATE_URI, OBJECT_DELETE_URI, UNDO_BEGIN_GROUP_URI, UNDO_END_GROUP_URI])
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
        target = _preflight_actor_mixer_mutation_target(client, reflected_uris)
        object_id: str | None = None
        group_open = False
        try:
            name = unique_2021_name("WAAPI_2021_UNDO_GROUP_", "actor")
            client.call(UNDO_BEGIN_GROUP_URI, {}, options={})
            group_open = True
            object_id = _create_object(client, target.parent_path, target.object_type, name)
            created = _read_one(client, object_id)
            assert created["id"] == object_id
            assert created["name"] == name

            client.call(UNDO_END_GROUP_URI, {"displayName": f"2021.1 {name}"}, options={})
            group_open = False
            after_end_group = _read_one(client, object_id)
            assert after_end_group["name"] == name

            client.call(OBJECT_DELETE_URI, {"object": object_id}, options={})
            read_after_cleanup_delete = _read_rows(client, object_id)
            assert read_after_cleanup_delete == []
            case_details = {
                "created_name": name,
                "created_id": object_id,
                "created_path": created["path"],
                "created_readback_type": created.get("type"),
                "read_after_end_group": after_end_group,
                "read_after_cleanup_delete": read_after_cleanup_delete,
                "undo_rollback_status": "deferred: ak.wwise.core.undo.undo is not reflected in 2021.1 functions.json",
                "preflight": target.as_dict(),
                "active_destructive_project": str(runtime.destructive_contract.active_destructive_project),
                "sandbox_project": str(sandbox.sandbox_project),
                "source_before": source_before,
                "source_after_before_runtime_exit": _source_state(runtime),
                "source_immutability_guard": "Destructive2021SandboxRuntime.assert_source_unchanged runs on exit and verifies source .wproj/.wwu checksum plus mtime",
            }
            _write_case_evidence(
                "undo_begin_end_group_create_cleanup_delete",
                [UNDO_BEGIN_GROUP_URI, UNDO_END_GROUP_URI, OBJECT_CREATE_URI, OBJECT_DELETE_URI],
                case_details,
            )
            object_id = None
        finally:
            if group_open:
                try:
                    client.call("ak.wwise.core.undo.cancelGroup", {}, options={})
                except BaseException:
                    pass
            if object_id is not None:
                _delete_if_present(client, object_id)

    assert runtime is not None and source_before is not None
    source_after = _source_state(runtime)
    assert source_after == source_before
    case_details["source_after_runtime_exit"] = source_after
    _write_case_evidence(
        "undo_begin_end_group_create_cleanup_delete",
        [UNDO_BEGIN_GROUP_URI, UNDO_END_GROUP_URI, OBJECT_CREATE_URI, OBJECT_DELETE_URI],
        case_details,
    )


class MutationTarget:
    def __init__(self, *, parent_path: str, parent_row: Mapping[str, Any], object_type: str, type_row: Mapping[str, Any]) -> None:
        self.parent_path = parent_path
        self.parent_row = dict(parent_row)
        self.object_type = object_type
        self.type_row = dict(type_row)

    def as_dict(self) -> dict[str, Any]:
        return {
            "parent_path": self.parent_path,
            "parent_row": self.parent_row,
            "object_type": self.object_type,
            "type_row": self.type_row,
            "source": "live 2021.1 copied-sandbox preflight before object.create/object.setNotes/object.delete/undo group mutation",
        }


def _preflight_actor_mixer_mutation_target(client: Any, reflected_uris: set[str]) -> MutationTarget:
    _require_reflected(reflected_uris, [OBJECT_GET_URI, OBJECT_GET_TYPES_URI])
    parent_rows = _read_by_path(client, ACTOR_MIXER_PARENT, PARENT_FIELDS)
    if len(parent_rows) != 1:
        _write_deferred_case_evidence(
            "missing_actor_mixer_default_work_unit",
            [OBJECT_CREATE_URI, OBJECT_SET_NOTES_URI, OBJECT_DELETE_URI],
            {
                "reason": "2021.1 copied sandbox did not expose exactly one writable Actor-Mixer default work unit parent before mutation",
                "parent_path": ACTOR_MIXER_PARENT,
                "rows": parent_rows,
            },
        )
        pytest.skip(f"2021.1 copied sandbox writable parent was unavailable: {ACTOR_MIXER_PARENT}")
    type_rows = _object_types(client)
    actor_rows = [row for row in type_rows if row.get("name") == ACTOR_MIXER_TYPE or row.get("type") == ACTOR_MIXER_TYPE]
    if not actor_rows:
        _write_deferred_case_evidence(
            "missing_actor_mixer_type",
            [OBJECT_CREATE_URI, OBJECT_SET_NOTES_URI, OBJECT_DELETE_URI],
            {
                "reason": "2021.1 copied sandbox object.getTypes did not report ActorMixer before mutation",
                "object_type": ACTOR_MIXER_TYPE,
                "sample_type_rows": type_rows[:25],
            },
        )
        pytest.skip("2021.1 copied sandbox did not report ActorMixer as a creatable object type")
    return MutationTarget(
        parent_path=ACTOR_MIXER_PARENT,
        parent_row=parent_rows[0],
        object_type=ACTOR_MIXER_TYPE,
        type_row=actor_rows[0],
    )


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


def _read_one(client: Any, object_id: str) -> Mapping[str, Any]:
    rows = _read_rows(client, object_id)
    assert len(rows) == 1, f"expected one object for {object_id}, got {rows!r}"
    return rows[0]


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


def _record_absent_reflected_candidates(reflected_uris: set[str]) -> None:
    absent = [uri for uri in [OBJECT_SET_URI, UNDO_UNDO_URI] if uri not in reflected_uris]
    if not absent:
        return
    _write_deferred_case_evidence(
        "absent_2021_1_newer_mutation_uris",
        absent,
        {
            "reason": "Task 10 must not test newer substitute URIs when these candidates are absent from 2021.1 reflection",
            "absent_from_reflection": absent,
            "reflection_source": "resources/manifest/2021.1/functions.json",
        },
    )


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
        "cleanup": "created objects are deleted and read back absent before test exit when mutation occurs",
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
            "task": "10. Prove 2021.1 object CRUD and undo in copied destructive sandbox",
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

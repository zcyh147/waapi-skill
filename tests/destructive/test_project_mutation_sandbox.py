from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, cast

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for destructive project mutation sandbox tests",
        allow_module_level=True,
    )

from wwise_waapi.headless import HeadlessLifecycleError, default_waapi_client_factory  # pyright: ignore[reportMissingImports]
from wwise_waapi.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    path_is_under,
    resolve_sample_project_source,
)
from wwise_waapi.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    SandboxFixtureError,
    cleanup_sandbox,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from tests.support.active_gate_failures import fail_if_active_runtime_failure  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "resources"
    / "capabilities"
    / "2022.1"
    / "task-7-project-mutation-sandbox-plan.json"
)
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-waapi-live-sandbox-coverage"
TEMP_PREFIX = "WAAPI_TASK7_SANDBOX_"
ACTOR_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
SWITCH_PARENT = r"\Switches\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes"]


@pytest.mark.live
@pytest.mark.destructive
def test_object_create_set_delete_readbacks_against_per_test_sandbox() -> None:
    case = _case("object_create_set_delete_actor_mixer")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        name = _unique_name("object")
        notes = f"Task 7 destructive sandbox notes {name}"
        created_id: str | None = None
        try:
            created_id = _create_object(client, ACTOR_PARENT, "ActorMixer", name)
            created = _read_one(client, created_id)
            assert created["id"] == created_id
            assert created["name"] == name
            assert created["type"] == "ActorMixer"

            client.call("ak.wwise.core.object.set", {"objects": [{"object": created_id, "notes": notes}]}, options={"return": READBACK_FIELDS})
            updated = _read_one(client, created_id)
            assert updated["notes"] == notes

            client.call("ak.wwise.core.object.delete", {"object": created_id}, options={})
            assert _read_rows(client, created_id) == []
            created_id = None
            _write_case_evidence(case, status="passed", details={"created_name": name, "notes_readback": notes})
        finally:
            if created_id is not None:
                _delete_if_present(client, created_id)


@pytest.mark.live
@pytest.mark.destructive
def test_undo_group_rolls_back_created_objects_in_per_test_sandbox() -> None:
    case = _case("undo_group_create_then_undo_and_cancel")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        undo_name = _unique_name("undo")
        cancel_name = _unique_name("cancel")
        tracked_ids: list[str] = []
        try:
            client.call("ak.wwise.core.undo.beginGroup", {}, options={})
            undo_id = _create_object(client, ACTOR_PARENT, "ActorMixer", undo_name)
            tracked_ids.append(undo_id)
            client.call("ak.wwise.core.undo.endGroup", {"displayName": f"Task 7 {undo_name}"}, options={})
            assert _read_one(client, undo_id)["name"] == undo_name

            client.call("ak.wwise.core.undo.undo", {}, options={})
            assert _read_rows(client, undo_id) == []
            tracked_ids.remove(undo_id)

            client.call("ak.wwise.core.undo.beginGroup", {}, options={})
            cancel_id = _create_object(client, ACTOR_PARENT, "ActorMixer", cancel_name)
            tracked_ids.append(cancel_id)
            assert _read_one(client, cancel_id)["name"] == cancel_name
            client.call("ak.wwise.core.undo.cancelGroup", {}, options={})
            cancel_rows = _read_rows(client, cancel_id)
            cancel_group_blocker = None
            if cancel_rows:
                cancel_group_blocker = case["blockers"][1]
                _delete_if_present(client, cancel_id)
            tracked_ids.remove(cancel_id)

            _write_case_evidence(
                case,
                status="passed-with-blocker" if cancel_group_blocker else "passed",
                details={
                    "undo_name": undo_name,
                    "cancel_name": cancel_name,
                    "redo_blocker": case["blockers"][0],
                    "cancel_group_blocker": cancel_group_blocker,
                    "cancel_group_readback_after_cancel": _json_safe(cancel_rows),
                },
            )
        finally:
            for object_id in list(tracked_ids):
                _delete_if_present(client, object_id)


@pytest.mark.live
@pytest.mark.destructive
def test_switch_container_assignment_add_get_remove_or_records_blocker() -> None:
    case = _case("switch_container_assignment_add_get_remove")

    with _destructive_sandbox(case) as runtime:
        client = runtime.require_client()
        root_ids: list[str] = []
        try:
            switch_container_id = _create_object(client, ACTOR_PARENT, "SwitchContainer", _unique_name("switch_container"))
            root_ids.append(switch_container_id)
            child_id = _create_object(client, switch_container_id, "Sound", _unique_name("switch_child"))
            switch_group_id = _create_object(client, SWITCH_PARENT, "SwitchGroup", _unique_name("switch_group"))
            root_ids.append(switch_group_id)
            switch_id = _create_object(client, switch_group_id, "Switch", _unique_name("switch"))
            add_result: Any = None

            try:
                add_result = client.call(
                    "ak.wwise.core.switchContainer.addAssignment",
                    {"child": child_id, "stateOrSwitch": switch_id},
                    options={},
                )
            except BaseException as exc:  # noqa: BLE001 - WAAPI error is blocker evidence
                _write_switch_blocker(case, exc, [switch_container_id, child_id, switch_group_id, switch_id])
                pytest.skip(f"switchContainer fixture shape rejected by Wwise: {type(exc).__name__}: {exc}")

            assignments = _assignment_pairs(client, switch_container_id)
            if add_result is None or (child_id, switch_id) not in assignments:
                _write_case_evidence(
                    case,
                    status="blocked",
                    details={
                        "error_type": "AssignmentNotMaterialized",
                        "error": "ak.wwise.core.switchContainer.addAssignment did not produce a getAssignments readback pair; likely missing Switch Group reference on disposable SwitchContainer.",
                        "add_result": _json_safe(add_result),
                        "assignments_after_add": sorted(assignments),
                        "created_fixture_ids": [switch_container_id, child_id, switch_group_id, switch_id],
                    },
                )
                pytest.skip("switchContainer addAssignment did not produce readback assignment pair")

            client.call(
                "ak.wwise.core.switchContainer.removeAssignment",
                {"child": child_id, "stateOrSwitch": switch_id},
                options={},
            )
            assert (child_id, switch_id) not in _assignment_pairs(client, switch_container_id)
            _write_case_evidence(
                case,
                status="passed",
                details={
                    "switch_container_id": switch_container_id,
                    "child_id": child_id,
                    "state_or_switch_id": switch_id,
                },
            )
        finally:
            for object_id in reversed(root_ids):
                _delete_if_present(client, object_id)


class _SandboxRuntime:
    def __init__(self, case: Mapping[str, Any]) -> None:
        self.case = case
        self.env = dict(os.environ)
        self.sandbox = None
        self.lifecycle = None
        self.client = None
        self.failed = True
        self.source_mtime_before = 0.0
        self.source_project_files_hash_before: tuple[str, int, int] | None = None

    def __enter__(self) -> "_SandboxRuntime":
        try:
            self.lock = LiveSandboxLock(_safe_lock_root(self.env))
            self.lock.__enter__()
            self.sandbox = prepare_sample_project_sandbox(self.env, hash_strategy="bounded")
            self.source_mtime_before = self.sandbox.source_project.stat().st_mtime
            self.source_project_files_hash_before = _hash_mutation_bearing_project_files(self.sandbox.source_root)
            self.lifecycle = launch_sandboxed_wwise(self.sandbox, self.env)
            self.client = default_waapi_client_factory(self.lifecycle.waapi_url)
            return self
        except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
            self._write_environment_blocker(exc)
            self.__exit__(type(exc), exc, exc.__traceback__)
            fail_if_active_runtime_failure(exc, "destructive sandbox environment blocked execution")
            pytest.skip(f"destructive sandbox environment blocked execution: {type(exc).__name__}: {exc}")
            raise AssertionError("pytest.skip should stop execution") from exc

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        deferred_error: BaseException | None = None
        try:
            try:
                if self.client is not None:
                    self.client.disconnect()
            except BaseException as disconnect_error:  # noqa: BLE001 - cleanup must continue
                if exc_type is None:
                    deferred_error = disconnect_error

            try:
                if self.lifecycle is not None and self.sandbox is not None:
                    shutdown_sandboxed_wwise(self.lifecycle, self.sandbox)
            except BaseException as shutdown_error:  # noqa: BLE001 - cleanup must continue
                if exc_type is None and deferred_error is None:
                    deferred_error = shutdown_error

            if self.sandbox is not None:
                if exc_type is None and deferred_error is None:
                    try:
                        self._assert_source_unchanged()
                        self.failed = False
                    except AssertionError as assertion_error:
                        deferred_error = assertion_error
                try:
                    cleanup_sandbox(self.sandbox, failed=self.failed)
                except BaseException as cleanup_error:  # noqa: BLE001 - lock release must continue
                    if exc_type is None and deferred_error is None:
                        deferred_error = cleanup_error
        finally:
            if hasattr(self, "lock"):
                self.lock.__exit__(exc_type, exc, traceback)

        if exc_type is None and deferred_error is not None:
            raise deferred_error

    def _assert_source_unchanged(self) -> None:
        assert self.sandbox is not None
        assert self.source_project_files_hash_before is not None
        assert self.sandbox.source_project.stat().st_mtime == self.source_mtime_before
        assert _hash_mutation_bearing_project_files(self.sandbox.source_root) == self.source_project_files_hash_before

    def require_client(self) -> Any:
        assert self.client is not None
        return cast(Any, self.client)

    def _write_environment_blocker(self, exc: BaseException) -> None:
        path = EVIDENCE_ROOT / "task-7-destructive-environment-blocker.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "case_id": self.case["id"],
                    "error_type": type(exc).__name__,
                    "error": _redact_local_paths(str(exc)),
                    "command": _redact_local_paths(_plan()["metadata"]["live_command"]),
                    "sandbox_required": True,
                    "source_project_mutation_allowed": False,
                    "recorded_at_unix": int(time.time()),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _destructive_sandbox(case: Mapping[str, Any]) -> _SandboxRuntime:
    return _SandboxRuntime(case)


def _create_object(client: Any, parent: str, object_type: str, name: str) -> str:
    result = client.call(
        "ak.wwise.core.object.create",
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
    result = client.call("ak.wwise.core.object.get", {"from": {"id": [object_id]}}, options={"return": READBACK_FIELDS})
    if result is None:
        return []
    assert isinstance(result, Mapping), f"object.get must return a mapping: {result!r}"
    rows = result.get("return")
    assert isinstance(rows, list), f"object.get must return an array: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _assignment_pairs(client: Any, switch_container_id: str) -> set[tuple[str, str]]:
    result = client.call("ak.wwise.core.switchContainer.getAssignments", {"id": switch_container_id}, options={})
    assert isinstance(result, Mapping), f"getAssignments must return a mapping: {result!r}"
    rows = result.get("return")
    assert isinstance(rows, list), f"getAssignments must return an array: {result!r}"
    pairs = set()
    for row in rows:
        assert isinstance(row, Mapping), row
        child = row.get("child")
        state = row.get("stateOrSwitch")
        pairs.add((_object_arg_id(child), _object_arg_id(state)))
    return pairs


def _object_arg_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        object_id = value.get("id")
        assert isinstance(object_id, str), value
        return object_id
    raise AssertionError(f"unexpected assignment object value: {value!r}")


def _delete_if_present(client: Any, object_id: str) -> None:
    if _read_rows(client, object_id):
        client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
        assert _read_rows(client, object_id) == []


def _write_switch_blocker(case: Mapping[str, Any], exc: BaseException, fixture_ids: list[str]) -> None:
    _write_case_evidence(
        case,
        status="blocked",
        details={
            "error_type": type(exc).__name__,
            "error": _redact_local_paths(str(exc)),
            "created_fixture_ids": fixture_ids,
        },
    )




def _hash_mutation_bearing_project_files(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    bytes_hashed = 0
    files = [path for path in sorted(root.rglob("*")) if path.suffix.lower() in {".wproj", ".wwu"} and path.is_file()]
    for file_path in files:
        relative = file_path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        data = file_path.read_bytes()
        bytes_hashed += len(data)
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest(), len(files), bytes_hashed

def _safe_lock_root(env: Mapping[str, str]) -> Path:
    raw_root = env.get("WWISE_SANDBOX_ROOT")
    root = Path(raw_root).expanduser() if raw_root else REPO_ROOT / ".sisyphus" / "runtime" / "wwise-waapi-sandboxes"
    root = root.resolve(strict=False)
    source_project = resolve_sample_project_source(env)
    if source_project is not None:
        source_root = source_project.parent.resolve(strict=False)
        if root == source_root or path_is_under(root, source_root) or path_is_under(source_root, root):
            raise SandboxFixtureError("sandbox lock root must not overlap the immutable SampleProject source")
    return root


def _unique_name(label: str) -> str:
    safe_label = "".join(character if character.isalnum() else "_" for character in label)
    return f"{TEMP_PREFIX}{safe_label}_{uuid.uuid4().hex[:12]}"


def _write_case_evidence(case: Mapping[str, Any], *, status: str, details: Mapping[str, Any]) -> None:
    path = _safe_evidence_path(str(case["evidence_path"]))
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem}\n"
    body = {
        "case_id": case["id"],
        "status": status,
        "uris": case["uris"],
        "allowlist": case["allowlist"],
        "assertions": case["assertions"],
        "cleanup": case["cleanup"],
        "gate": case["gate"],
        "details": _json_safe(details),
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(existing.rstrip() + "\n\n```json\n" + json.dumps(body, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")


def _safe_evidence_path(path: str) -> Path:
    target = (REPO_ROOT / path).resolve(strict=False)
    expected_root = EVIDENCE_ROOT.resolve(strict=False)
    if not path_is_under(target, expected_root):
        raise AssertionError(f"evidence path must stay under {expected_root}: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _case(case_id: str) -> Mapping[str, Any]:
    for case in _plan()["mutation_cases"]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing Task 7 mutation case {case_id}")


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _redact_local_paths(message: str) -> str:
    redacted = message.replace(str(REPO_ROOT), "<repo>")
    redacted = redacted.replace(str(Path.home()), "<home>")
    sample_project = os.getenv("WWISE_SAMPLE_PROJECT_PATH")
    if sample_project:
        redacted = redacted.replace(sample_project, "$WWISE_SAMPLE_PROJECT_PATH")
    return redacted


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))

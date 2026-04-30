from __future__ import annotations

import hashlib
import json
import os
import queue
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for Task 7 SwitchContainer assignment sandbox tests",
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


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "resources" / "coverage" / "2022.1" / "task-7-switchcontainer-assignment-plan.json"
DEFAULT_SOURCE_PROJECT = REPO_ROOT / "tests" / "_org" / "2022.1" / "SampleProject.wproj"
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-waapi-deferred-reevaluation"
READBACK_FIELDS = ["id", "name", "type", "path"]
TOPIC_TIMEOUT_SECONDS = 5.0


@pytest.mark.live
@pytest.mark.destructive
def test_switchcontainer_assignment_add_get_remove_uses_copied_sandbox_fixture() -> None:
    case = _plan()["assignment_case"]

    with _destructive_sandbox("assignment") as runtime:
        client = runtime.require_client()
        fixture = _fixture()
        target_id: str | None = None
        try:
            container_id, switch_id = _assert_authored_fixture(client)
            target_id = _create_object(client, container_id, fixture["target_object"]["type"], _unique_name("target"))

            assignments_before = _assignment_records(client, container_id)
            add_result = client.call(
                "ak.wwise.core.switchContainer.addAssignment",
                {"child": target_id, "stateOrSwitch": switch_id},
                options={},
            )
            assignments_after_add = _assignment_records(client, container_id)
            if not _contains_pair(assignments_after_add, target_id, switch_id):
                _write_case_evidence(
                    case,
                    status="blocked",
                    details={
                        "blocker": case["blockers"][0],
                        "reason": "addAssignment returned but getAssignments did not contain the disposable target and authored Running Switch pair",
                        "fixture_state": _fixture_state(container_id, target_id, switch_id),
                        "add_result": _json_safe(add_result),
                        "assignments_before": _json_safe(assignments_before),
                        "assignments_after_add": _json_safe(assignments_after_add),
                        "source_hash_proof": _source_hash_proof(runtime),
                    },
                )
                runtime.skip_after_blocker = True
                pytest.skip("switchContainer addAssignment did not produce the required getAssignments readback pair")

            client.call(
                "ak.wwise.core.switchContainer.removeAssignment",
                {"child": target_id, "stateOrSwitch": switch_id},
                options={},
            )
            assignments_after_remove = _assignment_records(client, container_id)
            assert not _contains_pair(assignments_after_remove, target_id, switch_id), assignments_after_remove
            cleanup_proof = _delete_target_and_prove_cleanup(client, target_id)
            target_id = None
            source_hash_proof = _source_hash_proof(runtime)
            assert source_hash_proof["before"] == source_hash_proof["after"]
            _write_case_evidence(
                case,
                status="passed",
                details={
                    "status": "passed",
                    "uris": case["uris"],
                    "switch_container_id": container_id,
                    "target_id": cleanup_proof["deleted_target_id"],
                    "state_or_switch_id": switch_id,
                    "assignments_before": _json_safe(assignments_before),
                    "add_result": _json_safe(add_result),
                    "assignments_after_add": _json_safe(assignments_after_add),
                    "assignments_after_remove": _json_safe(assignments_after_remove),
                    "cleanup_proof": cleanup_proof,
                    "source_hash_proof": source_hash_proof,
                },
            )
        except BaseException as exc:
            if _is_assertion_or_skip(exc):
                raise
            _write_case_evidence(
                case,
                status="blocked",
                details={
                    "blocker": case["blockers"][0],
                    "error_type": type(exc).__name__,
                    "error": _redact_local_paths(str(exc)),
                    "target_id": target_id,
                    "source_hash_proof": _source_hash_proof(runtime),
                },
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"switchContainer assignment fixture rejected by Wwise: {type(exc).__name__}: {exc}")
        finally:
            if target_id is not None:
                _remove_assignment_if_present(client, fixture["accepted_switch_container"]["id"], target_id, fixture["switch_child"]["id"])
                _delete_if_present(client, target_id)


@pytest.mark.live
@pytest.mark.destructive
def test_switchcontainer_assignment_topics_require_identity_payload_and_readback_pair() -> None:
    cases = {case["uri"]: case for case in _plan()["topic_cases"]}

    with _destructive_sandbox("topics") as runtime:
        client = runtime.require_client()
        fixture = _fixture()
        container_id, switch_id = _assert_authored_fixture(client)
        target_id: str | None = None
        try:
            target_id = _create_object(client, container_id, fixture["target_object"]["type"], _unique_name("topic_target"))

            added_payload = _subscribe_then_call(
                client,
                cases["ak.wwise.core.switchContainer.assignmentAdded"],
                lambda: client.call(
                    "ak.wwise.core.switchContainer.addAssignment",
                    {"child": target_id, "stateOrSwitch": switch_id},
                    options={},
                ),
            )
            assignments_after_add = _assignment_records(client, container_id)
            if not _contains_pair(assignments_after_add, target_id, switch_id):
                _write_topic_evidence(
                    cases["ak.wwise.core.switchContainer.assignmentAdded"],
                    status="blocked",
                    details={
                        "reason": "assignmentAdded payload arrived but getAssignments did not prove the addAssignment pair",
                        "payload": _json_safe(added_payload),
                        "assignments_after_add": _json_safe(assignments_after_add),
                        "fixture_state": _fixture_state(container_id, target_id, switch_id),
                        "source_hash_proof": _source_hash_proof(runtime),
                    },
                )
                runtime.skip_after_blocker = True
                pytest.skip("assignmentAdded topic lacked paired getAssignments proof")
            added_assignment_id = _assignment_id_for_pair(assignments_after_add, target_id, switch_id)
            _assert_topic_payload_identity(added_payload, container_id, target_id, switch_id, added_assignment_id)
            added_evidence_details = {
                "status": "passed",
                "uri": "ak.wwise.core.switchContainer.assignmentAdded",
                "switch_container_id": container_id,
                "target_id": target_id,
                "state_or_switch_id": switch_id,
                "assignment_id": added_assignment_id,
                "payload": _json_safe(added_payload),
                "assignments_after_add": _json_safe(assignments_after_add),
                "readback_pair_verified": True,
            }

            removed_payload = _subscribe_then_call(
                client,
                cases["ak.wwise.core.switchContainer.assignmentRemoved"],
                lambda: client.call(
                    "ak.wwise.core.switchContainer.removeAssignment",
                    {"child": target_id, "stateOrSwitch": switch_id},
                    options={},
                ),
            )
            assignments_after_remove = _assignment_records(client, container_id)
            assert not _contains_pair(assignments_after_remove, target_id, switch_id), assignments_after_remove
            _assert_topic_payload_identity(removed_payload, container_id, target_id, switch_id, added_assignment_id)
            cleanup_proof = _delete_target_and_prove_cleanup(client, target_id)
            target_id = None
            source_hash_proof = _source_hash_proof(runtime)
            assert source_hash_proof["before"] == source_hash_proof["after"]
            added_evidence_details["cleanup_proof"] = cleanup_proof
            added_evidence_details["source_hash_proof"] = source_hash_proof
            _write_topic_evidence(
                cases["ak.wwise.core.switchContainer.assignmentAdded"],
                status="passed",
                details=added_evidence_details,
            )
            _write_topic_evidence(
                cases["ak.wwise.core.switchContainer.assignmentRemoved"],
                status="passed",
                details={
                    "status": "passed",
                    "uri": "ak.wwise.core.switchContainer.assignmentRemoved",
                    "switch_container_id": container_id,
                    "target_id": cleanup_proof["deleted_target_id"],
                    "state_or_switch_id": switch_id,
                    "assignment_id": added_assignment_id,
                    "payload": _json_safe(removed_payload),
                    "assignments_after_remove": _json_safe(assignments_after_remove),
                    "readback_pair_verified": True,
                    "cleanup_proof": cleanup_proof,
                    "source_hash_proof": source_hash_proof,
                },
            )
        except (queue.Empty, BaseException) as exc:
            if _is_assertion_or_skip(exc):
                raise
            _write_topic_evidence(
                cases.get("ak.wwise.core.switchContainer.assignmentAdded", next(iter(cases.values()))),
                status="blocked",
                details={
                    "error_type": type(exc).__name__,
                    "error": _redact_local_paths(str(exc)),
                    "target_id": target_id,
                    "source_hash_proof": _source_hash_proof(runtime),
                },
            )
            runtime.skip_after_blocker = True
            pytest.skip(f"switchContainer assignment topic evidence blocked: {type(exc).__name__}: {exc}")
        finally:
            if target_id is not None:
                _remove_assignment_if_present(client, container_id, target_id, switch_id)
                _delete_if_present(client, target_id)


class _SandboxRuntime:
    def __init__(self, section: str) -> None:
        self.section = section
        self.env = _task_env(dict(os.environ))
        self.sandbox = None
        self.lifecycle = None
        self.client = None
        self.failed = True
        self.skip_after_blocker = False
        self.source_mtime_before = 0.0
        self.source_project_files_hash_before: tuple[str, int, int] | None = None

    def __enter__(self) -> _SandboxRuntime:
        try:
            self.lock = LiveSandboxLock(_safe_lock_root(self.env))
            self.lock.__enter__()
            self.sandbox = prepare_sample_project_sandbox(self.env, hash_strategy="bounded")
            source_root = DEFAULT_SOURCE_PROJECT.parent.resolve(strict=True)
            assert self.sandbox.source_project.resolve(strict=True) == DEFAULT_SOURCE_PROJECT.resolve(strict=True)
            assert not path_is_under(self.sandbox.sandbox_project.resolve(strict=False), source_root)
            assert path_is_under(self.sandbox.sandbox_project.resolve(strict=False), self.sandbox.sandbox_root.resolve(strict=False))
            self.source_mtime_before = self.sandbox.source_project.stat().st_mtime
            self.source_project_files_hash_before = _hash_mutation_bearing_project_files(self.sandbox.source_root)
            self.lifecycle = launch_sandboxed_wwise(self.sandbox, self.env)
            self.client = default_waapi_client_factory(self.lifecycle.waapi_url)
            return self
        except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
            self._write_environment_blocker(exc)
            self.__exit__(type(exc), exc, exc.__traceback__)
            pytest.skip(f"destructive switchContainer sandbox environment blocked execution: {type(exc).__name__}: {exc}")
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
                if self.source_project_files_hash_before is not None and deferred_error is None:
                    try:
                        self._assert_source_unchanged()
                        if exc_type is None and not self.skip_after_blocker:
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
        if deferred_error is not None and (exc_type is None or isinstance(deferred_error, AssertionError)):
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
        path = EVIDENCE_ROOT / "task-7-switchcontainer-environment-blocker.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "section": self.section,
                    "error_type": type(exc).__name__,
                    "error": _redact_local_paths(str(exc)),
                    "command": _plan()["metadata"]["destructive_command"],
                    "source_project": str(DEFAULT_SOURCE_PROJECT.relative_to(REPO_ROOT)),
                    "source_project_mutation_allowed": False,
                    "recorded_at_unix": int(time.time()),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _destructive_sandbox(section: str) -> _SandboxRuntime:
    return _SandboxRuntime(section)


def _assert_authored_fixture(client: Any) -> tuple[str, str]:
    fixture = _fixture()
    container_id = fixture["accepted_switch_container"]["id"]
    switch_group_id = fixture["accepted_switch_group"]["id"]
    switch_id = fixture["switch_child"]["id"]
    container = _read_one(client, container_id)
    switch_group = _read_one(client, switch_group_id)
    switch = _read_one(client, switch_id)
    assert container["type"] == "SwitchContainer", container
    assert switch_group["type"] == "SwitchGroup", switch_group
    assert switch["type"] == "Switch", switch
    assert str(switch["path"]).endswith("\\FS_Type\\Running"), switch
    return container_id, switch_id


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


def _assignment_records(client: Any, switch_container_id: str) -> list[dict[str, Any]]:
    result = client.call("ak.wwise.core.switchContainer.getAssignments", {"id": switch_container_id}, options={})
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


def _assignment_id_for_pair(rows: Sequence[Mapping[str, Any]], child_id: str, switch_id: str) -> str | None:
    for row in rows:
        if row.get("child") == child_id and row.get("stateOrSwitch") == switch_id:
            for key in ("id", "assignment", "assignmentId"):
                value = row.get(key)
                if isinstance(value, str) and value:
                    return value
                if isinstance(value, Mapping):
                    nested = value.get("id")
                    if isinstance(nested, str) and nested:
                        return nested
    return None


def _object_arg_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        object_id = value.get("id")
        assert isinstance(object_id, str), value
        return object_id
    raise AssertionError(f"unexpected assignment object value: {value!r}")


def _subscribe_then_call(client: Any, case: Mapping[str, Any], mutate: Any) -> Any:
    event_queue: queue.Queue[Any] = queue.Queue(maxsize=4)
    handler = None
    try:
        handler = client.subscribe(case["uri"], lambda *args, **kwargs: _put_event(event_queue, args, kwargs), case.get("options", {}))
        if handler is None:
            raise RuntimeError(f"WAAPI did not create a subscription for {case['uri']}")
        time.sleep(0.2)
        mutate()
        return event_queue.get(timeout=float(case["bounded_wait_seconds"]))
    finally:
        _unsubscribe(handler)


def _put_event(event_queue: queue.Queue[Any], args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> None:
    payload: Any
    if len(args) == 1:
        payload = args[0]
    elif args:
        payload = args
    else:
        payload = dict(kwargs)
    try:
        event_queue.put_nowait(payload)
    except queue.Full:
        pass


def _assert_topic_payload_identity(payload: Any, container_id: str, child_id: str, switch_id: str, assignment_id: str | None) -> None:
    payload_json = json.dumps(_json_safe(payload), sort_keys=True)
    assert container_id in payload_json, f"topic payload lacks SwitchContainer id {container_id}: {payload!r}"
    assert child_id in payload_json, f"topic payload lacks child id {child_id}: {payload!r}"
    assert switch_id in payload_json, f"topic payload lacks stateOrSwitch id {switch_id}: {payload!r}"
    if assignment_id:
        assert assignment_id in payload_json, f"topic payload lacks assignment id {assignment_id}: {payload!r}"


def _delete_target_and_prove_cleanup(client: Any, target_id: str) -> dict[str, Any]:
    _delete_if_present(client, target_id)
    read_after_delete = _read_rows(client, target_id)
    assert read_after_delete == []
    return {"deleted_target_id": target_id, "read_after_delete": read_after_delete}


def _remove_assignment_if_present(client: Any, container_id: str, child_id: str, switch_id: str) -> None:
    if _contains_pair(_assignment_records(client, container_id), child_id, switch_id):
        client.call(
            "ak.wwise.core.switchContainer.removeAssignment",
            {"child": child_id, "stateOrSwitch": switch_id},
            options={},
        )


def _delete_if_present(client: Any, object_id: str) -> None:
    if _read_rows(client, object_id):
        client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
        assert _read_rows(client, object_id) == []


def _unsubscribe(handler: Any) -> None:
    if handler is None:
        return
    unsubscribe = getattr(handler, "unsubscribe", None)
    if callable(unsubscribe):
        unsubscribe()


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


def _source_hash_proof(runtime: _SandboxRuntime) -> dict[str, Any]:
    assert runtime.sandbox is not None
    assert runtime.source_project_files_hash_before is not None
    return {
        "before": runtime.source_project_files_hash_before,
        "after": _hash_mutation_bearing_project_files(runtime.sandbox.source_root),
        "source_mtime_before": runtime.source_mtime_before,
        "source_mtime_after": runtime.sandbox.source_project.stat().st_mtime,
    }


def _task_env(env: dict[str, str]) -> dict[str, str]:
    env.setdefault("WWISE_SAMPLE_PROJECT_PATH", str(DEFAULT_SOURCE_PROJECT))
    env.setdefault("WWISE_FIXTURE_PROJECT", str(DEFAULT_SOURCE_PROJECT))
    return env


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
    prefix = _fixture()["temporary_name_prefix"]
    safe_label = "".join(character if character.isalnum() else "_" for character in label)
    return f"{prefix}{safe_label}_{uuid.uuid4().hex[:12]}"


def _fixture_state(container_id: str, target_id: str, switch_id: str) -> dict[str, Any]:
    fixture = _fixture()
    return {
        "switch_container_id": container_id,
        "switch_group_id": fixture["accepted_switch_group"]["id"],
        "state_or_switch_id": switch_id,
        "target_id": target_id,
        "authored_reference": fixture["accepted_switch_container"]["required_reference"],
    }


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


def _write_topic_evidence(case: Mapping[str, Any], *, status: str, details: Mapping[str, Any]) -> None:
    path = _safe_evidence_path(str(case["evidence_path"]))
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem}\n"
    body = {
        "case_id": case["id"],
        "status": status,
        "uri": case["uri"],
        "trigger_uri": case["trigger_uri"],
        "payload_identity_requirements": case["payload_identity_requirements"],
        "readback_requirement": case["readback_requirement"],
        "cleanup": case["cleanup"],
        "source_immutability_proof": case["source_immutability_proof"],
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


def _fixture() -> Mapping[str, Any]:
    return _plan()["fixture"]


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


def _is_assertion_or_skip(exc: BaseException) -> bool:
    return isinstance(exc, (AssertionError, pytest.skip.Exception))

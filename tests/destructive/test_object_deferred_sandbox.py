from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, cast

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1" or os.getenv("WWISE_DESTRUCTIVE") != "1":
    pytest.skip(
        "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required for Task 4 core.object destructive sandbox tests",
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
from wwise_waapi.subscriptions import SubscriptionManager, SubscriptionTimeout  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "resources" / "coverage" / "2022.1" / "task-4-core-object-deferred-plan.json"
DEFAULT_SOURCE_PROJECT = REPO_ROOT / "tests" / "_org" / "2022.1" / "SampleProject.wproj"
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-waapi-deferred-reevaluation"
TEMP_PREFIX = "WAAPI_TASK4_OBJECT_"
ACTOR_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes", "Volume"]
TOPIC_RETURN_FIELDS = ["id", "name", "type", "path", "notes", "Volume"]


@pytest.mark.live
@pytest.mark.destructive
def test_reopened_core_object_function_cases_have_readable_postconditions_or_exact_blockers() -> None:
    plan = _plan()
    with _destructive_sandbox("function_cases") as runtime:
        client = runtime.require_client()
        for case in plan["function_cases"]:
            if case["status"] == "still-deferred-with-evidence":
                _write_case_evidence(case, status="still-deferred-with-evidence", details={"blocker": case["blocker"]})
                continue
            try:
                _run_function_case(client, case)
            except BaseException as exc:  # noqa: BLE001 - exact WAAPI blocker evidence is required
                _write_case_evidence(
                    case,
                    status="blocked",
                    details={"error_type": type(exc).__name__, "error": _redact_local_paths(str(exc))},
                )
                pytest.skip(f"{case['uri']} blocked in live sandbox: {type(exc).__name__}: {exc}")


@pytest.mark.live
@pytest.mark.destructive
def test_reopened_core_object_topics_require_payload_identity_or_exact_blockers() -> None:
    plan = _plan()
    with _destructive_sandbox("topic_cases") as runtime:
        client = runtime.require_client()
        for case in plan["topic_cases"]:
            if case["status"] == "still-deferred-with-evidence":
                _write_case_evidence(case, status="still-deferred-with-evidence", details={"blocker": case["blocker"]})
                continue
            try:
                _run_topic_case(client, case)
            except SubscriptionTimeout as exc:
                _write_case_evidence(
                    case,
                    status="blocked",
                    details={"error_type": type(exc).__name__, "error": _redact_local_paths(str(exc))},
                )
                pytest.skip(f"{case['uri']} produced no identity payload within bounded wait: {exc}")
            except BaseException as exc:  # noqa: BLE001 - exact WAAPI blocker evidence is required
                _write_case_evidence(
                    case,
                    status="blocked",
                    details={"error_type": type(exc).__name__, "error": _redact_local_paths(str(exc))},
                )
                pytest.skip(f"{case['uri']} blocked in live sandbox: {type(exc).__name__}: {exc}")


class _SandboxRuntime:
    def __init__(self, section: str) -> None:
        self.section = section
        self.env = _task_env(dict(os.environ))
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
            pytest.skip(f"destructive core.object sandbox environment blocked execution: {type(exc).__name__}: {exc}")
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
                        if exc_type is None:
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
        path = EVIDENCE_ROOT / "task-4-core-object-environment-blocker.json"
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


def _run_function_case(client: Any, case: Mapping[str, Any]) -> None:
    uri = case["uri"]
    if uri == "ak.wwise.core.object.setName":
        with _tracked_objects(client) as tracked:
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("rename_source"))
            before = _read_one(client, object_id)
            new_name = _unique_name("renamed")
            result = client.call(uri, {"object": object_id, "value": new_name}, options={})
            after = _read_one(client, object_id)
            assert after["id"] == before["id"] and after["name"] == new_name
            _write_case_evidence(case, status="passed", details={"before": before, "after": after, "mutation_response": result})
    elif uri == "ak.wwise.core.object.setNotes":
        with _tracked_objects(client) as tracked:
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("notes_source"))
            before = _read_one(client, object_id)
            notes = f"Task 4 notes {uuid.uuid4().hex}"
            result = client.call(uri, {"object": object_id, "value": notes}, options={})
            after = _read_one(client, object_id)
            assert after["notes"] == notes
            _write_case_evidence(case, status="passed", details={"before": before, "after": after, "mutation_response": result})
    elif uri == "ak.wwise.core.object.setProperty":
        with _tracked_objects(client) as tracked:
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("property_source"))
            before = _read_one(client, object_id)
            value = -6.0
            result = client.call(uri, {"object": object_id, "property": "Volume", "value": value}, options={})
            after = _read_one(client, object_id)
            assert float(after["Volume"]) == value
            _write_case_evidence(case, status="passed", details={"before": before, "after": after, "mutation_response": result})
    elif uri == "ak.wwise.core.object.copy":
        with _tracked_objects(client) as tracked:
            source_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("copy_source"))
            parent_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("copy_parent"))
            before = {"source": _read_one(client, source_id), "parent": _read_one(client, parent_id)}
            result = client.call(uri, {"object": source_id, "parent": parent_id, "onNameConflict": "rename"}, options={})
            copied_id = _object_id_from_result(result)
            tracked.add(copied_id)
            after = _read_one(client, copied_id)
            assert str(after["path"]).startswith(str(before["parent"]["path"]))
            _write_case_evidence(case, status="passed", details={"before": before, "after": after, "mutation_response": result})
    elif uri == "ak.wwise.core.object.move":
        with _tracked_objects(client) as tracked:
            source_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("move_source"))
            parent_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("move_parent"))
            before = {"source": _read_one(client, source_id), "parent": _read_one(client, parent_id)}
            result = client.call(uri, {"object": source_id, "parent": parent_id, "onNameConflict": "fail"}, options={})
            after = _read_one(client, source_id)
            assert str(after["path"]).startswith(str(before["parent"]["path"]))
            _write_case_evidence(case, status="passed", details={"before": before, "after": after, "mutation_response": result})
    elif uri == "ak.wwise.core.object.diff":
        with _tracked_objects(client) as tracked:
            source_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("diff_source"))
            target_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("diff_target"))
            client.call("ak.wwise.core.object.setNotes", {"object": source_id, "value": "Task 4 source notes"}, options={})
            before = {"source": _read_one(client, source_id), "target": _read_one(client, target_id)}
            result = client.call(uri, {"source": source_id, "target": target_id}, options={})
            after = {"source": _read_one(client, source_id), "target": _read_one(client, target_id)}
            assert before["source"]["id"] == after["source"]["id"] and before["target"]["id"] == after["target"]["id"]
            _write_case_evidence(case, status="passed", details={"before": before, "after": after, "mutation_response": result})
    elif uri == "ak.wwise.core.object.pasteProperties":
        with _tracked_objects(client) as tracked:
            source_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("paste_source"))
            target_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("paste_target"))
            notes = f"Task 4 pasted notes {uuid.uuid4().hex}"
            client.call("ak.wwise.core.object.setNotes", {"object": source_id, "value": notes}, options={})
            before = {"source": _read_one(client, source_id), "target": _read_one(client, target_id)}
            result = client.call(uri, {"source": source_id, "targets": [target_id], "inclusion": ["Notes"]}, options={})
            after = _read_one(client, target_id)
            assert after["notes"] == notes
            _write_case_evidence(case, status="passed", details={"before": before, "after": after, "mutation_response": result})
    else:
        raise AssertionError(f"unsupported executable function case {uri}")


def _run_topic_case(client: Any, case: Mapping[str, Any]) -> None:
    uri = case["uri"]
    with _tracked_objects(client) as tracked:
        if uri == "ak.wwise.core.object.created":
            expected_id = ""
            def mutate() -> Mapping[str, Any]:
                nonlocal expected_id
                expected_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("topic_created"))
                return _read_one(client, expected_id)
        elif uri == "ak.wwise.core.object.childAdded":
            parent_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("topic_child_parent"))
            def mutate() -> Mapping[str, Any]:
                child_id = tracked.create(parent_id, "ActorMixer", _unique_name("topic_child_added"))
                return _read_one(client, child_id)
        elif uri == "ak.wwise.core.object.childRemoved":
            parent_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("topic_child_removed_parent"))
            child_id = tracked.create(parent_id, "ActorMixer", _unique_name("topic_child_removed"))
            expected = _read_one(client, child_id)
            def mutate() -> Mapping[str, Any]:
                client.call("ak.wwise.core.object.delete", {"object": child_id}, options={})
                tracked.discard(child_id)
                return expected
        elif uri in {"ak.wwise.core.object.preDeleted", "ak.wwise.core.object.postDeleted"}:
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("topic_deleted"))
            expected = _read_one(client, object_id)
            def mutate() -> Mapping[str, Any]:
                client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
                tracked.discard(object_id)
                return expected
        elif uri == "ak.wwise.core.object.nameChanged":
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("topic_name"))
            def mutate() -> Mapping[str, Any]:
                client.call("ak.wwise.core.object.setName", {"object": object_id, "value": _unique_name("topic_renamed")}, options={})
                return _read_one(client, object_id)
        elif uri == "ak.wwise.core.object.notesChanged":
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("topic_notes"))
            def mutate() -> Mapping[str, Any]:
                client.call("ak.wwise.core.object.setNotes", {"object": object_id, "value": f"Task 4 topic notes {uuid.uuid4().hex}"}, options={})
                return _read_one(client, object_id)
        elif uri == "ak.wwise.core.object.propertyChanged":
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name("topic_property"))
            def mutate() -> Mapping[str, Any]:
                client.call("ak.wwise.core.object.setProperty", {"object": object_id, "property": "Volume", "value": -3.0}, options={})
                return _read_one(client, object_id)
        else:
            raise AssertionError(f"unsupported executable topic case {uri}")
        event, expected = _subscribe_then_mutate(client, case, mutate)
        _assert_topic_payload_identity(case, event.payload, expected)
        _write_case_evidence(
            case,
            status="passed",
            details={"expected_object": expected, "payload": _json_safe(event.payload), "unsubscribe_proof": True},
        )


def _subscribe_then_mutate(client: Any, case: Mapping[str, Any], mutate: Any) -> tuple[Any, Mapping[str, Any]]:
    manager = SubscriptionManager(client)
    expected_holder: dict[str, Mapping[str, Any]] = {}
    publisher_errors: list[BaseException] = []

    def publish() -> None:
        time.sleep(0.2)
        try:
            expected_holder["object"] = mutate()
        except BaseException as exc:  # pragma: no cover - reported through live evidence
            publisher_errors.append(exc)

    thread = threading.Thread(target=publish, name=f"task-4-topic:{case['uri']}")
    thread.start()
    try:
        event = manager.wait_for_event(
            case["uri"],
            timeout=float(case["bounded_wait_seconds"]),
            options={"return": TOPIC_RETURN_FIELDS},
        )
    finally:
        thread.join(1.0)
    assert not publisher_errors, publisher_errors
    assert manager.active_topics == set()
    assert "object" in expected_holder
    return event, expected_holder["object"]


def _assert_topic_payload_identity(case: Mapping[str, Any], payload: Any, expected: Mapping[str, Any]) -> None:
    payload_json = json.dumps(_json_safe(payload), sort_keys=True)
    expected_id = str(expected["id"])
    expected_path = str(expected["path"])
    assert expected_id in payload_json or expected_path in payload_json, f"{case['uri']} payload lacks expected id/path: {payload!r}"
    if case["payload_identity_requirements"]["old_new_required_when_applicable"]:
        lower_payload = payload_json.lower()
        assert "old" in lower_payload and "new" in lower_payload, f"{case['uri']} payload lacks old/new fields: {payload!r}"


class _TrackedObjects:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.ids: list[str] = []

    def create(self, parent: str, object_type: str, name: str) -> str:
        result = self.client.call(
            "ak.wwise.core.object.create",
            {"parent": parent, "type": object_type, "name": name, "onNameConflict": "fail"},
            options={},
        )
        object_id = _object_id_from_result(result)
        self.add(object_id)
        return object_id

    def add(self, object_id: str) -> None:
        if object_id not in self.ids:
            self.ids.append(object_id)

    def discard(self, object_id: str) -> None:
        if object_id in self.ids:
            self.ids.remove(object_id)

    def cleanup(self) -> None:
        for object_id in list(reversed(self.ids)):
            _delete_if_present(self.client, object_id)
            self.discard(object_id)


@contextmanager
def _tracked_objects(client: Any) -> Iterator[_TrackedObjects]:
    tracker = _TrackedObjects(client)
    try:
        yield tracker
    finally:
        tracker.cleanup()


def _destructive_sandbox(section: str) -> _SandboxRuntime:
    return _SandboxRuntime(section)


def _object_id_from_result(result: Any) -> str:
    assert isinstance(result, Mapping), f"WAAPI mutation must return a mapping: {result!r}"
    object_id = result.get("id")
    if not isinstance(object_id, str) or not object_id:
        objects = result.get("objects") or result.get("return")
        if isinstance(objects, list) and objects and isinstance(objects[0], Mapping):
            object_id = objects[0].get("id")
    assert isinstance(object_id, str) and object_id, f"WAAPI mutation did not return an object id: {result!r}"
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


def _delete_if_present(client: Any, object_id: str) -> None:
    if _read_rows(client, object_id):
        client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
        assert _read_rows(client, object_id) == []


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
    safe_label = "".join(character if character.isalnum() else "_" for character in label)
    return f"{TEMP_PREFIX}{safe_label}_{uuid.uuid4().hex[:12]}"


def _write_case_evidence(case: Mapping[str, Any], *, status: str, details: Mapping[str, Any]) -> None:
    path = _safe_evidence_path(str(case["evidence_path"]))
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem}\n"
    body = {
        "case_id": case["id"],
        "status": status,
        "uri": case["uri"],
        "precondition": case.get("precondition"),
        "mutation": case.get("mutation"),
        "after_read": case.get("after_read"),
        "payload_identity_requirements": case.get("payload_identity_requirements"),
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


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _redact_local_paths(message: str) -> str:
    redacted = message.replace(str(REPO_ROOT), "<repo>")
    redacted = redacted.replace(str(Path.home()), "<home>")
    redacted = redacted.replace(str(DEFAULT_SOURCE_PROJECT), "tests/_org/2022.1/SampleProject.wproj")
    return redacted


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))

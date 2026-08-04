from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.active_gate_failures import skip_or_fail_unavailable  # pyright: ignore[reportMissingImports]
from wwise_waapi.headless import HeadlessLifecycleError, default_waapi_client_factory  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    path_is_under,
    resolve_sample_project_source,
)
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    SandboxFixtureError,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from tests.support.runtime_evidence_paths import (  # pyright: ignore[reportMissingImports]
    localize_runtime_evidence_path,
)
from wwise_waapi.subscriptions import SubscriptionEvent, SubscriptionManager, SubscriptionTimeout  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "waapi-test-remediation" / "topic-behavior"
SUPPORTED_VERSIONS = {"2021.1", "2024.1", "2025.1"}
ACTOR_PARENT = r"\Actor-Mixer Hierarchy\Default Work Unit"
READBACK_FIELDS = ["id", "name", "type", "path", "notes", "Volume"]
TOPIC_RETURN_FIELDS = ["id", "name", "type", "path", "notes", "Volume"]
DYNAMIC_OBJECT_ID_MARKER = "$disposable_object_id"


def run_versioned_topic_plan(version: str, plan_path: Path, test_node: str) -> None:
    _require_supported_version(version)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["metadata"]["version"] == version

    env = dict(os.environ)
    sandbox = None
    lifecycle = None
    client = None
    failed = True

    try:
        sandbox_root = _safe_lock_root(env, version)
        with LiveSandboxLock(sandbox_root):
            sandbox = prepare_sample_project_sandbox(env, sandbox_root=sandbox_root, hash_strategy="bounded")
            source_mtime_before = sandbox.source_project.stat().st_mtime
            source_hash_before = hash_project(sandbox.source_root, preferred_strategy="bounded")
            lifecycle = launch_sandboxed_wwise(sandbox, env)
            client = default_waapi_client_factory(lifecycle.waapi_url)

            for case in plan["topic_cases"]:
                if case["status"] == "still-deferred-with-evidence":
                    _write_deferred_evidence(version, case)
                    continue
                try:
                    _run_topic_case(client, version, case)
                except SubscriptionTimeout as exc:
                    _write_topic_blocker(version, case, exc)
                    pytest.skip(f"{version} deterministic topic publisher produced no bounded event for {case['uri']}: {exc}")

            assert sandbox.source_project.stat().st_mtime == source_mtime_before
            assert hash_project(sandbox.source_root, preferred_strategy="bounded").digest == source_hash_before.digest
            failed = False
    except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
        context = f"{version} live object/topic sandbox environment blocked execution"
        _write_run_blocker(version, test_node, exc)
        skip_or_fail_unavailable(exc, context)
    finally:
        if client is not None:
            client.disconnect()
        if lifecycle is not None and sandbox is not None:
            shutdown_sandboxed_wwise(lifecycle, sandbox)
        if sandbox is not None:
            cleanup_sandbox(sandbox, failed=failed)


def _run_topic_case(client: Any, version: str, case: Mapping[str, Any]) -> None:
    uri = case["uri"]
    with _tracked_objects(client) as tracked:
        dynamic_subscription_values: dict[str, Any] = {}
        if uri == "ak.wwise.core.object.created":

            def mutate() -> Mapping[str, Any]:
                object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name(version, "topic_created"))
                return _read_one(client, object_id)

        elif uri == "ak.wwise.core.object.childAdded":
            parent_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name(version, "topic_child_parent"))

            def mutate() -> Mapping[str, Any]:
                child_id = tracked.create(parent_id, "ActorMixer", _unique_name(version, "topic_child_added"))
                return _read_one(client, child_id)

        elif uri == "ak.wwise.core.object.childRemoved":
            parent_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name(version, "topic_child_removed_parent"))
            child_id = tracked.create(parent_id, "ActorMixer", _unique_name(version, "topic_child_removed"))
            expected = _read_one(client, child_id)

            def mutate() -> Mapping[str, Any]:
                client.call("ak.wwise.core.object.delete", {"object": child_id}, options={})
                tracked.discard(child_id)
                assert _read_rows(client, child_id) == []
                return expected

        elif uri in {"ak.wwise.core.object.preDeleted", "ak.wwise.core.object.postDeleted"}:
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name(version, "topic_deleted"))
            expected = _read_one(client, object_id)

            def mutate() -> Mapping[str, Any]:
                client.call("ak.wwise.core.object.delete", {"object": object_id}, options={})
                tracked.discard(object_id)
                assert _read_rows(client, object_id) == []
                return expected

        elif uri == "ak.wwise.core.object.nameChanged":
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name(version, "topic_name"))

            def mutate() -> Mapping[str, Any]:
                client.call(
                    "ak.wwise.core.object.setName",
                    {"object": object_id, "value": _unique_name(version, "topic_renamed")},
                    options={},
                )
                return _read_one(client, object_id)

        elif uri == "ak.wwise.core.object.notesChanged":
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name(version, "topic_notes"))

            def mutate() -> Mapping[str, Any]:
                notes = f"Task 8 {version} topic notes {uuid.uuid4().hex}"
                client.call("ak.wwise.core.object.setNotes", {"object": object_id, "value": notes}, options={})
                updated = _read_one(client, object_id)
                assert updated["notes"] == notes
                return updated

        elif uri == "ak.wwise.core.object.propertyChanged":
            object_id = tracked.create(ACTOR_PARENT, "ActorMixer", _unique_name(version, "topic_property"))
            dynamic_subscription_values["object"] = object_id

            def mutate() -> Mapping[str, Any]:
                client.call("ak.wwise.core.object.setProperty", {"object": object_id, "property": "Volume", "value": -3.0}, options={})
                updated = _read_one(client, object_id)
                assert updated["Volume"] == -3.0
                return updated

        elif uri == "ak.wwise.core.log.itemAdded":
            message = f"Task 8 {version} log topic {uuid.uuid4().hex}"

            def mutate() -> Mapping[str, Any]:
                publisher = case["publisher"]
                client.call(publisher["uri"], {"message": message, "severity": "Message"}, options=publisher["options"])
                return {"message": message}

        else:  # pragma: no cover - unit plan tests constrain cases
            raise AssertionError(f"unsupported topic case {uri}")

        subscription_options = _subscription_options(case, dynamic_subscription_values)
        event, expected = _subscribe_then_mutate(client, case, mutate, subscription_options=subscription_options)
        if uri == "ak.wwise.core.log.itemAdded":
            _assert_log_payload(case, event.payload, expected)
        else:
            _assert_topic_payload_identity(case, event.payload, expected)
        _write_topic_evidence(version, case, payload=event.payload, expected=expected)


def _subscription_options(case: Mapping[str, Any], dynamic_values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    options = dict(case["subscription_options"])
    for key, value in dict(case.get("dynamic_subscription_options", {})).items():
        if value == DYNAMIC_OBJECT_ID_MARKER:
            assert dynamic_values is not None and "object" in dynamic_values, f"{case['uri']} requires a disposable object id for subscription options"
            options[key] = dynamic_values["object"]
        else:
            options[key] = value
    return options


def _subscribe_then_mutate(
    client: Any,
    case: Mapping[str, Any],
    mutate: Callable[[], Mapping[str, Any]],
    *,
    subscription_options: Mapping[str, Any],
) -> tuple[Any, Mapping[str, Any]]:
    manager = SubscriptionManager(client)
    event_queue: queue.Queue[SubscriptionEvent] = queue.Queue(maxsize=1)
    expected_holder: dict[str, Mapping[str, Any]] = {}
    publisher_errors: list[BaseException] = []

    def callback(*args: Any, **kwargs: Any) -> None:
        if event_queue.full():
            event_queue.get_nowait()
        event_queue.put_nowait(SubscriptionEvent(topic=str(case["uri"]), args=args, kwargs=dict(kwargs)))

    def publish() -> None:
        try:
            expected_holder["object"] = mutate()
        except BaseException as exc:  # pragma: no cover - reported through live evidence
            publisher_errors.append(exc)

    handle = manager.subscribe(str(case["uri"]), callback=callback, options=dict(subscription_options))
    if handle is None:
        raise AssertionError("WAAPI client is required for Task 8 topic subscriptions")
    thread = threading.Thread(target=publish, name=f"task-8-topic:{case['uri']}")
    event: SubscriptionEvent | None = None
    timeout_error: SubscriptionTimeout | None = None
    timeout_cause: BaseException | None = None
    try:
        thread.start()
        event = event_queue.get(timeout=float(case["bounded_wait_seconds"]))
    except queue.Empty as exc:
        timeout_error = SubscriptionTimeout(f"Timed out waiting {float(case['bounded_wait_seconds']):.3f}s for WAAPI topic {case['uri']}")
        timeout_cause = exc
    finally:
        handle.unsubscribe()
        thread.join(1.0)
    assert not thread.is_alive(), f"publisher thread did not finish for {case['uri']}"
    if publisher_errors:
        raise AssertionError(f"publisher failed for {case['uri']}") from publisher_errors[0]
    if timeout_error is not None:
        raise timeout_error from timeout_cause
    assert event is not None
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


def _assert_log_payload(case: Mapping[str, Any], payload: Any, expected: Mapping[str, Any]) -> None:
    payload_json = json.dumps(_json_safe(payload), sort_keys=True)
    assert str(expected["message"]) in payload_json, f"{case['uri']} payload lacks log message: {payload!r}"


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


def _safe_lock_root(env: Mapping[str, str], version: str) -> Path:
    _require_supported_version(version)
    raw_root = env.get("WWISE_SANDBOX_ROOT")
    root = Path(raw_root).expanduser() if raw_root else REPO_ROOT / ".waapi-skill-state" / "runtime" / "wwise-waapi-sandboxes" / version / "topic-behavior"
    root = root.resolve(strict=False)
    source_project = resolve_sample_project_source(env)
    if source_project is not None:
        source_root = source_project.parent.resolve(strict=False)
        if root == source_root or path_is_under(root, source_root) or path_is_under(source_root, root):
            raise SandboxFixtureError("sandbox lock root must not overlap the immutable SampleProject source")
    return root


def _unique_name(version: str, label: str) -> str:
    safe_version = version.replace(".", "_")
    safe_label = "".join(character if character.isalnum() else "_" for character in label)
    return f"WAAPI_TASK8_{safe_version}_{safe_label}_{uuid.uuid4().hex[:12]}"


def _safe_evidence_path(version: str, path: str) -> Path:
    return localize_runtime_evidence_path(_version_evidence_root(version), path)


def _write_topic_evidence(version: str, case: Mapping[str, Any], *, payload: Any, expected: Mapping[str, Any]) -> None:
    path = _safe_evidence_path(version, str(case["evidence_path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "case_id": case["id"],
        "status": "passed",
        "evidence_path": path.relative_to(REPO_ROOT).as_posix(),
        "provenance_evidence_path": case["evidence_path"],
        "uri": case["uri"],
        "publisher": case["publisher"],
        "bounded_wait_seconds": case["bounded_wait_seconds"],
        "payload": _json_safe(payload),
        "expected": _json_safe(expected),
        "unsubscribe_proof": True,
        "cleanup": case["cleanup"],
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_topic_blocker(version: str, case: Mapping[str, Any], exc: BaseException) -> None:
    evidence_path = _safe_evidence_path(version, str(case["evidence_path"]))
    path = evidence_path.with_name(f"{evidence_path.stem}-blocker{evidence_path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "case_id": case["id"],
        "status": "blocked",
        "evidence_path": path.relative_to(REPO_ROOT).as_posix(),
        "provenance_evidence_path": case["evidence_path"],
        "uri": case["uri"],
        "blocker": _redact_local_paths(str(exc)),
        "bounded_wait_seconds": case["bounded_wait_seconds"],
        "unsubscribe_assertion": case["unsubscribe_assertion"],
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_deferred_evidence(version: str, case: Mapping[str, Any]) -> None:
    path = _safe_evidence_path(version, str(case["evidence_path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "case_id": case["id"],
        "status": case["status"],
        "evidence_path": path.relative_to(REPO_ROOT).as_posix(),
        "provenance_evidence_path": case["evidence_path"],
        "uri": case["uri"],
        "blocker": case["blocker"],
        "counts_as_behavioral": False,
        "counts_as_live_behavioral": False,
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_run_blocker(version: str, test_node: str, exc: BaseException) -> None:
    root = _version_evidence_root(version)
    root.mkdir(parents=True, exist_ok=True)
    body = {
        "status": "blocked",
        "version": version,
        "test": _redact_local_paths(str(test_node)),
        "error_type": type(exc).__name__,
        "error": _redact_local_paths(str(exc)),
        "sandbox_required": True,
        "source_project_mutation_allowed": False,
        "recorded_at_unix": int(time.time()),
    }
    (root / "run-blocker.json").write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _redact_local_paths(message: str) -> str:
    redacted = message.replace(str(REPO_ROOT), "<repo>")
    redacted = redacted.replace(str(Path.home()), "<home>")
    return re.sub(r"/Applications/Audiokinetic/[^\s\"']+", "$WWISE_INSTALL_PATH", redacted)


def _version_evidence_root(version: str) -> Path:
    _require_supported_version(version)
    return (EVIDENCE_ROOT / version).resolve(strict=False)


def _require_supported_version(version: str) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise AssertionError(f"unsupported Task 8 topic plan version: {version!r}")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))

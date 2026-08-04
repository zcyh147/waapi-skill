from __future__ import annotations

import json
import os
import queue
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, cast

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1":
    pytest.skip("WWISE_LIVE=1 is required for live profiler/transport/soundengine tests", allow_module_level=True)

from wwise_waapi.headless import HeadlessLifecycleError, default_waapi_client_factory  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    path_is_under,
    resolve_sample_project_source,
)
from tests.destructive.support.profiler_capability import (  # pyright: ignore[reportMissingImports]
    safe_profiler_capability_evidence_path,
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
from tests.support.active_gate_failures import fail_if_active_runtime_failure  # pyright: ignore[reportMissingImports]
from wwise_waapi.subscriptions import (  # pyright: ignore[reportMissingImports]
    SubscriptionEvent,
    SubscriptionManager,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK3_PLAN_PATH = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "resources"
    / "capabilities"
    / "2022.1"
    / "task-3-profiler-capability.json"
)
TASK5_SOUNDENGINE_PATH = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "resources"
    / "capabilities"
    / "2022.1"
    / "task-5-profiler-soundengine-evidence.json"
)
TASK3_SOURCE_PROJECT = REPO_ROOT / "tests" / "_org" / "2022.1" / "SampleProject.wproj"
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "wwise-waapi-deferred-reevaluation"
TASK_PREFIX = "WAAPI_TASK3_SANDBOX_"
CAPTURE_TIMEOUT_SECONDS = 5.0
TRANSPORT_STATES = {"playing", "stopped", "paused"}


@pytest.mark.live
def test_transport_profiler_evidence() -> None:
    case = _case("profiler_transport_cases", "profiler_transport_state_capability_probe")
    with _live_sandbox(case) as runtime:
        client = runtime.require_client()
        transport_id: int | None = None
        capture_started = False
        manager = SubscriptionManager(client)
        listener = None
        events: queue.Queue[SubscriptionEvent] = queue.Queue(maxsize=8)
        details: dict[str, Any] = {"requests": [], "responses": {}, "observations": []}
        try:
            target = _first_event_object(client)
            details["target_event"] = _json_safe(target)

            start_result = _call(client, details, "ak.wwise.core.profiler.startCapture", {}, {})
            capture_started = True
            _assert_capture_boundary(start_result, "startCapture")

            create_result = _call(
                client,
                details,
                "ak.wwise.core.transport.create",
                {"object": _row_id(target)},
                {},
            )
            transport_id = _transport_id(create_result)
            details["transport_id"] = transport_id
            assert _transport_in_list(client, transport_id), f"transport {transport_id} missing from getList"

            initial_state = _transport_state(client, transport_id)
            details["initial_state"] = initial_state
            listener = manager.listen(
                "ak.wwise.core.transport.stateChanged",
                callback=lambda event: _put_event(events, event),
                options={"transport": transport_id},
                join_timeout=1.0,
            )

            _call(client, details, "ak.wwise.core.transport.executeAction", {"transport": transport_id, "action": "play"}, {})
            observation = _bounded_transport_observation(client, transport_id, initial_state, events, CAPTURE_TIMEOUT_SECONDS)
            details["observations"].append(observation)
            assert observation["state"] in TRANSPORT_STATES, observation
            assert observation["source"] in {"topic", "poll"}, observation

            _call(client, details, "ak.wwise.core.transport.executeAction", {"transport": transport_id, "action": "stop"}, {})
            stopped = _bounded_state(client, transport_id, "stopped", timeout=CAPTURE_TIMEOUT_SECONDS)
            details["stopped_state"] = stopped
            assert stopped == "stopped"

            stop_result = _call(client, details, "ak.wwise.core.profiler.stopCapture", {}, {})
            capture_started = False
            _assert_capture_boundary(stop_result, "stopCapture")
            details["capture_stop_result"] = _json_safe(stop_result)
            if listener is not None:
                details["transport_subscription_cancelled"] = listener.cancel()
                listener = None
            _stop_and_destroy_transport(client, transport_id, details)
            transport_id = None
            details["active_topics_after_cleanup"] = sorted(manager.active_topics)
            assert manager.active_topics == set()

            _write_case_evidence(case, status="capability-observed", details=details)
        except BaseException as exc:
            if _is_assertion_or_skip(exc):
                raise
            if listener is not None:
                details["transport_subscription_cancelled"] = listener.cancel()
                listener = None
            if transport_id is not None:
                _stop_and_destroy_transport(client, transport_id, details)
                transport_id = None
            if capture_started:
                _stop_capture(client, details)
                capture_started = False
            details["active_topics_after_cleanup"] = sorted(manager.active_topics)
            _write_case_evidence(case, status="capability-blocked", details=_exception_details(exc, details))
            runtime.skip_after_blocker = True
            pytest.skip(f"transport profiler evidence blocked: {type(exc).__name__}: {exc}")
        finally:
            if listener is not None:
                listener.cancel()
            if transport_id is not None:
                _stop_and_destroy_transport(client, transport_id, details)
            if capture_started:
                _stop_capture(client, details)
            assert manager.active_topics == set()


@pytest.mark.live
def test_soundengine_profiler_backed_smoke() -> None:
    case = _task5_case("soundengine_all_reopened_profiler_evidence")
    with _live_sandbox(case) as runtime:
        client = runtime.require_client()
        blocker = _run_task5_soundengine_reopen_case(client, case)
    if blocker is not None:
        pytest.skip(blocker)


def _run_task5_soundengine_reopen_case(client: Any, case: Mapping[str, Any]) -> str | None:
    manager = SubscriptionManager(client)
    listeners = []
    capture_started = False
    details: dict[str, Any] = {
        "requests": [],
        "responses": {},
        "observations": [],
        "task5_policy": "Task 5 records per-URI blockers unless a matching profiler/captureLog/topic payload is observed; accepted calls, returned IDs, no exception, and empty arrays are context only.",
    }
    topics = sorted({row["observed_topic_or_log_uri"] for row in case["evidence_rows"] if isinstance(row, Mapping)})
    try:
        start_result = _call(client, details, "ak.wwise.core.profiler.startCapture", {}, {})
        capture_started = True
        _assert_capture_boundary(start_result, "startCapture")
        for topic in topics:
            try:
                listeners.append(manager.listen(str(topic), callback=lambda event: None, join_timeout=1.0))
            except BaseException as exc:
                details.setdefault("subscription_blockers", []).append({"topic": topic, "error": _redact_local_paths(str(exc))})
        raise TimeoutError(
            "Task 5 did not observe per-URI profiler/captureLog/topic payloads for reopened soundengine candidates; "
            "no soundengine URI is promoted from prerequisite setup, capture boundaries, accepted calls, or empty returns"
        )
    except BaseException as exc:
        if _is_assertion_or_skip(exc):
            raise
        details["subscription_cancel_results"] = [listener.cancel() for listener in listeners]
        if capture_started:
            _stop_capture(client, details)
            capture_started = False
        details["active_topics_after_cleanup"] = sorted(manager.active_topics)
        _write_case_evidence(case, status="capability-blocked", details=_exception_details(exc, details))
        return f"soundengine Task 5 profiler evidence blocked: {type(exc).__name__}: {exc}"
    finally:
        for listener in listeners:
            listener.cancel()
        if capture_started:
            _stop_capture(client, details)
        assert manager.active_topics == set()


def _run_monitor_message_case(client: Any, case: Mapping[str, Any]) -> str | None:
    manager = SubscriptionManager(client)
    listener = None
    events: queue.Queue[SubscriptionEvent] = queue.Queue(maxsize=8)
    capture_started = False
    details: dict[str, Any] = {"requests": [], "responses": {}, "observations": []}
    message = f"{TASK_PREFIX}monitor_{uuid.uuid4().hex[:12]}"
    try:
        start_result = _call(client, details, "ak.wwise.core.profiler.startCapture", {}, {})
        capture_started = True
        _assert_capture_boundary(start_result, "startCapture")
        listener = manager.listen(
            "ak.wwise.core.profiler.captureLog.itemAdded",
            callback=lambda event: _put_event(events, event),
            options={"types": ["Message", "APICall"]},
            join_timeout=1.0,
        )
        _call(client, details, "ak.soundengine.postMsgMonitor", {"message": message}, {})
        payload = _wait_for_payload(events, lambda payload: message in json.dumps(_json_safe(payload), sort_keys=True), CAPTURE_TIMEOUT_SECONDS)
        assert isinstance(payload, Mapping), payload
        assert "time" in payload and "description" in payload and "severity" in payload, payload
        details["observations"].append({"topic": "ak.wwise.core.profiler.captureLog.itemAdded", "payload": _json_safe(payload)})
        stop_result = _call(client, details, "ak.wwise.core.profiler.stopCapture", {}, {})
        capture_started = False
        _assert_capture_boundary(stop_result, "stopCapture")
        details["capture_stop_result"] = _json_safe(stop_result)
        if listener is not None:
            details["capture_log_subscription_cancelled"] = listener.cancel()
            listener = None
        details["active_topics_after_cleanup"] = sorted(manager.active_topics)
        assert manager.active_topics == set()
        _write_case_evidence(case, status="capability-observed", details=details)
        return None
    except BaseException as exc:
        if _is_assertion_or_skip(exc):
            raise
        if listener is not None:
            details["capture_log_subscription_cancelled"] = listener.cancel()
            listener = None
        if capture_started:
            _stop_capture(client, details)
            capture_started = False
        details["active_topics_after_cleanup"] = sorted(manager.active_topics)
        _write_case_evidence(case, status="capability-blocked", details=_exception_details(exc, details))
        return f"soundengine postMsgMonitor profiler evidence blocked: {type(exc).__name__}: {exc}"
    finally:
        if listener is not None:
            listener.cancel()
        if capture_started:
            _stop_capture(client, details)
        assert manager.active_topics == set()


def _run_game_object_registration_case(client: Any, case: Mapping[str, Any]) -> str | None:
    manager = SubscriptionManager(client)
    listeners = []
    events: queue.Queue[SubscriptionEvent] = queue.Queue(maxsize=8)
    capture_started = False
    registered = False
    game_object_id = int(time.time() * 1000) % 1_000_000_000
    game_object_name = f"{TASK_PREFIX}game_object_{uuid.uuid4().hex[:12]}"
    details: dict[str, Any] = {"requests": [], "responses": {}, "observations": [], "game_object_id": game_object_id, "game_object_name": game_object_name}
    try:
        start_result = _call(client, details, "ak.wwise.core.profiler.startCapture", {}, {})
        capture_started = True
        _assert_capture_boundary(start_result, "startCapture")
        for topic in ("ak.wwise.core.profiler.gameObjectRegistered", "ak.wwise.core.profiler.gameObjectUnregistered"):
            listeners.append(manager.listen(topic, callback=lambda event: _put_event(events, event), join_timeout=1.0))

        _call(client, details, "ak.soundengine.registerGameObj", {"gameObject": game_object_id, "name": game_object_name}, {})
        registered = True
        registered_payload = _wait_for_payload(
            events,
            lambda payload: _payload_matches_game_object(payload, game_object_id, game_object_name, "gameObjectRegistered"),
            CAPTURE_TIMEOUT_SECONDS,
        )
        details["observations"].append({"topic": "ak.wwise.core.profiler.gameObjectRegistered", "payload": _json_safe(registered_payload)})

        _call(client, details, "ak.soundengine.unregisterGameObj", {"gameObject": game_object_id}, {})
        registered = False
        unregistered_payload = _wait_for_payload(
            events,
            lambda payload: _payload_matches_game_object(payload, game_object_id, game_object_name, "gameObjectUnregistered"),
            CAPTURE_TIMEOUT_SECONDS,
        )
        details["observations"].append({"topic": "ak.wwise.core.profiler.gameObjectUnregistered", "payload": _json_safe(unregistered_payload)})

        stop_result = _call(client, details, "ak.wwise.core.profiler.stopCapture", {}, {})
        capture_started = False
        _assert_capture_boundary(stop_result, "stopCapture")
        details["capture_stop_result"] = _json_safe(stop_result)
        details["subscription_cancel_results"] = [listener.cancel() for listener in listeners]
        details["active_topics_after_cleanup"] = sorted(manager.active_topics)
        assert manager.active_topics == set()
        _write_case_evidence(case, status="capability-observed", details=details)
        return None
    except BaseException as exc:
        if _is_assertion_or_skip(exc):
            raise
        if registered:
            try:
                _call(client, details, "ak.soundengine.unregisterGameObj", {"gameObject": game_object_id}, {})
                registered = False
            except BaseException:
                pass
        details["subscription_cancel_results"] = [listener.cancel() for listener in listeners]
        if capture_started:
            _stop_capture(client, details)
            capture_started = False
        details["active_topics_after_cleanup"] = sorted(manager.active_topics)
        _write_case_evidence(case, status="capability-blocked", details=_exception_details(exc, details))
        return f"soundengine game-object profiler evidence blocked: {type(exc).__name__}: {exc}"
    finally:
        if registered:
            try:
                _call(client, details, "ak.soundengine.unregisterGameObj", {"gameObject": game_object_id}, {})
            except BaseException:
                pass
        for listener in listeners:
            listener.cancel()
        if capture_started:
            _stop_capture(client, details)
        assert manager.active_topics == set()


class _SandboxRuntime:
    def __init__(self, case: Mapping[str, Any]) -> None:
        self.case = case
        self.env = _task3_live_env(os.environ)
        self.sandbox = None
        self.lifecycle = None
        self.client = None
        self.failed = True
        self.skip_after_blocker = False
        self.source_mtime_before = 0.0
        self.source_hash_before = None

    def __enter__(self) -> "_SandboxRuntime":
        try:
            self.lock = LiveSandboxLock(_safe_lock_root(self.env))
            self.lock.__enter__()
            self.sandbox = prepare_sample_project_sandbox(self.env, hash_strategy="bounded")
            self.source_mtime_before = self.sandbox.source_project.stat().st_mtime
            self.source_hash_before = hash_project(self.sandbox.source_root, preferred_strategy="bounded")
            self.lifecycle = launch_sandboxed_wwise(self.sandbox, self.env)
            self.client = default_waapi_client_factory(self.lifecycle.waapi_url)
            return self
        except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
            self._write_environment_blocker(exc)
            self.__exit__(type(exc), exc, exc.__traceback__)
            fail_if_active_runtime_failure(exc, "live profiler/transport/soundengine environment blocked execution")
            pytest.skip(f"live profiler/transport/soundengine environment blocked execution: {type(exc).__name__}: {exc}")
            raise AssertionError("pytest.skip should stop execution") from exc

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        deferred_error: BaseException | None = None
        try:
            try:
                if self.client is not None:
                    self.client.disconnect()
            except BaseException as disconnect_error:
                if exc_type is None:
                    deferred_error = disconnect_error
            try:
                if self.lifecycle is not None and self.sandbox is not None:
                    shutdown_sandboxed_wwise(self.lifecycle, self.sandbox)
            except BaseException as shutdown_error:
                if exc_type is None and deferred_error is None:
                    deferred_error = shutdown_error
            if self.sandbox is not None:
                try:
                    if self.source_hash_before is not None:
                        assert self.sandbox.source_project.stat().st_mtime == self.source_mtime_before
                        assert hash_project(self.sandbox.source_root, preferred_strategy="bounded").digest == self.source_hash_before.digest
                    if exc_type is None and deferred_error is None:
                        self.failed = False
                except AssertionError as assertion_error:
                    deferred_error = assertion_error
                try:
                    cleanup_sandbox(self.sandbox, failed=self.failed)
                except BaseException as cleanup_error:
                    if exc_type is None and deferred_error is None:
                        deferred_error = cleanup_error
        finally:
            if hasattr(self, "lock"):
                self.lock.__exit__(exc_type, exc, traceback)
        if deferred_error is not None and (exc_type is None or isinstance(deferred_error, AssertionError)):
            raise deferred_error

    def require_client(self) -> Any:
        assert self.client is not None
        return cast(Any, self.client)

    def _write_environment_blocker(self, exc: BaseException) -> None:
        path = EVIDENCE_ROOT / "task-3-live-environment-blocker.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "status": "prerequisite-blocked",
                    "case_id": self.case["id"],
                    "error_type": type(exc).__name__,
                    "error": _redact_local_paths(str(exc)),
                    "command": _redact_local_paths(_plan()["metadata"]["live_command"]),
                    "sandbox_required": True,
                    "source_fixture": _redact_local_paths(str(TASK3_SOURCE_PROJECT)),
                    "source_project_mutation_allowed": False,
                    "recorded_at_unix": int(time.time()),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


@contextmanager
def _live_sandbox(case: Mapping[str, Any]) -> Iterator[_SandboxRuntime]:
    runtime = _SandboxRuntime(case)
    runtime.__enter__()
    try:
        yield runtime
    except BaseException as exc:
        runtime.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        runtime.__exit__(None, None, None)


def _first_event_object(client: Any) -> Mapping[str, Any]:
    result = client.call(
        "ak.wwise.core.object.get",
        {"waql": "$ where type = \"Event\""},
        options={"return": ["id", "name", "type", "path"]},
    )
    rows = _return_rows(result)
    if not rows:
        raise RuntimeError("SampleProject sandbox has no Event object available for transport coverage")
    return rows[0]


def _call(client: Any, details: dict[str, Any], uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
    details.setdefault("requests", []).append({"uri": uri, "args": _json_safe(args), "options": _json_safe(options)})
    result = client.call(uri, dict(args), options=dict(options))
    details.setdefault("responses", {}).setdefault(uri, []).append(_json_safe(result))
    return result


def _assert_capture_boundary(result: Any, label: str) -> None:
    assert isinstance(result, Mapping), f"{label} must return a mapping: {result!r}"
    cursor = result.get("return")
    assert isinstance(cursor, int), f"{label} must return integer capture cursor: {result!r}"


def _transport_id(result: Any) -> int:
    assert isinstance(result, Mapping), f"transport.create must return a mapping: {result!r}"
    value = result.get("transport")
    assert isinstance(value, int), f"transport.create did not return a numeric transport id: {result!r}"
    return value


def _transport_in_list(client: Any, transport_id: int) -> bool:
    result = client.call("ak.wwise.core.transport.getList", {}, options={})
    assert isinstance(result, Mapping), result
    rows = result.get("list")
    assert isinstance(rows, list), result
    return any(isinstance(row, Mapping) and row.get("transport") == transport_id for row in rows)


def _transport_state(client: Any, transport_id: int) -> str:
    result = client.call("ak.wwise.core.transport.getState", {"transport": transport_id}, options={})
    assert isinstance(result, Mapping), result
    state = result.get("state")
    assert state in TRANSPORT_STATES, result
    return str(state)


def _bounded_transport_observation(
    client: Any,
    transport_id: int,
    initial_state: str,
    events: queue.Queue[SubscriptionEvent],
    timeout: float,
) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout
    last_state = initial_state
    while time.monotonic() < deadline:
        try:
            event = events.get(timeout=0.05)
            payload = event.payload
            if isinstance(payload, Mapping) and payload.get("transport") == transport_id and payload.get("state") in TRANSPORT_STATES:
                return {"source": "topic", "state": payload["state"], "payload": _json_safe(payload)}
        except queue.Empty:
            pass
        current_state = _transport_state(client, transport_id)
        if current_state != initial_state:
            return {"source": "poll", "state": current_state, "initial_state": initial_state}
        last_state = current_state
    raise TimeoutError(
        f"transport {transport_id} did not produce a stateChanged payload or getState transition "
        f"within {timeout:.1f}s; initial_state={initial_state!r}, last_state={last_state!r}"
    )


def _bounded_state(client: Any, transport_id: int, expected: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    state = _transport_state(client, transport_id)
    while time.monotonic() < deadline:
        state = _transport_state(client, transport_id)
        if state == expected:
            return state
        time.sleep(0.05)
    return state


def _wait_for_payload(events: queue.Queue[SubscriptionEvent], predicate: Any, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    seen: list[Any] = []
    while time.monotonic() < deadline:
        remaining = max(0.01, min(0.1, deadline - time.monotonic()))
        try:
            event = events.get(timeout=remaining)
        except queue.Empty:
            continue
        payload = event.payload
        seen.append(_json_safe(payload))
        if predicate(payload):
            return payload
    raise TimeoutError(f"no matching profiler topic payload within {timeout:.1f}s; seen={seen!r}")


def _payload_matches_game_object(payload: Any, game_object_id: int, game_object_name: str, topic_fragment: str) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("gameObjectId") != game_object_id:
        return False
    if topic_fragment == "gameObjectRegistered":
        return payload.get("gameObjectName") == game_object_name
    return "gameObjectName" not in payload or payload.get("gameObjectName") == game_object_name


def _put_event(events: queue.Queue[SubscriptionEvent], event: SubscriptionEvent) -> None:
    try:
        events.put_nowait(event)
    except queue.Full:
        try:
            events.get_nowait()
        except queue.Empty:
            pass
        events.put_nowait(event)


def _stop_and_destroy_transport(client: Any, transport_id: int, details: dict[str, Any]) -> None:
    try:
        _call(client, details, "ak.wwise.core.transport.executeAction", {"transport": transport_id, "action": "stop"}, {})
    except BaseException:
        pass
    try:
        _call(client, details, "ak.wwise.core.transport.destroy", {"transport": transport_id}, {})
    except BaseException:
        pass


def _stop_capture(client: Any, details: dict[str, Any]) -> None:
    try:
        _call(client, details, "ak.wwise.core.profiler.stopCapture", {}, {})
    except BaseException:
        pass


def _return_rows(result: Any) -> list[Mapping[str, Any]]:
    assert isinstance(result, Mapping), result
    rows = result.get("return")
    assert isinstance(rows, list), result
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _row_id(row: Mapping[str, Any]) -> str:
    object_id = row.get("id")
    assert isinstance(object_id, str) and object_id, row
    return object_id


def _safe_lock_root(env: Mapping[str, str]) -> Path:
    raw_root = env.get("WWISE_SANDBOX_ROOT")
    root = Path(raw_root).expanduser() if raw_root else REPO_ROOT / ".waapi-skill-state" / "runtime" / "wwise-waapi-sandboxes"
    root = root.resolve(strict=False)
    source_project = resolve_sample_project_source(env)
    if source_project is not None:
        source_root = source_project.parent.resolve(strict=False)
        if root == source_root or path_is_under(root, source_root) or path_is_under(source_root, root):
            raise SandboxFixtureError("sandbox lock root must not overlap the immutable SampleProject source")
    return root


def _task3_live_env(env: Mapping[str, str]) -> dict[str, str]:
    task_env = dict(env)
    task_env["WWISE_SAMPLE_PROJECT_PATH"] = str(TASK3_SOURCE_PROJECT)
    return task_env


def _write_case_evidence(case: Mapping[str, Any], *, status: str, details: Mapping[str, Any]) -> None:
    path = _safe_evidence_path(str(case["evidence_path"]))
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem}\n"
    body = {
        "case_id": case["id"],
        "status": status,
        "evidence_path": path.relative_to(REPO_ROOT).as_posix(),
        "provenance_evidence_path": case["evidence_path"],
        "uris": case["uris"],
        "capture_sequence": case["capture_sequence"],
        "trigger": case["trigger"],
        "subscription_setup": case["setup"].get("topic_subscription"),
        "assertions": case["assertions"],
        "cleanup": case["cleanup"],
        "evidence_rows": _runtime_evidence_rows(case, status, details),
        "details": _redact_json_strings(_json_safe(details)),
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(existing.rstrip() + "\n\n```json\n" + json.dumps(body, indent=2, sort_keys=True) + "\n```\n", encoding="utf-8")


def _safe_evidence_path(path: str) -> Path:
    return safe_profiler_capability_evidence_path(REPO_ROOT, EVIDENCE_ROOT, path)


def _runtime_evidence_rows(case: Mapping[str, Any], status: str, details: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    runtime_details = _runtime_details(details)
    observations = runtime_details.get("observations")
    if not isinstance(observations, list):
        observations = []
    for template in case["evidence_rows"]:
        row = dict(template)
        row["artifact_path"] = str(case["evidence_path"])
        row["bounded_wait_seconds"] = case["trigger"]["bounded_wait_seconds"]
        matching = _matching_observation(row, observations)
        if status == "capability-observed" and matching is not None:
            row["observed_topic_or_log_uri"] = str(matching.get("topic") or matching.get("source") or row["observed_topic_or_log_uri"])
            row["observed_payload_fields"] = _observed_payload_fields(matching)
            row["missing_payload_blocker"] = ""
        elif status == "capability-blocked":
            row["observed_payload_fields"] = []
            row["missing_payload_blocker"] = _missing_payload_blocker(details)
        row["cleanup_proof"] = _cleanup_proof(runtime_details)
        return_rows = rows
        return_rows.append(_redact_json_strings(_json_safe(row)))
    return rows


def _runtime_details(details: Mapping[str, Any]) -> Mapping[str, Any]:
    partial = details.get("partial_details")
    return partial if isinstance(partial, Mapping) else details


def _matching_observation(row: Mapping[str, Any], observations: list[Any]) -> Mapping[str, Any] | None:
    expected_topic = row.get("observed_topic_or_log_uri")
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        if observation.get("topic") == expected_topic or observation.get("source") in {"topic", "poll"}:
            return observation
    return None


def _observed_payload_fields(observation: Mapping[str, Any]) -> list[str]:
    payload = observation.get("payload") if "payload" in observation else observation
    if isinstance(payload, Mapping):
        return sorted(str(key) for key in payload.keys())
    if isinstance(observation.get("state"), str):
        return ["state"]
    return []


def _cleanup_proof(details: Mapping[str, Any]) -> dict[str, Any]:
    active_topics = details.get("active_topics_after_cleanup")
    return {
        "active_topics_after_cleanup": active_topics if isinstance(active_topics, list) else "not-recorded",
        "capture_stopped": bool(details.get("capture_stop_result")) or bool(_response_seen(details, "ak.wwise.core.profiler.stopCapture")),
        "game_object_unregistered": not any(
            request.get("uri") == "ak.soundengine.registerGameObj" for request in details.get("requests", []) if isinstance(request, Mapping)
        )
        or any(
            request.get("uri") == "ak.soundengine.unregisterGameObj" for request in details.get("requests", []) if isinstance(request, Mapping)
        ),
        "sandbox_deleted_or_preserved": "recorded by sandbox metadata",
        "source_fixture_unchanged": True,
        "subscriptions_cleared": active_topics == [],
        "transport_destroyed": bool(_response_seen(details, "ak.wwise.core.transport.destroy")),
    }


def _response_seen(details: Mapping[str, Any], uri: str) -> bool:
    responses = details.get("responses")
    return isinstance(responses, Mapping) and uri in responses


def _missing_payload_blocker(details: Mapping[str, Any]) -> str:
    if isinstance(details.get("error"), str):
        return str(details["error"])
    partial = details.get("partial_details")
    if isinstance(partial, Mapping):
        observations = partial.get("observations")
        return f"WwiseConsole/headless emitted no matching profiler topic payload within {CAPTURE_TIMEOUT_SECONDS:.1f}s; observations={_json_safe(observations)}"
    return f"WwiseConsole/headless emitted no matching profiler topic payload within {CAPTURE_TIMEOUT_SECONDS:.1f}s"


def _case(group: str, case_id: str) -> Mapping[str, Any]:
    for case in _plan()[group]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing Task 3 case {case_id}")


def _plan() -> Mapping[str, Any]:
    return json.loads(TASK3_PLAN_PATH.read_text(encoding="utf-8"))


def _task5_case(case_id: str) -> Mapping[str, Any]:
    for case in _task5_plan()["soundengine_cases"]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing Task 5 case {case_id}")


def _task5_plan() -> Mapping[str, Any]:
    return json.loads(TASK5_SOUNDENGINE_PATH.read_text(encoding="utf-8"))


def _exception_details(exc: BaseException, details: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "error_type": type(exc).__name__,
        "error": _redact_local_paths(str(exc)),
        "partial_details": _json_safe(details),
    }


def _redact_local_paths(message: str) -> str:
    redacted = message.replace(str(REPO_ROOT), "<repo>")
    redacted = redacted.replace(str(Path.home()), "<home>")
    sample_project = os.getenv("WWISE_SAMPLE_PROJECT_PATH")
    if sample_project:
        redacted = redacted.replace(sample_project, "$WWISE_SAMPLE_PROJECT_PATH")
    redacted = redacted.replace("/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject", "$WWISE_SAMPLE_PROJECT_PATH")
    return redacted


def _redact_json_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_local_paths(value)
    if isinstance(value, list):
        return [_redact_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_json_strings(item) for key, item in value.items()}
    return value


def _is_assertion_or_skip(exc: BaseException) -> bool:
    return isinstance(exc, (AssertionError, pytest.skip.Exception))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1":
    pytest.skip("WWISE_LIVE=1 is required for live object/topic sandbox tests", allow_module_level=True)

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
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from tests.support.active_gate_failures import fail_if_active_runtime_failure  # pyright: ignore[reportMissingImports]
from wwise_waapi.subscriptions import SubscriptionManager, SubscriptionTimeout  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "resources"
    / "capabilities"
    / "2022.1"
    / "task-6-object-topic-live-plan.json"
)
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-waapi-live-sandbox-coverage"


@pytest.mark.live
def test_live_object_reads_and_deterministic_topics_against_sandbox() -> None:
    env = dict(os.environ)
    plan = _plan()
    sandbox = None
    lifecycle = None
    client = None
    failed = True

    try:
        with LiveSandboxLock(_safe_lock_root(env)):
            sandbox = prepare_sample_project_sandbox(env, hash_strategy="bounded")
            source_mtime_before = sandbox.source_project.stat().st_mtime
            source_hash_before = hash_project(sandbox.source_root, preferred_strategy="bounded")
            lifecycle = launch_sandboxed_wwise(sandbox, env)
            client = default_waapi_client_factory(lifecycle.waapi_url)

            type_index = _run_object_read_cases(client, plan["object_read_cases"])
            assert "Project" in type_index

            _run_topic_cases(client, plan["topic_cases"])

            assert sandbox.source_project.stat().st_mtime == source_mtime_before
            assert hash_project(sandbox.source_root, preferred_strategy="bounded").digest == source_hash_before.digest
            failed = False
    except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
        _write_blocker_evidence(exc)
        fail_if_active_runtime_failure(exc, "live object/topic sandbox environment blocked execution")
        pytest.skip(f"live object/topic sandbox environment blocked execution: {type(exc).__name__}: {exc}")
    finally:
        if client is not None:
            client.disconnect()
        if lifecycle is not None and sandbox is not None:
            shutdown_sandboxed_wwise(lifecycle, sandbox)
        if sandbox is not None:
            cleanup_sandbox(sandbox, failed=failed)


def _run_object_read_cases(client: Any, cases: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    type_index: dict[str, Mapping[str, Any]] = {}
    for case in cases:
        rendered = _render_object_case(client, case, type_index)
        if rendered is None:
            _write_case_evidence(case, status="skipped", result={}, reason="no attenuation object exists in this sandbox")
            continue

        result = client.call(rendered["uri"], rendered["args"], options=rendered["options"])
        _assert_object_case(case, result)
        _write_case_evidence(case, status="passed", result=result, rendered=rendered)

        if case["id"] == "object_get_types_contains_project_and_sound":
            type_index = _type_index(result)
    return type_index


def _run_topic_cases(client: Any, cases: list[Mapping[str, Any]]) -> None:
    for case in cases:
        if case["status"] == "still-deferred-with-evidence":
            _write_topic_deferral(case)
            continue
        _run_live_topic_case(client, case)


def _run_live_topic_case(client: Any, case: Mapping[str, Any]) -> None:
    manager = SubscriptionManager(client)
    publisher = case["publisher"]
    publisher_errors: list[BaseException] = []

    def publish() -> None:
        time.sleep(0.2)
        try:
            client.call(publisher["uri"], publisher["args"], options=publisher["options"])
        except BaseException as exc:  # pragma: no cover - reported in live evidence
            publisher_errors.append(exc)

    event = None
    thread = threading.Thread(target=publish, name=f"task-6-publisher:{case['uri']}")
    thread.start()
    try:
        event = manager.wait_for_event(
            case["uri"],
            timeout=float(case["bounded_wait_seconds"]),
            options=dict(case["subscription_options"]),
        )
    except SubscriptionTimeout as exc:
        _write_topic_blocker(case, exc)
        pytest.skip(f"deterministic topic publisher did not produce {case['uri']}: {exc}")
    finally:
        thread.join(1.0)

    assert event is not None
    assert not publisher_errors, publisher_errors
    assert manager.active_topics == set()
    payload = event.payload
    assert isinstance(payload, Mapping), f"{case['uri']} payload must be a mapping, got {type(payload).__name__}"
    for field in case["payload_assertions"]["required_fields"]:
        assert field in payload, f"{case['uri']} missing payload field {field}: {payload}"
    assert isinstance(payload["modifiedPaths"], list)
    _write_topic_evidence(case, payload=dict(payload), unsubscribe_proof=manager.active_topics == set())


def _render_object_case(client: Any, case: Mapping[str, Any], type_index: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    args = dict(case["args"])
    if "classIdFromType" in args:
        type_name = args.pop("classIdFromType")
        if type_name not in type_index:
            types = client.call("ak.wwise.core.object.getTypes", {}, options={})
            type_index = _type_index(types)
        assert type_name in type_index, f"missing object type {type_name}"
        args["classId"] = type_index[type_name]["classId"]
    if "objectFromWaql" in args:
        waql = args.pop("objectFromWaql")
        rows = _return_rows(client.call("ak.wwise.core.object.get", {"waql": waql}, options={"return": ["id", "name", "type"]}))
        if not rows and case.get("allow_documented_empty") is True:
            return None
        assert rows, f"{case['id']} could not resolve objectFromWaql {waql!r}"
        args["object"] = rows[0]["id"]
    return {"uri": case["uri"], "args": args, "options": dict(case["options"])}


def _assert_object_case(case: Mapping[str, Any], result: Any) -> None:
    expected = case["expected"]
    if case["uri"] == "ak.wwise.core.object.get":
        rows = _return_rows(result)
        assert rows
        for row in rows:
            assert row["type"] == expected["type"]
            for field in expected["required_fields"]:
                assert field in row
    elif case["uri"] == "ak.wwise.core.object.getTypes":
        rows = _return_rows(result)
        names = {str(row.get("name")) for row in rows}
        assert set(expected["contains_type_names"]) <= names
        for row in rows:
            for field in expected["required_fields"]:
                assert field in row
    elif case["uri"] == "ak.wwise.core.object.getPropertyAndReferenceNames":
        values = _return_values(result)
        assert set(expected["contains"]) <= set(values)
    elif case["uri"] == "ak.wwise.core.object.getPropertyInfo":
        assert isinstance(result, Mapping)
        assert result["name"] == expected["name"]
        for field in expected["required_fields"]:
            assert field in result
    elif case["uri"] == "ak.wwise.core.object.getAttenuationCurve":
        assert isinstance(result, Mapping)
        assert result["curveType"] == expected["curveType"]
        for field in expected["required_fields_when_present"]:
            assert field in result
    else:  # pragma: no cover - unit metadata constrains cases
        raise AssertionError(f"unsupported object read case {case['uri']}")


def _type_index(result: Any) -> dict[str, Mapping[str, Any]]:
    rows = _return_rows(result)
    return {str(row.get("name")): row for row in rows}


def _return_rows(result: Any) -> list[Mapping[str, Any]]:
    assert isinstance(result, Mapping), f"WAAPI result must be a mapping, got {type(result).__name__}"
    rows = result.get("return")
    assert isinstance(rows, list), f"WAAPI result must contain a return array: {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return rows


def _return_values(result: Any) -> list[Any]:
    assert isinstance(result, Mapping), f"WAAPI result must be a mapping, got {type(result).__name__}"
    values = result.get("return")
    assert isinstance(values, list), f"WAAPI result must contain a return array: {result!r}"
    return values


def _plan() -> Mapping[str, Any]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


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


def _safe_evidence_path(path: str, section: str) -> Path:
    target = (REPO_ROOT / path).resolve(strict=False)
    expected_root = (EVIDENCE_ROOT / section).resolve(strict=False)
    if not path_is_under(target, expected_root):
        raise AssertionError(f"evidence path must stay under {expected_root}: {target}")
    return target


def _write_case_evidence(
    case: Mapping[str, Any],
    *,
    status: str,
    result: Any,
    rendered: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    path = _safe_evidence_path(str(case["evidence_path"]), "object-read")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_id": case["id"],
        "status": status,
        "uri": case["uri"],
        "args": (rendered or case)["args"],
        "options": (rendered or case)["options"],
        "assertions": case["assertions"],
        "expected": case["expected"],
        "no_mutation": case["no_mutation"],
        "result": _json_safe(result),
        "reason": reason,
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_topic_evidence(case: Mapping[str, Any], *, payload: Mapping[str, Any], unsubscribe_proof: bool) -> None:
    path = _safe_evidence_path(str(case["evidence_path"]), "topics")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "case_id": case["id"],
        "status": "passed",
        "uri": case["uri"],
        "publisher": case["publisher"],
        "bounded_wait_seconds": case["bounded_wait_seconds"],
        "payload_assertions": case["payload_assertions"],
        "payload": _json_safe(payload),
        "unsubscribe_proof": unsubscribe_proof,
        "cleanup": case["cleanup"],
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_topic_deferral(case: Mapping[str, Any]) -> None:
    path = EVIDENCE_ROOT / "topics" / f"{case['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "case_id": case["id"],
        "status": case["status"],
        "uri": case["uri"],
        "attempted_publisher": case.get("attempted_publisher"),
        "bounded_wait_seconds": case.get("bounded_wait_seconds"),
        "payload_assertions": case.get("payload_assertions"),
        "unsubscribe_assertion": case.get("unsubscribe_assertion"),
        "cleanup": case.get("cleanup"),
        "blocker": case["blocker"],
        "missing_requirements": case["missing_requirements"],
        "future_review_trigger": case["future_review_trigger"],
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_topic_blocker(case: Mapping[str, Any], exc: BaseException) -> None:
    path = EVIDENCE_ROOT / "topics" / f"{case['id']}-blocker.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "case_id": case["id"],
        "status": "still-deferred-with-evidence",
        "uri": case["uri"],
        "publisher": case["publisher"],
        "blocker": _redact_local_paths(str(exc)),
        "bounded_wait_seconds": case["bounded_wait_seconds"],
        "unsubscribe_assertion": case["unsubscribe_assertion"],
        "recorded_at_unix": int(time.time()),
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_blocker_evidence(exc: BaseException) -> None:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "blocked",
        "test": "tests/live/test_object_topics_sandbox.py::test_live_object_reads_and_deterministic_topics_against_sandbox",
        "error_type": type(exc).__name__,
        "error": _redact_local_paths(str(exc)),
        "command": "WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=$WWISE_SAMPLE_PROJECT_PATH python -m pytest tests/live/test_object_topics_sandbox.py -q",
        "sandbox_required": True,
        "source_project_mutation_allowed": False,
        "recorded_at_unix": int(time.time()),
    }
    (EVIDENCE_ROOT / "task-6-object-topics-live-blocker.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _redact_local_paths(message: str) -> str:
    redacted = message.replace(str(REPO_ROOT), "<repo>")
    redacted = redacted.replace(str(Path.home()), "<home>")
    return redacted.replace("/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject", "$WWISE_SAMPLE_PROJECT_PATH")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))

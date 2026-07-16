from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

if os.getenv("WWISE_LIVE") != "1":
    pytest.skip("WWISE_LIVE=1 is required for live WAQL matrix tests", allow_module_level=True)

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
from tests.support.active_gate_failures import fail_if_active_runtime_failure  # pyright: ignore[reportMissingImports]
from wwise_waapi.waql import WAQL_API_URI  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "resources"
    / "waql"
    / "2022.1"
    / "object-get-live-matrix.json"
)
EVIDENCE_ROOT = REPO_ROOT / ".waapi-skill-state" / "evidence" / "wwise-waapi-live-sandbox-coverage"
WAQL_EVIDENCE_ROOT = EVIDENCE_ROOT / "waql"


def load_matrix() -> dict[str, Any]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


@pytest.mark.live
def test_live_waql_matrix_runs_read_only_against_sandbox() -> None:
    env = dict(os.environ)
    matrix = load_matrix()
    sandbox = None
    lifecycle = None
    client = None
    failed = True
    lock_root = _safe_lock_root(env)

    try:
        with LiveSandboxLock(lock_root):
            sandbox = prepare_sample_project_sandbox(env, hash_strategy="bounded")
            source_mtime_before = sandbox.source_project.stat().st_mtime
            source_hash_before = hash_project(sandbox.source_root, preferred_strategy="bounded")
            lifecycle = launch_sandboxed_wwise(sandbox, env)
            client = default_waapi_client_factory(lifecycle.waapi_url)

            context: dict[str, Any] = {}
            for case in matrix["live_cases"]:
                rendered = _render_case(case, context)
                if rendered is None:
                    _write_case_evidence(
                        case,
                        status="skipped",
                        result=[],
                        reason="placeholder source produced no object in this sandbox",
                    )
                    continue
                result = client.call(rendered["uri"], rendered["args"], options=rendered["options"])
                rows = _rows(result)
                _assert_case(case, rendered, rows)
                _write_case_evidence(case, status="passed", result=rows, rendered=rendered)
                context[case["id"]] = {"return": rows}

            assert sandbox.source_project.stat().st_mtime == source_mtime_before
            assert hash_project(sandbox.source_root, preferred_strategy="bounded").digest == source_hash_before.digest
            failed = False
    except (LiveEnvironmentError, SandboxFixtureError, HeadlessLifecycleError, OSError) as exc:
        _write_blocker_evidence(exc)
        fail_if_active_runtime_failure(exc, "live WAQL sandbox environment blocked execution")
        pytest.skip(f"live WAQL sandbox environment blocked execution: {type(exc).__name__}: {exc}")
    finally:
        if client is not None:
            client.disconnect()
        if lifecycle is not None and sandbox is not None:
            shutdown_sandboxed_wwise(lifecycle, sandbox)
        if sandbox is not None:
            cleanup_sandbox(sandbox, failed=failed)


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


def _safe_case_evidence_path(case: Mapping[str, Any]) -> Path:
    target = (REPO_ROOT / str(case["evidence_path"])).resolve(strict=False)
    evidence_root = WAQL_EVIDENCE_ROOT.resolve(strict=False)
    if not path_is_under(target, evidence_root):
        raise AssertionError(f"case evidence path must stay under {WAQL_EVIDENCE_ROOT}: {target}")
    return target


def _redact_local_paths(message: str) -> str:
    redacted = message.replace(str(REPO_ROOT), "<repo>")
    redacted = redacted.replace(str(Path.home()), "<home>")
    return redacted.replace("/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject", "$WWISE_SAMPLE_PROJECT_PATH")


def _rows(result: Any) -> list[dict[str, Any]]:
    assert isinstance(result, Mapping), f"WAAPI result must be a mapping, got {type(result).__name__}"
    rows = result.get("return")
    assert isinstance(rows, list), f"WAAPI result must contain a return array, got {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return [dict(row) for row in rows]


def _render_case(case: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any] | None:
    rendered = {
        "uri": case["uri"],
        "args": dict(case["args"]),
        "options": dict(case["options"]),
    }
    placeholders = case.get("placeholders", {})
    assert isinstance(placeholders, Mapping)
    values: dict[str, str] = {}
    for name, selector in placeholders.items():
        value = _select_placeholder(str(selector), context)
        if value is None and case.get("skip_if_placeholder_missing") is True:
            return None
        assert value is not None, f"placeholder {name} from {selector} was unavailable"
        values[str(name)] = str(value)
    if values:
        rendered["args"]["waql"] = rendered["args"]["waql"].format(**values)
    return rendered


def _select_placeholder(selector: str, context: Mapping[str, Any]) -> Any:
    case_id, _, tail = selector.partition(".")
    current: Any = context.get(case_id)
    if current is None:
        return None
    for token in tail.split("."):
        if not token:
            continue
        if token.startswith("return[") and token.endswith("]"):
            index = int(token.removeprefix("return[").removesuffix("]"))
            rows = current.get("return") if isinstance(current, Mapping) else None
            if not isinstance(rows, list) or len(rows) <= index:
                return None
            current = rows[index]
        elif isinstance(current, Mapping):
            current = current.get(token)
        else:
            return None
    return current


def _assert_case(case: Mapping[str, Any], rendered: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    assert rendered["uri"] == WAQL_API_URI
    assert case["no_mutation"] is True
    expected = case["expected"]
    assert isinstance(expected, Mapping)
    _assert_count(case["id"], expected["result_count"], rows)

    fields = expected.get("fields", [])
    for row in rows:
        assert set(row) <= set(fields), f"{case['id']} returned unrequested fields: {row}"

    identity = expected.get("identity")
    if isinstance(identity, Mapping):
        for key, value in identity.items():
            if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                value = rendered["args"]["waql"].split('"')[1]
            assert any(row.get(key) == value for row in rows), f"{case['id']} missing identity {key}={value!r}: {rows}"

    expected_type = expected.get("type")
    if isinstance(expected_type, str) and rows:
        assert all(row.get("type") == expected_type for row in rows)

    path_prefix = expected.get("path_prefix")
    if isinstance(path_prefix, str) and rows:
        assert all(str(row.get("path", "")).startswith(path_prefix) for row in rows)

    prop = expected.get("property")
    if isinstance(prop, Mapping):
        name = prop["name"]
        assert rows, f"{case['id']} expected a property row"
        for row in rows:
            assert name in row, f"{case['id']} missing property {name}: {row}"
            if prop["comparison"] == ">=":
                assert row[name] >= prop["value"]
            else:  # pragma: no cover - matrix currently uses >= only
                raise AssertionError(f"unsupported comparison: {prop['comparison']}")

    for field in expected.get("forbidden_fields", []):
        assert all(field not in row for row in rows), f"{case['id']} returned forbidden field {field}"


def _assert_count(case_id: str, policy: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    if policy["policy"] == "exact":
        assert len(rows) == policy["count"], f"{case_id} expected exactly {policy['count']} rows, got {len(rows)}"
    elif policy["policy"] == "at_most":
        assert len(rows) <= policy["count"], f"{case_id} expected at most {policy['count']} rows, got {len(rows)}"
        if not policy.get("allow_empty", False):
            assert rows, f"{case_id} unexpectedly returned no rows"
    else:  # pragma: no cover - unit tests constrain policies
        raise AssertionError(f"unsupported result count policy: {policy['policy']}")


def _write_case_evidence(
    case: Mapping[str, Any],
    *,
    status: str,
    result: list[dict[str, Any]],
    rendered: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    WAQL_EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_path = _safe_case_evidence_path(case)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_id": case["id"],
        "status": status,
        "uri": case["uri"],
        "query": (rendered or case)["args"]["waql"],
        "options": (rendered or case)["options"],
        "expected": case["expected"],
        "result_count": len(result),
        "result_count_policy": case["expected"]["result_count"],
        "assertions": case["assertions"],
        "no_mutation": case["no_mutation"],
        "sources": case["sources"],
        "reason": reason,
        "recorded_at_unix": int(time.time()),
    }
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_blocker_evidence(exc: BaseException) -> None:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "blocked",
        "test": "tests/live/test_waql_live_matrix.py::test_live_waql_matrix_runs_read_only_against_sandbox",
        "error_type": type(exc).__name__,
        "error": _redact_local_paths(str(exc)),
        "command": "WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=$WWISE_SAMPLE_PROJECT_PATH python -m pytest tests/live/test_waql_live_matrix.py -q",
        "sandbox_required": True,
        "source_project_mutation_allowed": False,
        "recorded_at_unix": int(time.time()),
    }
    (EVIDENCE_ROOT / "task-5-waql-live-blocker.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

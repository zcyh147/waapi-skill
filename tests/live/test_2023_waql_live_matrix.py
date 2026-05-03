from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import default_waapi_client_factory  # pyright: ignore[reportMissingImports]
from tests.destructive.support.live_environment import path_is_under  # pyright: ignore[reportMissingImports]
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from wwise_waapi.waql import WAQL_API_URI  # pyright: ignore[reportMissingImports]

from tests.live.test_2023_live_prerequisites import (  # pyright: ignore[reportMissingImports]
    EXPECTED_SAMPLE_PROJECT,
    EXPECTED_WWISE_VERSION,
    require_2023_live_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "waql" / EXPECTED_WWISE_VERSION / "object-get-live-matrix.json"
SANDBOX_ROOT = REPO_ROOT / ".sisyphus" / "runtime" / "wwise-2023-live-smoke-sandboxes"
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence" / "wwise-2023-test-parity" / "live-read-only"
MUTATING_TOKENS = ("set", "delete", "create", "import", "move", "rename")


@pytest.mark.live
def test_2023_live_waql_object_get_matrix_runs_read_only_against_sandbox() -> None:
    contract = require_2023_live_environment()
    assert contract.sample_project_source == EXPECTED_SAMPLE_PROJECT

    env = dict(os.environ)
    matrix = _load_matrix()
    sandbox = None
    lifecycle = None
    client = None
    failed = True

    with LiveSandboxLock(SANDBOX_ROOT):
        sandbox = prepare_sample_project_sandbox(env, sandbox_root=SANDBOX_ROOT, hash_strategy="bounded")
        source_mtime_before = sandbox.source_project.stat().st_mtime
        source_hash_before = hash_project(sandbox.source_root, preferred_strategy="bounded")
        try:
            lifecycle = launch_sandboxed_wwise(sandbox, env)
            assert str(sandbox.sandbox_project) in lifecycle.command
            assert str(EXPECTED_SAMPLE_PROJECT) not in lifecycle.command
            client = default_waapi_client_factory(lifecycle.waapi_url)

            context: dict[str, Any] = {}
            for case in matrix["live_cases"]:
                rendered = _render_case(case, context)
                rows = _execute_case(client, rendered)
                _assert_case_result(case, rendered, rows)
                _write_case_evidence(case, rendered, rows)
                context[case["id"]] = {"return": rows}

            failed = False
        finally:
            if client is not None:
                client.disconnect()
            if lifecycle is not None:
                shutdown_sandboxed_wwise(lifecycle, sandbox)
            cleanup_sandbox(sandbox, failed=failed)

    assert sandbox.source_project.stat().st_mtime == source_mtime_before
    assert hash_project(sandbox.source_root, preferred_strategy="bounded").digest == source_hash_before.digest
    assert not sandbox.sandbox_path.exists()


def _load_matrix() -> dict[str, Any]:
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert matrix["metadata"]["wwise_version_target"] == EXPECTED_WWISE_VERSION
    assert matrix["metadata"]["default_live"] is False
    assert matrix["metadata"]["sandbox_required"] is True
    assert matrix["metadata"]["source_project_mutation_allowed"] is False
    return matrix



def _execute_case(client: Any, case: Mapping[str, Any]) -> list[dict[str, Any]]:
    _assert_case_is_read_only(case)
    result = client.call(case["uri"], case["args"], options=case["options"])
    return _rows(result)


def _assert_case_is_read_only(case: Mapping[str, Any]) -> None:
    assert case["uri"] == WAQL_API_URI
    assert case["no_mutation"] is True
    query_tokens = set(re.findall(r"[a-zA-Z_]+", str(case["args"]["waql"]).lower()))
    blocked = sorted(token for token in MUTATING_TOKENS if token in query_tokens)
    if blocked:
        raise AssertionError(f"mutating WAQL token(s) not allowed: {', '.join(blocked)}")


def _render_case(case: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    rendered: dict[str, Any] = dict(case)
    rendered["args"] = dict(case["args"])
    rendered["options"] = dict(case["options"])
    placeholders = case.get("placeholders", {})
    assert isinstance(placeholders, Mapping)

    values: dict[str, str] = {}
    for name, selector in placeholders.items():
        value = _select_placeholder(str(selector), context)
        assert value is not None, f"placeholder {name} from {selector} was unavailable"
        values[str(name)] = str(value)

    if values:
        rendered["args"]["waql"] = rendered["args"]["waql"].format(**values)
        rendered["_placeholder_values"] = values
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


def _rows(result: Any) -> list[dict[str, Any]]:
    assert isinstance(result, Mapping), f"WAAPI result must be a mapping, got {type(result).__name__}"
    rows = result.get("return")
    assert isinstance(rows, list), f"WAAPI result must contain a return array, got {result!r}"
    assert all(isinstance(row, Mapping) for row in rows)
    return [dict(row) for row in rows]


def _assert_case_result(case: Mapping[str, Any], rendered: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    expected = case["expected"]
    assert isinstance(expected, Mapping)
    _assert_count(case["id"], expected["result_count"], rows)

    returned_fields = set(rendered["options"]["return"])
    expected_fields = set(expected.get("fields", rendered["options"]["return"]))
    assert expected_fields <= returned_fields, f"{case['id']} expected fields outside return options"
    for row in rows:
        assert set(row) <= returned_fields, f"{case['id']} returned unrequested fields: {row}"
        assert set(row) <= expected_fields, f"{case['id']} returned fields outside expected assertion set: {row}"

    identity = expected.get("identity")
    if isinstance(identity, Mapping) and rows:
        placeholders = rendered.get("_placeholder_values", {})
        assert isinstance(placeholders, Mapping)
        for key, value in identity.items():
            if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
                value = placeholders[value[1:-1]]
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
            else:
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
    else:
        raise AssertionError(f"unsupported result count policy: {policy['policy']}")


def _write_case_evidence(case: Mapping[str, Any], rendered: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    evidence_path = _safe_case_evidence_path(case)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    actual_fields = sorted({field for row in rows for field in row})
    payload = {
        "case_id": case["id"],
        "status": "passed",
        "uri": case["uri"],
        "query": rendered["args"]["waql"],
        "options": rendered["options"],
        "expected": case["expected"],
        "actual": {
            "result_count": len(rows),
            "returned_fields": actual_fields,
            "rows": rows,
        },
        "result_count": len(rows),
        "result_count_policy": case["expected"]["result_count"],
        "assertions": case["assertions"],
        "evidence_path": case["evidence_path"],
        "no_mutation": case["no_mutation"],
        "sources": case["sources"],
        "wwise_version": EXPECTED_WWISE_VERSION,
        "recorded_at_unix": int(time.time()),
    }
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_case_evidence_path(case: Mapping[str, Any]) -> Path:
    evidence_path = (REPO_ROOT / str(case["evidence_path"])).resolve(strict=False)
    evidence_root = EVIDENCE_ROOT.resolve(strict=False)
    if not path_is_under(evidence_path, evidence_root):
        raise AssertionError(f"case evidence path must stay under {EVIDENCE_ROOT}: {evidence_path}")
    return evidence_path

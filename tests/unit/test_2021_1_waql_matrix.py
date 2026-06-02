from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from tests.live.test_2021_1_object_get_matrix import (  # pyright: ignore[reportMissingImports]
    MUTATING_TOKENS,
    READ_ONLY_WAAPI_OPERATIONS,
    _assert_case_result,
    _execute_case,
    _load_matrix,
)
from wwise_waapi.waql import WAQL_API_URI, validate_waql_example  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2021.1"
MATRIX_PATH = REPO_ROOT / "tests" / "fixtures" / "resource-evidence" / "waql" / VERSION / "object-get-live-matrix.json"
SCHEMA_PATH = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "manifest" / VERSION / "schemas.json"
FORBIDDEN_PROOF_FRAGMENTS = ("2022.1", "2023.1", "2024.1", "2025.1")


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(self, uri: str, args: Mapping[str, Any], *, options: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((uri, args, options))
        return {"return": []}


def test_2021_1_waql_matrix_is_exact_versioned_and_schema_linked() -> None:
    matrix = _matrix()
    object_get_schema = _object_get_schema()

    assert MATRIX_PATH.exists()
    assert matrix["metadata"]["wwise_version_target"] == VERSION
    assert matrix["metadata"]["wwise_build"] == "2021.1.14.8108"
    assert matrix["metadata"]["wwise_version_display"] == "v2021.1.14"
    assert matrix["metadata"]["uri"] == WAQL_API_URI
    assert matrix["metadata"]["schema_source"] == "resources/manifest/2021.1/schemas.json#ak.wwise.core.object.get"
    assert matrix["metadata"]["sandbox_required"] is True
    assert matrix["metadata"]["source_project_mutation_allowed"] is False
    assert matrix["metadata"]["default_live"] is False
    assert matrix["metadata"]["fresh_2021_live_evidence_required"] is True
    assert matrix["metadata"]["read_only_waapi_operations"] == READ_ONLY_WAAPI_OPERATIONS
    assert object_get_schema["schema"]["argsSchema"]["properties"]["waql"]["type"] == "string"
    assert object_get_schema["schema"]["resultSchema"]["properties"]["return"]["type"] == "array"


def test_2021_1_waql_live_cases_are_read_only_and_use_2021_evidence_only() -> None:
    matrix = _matrix()
    seen_ids: set[str] = set()

    assert matrix["summary"]["case_count"] == len(matrix["live_cases"]) == 9
    assert matrix["summary"]["live_tested_cases"] == 9
    for case in matrix["live_cases"]:
        assert case["id"] not in seen_ids
        seen_ids.add(case["id"])
        assert case["uri"] == WAQL_API_URI
        assert case["coverage_status"] == "live-tested"
        assert case["no_mutation"] is True
        assert case["evidence_path"].startswith(
            ".sisyphus/evidence/wwise-2021-waapi-integration-coverage/live-read-only/"
        )
        assert case["evidence_path"].endswith(f"/{case['id']}.json")
        assert case["promotion_evidence"] == case["evidence_path"]
        assert "2021.1" in case["promotion_required_evidence"]
        assert case["assertions"]
        assert case["expected"]["fields"]
        assert case["expected"]["result_count"]["policy"] in {"exact", "at_most", "at_least_roots"}
        assert not any(fragment in case["evidence_path"] for fragment in FORBIDDEN_PROOF_FRAGMENTS)
        assert not any(fragment in " ".join(case["sources"]) for fragment in FORBIDDEN_PROOF_FRAGMENTS)
        validate_waql_example({**case, "expect_live_safe": True})


def test_2021_1_hierarchy_preflight_records_actual_roots_before_path_assertions() -> None:
    matrix = _matrix()
    preflight = matrix["hierarchy_preflight"]
    roots = preflight["confirmed_roots"]
    root_paths = [root["path"] for root in roots]

    assert preflight["live_preflight_case"] == "hierarchy_roots_preflight_2021_contract"
    assert preflight["root_count"] == len(roots) == 23
    assert roots[0] == {"name": "SampleProject", "path": "\\", "type": "Project"}
    assert {"name": "Actor-Mixer Hierarchy", "path": "\\Actor-Mixer Hierarchy", "type": "WorkUnit"} in roots
    assert "\\Containers" not in root_paths
    assert all(root["type"] in {"Project", "WorkUnit"} for root in roots)

    preflight_case = next(case for case in matrix["live_cases"] if case["id"] == preflight["live_preflight_case"])
    assert preflight_case["category"] == "hierarchy preflight"
    assert preflight_case["expected"]["root_paths"] == root_paths
    assert preflight_case["expected"]["absent_paths"] == ["\\Containers"]


def test_2021_1_missing_assumed_hierarchy_root_is_deferred_not_promoted() -> None:
    matrix = _matrix()
    blocked = matrix["hierarchy_preflight"]["absent_assumptions"]

    assert blocked == [
        {
            "blocked_reason": "Fresh 2021.1 hierarchy preflight did not return this root path; newer-version root names must not be promoted as 2021.1 behavior proof.",
            "coverage_status": "deferred-not-live-tested",
            "path": "\\Containers",
            "promotion_allowed": False,
            "source": "blocked-newer-version-assumption",
        }
    ]
    assert all(case["args"]["waql"] != '"\\\\Containers"' for case in matrix["live_cases"])
    assert all("Containers" not in case["id"] for case in matrix["live_cases"])


def test_2021_1_waql_mutation_guard_rejects_each_token_before_client_call() -> None:
    matrix = _load_matrix()

    for token in MUTATING_TOKENS:
        mutating_case = dict(matrix["live_cases"][0])
        mutating_case["id"] = f"mutation_guard_rejects_{token}_before_call"
        mutating_case["args"] = {"waql": f"from type Sound {token}"}
        client = _RecordingClient()

        with pytest.raises(AssertionError, match="mutating WAQL token"):
            _execute_case(client, mutating_case)

        assert client.calls == []


def test_2021_1_waql_allow_empty_identity_case_accepts_empty_rows() -> None:
    case = {
        "id": "allow_empty_identity_contract",
        "expected": {
            "result_count": {"policy": "at_most", "count": 1, "allow_empty": True},
            "identity": {"name": "Default Work Unit"},
            "fields": ["id", "name"],
        },
    }
    rendered = {"options": {"return": ["id", "name"]}}

    _assert_case_result(case, rendered, [], matrix=_matrix())


def _matrix() -> dict[str, Any]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _object_get_schema() -> Mapping[str, Any]:
    schemas = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["schemas"]
    return next(entry for entry in schemas if entry["uri"] == WAQL_API_URI)

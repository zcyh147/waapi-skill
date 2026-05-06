from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.waql import WAQL_API_URI, validate_waql_example  # pyright: ignore[reportMissingImports]


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
RESOURCE_REFERENCE = REPO_ROOT / "skills" / "waapi-skill" / "resources" / "waql" / "2022.1" / "object-get-live-matrix.json"
GAP_EVIDENCE_PATH = REPO_ROOT / ".sisyphus" / "evidence" / "task-8-waql-missing.md"
MANIFEST_PATH = (
    REPO_ROOT
    / "skills"
    / "waapi-skill"
    / "resources"
    / "manifest"
    / "2022.1"
    / "schemas.json"
)

REQUIRED_LIVE_CATEGORIES = {
    "path queries",
    "GUID queries",
    "name/type filters",
    "quoted strings and JSON escaping",
    "descendant traversal",
    "ancestor traversal",
    "property comparisons",
    "return/options selection",
    "empty results",
}
REQUIRED_GAP_IDS = {
    "invalid_syntax_error_payload_schema",
    "mutation_semantics_rejection",
    "raw_quote_escaping_beyond_json",
    "exhaustive_property_reference_inventory",
    "performance_limit_semantics",
}
MUTATING_TOKENS = (" set ", " delete ", " create ", " import ", " move ", " rename ")


def load_matrix() -> dict[str, Any]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def test_waql_matrix_resource_is_source_grounded_and_schema_linked() -> None:
    matrix = load_matrix()
    metadata = matrix["metadata"]
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    object_get_schema = next(entry for entry in manifest["schemas"] if entry["uri"] == WAQL_API_URI)

    assert MATRIX_PATH.exists()
    assert RESOURCE_REFERENCE.exists()
    if not GAP_EVIDENCE_PATH.exists():
        pytest.skip("WAQL gap evidence file is not present in this checkout")
    assert metadata["uri"] == WAQL_API_URI
    assert metadata["reference"] == "resources/waql/2022.1/object-get-live-matrix.json"
    assert metadata["gap_evidence"] == ".sisyphus/evidence/task-8-waql-missing.md"
    assert metadata["sandbox_required"] is True
    assert metadata["source_project_mutation_allowed"] is False
    assert metadata["default_live"] is False
    assert object_get_schema["schema"]["argsSchema"]["properties"]["waql"]["type"] == "string"
    assert object_get_schema["schema"]["resultSchema"]["properties"]["return"]["type"] == "array"


def test_waql_live_cases_have_required_shape_and_no_mutation() -> None:
    matrix = load_matrix()
    live_cases = matrix["live_cases"]
    seen_ids: set[str] = set()

    assert {case["category"] for case in live_cases} >= REQUIRED_LIVE_CATEGORIES
    assert len(live_cases) >= len(REQUIRED_LIVE_CATEGORIES)

    for case in live_cases:
        assert case["id"] not in seen_ids
        seen_ids.add(case["id"])
        assert case["uri"] == WAQL_API_URI
        assert case["no_mutation"] is True
        assert case["evidence_path"].startswith(
            ".sisyphus/evidence/wwise-2022-test-parity/live-read-only/"
        )
        assert case["evidence_path"].endswith(f"{case['id']}.json")
        assert case["sources"]
        assert all("waql-2022.1.md" not in source for source in case["sources"])
        assert case["assertions"]
        assert "expected" in case
        assert "result_count" in case["expected"]
        assert case["expected"]["result_count"]["policy"] in {"exact", "at_most"}
        validate_waql_example({**case, "expect_live_safe": True})
        padded = f" {case['args']['waql'].lower()} "
        assert not any(token in padded for token in MUTATING_TOKENS)


def test_waql_live_cases_record_behavioral_assertions_not_just_success() -> None:
    matrix = load_matrix()

    for case in matrix["live_cases"]:
        expected: Mapping[str, Any] = case["expected"]
        has_behavior_assertion = any(
            key in expected
            for key in ("identity", "type", "property", "path_prefix", "forbidden_fields")
        ) or expected["result_count"] == {"policy": "exact", "count": 0}
        assert has_behavior_assertion, case["id"]
        assert expected.get("fields"), case["id"]


def test_waql_fail_closed_gaps() -> None:
    matrix = load_matrix()
    gaps = matrix["fail_closed_gaps"]
    by_id = {gap["id"]: gap for gap in gaps}

    assert set(by_id) == REQUIRED_GAP_IDS
    for gap in gaps:
        assert gap["status"] == "fail-closed"
        assert gap["counts_as_live_coverage"] is False
        assert gap["blocked_behavior"]
        assert gap["reason"]
        assert gap["references"]
        assert any("task-8-waql-missing.md" in reference for reference in gap["references"])
        assert any("object-get-live-matrix.json" in reference for reference in gap["references"])

    assert "where" in by_id["invalid_syntax_error_payload_schema"]["example_query"]
    assert "delete" in by_id["mutation_semantics_rejection"]["example_query"]
    assert "raw WAQL" in by_id["raw_quote_escaping_beyond_json"]["blocked_behavior"]
    assert "property/reference" in by_id["exhaustive_property_reference_inventory"]["blocked_behavior"]
    assert "timeout" in by_id["performance_limit_semantics"]["blocked_behavior"]

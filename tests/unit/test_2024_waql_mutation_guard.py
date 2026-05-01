from __future__ import annotations

from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from tests.live.test_2024_waql_live_matrix import (  # pyright: ignore[reportMissingImports]
    MUTATING_TOKENS,
    _assert_case_result,
    _execute_case,
    _load_matrix,
)


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(self, uri: str, args: Mapping[str, Any], *, options: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((uri, args, options))
        return {"return": []}


def test_2024_waql_mutation_guard_rejects_each_mutating_token_before_client_call() -> None:
    matrix = _load_matrix()

    for token in MUTATING_TOKENS:
        mutating_case = dict(matrix["live_cases"][0])
        mutating_case["id"] = f"mutation_guard_rejects_{token}_before_call"
        mutating_case["args"] = {"waql": f"from type Sound {token}"}
        client = _RecordingClient()

        with pytest.raises(AssertionError, match="mutating WAQL token"):
            _execute_case(client, mutating_case)

        assert client.calls == []


def test_2024_waql_matrix_cases_are_declared_read_only_and_versioned() -> None:
    matrix = _load_matrix()

    assert matrix["metadata"]["wwise_version_target"] == "2024.1"
    assert matrix["metadata"]["sandbox_required"] is True
    assert matrix["metadata"]["source_project_mutation_allowed"] is False
    assert matrix["summary"]["case_count"] == len(matrix["live_cases"])
    for case in matrix["live_cases"]:
        assert case["uri"] == "ak.wwise.core.object.get"
        assert case["no_mutation"] is True
        assert "2024.1" in " ".join(case["sources"])
        assert case["evidence_path"].startswith(
            ".sisyphus/evidence/wwise-2024-waapi-integration-coverage/live-read-only/"
        )
        assert "2023" not in case["evidence_path"]


def test_2024_waql_allow_empty_identity_case_accepts_empty_rows() -> None:
    case = {
        "id": "allow_empty_identity_contract",
        "expected": {
            "result_count": {"policy": "at_most", "count": 1, "allow_empty": True},
            "identity": {"name": "Default Work Unit"},
            "fields": ["id", "name"],
        },
    }
    rendered = {"options": {"return": ["id", "name"]}}

    _assert_case_result(case, rendered, [])

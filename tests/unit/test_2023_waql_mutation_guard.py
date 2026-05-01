from __future__ import annotations

from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from tests.live.test_2023_waql_live_matrix import (  # pyright: ignore[reportMissingImports]
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


def test_2023_waql_mutation_guard_rejects_before_client_call() -> None:
    matrix = _load_matrix()
    mutating_case = dict(matrix["live_cases"][0])
    mutating_case["id"] = "mutation_guard_rejects_delete_before_call"
    mutating_case["args"] = {"waql": "from type Sound delete"}
    client = _RecordingClient()

    with pytest.raises(AssertionError, match="mutating WAQL token"):
        _execute_case(client, mutating_case)

    assert client.calls == []


def test_2023_waql_allow_empty_identity_case_accepts_empty_rows() -> None:
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

from __future__ import annotations

from typing import Any, Mapping

from wwise_waapi.builders.container_suitability import (  # pyright: ignore[reportMissingImports]
    OBJECT_GET_URI,
    assess_writable_container_suitability,
)


class FakeSafeReadClient:
    def __init__(self, rows: list[Mapping[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any] | None]] = []

    def call(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        self.calls.append((uri, args, options))
        return {"return": self.rows}


def test_management_root_returns_default_work_unit_candidate_without_retargeting() -> None:
    result = assess_writable_container_suitability(r"\Master-Mixer Hierarchy")

    assert result.valid is False
    assert result.invalid_target == r"\Master-Mixer Hierarchy"
    assert result.reason == "management-root-not-directly-writable"
    assert result.candidate_targets == (r"\Master-Mixer Hierarchy\Default Work Unit",)
    assert result.requires_user_confirmation is True
    assert result.requires_live_verification is False
    assert result.as_dict()["candidate_targets"] == [r"\Master-Mixer Hierarchy\Default Work Unit"]


def test_no_writable_candidate_blocks_safely_without_mutation_payload() -> None:
    result = assess_writable_container_suitability(r"\Not A Wwise Root")

    assert result.valid is False
    assert result.invalid_target == r"\Not A Wwise Root"
    assert result.reason == "unknown-management-root"
    assert result.candidate_targets == ()
    assert result.requires_user_confirmation is False
    assert result.requires_live_verification is True
    assert "resolved_identity" not in result.as_dict()


def test_root_level_type_segment_is_structural_candidate_not_direct_target() -> None:
    result = assess_writable_container_suitability(r"\Actor-Mixer Hierarchy\<Sound>Encoded")

    assert result.valid is False
    assert result.reason == "type-segment-not-directly-writable"
    assert result.candidate_targets == (r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Encoded",)
    assert result.requires_user_confirmation is True


def test_ambiguous_known_root_child_blocks_until_live_verification_or_confirmation() -> None:
    result = assess_writable_container_suitability(r"\Actor-Mixer Hierarchy\Custom Work Unit")

    assert result.valid is False
    assert result.reason == "no-obvious-writable-candidate"
    assert result.candidate_targets == ()
    assert result.requires_user_confirmation is False
    assert result.requires_live_verification is True


def test_live_child_resolution_hook_uses_only_safe_read_and_requires_confirmation() -> None:
    client = FakeSafeReadClient(
        [
            {
                "id": "{default-work-unit}",
                "name": "Default Work Unit",
                "type": "WorkUnit",
                "path": r"\Custom Root\Default Work Unit",
            }
        ]
    )

    result = assess_writable_container_suitability(r"\Custom Root", safe_read_client=client)

    assert result.valid is False
    assert result.reason == "live-child-candidate-requires-confirmation"
    assert result.candidate_targets == (r"\Custom Root\Default Work Unit",)
    assert result.requires_user_confirmation is True
    assert result.requires_live_verification is False
    assert result.resolved_identity == client.rows[0]
    assert client.calls == [
        (
            OBJECT_GET_URI,
            {"waql": r'"\\Custom Root" select children where name = "Default Work Unit"'},
            {"return": ["id", "name", "type", "path"]},
        )
    ]


def test_confirmed_candidate_policy_does_not_rewrite_target() -> None:
    result = assess_writable_container_suitability(r"\Master-Mixer Hierarchy", allow_confirmed_candidate=True)

    assert result.valid is True
    assert result.invalid_target == r"\Master-Mixer Hierarchy"
    assert result.candidate_targets == (r"\Master-Mixer Hierarchy\Default Work Unit",)


def test_live_child_resolution_escapes_waql_literals() -> None:
    client = FakeSafeReadClient([])

    assess_writable_container_suitability(r'\Custom "Root"', safe_read_client=client)

    assert client.calls[0][1] == {"waql": r'"\\Custom \"Root\"" select children where name = "Default Work Unit"'}


def test_live_child_resolution_rejects_mismatched_rows() -> None:
    client = FakeSafeReadClient(
        [
            {"name": "Default Work Unit", "type": "WorkUnit", "path": r"\Different Root\Default Work Unit"},
            {"name": "Default Work Unit", "type": "Sound", "path": r"\Custom Root\Default Work Unit"},
            {"name": "Not Default", "type": "WorkUnit", "path": r"\Custom Root\Default Work Unit"},
        ]
    )

    result = assess_writable_container_suitability(r"\Custom Root", safe_read_client=client)

    assert result.valid is False
    assert result.reason == "unknown-management-root"
    assert result.candidate_targets == ()

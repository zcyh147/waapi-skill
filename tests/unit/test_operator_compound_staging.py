from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from wwise_waapi.config import SkillConfig  # pyright: ignore[reportMissingImports]
from wwise_waapi.dispatcher import WwiseDispatcher  # pyright: ignore[reportMissingImports]
from wwise_waapi.manifest import ManifestStore  # pyright: ignore[reportMissingImports]
from wwise_waapi.operator import execute_operator_compound_staging  # pyright: ignore[reportMissingImports]


COMPOUND_PROMPT = "Find every sound under Default Work Unit with volume below zero, summarize them, then fix them one by one after confirmation."


class FakeWaapiClient:
    def __init__(self, result: Any | None = None) -> None:
        self.result = {"return": []} if result is None else result
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(self, uri: str, args: Mapping[str, Any] | None = None, options: Mapping[str, Any] | None = None) -> Any:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return {"version": "2022.1"}
        return self.result


def ready_config(tmp_path: Path) -> SkillConfig:
    return SkillConfig(tmp_path, wwise_version="2022.1", waapi_host="127.0.0.1", waapi_port=8080)


def manifest_store() -> ManifestStore:
    store = ManifestStore()
    store.record(
        "2022.1",
        {
            "functions": [
                {"uri": "ak.wwise.core.getInfo"},
                {"uri": "ak.wwise.core.object.get"},
            ],
            "topics": [],
        },
    )
    return store


def test_compound_prompt_executes_read_first_and_stops_before_preview(tmp_path: Path) -> None:
    client = FakeWaapiClient(
        {
            "return": [
                {
                    "id": "{sound-1}",
                    "name": "Too Loud",
                    "type": "Sound",
                    "path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\Too Loud",
                }
            ]
        }
    )
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = execute_operator_compound_staging(
        COMPOUND_PROMPT,
        config=ready_config(tmp_path),
        dispatcher=dispatcher,
        evidence_dir=tmp_path,
        connection_available=True,
    )

    assert result.status == "read_complete"
    assert result.policy.intent_family == "compound_read_then_confirm"
    assert [stage.status for stage in result.stages] == ["read_complete"]
    assert result.stages[0].stage_id == "read-1"
    assert result.stages[0].evidence["mutation_preview_created"] is False
    assert result.stages[0].evidence["mutation_dispatcher_called"] is False
    assert client.calls[0][0] == "ak.wwise.core.object.get"
    assert client.calls == [
        (
            "ak.wwise.core.object.get",
            {"waql": "from type Sound"},
            {"return": ["id", "name", "type", "path"]},
        )
    ]


def test_compound_does_not_create_mutation_preview_without_read_evidence(tmp_path: Path) -> None:
    client = FakeWaapiClient({"return": []})
    dispatcher = WwiseDispatcher(client=client, manifest_store=manifest_store())

    result = execute_operator_compound_staging(
        "Find the sound then rename it after confirmation.",
        config=ready_config(tmp_path),
        dispatcher=dispatcher,
        connection_available=True,
    )

    assert result.status == "read_complete"
    assert tuple(stage.stage_id for stage in result.stages) == ("read-1",)
    assert not any(stage.status in {"preview_ready", "awaiting_confirmation", "executed"} for stage in result.stages)
    assert result.stages[0].evidence["mutation_preview_created"] is False


def test_compound_preview_waits_for_confirmation_and_never_dispatches_mutation(tmp_path: Path) -> None:
    read_evidence = {"dispatcher_called": True, "dispatcher_request": {"api": "ak.wwise.core.object.get"}}
    read_rows = ({"id": "{sound-1}", "name": "Too Loud", "type": "Sound"},)

    result = execute_operator_compound_staging(
        COMPOUND_PROMPT,
        config=ready_config(tmp_path),
        read_evidence=read_evidence,
        read_rows=read_rows,
        confirmation_state="unknown",
        connection_available=True,
    )

    assert result.status == "awaiting_confirmation"
    assert [stage.status for stage in result.stages] == ["read_complete", "preview_ready", "awaiting_confirmation"]
    assert [stage.stage_id for stage in result.stages] == ["read-1", "preview-1", "confirm-1"]
    assert result.stages[1].evidence["read_stage_id"] == "read-1"
    assert result.stages[1].evidence["target_identity"] == ["{sound-1}"]
    assert result.stages[1].evidence["dispatcher_called"] is False
    assert result.stages[1].evidence["allow_destructive"] is False
    assert result.stages[2].evidence["preview_stage_id"] == "preview-1"
    assert result.stages[2].evidence["executed"] is False
    assert result.stages[2].evidence["verified"] is False
    assert result.stages[2].evidence["dispatcher_called"] is False
    assert result.blockers == ("explicit confirmation state is required",)


def test_read_and_preview_evidence_are_separate_stage_entries(tmp_path: Path) -> None:
    result = execute_operator_compound_staging(
        "Find the sound then set its volume after confirmation.",
        config=ready_config(tmp_path),
        read_evidence={"dispatcher_called": True, "read_token": "read-evidence"},
        read_rows=({"id": "{sound-1}", "name": "Tone"},),
        connection_available=True,
    )

    payload = result.as_dict()
    read_stage, preview_stage, confirm_stage = payload["stages"]

    assert read_stage["stage_id"] != preview_stage["stage_id"]
    assert read_stage["evidence"] == {"dispatcher_called": True, "read_token": "read-evidence"}
    assert preview_stage["evidence"]["preview_ready"] is True
    assert preview_stage["evidence"]["read_stage_id"] == read_stage["stage_id"]
    assert confirm_stage["status"] == "awaiting_confirmation"


def test_confirmed_compound_reuses_preview_identity_but_still_does_not_execute(tmp_path: Path) -> None:
    result = execute_operator_compound_staging(
        COMPOUND_PROMPT,
        config=ready_config(tmp_path),
        read_evidence={"dispatcher_called": True},
        read_rows=({"id": "{sound-1}", "name": "Too Loud"},),
        preview_evidence={"target_identity": ["{sound-1}"]},
        confirmation_state="confirmed",
        connection_available=True,
    )

    assert result.status == "blocked"
    assert [stage.stage_id for stage in result.stages] == ["read-1", "preview-1", "execute-1"]
    assert result.stages[1].evidence["target_identity"] == ["{sound-1}"]
    assert result.stages[2].status == "blocked"
    assert result.stages[2].evidence["executed"] is False
    assert result.stages[2].evidence["verified"] is False
    assert result.stages[2].evidence["dispatcher_called"] is False


def test_confirmed_compound_mismatched_preview_identity_blocks_repreview(tmp_path: Path) -> None:
    result = execute_operator_compound_staging(
        COMPOUND_PROMPT,
        config=ready_config(tmp_path),
        read_evidence={"dispatcher_called": True},
        read_rows=({"id": "{sound-1}", "name": "Too Loud"},),
        preview_evidence={"target_identity": ["{other-sound}"]},
        confirmation_state="confirmed",
        connection_available=True,
    )

    assert result.status == "blocked"
    assert [stage.stage_id for stage in result.stages] == ["read-1", "preview-1"]
    assert result.stages[1].status == "blocked"
    assert "abort and re-preview" in result.stages[1].summary
    assert result.stages[1].evidence["expected_target_identity"] == ["{sound-1}"]
    assert result.stages[1].evidence["provided_target_identity"] == ["{other-sound}"]
    assert result.stages[1].evidence["dispatcher_called"] is False

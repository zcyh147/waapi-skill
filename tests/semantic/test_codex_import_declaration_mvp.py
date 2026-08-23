from __future__ import annotations

import json
from pathlib import Path
from collections import deque
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from tests.semantic.support.codex_import_declaration_mvp import (
    ImportBusinessMvp,
    MvpRepairError,
)
from tests.semantic.support.codex_import_mvp_profile import (
    MODEL,
    REASONING_EFFORT,
    SERVICE_TIER,
    load_import_mvp_profile,
)
from tests.semantic.support.codex_import_mvp_fake_gateway import (
    AUX_BUS_ID,
    RUNTIME_ROOT_ENV,
    SKILL_ROOT_ENV,
    VERSION_ENV,
    main as fake_gateway_main,
    prepare_import_mvp_runtime,
)
from tests.semantic.support.codex_import_mvp_agent_runner import (
    import_mvp_developer_instructions,
    mvp_command_set_is_closed,
    mvp_continuations_were_used,
    preview_was_reported,
)
from tests.semantic.support.codex_gateway_broker import (
    ExpectedGatewayStep,
    _normalize_commutative_option_pairs,
)
from wwise_waapi.transactions import TransactionStore


PARENT_ID = "{11111111-1111-1111-1111-111111111111}"
BUS_ID = "{22222222-2222-2222-2222-222222222222}"
ROOT = Path(__file__).resolve().parents[2]
MVP_PROFILE = ROOT / "tests/semantic/data/deep-interface-mvp/profile.json"
SKILL_ROOT = ROOT / "skills/waapi-skill"


class ScriptedReader:
    def __init__(self, responses: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.responses = {uri: deque(rows) for uri, rows in responses.items()}
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def __call__(
        self,
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args), dict(options)))
        return self.responses[uri].popleft()


def _object_row(*, object_id: str, name: str, object_type: str, path: str) -> dict[str, Any]:
    return {
        "id": object_id,
        "name": name,
        "type": object_type,
        "path": path,
        "parent": {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"},
        "notes": "",
    }


def _project_info(project_root: Path) -> dict[str, Any]:
    originals = project_root / "Originals"
    originals.mkdir(parents=True)
    return {
        "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "name": "SampleProject",
        "displayTitle": "SampleProject",
        "path": str(project_root / "SampleProject.wproj"),
        "isDirty": False,
        "currentLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "referenceLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "currentPlatformId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        "directories": {
            "root": str(project_root),
            "cache": str(project_root / ".cache"),
            "originals": str(originals),
            "soundBankOutputRoot": str(project_root / "GeneratedSoundBanks"),
            "commands": str(project_root / "Commands"),
            "properties": str(project_root / "Properties"),
        },
        "platforms": [
            {
                "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "name": "Mac",
                "baseName": "Mac",
                "baseDisplayName": "Mac",
                "soundBankPath": str(project_root / "GeneratedSoundBanks/Mac"),
                "copiedMediaPath": str(
                    project_root / "GeneratedSoundBanks/Mac/Media"
                ),
            }
        ],
        "languages": [
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "SFX",
                "shortId": 1,
            }
        ],
        "defaultConversion": {
            "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
            "name": "Default",
        },
    }


def test_business_asset_compiles_without_model_authored_wwise_mechanics(
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain_bed.wav"
    media.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    mvp = ImportBusinessMvp.create(
        version="2022.1",
        task_authority="task-weather",
        project_id="sample-project",
    )
    parent = mvp.bind_object(
        object_id=PARENT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    output_bus = mvp.bind_object(
        object_id=BUS_ID,
        name="Weather_Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus",
    )

    result = mvp.declare_asset(
        parent=parent,
        name="Rain_Bed",
        kind="sound-sfx",
        media_file=media,
        language="SFX",
        volume_db=-4,
        loop="infinite",
        output_bus=output_bus,
    )
    compiled = result.draft.compile()

    assert compiled.metadata_scopes == ("Sound",)
    assert compiled.request["arguments"] == {
        "imports": [
            {
                "object_path": (
                    r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
                    r"\<Sound SFX>Rain_Bed"
                ),
                "object_type": "Sound SFX",
                "audio_file": str(media),
                "import_language": "SFX",
                "properties": [
                    {"name": "IsLoopingEnabled", "value": True},
                    {"name": "IsLoopingInfinite", "value": True},
                    {"name": "Volume", "value": -4.0},
                ],
                "references": [
                    {
                        "name": "OutputBus",
                        "target": {"kind": "id", "value": BUS_ID},
                    }
                ],
            }
        ]
    }
    assert [row["kind"] for row in compiled.native_rows] == [
        "sound_structure",
        "audio_file_source_media",
    ]
    assert compiled.next_command["copy_instruction"]["source_field"] == (
        "shell_command"
    )
    assert compiled.next_command["full_argv"][-1] == "mvp-preview"
    assert compiled.next_command["shell_command"].endswith("mvp-preview")
    assert set(compiled.model_authored_fields) == {
        "parent",
        "name",
        "kind",
        "media_file",
        "language",
        "volume_db",
        "loop",
        "output_bus",
        "switch_value",
    }
    forbidden = {
        "object_path",
        "object_type",
        "metadata_scope",
        "native_rows",
        "action_order",
        "batch_boundary",
        "revision",
        "request_json",
        "shell_command",
    }
    assert forbidden.isdisjoint(compiled.model_authored_fields)


def test_multiple_business_items_compile_to_one_native_import_batch(
    tmp_path: Path,
) -> None:
    rain = tmp_path / "rain.wav"
    wind = tmp_path / "wind.wav"
    rain.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    wind.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    mvp = ImportBusinessMvp.create(
        version="2025.1",
        task_authority="task-weather-batch",
        project_id="sample-project",
    )
    root = mvp.bind_object(
        object_id=PARENT_ID,
        name="Default Work Unit",
        object_type="WorkUnit",
        path=r"\Containers\Default Work Unit",
    )
    weather = mvp.declare_structure(
        parent=root,
        name="Weather",
        kind="actor-mixer",
    ).handle
    mvp.declare_asset(
        parent=weather,
        name="Rain",
        kind="sound-sfx",
        media_file=rain,
        language="SFX",
        loop="infinite",
    )
    mvp.declare_asset(
        parent=weather,
        name="Wind",
        kind="sound-sfx",
        media_file=wind,
        language="SFX",
        volume_db=-6,
    )

    compiled = mvp.compile()

    assert compiled.request["arguments"]["imports"][0] == {
        "object_path": r"\Containers\Default Work Unit\<Actor-Mixer>Weather",
        "object_type": "ActorMixer",
    }
    assert len(compiled.request["arguments"]["imports"]) == 3
    assert [row["kind"] for row in compiled.native_rows] == [
        "single",
        "sound_structure",
        "audio_file_source_media",
        "sound_structure",
        "audio_file_source_media",
    ]
    assert compiled.native_call_count == 1


def test_existing_target_derives_reimport_and_replace_requires_explicit_intent(
    tmp_path: Path,
) -> None:
    media = tmp_path / "rifle.wav"
    media.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    existing_path = (
        r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons\Rifle"
    )

    def prepared() -> tuple[ImportBusinessMvp, str]:
        current = ImportBusinessMvp.create(
            version="2022.1",
            task_authority="task-rifle",
            project_id="sample-project",
        )
        handle = current.bind_object(
            object_id=PARENT_ID,
            name="Rifle",
            object_type="Sound",
            path=existing_path,
        )
        return current, handle

    reimport, target = prepared()
    reimport.declare_existing_asset(
        target=target,
        media_file=media,
        language="SFX",
    )
    reimported = reimport.compile()
    assert reimported.request["arguments"]["import_operation"] == "useExisting"
    assert reimported.request["arguments"]["imports"][0]["object_path"] == (
        existing_path
    )

    replacement, target = prepared()
    replacement.declare_existing_asset(
        target=target,
        media_file=media,
        language="SFX",
        replace=True,
    )
    replaced = replacement.compile()
    assert replaced.request["arguments"]["import_operation"] == (
        "replaceExisting"
    )


def test_invalid_field_handle_returns_structured_repair_without_revision_change(
    tmp_path: Path,
) -> None:
    media = tmp_path / "footstep.wav"
    media.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    mvp = ImportBusinessMvp.create(
        version="2022.1",
        task_authority="task-footsteps",
        project_id="sample-project",
    )
    parent = mvp.bind_object(
        object_id=PARENT_ID,
        name="Footsteps",
        object_type="SwitchContainer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps",
    )
    before = mvp.inspect()

    with pytest.raises(MvpRepairError) as caught:
        mvp.declare_asset(
            parent=parent,
            name="Snow",
            kind="sound-sfx",
            media_file=media,
            language="SFX",
            fields={"mvp-field-stale": True},
        )

    assert mvp.inspect() == before
    assert caught.value.repair == {
        "contract": "waapi-skill.business-repair/v1",
        "error_code": "FIELD_HANDLE_STALE_OR_OUT_OF_SCOPE",
        "field": "fields",
        "rejected_handle": "mvp-field-stale",
        "draft_revision": before["revision"],
        "draft_changed": False,
        "action": "discover the field in this task and resubmit its handle",
    }


def test_live_bound_field_handle_materializes_long_tail_property(
    tmp_path: Path,
) -> None:
    media = tmp_path / "weapon.wav"
    media.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    mvp = ImportBusinessMvp.create(
        version="2022.1",
        task_authority="task-weapons",
        project_id="sample-project",
    )
    parent = mvp.bind_object(
        object_id=PARENT_ID,
        name="Weapons",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons",
    )
    wetness = mvp.bind_field(
        metadata_scope="Sound",
        name="CustomWetness",
        field_kind="property",
        value_type="number",
        minimum=0,
        maximum=1,
        metadata_digest="metadata-snapshot-1",
    )
    mvp.declare_asset(
        parent=parent,
        name="Rifle",
        kind="sound-sfx",
        media_file=media,
        language="SFX",
        fields={wetness: 0.75},
    )

    compiled = mvp.compile()

    assert compiled.request["arguments"]["imports"][0]["properties"] == [
        {"name": "CustomWetness", "value": 0.75}
    ]
    assert compiled.native_rows[0]["@CustomWetness"] == 0.75


def test_field_handle_scope_and_range_fail_closed_atomically(tmp_path: Path) -> None:
    media = tmp_path / "weapon.wav"
    media.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    mvp = ImportBusinessMvp.create(
        version="2022.1",
        task_authority="task-weapons-negative",
        project_id="sample-project",
    )
    parent = mvp.bind_object(
        object_id=PARENT_ID,
        name="Weapons",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weapons",
    )
    mixer_field = mvp.bind_field(
        metadata_scope="ActorMixer",
        name="MixerOnly",
        field_kind="property",
        value_type="number",
        metadata_digest="metadata-snapshot-2",
    )
    volume = mvp.bind_field(
        metadata_scope="Sound",
        name="Volume",
        field_kind="property",
        value_type="number",
        minimum=-96,
        maximum=12,
        metadata_digest="metadata-snapshot-3",
    )

    for handle, value, code in (
        (mixer_field, 1, "FIELD_HANDLE_SCOPE_MISMATCH"),
        (volume, 30, "FIELD_VALUE_OUT_OF_RANGE"),
        (volume, "loud", "FIELD_VALUE_TYPE_MISMATCH"),
    ):
        before = mvp.inspect()
        with pytest.raises(MvpRepairError) as caught:
            mvp.declare_asset(
                parent=parent,
                name="Rifle",
                kind="sound-sfx",
                media_file=media,
                language="SFX",
                fields={handle: value},
            )
        assert caught.value.repair["error_code"] == code
        assert caught.value.repair["draft_changed"] is False
        assert mvp.inspect() == before


def test_common_business_input_failures_return_atomic_structured_repairs(
    tmp_path: Path,
) -> None:
    media = tmp_path / "valid.wav"
    media.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    mvp = ImportBusinessMvp.create(
        version="2022.1",
        task_authority="task-common-repairs",
        project_id="sample-project",
    )
    parent = mvp.bind_object(
        object_id=PARENT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    invalid_rows = (
        ({"name": "Bad\\Path", "media_file": media}, "INVALID_CHILD_NAME"),
        ({"name": "Rain", "media_file": tmp_path / "missing.wav"}, "MEDIA_FILE_UNAVAILABLE"),
        ({"name": "Rain", "media_file": media, "language": ""}, "REQUIRED_FIELD_MISSING"),
        ({"name": "Rain", "media_file": media, "loop": "sometimes"}, "FIELD_VALUE_UNAVAILABLE"),
        ({"name": "Rain", "media_file": media, "volume_db": 500}, "FIELD_VALUE_OUT_OF_RANGE"),
    )
    for overrides, error_code in invalid_rows:
        before = mvp.inspect()
        arguments = {
            "parent": parent,
            "name": "Rain",
            "kind": "sound-sfx",
            "media_file": media,
            "language": "SFX",
            **overrides,
        }
        with pytest.raises(MvpRepairError) as caught:
            mvp.declare_asset(**arguments)
        assert caught.value.repair["error_code"] == error_code
        assert caught.value.repair["draft_changed"] is False
        assert mvp.inspect() == before

    with pytest.raises(MvpRepairError) as empty:
        mvp.compile()
    assert empty.value.repair["error_code"] == "INCOMPLETE_DECLARATION"
    assert empty.value.repair["draft_changed"] is False


def test_business_declaration_enters_existing_immutable_preview_pipeline(
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    parent_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
    target_path = parent_path + r"\<Sound SFX>Rain"
    mvp = ImportBusinessMvp.create(
        version="2022.1",
        task_authority="task-preview",
        project_id="sample-project",
    )
    parent = mvp.bind_object(
        object_id=PARENT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=parent_path,
    )
    mvp.declare_asset(
        parent=parent,
        name="Rain",
        kind="sound-sfx",
        media_file=media,
        language="SFX",
    )
    reader = ScriptedReader(
        {
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {"classId": 65552, "name": "Sound", "type": "WObject"}
                    ]
                }
            ],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        _object_row(
                            object_id=PARENT_ID,
                            name="Weather",
                            object_type="ActorMixer",
                            path=parent_path,
                        )
                    ]
                },
                {"return": []},
            ],
            "ak.wwise.core.getProjectInfo": [
                _project_info(tmp_path / "SampleProject")
            ],
        }
    )

    artifact = mvp.build_preview_artifact(
        read_call=reader,
        project_guard={
            "contract": "waapi-skill.project-guard/v1",
            "project_guard_mode": "invariant",
            "project": {"state": "open", "id": "sample-project"},
        },
        skill_root=SKILL_ROOT,
    )
    artifact_payload = artifact.as_dict()
    store = TransactionStore(tmp_path / "state")
    record = store.create_preview("tx-mvp-preview", artifact_payload)
    sealed = store.load_preview("tx-mvp-preview")

    assert record.state.value == "draft"
    assert sealed.artifact_hash == record.artifact_hash
    assert sealed.artifact == artifact_payload
    assert sealed.artifact["request"] == mvp.compile().request
    assert sealed.artifact["prepared_operation"]["dispatch"] == {
        "uri": "ak.wwise.core.audio.import",
        "args": {
            "imports": [
                {
                    "objectPath": target_path,
                    "objectType": "Sound SFX",
                    "audioFile": str(media),
                    "importLanguage": "SFX",
                }
            ],
            "importOperation": "createNew",
            "autoAddToSourceControl": False,
        },
        "options": {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "parent",
                "notes",
                "activeSource",
                "originalFilePath",
                "sound:originalWavFilePath",
                "audioSource:language",
            ]
        },
    }


def test_fixed_mvp_profile_runs_each_family_paraphrase_independently() -> None:
    profile = load_import_mvp_profile(MVP_PROFILE)

    assert (MODEL, REASONING_EFFORT, SERVICE_TIER) == (
        "gpt-5.6-terra",
        "medium",
        "default",
    )
    assert [unit.family for unit in profile.units] == [
        "weather",
        "weather",
        "rifle",
        "rifle",
        "footsteps",
        "footsteps",
        "weapons",
        "weapons",
    ]
    assert [unit.variant for unit in profile.units] == ["A", "B"] * 4
    assert len({unit.prompt for unit in profile.units}) == 8
    forbidden_tokens = {
        "object_path",
        "objectType",
        "metadata_scope",
        "native_rows",
        "action_order",
        "batch_boundary",
        "request_json",
        "shell_command",
    }
    for unit in profile.units:
        assert len(unit.paraphrases) == 2
        assert unit.prompt == unit.paraphrases[0 if unit.variant == "A" else 1]
        command_tokens = {token for command in unit.commands for token in command}
        assert forbidden_tokens.isdisjoint(command_tokens)
        assert unit.commands[0] == ("mvp-context", "--family", unit.family)
        assert unit.commands[-1] == ("mvp-preview",)
        for command in unit.commands:
            if command[0] != "mvp-asset":
                continue
            name = command[command.index("--name") + 1]
            media = command[command.index("--media") + 1]
            assert name in unit.prompt
            assert media in unit.prompt
            assert f"{name}(" not in unit.prompt


def test_fixed_fake_gateway_cases_use_real_compiler_and_immutable_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile = load_import_mvp_profile(MVP_PROFILE)
    previews_by_family: dict[str, list[dict[str, Any]]] = {}

    for unit in profile.units:
        task_root = tmp_path / unit.unit_id
        runtime_root = prepare_import_mvp_runtime(task_root / "runtime")
        state_dir = task_root / "state"
        state_dir.mkdir()
        monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))
        monkeypatch.setenv(SKILL_ROOT_ENV, str(SKILL_ROOT))
        monkeypatch.setenv(VERSION_ENV, unit.version)
        monkeypatch.setenv("WAAPI_SKILL_STATE_DIR", str(state_dir))
        family_previews: list[dict[str, Any]] = []
        for command_index, command in enumerate(unit.commands):
            assert fake_gateway_main(["gateway.py", *command]) == 0
            payload = json.loads(capsys.readouterr().out)
            assert payload["ok"] is True
            assert payload["command"] == command[0]
            if command[0] == "mvp-context":
                assert "parent_handle" in payload["agent_result"]
                assert "root_handle" not in payload["agent_result"]
            if command[0] == "mvp-existing-asset":
                assert payload["agent_result"]["next_action"].startswith(
                    "execute next_command"
                )
            if command[0] in {"mvp-structure", "mvp-asset", "mvp-existing-asset"}:
                next_is_preview = (
                    command_index + 1 < len(unit.commands)
                    and unit.commands[command_index + 1][0] == "mvp-preview"
                )
                assert ("next_command" in payload["agent_result"]) is next_is_preview
                if next_is_preview:
                    next_command = payload["agent_result"]["next_command"]
                    source = next_command["copy_instruction"]["source_field"]
                    assert next_command[source]
                    assert next_command["full_argv"][-1] == "mvp-preview"
            if command[0] == "mvp-preview":
                preview = payload["agent_result"]
                family_previews.append(preview)
                assert preview["test_only"] is True
                assert preview["wwise_connected"] is False
                assert preview["wwise_mutated"] is False
                assert preview["production_accepted"] is False
                assert len(preview["immutable_preview_sha256"]) == 64
                evidence = preview["compiler_evidence"]
                assert evidence["canonical_request"]["operation"] == "audio.import"
                assert evidence["dispatch"]["uri"] == "ak.wwise.core.audio.import"
                assert evidence["next_command"]["full_argv"][-1] == "mvp-preview"
        previews_by_family[unit.family] = family_previews

    assert len(previews_by_family["rifle"]) == 2
    assert [
        preview["compiler_evidence"]["canonical_request"]["arguments"][
            "import_operation"
        ]
        for preview in previews_by_family["rifle"]
    ] == ["useExisting", "replaceExisting"]
    weapons_dispatch = previews_by_family["weapons"][0]["compiler_evidence"][
        "dispatch"
    ]
    assert any(
        row.get("@CustomWetness") == 0.75
        for row in weapons_dispatch["args"]["imports"]
    )
    assert any(
        row.get("@CustomAuxBus") == AUX_BUS_ID
        for row in weapons_dispatch["args"]["imports"]
    )
    footsteps_dispatch = previews_by_family["footsteps"][0]["compiler_evidence"][
        "dispatch"
    ]
    assert any(
        row.get("switchAssignation") == "Snow"
        for row in footsteps_dispatch["args"]["imports"]
    )


def test_fake_gateway_cli_shape_errors_are_structured_and_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_root = prepare_import_mvp_runtime(tmp_path / "runtime")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv(RUNTIME_ROOT_ENV, str(runtime_root))
    monkeypatch.setenv(SKILL_ROOT_ENV, str(SKILL_ROOT))
    monkeypatch.setenv(VERSION_ENV, "2022.1")
    monkeypatch.setenv("WAAPI_SKILL_STATE_DIR", str(state_dir))
    assert fake_gateway_main(
        ["gateway.py", "mvp-context", "--family", "weather"]
    ) == 0
    capsys.readouterr()
    state_path = state_dir / "deep-import-mvp.json"
    before = state_path.read_bytes()

    assert fake_gateway_main(
        ["gateway.py", "mvp-asset", "--volume-db", "not-a-number"]
    ) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is False
    assert payload["agent_result"]["contract"] == "waapi-skill.business-repair/v1"
    assert payload["agent_result"]["error_code"] == (
        "INCOMPLETE_OR_MISTYPED_DECLARATION"
    )
    assert payload["agent_result"]["draft_changed"] is False
    assert state_path.read_bytes() == before


def test_mvp_agent_contract_uses_standard_skill_bootstrap_and_semantic_preview_grade(
    tmp_path: Path,
) -> None:
    skill_install = tmp_path / "workspace/.agents/skills/waapi-skill"
    instructions = import_mvp_developer_instructions(
        skill_source=ROOT / "tests/semantic/data/deep-interface-mvp/skill",
        skill_install=skill_install,
    )

    assert "cat '.agents/skills/waapi-skill/SKILL.md'" in instructions
    assert "python .agents/skills/waapi-skill/scripts/run.py gateway.py" in instructions

    class Record:
        step_name = "step-05-mvp-preview"
        payload = {
            "agent_result": {
                "preview": [
                    "对象：Rain_Bed",
                    "循环方式：Infinite",
                    "音量：-4 dB",
                ],
                "wwise_mutated": False,
            }
        }

    assert preview_was_reported(
        final_response="业务预览已生成；未执行任何 Wwise 修改。",
        expected_markers=("Rain_Bed", "Infinite", "-4 dB"),
        broker_records=(Record(),),
    )
    assert preview_was_reported(
        final_response="Preview complete; no changes were made.",
        expected_markers=("Rain_Bed", "Infinite", "-4 dB"),
        broker_records=(Record(),),
    )

    facts = SimpleNamespace(
        command_records=("skill-read", "gateway-1", "gateway-2"),
        allowed_read_commands=("skill-read",),
        discovery_commands=(),
        write_like_commands=(),
    )
    argvs = (("python", "runner", "gateway.py", "mvp-context"), ("python", "runner", "gateway.py", "mvp-preview"))
    assert mvp_command_set_is_closed(
        command_facts=facts,
        gateway_argvs=argvs,
        reconciliation_passed=True,
    )
    facts.command_records += ("python -c unexpected",)
    assert not mvp_command_set_is_closed(
        command_facts=facts,
        gateway_argvs=argvs,
        reconciliation_passed=True,
    )

    declaration = SimpleNamespace(
        step_name="step-02-mvp-asset",
        payload={
            "agent_result": {
                "next_command": {
                    "full_argv": [
                        "python",
                        ".agents/skills/waapi-skill/scripts/run.py",
                        "gateway.py",
                        "mvp-preview",
                    ],
                    "shell_command": (
                        "python .agents/skills/waapi-skill/scripts/run.py "
                        "gateway.py mvp-preview"
                    ),
                    "copy_instruction": {"source_field": "shell_command"},
                }
            }
        },
    )
    preview = SimpleNamespace(
        step_name="step-03-mvp-preview",
        model_argv=(
            "/broker/python",
            ".agents/skills/waapi-skill/scripts/run.py",
            "gateway.py",
            "mvp-preview",
        ),
    )
    assert mvp_continuations_were_used((declaration, preview))


def test_mvp_broker_compares_high_level_option_pairs_semantically() -> None:
    step = ExpectedGatewayStep(
        name="mvp-asset",
        subcommand="mvp-asset",
        arguments=(
            "--name",
            "Rain_Bed",
            "--volume-db",
            "-4",
            "--loop",
            "infinite",
        ),
        commutative_option_pairs=True,
    )

    assert _normalize_commutative_option_pairs(
        step,
        (
            "--loop",
            "infinite",
            "--volume-db=-4",
            "--name",
            "Rain_Bed",
        ),
    ) == step.arguments
    assert _normalize_commutative_option_pairs(
        step,
        ("--name", "Wrong", "--volume-db", "-4", "--loop", "infinite"),
    ) != step.arguments

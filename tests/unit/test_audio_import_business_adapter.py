from __future__ import annotations

import base64
import shlex
from pathlib import Path

import pytest

from wwise_waapi.audio_import_business import (
    compile_audio_import_business,
    materialize_audio_import_business_request,
)
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    ExistingObjectTarget,
    NewDescendantTarget,
    SUPPORTED_WWISE_VERSIONS,
)
from wwise_waapi.business_planning import BusinessPlanningDeadline


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"
BUS_ID = "{22222222-2222-2222-2222-222222222222}"
SOUND_ID = "{33333333-3333-3333-3333-333333333333}"
EVENT_PARENT_ID = "{44444444-4444-4444-4444-444444444444}"


def _context(version: str) -> BusinessContext:
    return BusinessContext.create(
        task_authority="da1-" + "1" * 40,
        project_id=PROJECT_ID,
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )


def _continuation(
    request: dict[str, object],
    request_digest: str,
    deadline: BusinessPlanningDeadline,
) -> dict[str, object]:
    deadline.checkpoint()
    gateway_argv = ["transaction-preview", "--request-digest", request_digest]
    full_argv = ["python", "skill/run.py", "gateway.py", *gateway_argv]
    return {
        "contract": "waapi-skill.gateway-next-command/v2",
        "gateway_argv": gateway_argv,
        "full_argv": full_argv,
        "shell_family": "posix-sh",
        "shell_command": shlex.join(full_argv),
        "copy_exactly": True,
        "copy_instruction": {
            "contract": "waapi-skill.gateway-command-copy-instruction/v2",
            "source_field": "shell_command",
            "action": "execute_verbatim_as_one_shell_tool_call",
        },
    }


def _session(version: str) -> tuple[BusinessDeclarationSession, str, str]:
    session = BusinessDeclarationSession.create(_context(version))
    root = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
    parent = session.handles.bind_object(
        object_id=PARENT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=rf"\{root}\Default Work Unit\Weather",
    )
    bus = session.handles.bind_object(
        object_id=BUS_ID,
        name="Weather_Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Weather_Bus",
    )
    return session, parent.handle, bus.handle


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_new_media_declaration_compiles_all_common_business_fields(
    version: str,
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF-test")
    session, parent, bus = _session(version)
    session = session.with_settings(
        {"mode": "create", "add_to_source_control": True}
    ).with_new_declaration(
        declaration_id="rain-bed",
        target=NewDescendantTarget(
            parent_handle=parent,
            name="Rain_Bed",
            kind="sound-sfx",
        ),
        fields={
            "media_file": str(media),
            "language": "SFX",
            "volume_db": -4.0,
            "loop": "infinite",
            "max_instances": 3,
            "override_parent_instance_limit": True,
            "output_bus": bus,
            "switch_value": "Rain",
            "notes": "steady rain bed",
            "audio_source_notes": "field recording",
            "originals_subfolder": "Weather/Rain",
        },
    )

    compiled = compile_audio_import_business(
        session,
        build_continuation=_continuation,
    )

    arguments = compiled.request["arguments"]
    assert arguments["auto_add_to_source_control"] is True
    row = arguments["imports"][0]
    assert row["object_path"].endswith(r"\<Sound SFX>Rain_Bed")
    assert row["object_type"] == "Sound SFX"
    assert row["audio_file"] == str(media)
    assert row["import_language"] == "SFX"
    assert row["properties"] == [
        {"name": "IsLoopingEnabled", "value": True},
        {"name": "IsLoopingInfinite", "value": True},
        {"name": "Volume", "value": -4.0},
        {"name": "UseMaxSoundPerInstance", "value": True},
        {"name": "MaxSoundPerInstance", "value": 3},
        {"name": "IgnoreParentMaxSoundInstance", "value": True},
    ]
    assert row["references"] == [
        {"name": "OutputBus", "target": {"kind": "id", "value": BUS_ID}}
    ]
    assert row["switch_assignment"] == "Rain"
    assert compiled.preview.readable_lines[:3] == (
        "对象：Rain_Bed",
        "类型：Sound SFX",
        "音量：-4 dB",
    )


def test_request_materialization_has_no_continuation_and_allows_sealed_file_cleanup(
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF-test")
    session, parent, _bus = _session("2022.1")
    session = session.with_new_declaration(
        declaration_id="rain-bed",
        target=NewDescendantTarget(
            parent_handle=parent,
            name="Rain_Bed",
            kind="sound-sfx",
        ),
        fields={"media_file": str(media), "language": "SFX"},
    )

    request = materialize_audio_import_business_request(session)
    media.unlink()

    with pytest.raises(BusinessDeclarationError) as stale:
        materialize_audio_import_business_request(session)
    assert stale.value.repair["error_code"] == "MEDIA_FILE_UNAVAILABLE"
    assert (
        materialize_audio_import_business_request(
            session,
            allow_cleaned_file_evidence=True,
        )
        == request
    )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_sound_sfx_kind_derives_the_only_valid_import_language(
    version: str,
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF-test")
    session, parent, _bus = _session(version)
    session = session.with_new_declaration(
        declaration_id="rain-bed",
        target=NewDescendantTarget(parent, "Rain_Bed", "sound-sfx"),
        fields={"media_file": str(media)},
    )

    request = materialize_audio_import_business_request(session)

    assert request["arguments"]["imports"][0]["import_language"] == "SFX"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_sound_voice_still_requires_an_exact_project_language(
    version: str,
    tmp_path: Path,
) -> None:
    media = tmp_path / "line.wav"
    media.write_bytes(b"RIFF-test")
    session, parent, _bus = _session(version)
    session = session.with_new_declaration(
        declaration_id="line",
        target=NewDescendantTarget(parent, "Line", "sound-voice"),
        fields={"media_file": str(media)},
    )

    with pytest.raises(BusinessDeclarationError) as missing:
        materialize_audio_import_business_request(session)

    assert missing.value.repair["error_code"] == "REQUIRED_FIELD_MISSING"
    assert missing.value.repair["field"] == "language"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_exact_existing_sfx_kind_also_derives_sfx_for_reimport(
    version: str,
    tmp_path: Path,
) -> None:
    media = tmp_path / "rifle.wav"
    media.write_bytes(b"RIFF-test")
    session, parent, _bus = _session(version)
    existing = session.handles.bind_object(
        object_id=SOUND_ID,
        name="Rifle",
        object_type="Sound",
        path=session.handles.resolve_object(parent).path + r"\Rifle",
        semantic_kind="sound-sfx",
    )
    session = session.with_existing_declaration(
        declaration_id="rifle",
        target=ExistingObjectTarget(existing.handle),
        fields={"media_file": str(media)},
    )

    request = materialize_audio_import_business_request(session)

    assert request["arguments"]["import_operation"] == "useExisting"
    assert request["arguments"]["imports"][0]["import_language"] == "SFX"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_structure_inline_existing_and_explicit_replace_modes(
    version: str,
    tmp_path: Path,
) -> None:
    session, parent, _bus = _session(version)
    structure = session.with_new_declaration(
        declaration_id="container",
        target=NewDescendantTarget(
            parent_handle=parent,
            name="Variants",
            kind="random-container",
        ),
        fields={},
    )
    structure_plan = compile_audio_import_business(
        structure,
        build_continuation=_continuation,
    )
    assert structure_plan.request["arguments"]["imports"][0]["object_type"] == (
        "RandomSequenceContainer"
    )

    inline_payload = b"RIFF" + (4).to_bytes(4, "little") + b"WAVE" + b"data"
    inline = base64.b64encode(inline_payload).decode("ascii")
    inline_session = session.with_new_declaration(
        declaration_id="inline",
        target=NewDescendantTarget(
            parent_handle=parent,
            name="Inline",
            kind="sound-sfx",
        ),
        fields={"inline_wav": f"inline.wav|{inline}", "language": "SFX"},
    )
    inline_plan = compile_audio_import_business(
        inline_session,
        build_continuation=_continuation,
    )
    assert inline_plan.request["arguments"]["imports"][0]["audio_file_base64"].startswith(
        "inline.wav|"
    )

    existing = session.handles.bind_object(
        object_id=SOUND_ID,
        name="Rifle_Shot",
        object_type="Sound",
        path=(
            (r"\Containers" if version == "2025.1" else r"\Actor-Mixer Hierarchy")
            + r"\Default Work Unit\Weapons\Rifle_Shot"
        ),
    )
    media = tmp_path / "rifle.wav"
    media.write_bytes(b"RIFF-rifle")
    replaced = session.with_settings({"mode": "replace"}).with_existing_declaration(
        declaration_id="rifle",
        target=ExistingObjectTarget(existing.handle),
        fields={"media_file": str(media), "language": "SFX"},
    )
    replace_plan = compile_audio_import_business(
        replaced,
        build_continuation=_continuation,
    )
    assert replace_plan.request["arguments"]["import_operation"] == "replaceExisting"
    assert replace_plan.request["arguments"]["imports"][0]["object_path"].endswith(
        r"\Rifle_Shot"
    )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize(
    ("semantic_kind", "expected_type"),
    (("sound-sfx", "Sound SFX"), ("sound-voice", "Sound Voice")),
)
def test_structure_only_existing_sound_preserves_live_subtype_without_language(
    version: str,
    semantic_kind: str,
    expected_type: str,
) -> None:
    session, _parent, _bus = _session(version)
    existing = session.handles.bind_object(
        object_id=SOUND_ID,
        name="Existing_Line",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Existing_Line",
        semantic_kind=semantic_kind,
    )
    session = session.with_existing_declaration(
        declaration_id="existing-line",
        target=ExistingObjectTarget(existing.handle),
        fields={"notes": "preserve the exact live Sound kind"},
    )

    request = materialize_audio_import_business_request(session)

    assert request["arguments"]["imports"] == [
        {
            "object_path": existing.path,
            "object_type": expected_type,
            "notes": "preserve the exact live Sound kind",
        }
    ]


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_invalid_mixed_modes_and_native_fields_repair_without_guessing(
    version: str,
    tmp_path: Path,
) -> None:
    media = tmp_path / "one.wav"
    media.write_bytes(b"RIFF-one")
    session, parent, _bus = _session(version)
    existing = session.handles.bind_object(
        object_id=SOUND_ID,
        name="Existing",
        object_type="Sound",
        path=session.handles.resolve_object(parent).path + r"\Existing",
    )
    mixed = session.with_new_declaration(
        declaration_id="new",
        target=NewDescendantTarget(parent, "New", "sound-sfx"),
        fields={"media_file": str(media), "language": "SFX"},
    ).with_existing_declaration(
        declaration_id="existing",
        target=ExistingObjectTarget(existing.handle),
        fields={"media_file": str(media), "language": "SFX"},
    )

    before = mixed.as_dict()
    with pytest.raises(BusinessDeclarationError) as conflict:
        compile_audio_import_business(mixed, build_continuation=_continuation)
    assert conflict.value.repair["error_code"] == "AUDIO_IMPORT_MODE_AMBIGUOUS"
    assert conflict.value.repair["draft_revision"] == mixed.revision
    assert mixed.as_dict() == before

    with pytest.raises(BusinessDeclarationError) as native:
        session.with_new_declaration(
            declaration_id="native",
            target=NewDescendantTarget(parent, "Native", "sound-sfx"),
            fields={"object_path": r"\Actor-Mixer Hierarchy\Bad"},
        )
    assert native.value.repair["error_code"] == "NATIVE_PLANNING_FIELD_FORBIDDEN"

    explicit_reimport = session.with_settings({"mode": "reimport"}).with_new_declaration(
        declaration_id="new-reimport",
        target=NewDescendantTarget(parent, "New_Reimport", "sound-sfx"),
        fields={"media_file": str(media), "language": "SFX"},
    )
    with pytest.raises(BusinessDeclarationError) as wrong_form:
        compile_audio_import_business(
            explicit_reimport,
            build_continuation=_continuation,
        )
    assert wrong_form.value.repair["error_code"] == (
        "AUDIO_IMPORT_MODE_TARGET_MISMATCH"
    )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_existing_structure_preserves_bound_non_sound_type(version: str) -> None:
    session, parent, _bus = _session(version)
    existing = session.handles.bind_object(
        object_id=SOUND_ID,
        name="Variants",
        object_type="RandomSequenceContainer",
        path=session.handles.resolve_object(parent).path + r"\Variants",
    )
    session = session.with_existing_declaration(
        declaration_id="variants",
        target=ExistingObjectTarget(existing.handle),
        fields={},
    )

    compiled = compile_audio_import_business(
        session,
        build_continuation=_continuation,
    )

    row = compiled.request["arguments"]["imports"][0]
    assert row["object_type"] == "RandomSequenceContainer"
    assert "audio_file" not in row
    assert "import_language" not in row


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_object_scoped_field_handle_cannot_cross_existing_targets(
    version: str,
) -> None:
    session, parent, _bus = _session(version)
    first = session.handles.bind_object(
        object_id=SOUND_ID,
        name="First",
        object_type="Sound",
        path=session.handles.resolve_object(parent).path + r"\First",
    )
    second = session.handles.bind_object(
        object_id=EVENT_PARENT_ID,
        name="Second",
        object_type="Sound",
        path=session.handles.resolve_object(parent).path + r"\Second",
    )
    custom = session.handles.bind_field(
        scope_kind="object",
        scope_value=first.object_id,
        token="CustomGain",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": -24.0, "maximum": 24.0},
        metadata_digest="c" * 64,
    )
    session = session.with_existing_declaration(
        declaration_id="second",
        target=ExistingObjectTarget(second.handle),
        fields={"field_values": {custom.handle: -3.0}},
    )

    with pytest.raises(BusinessDeclarationError) as mismatch:
        compile_audio_import_business(
            session,
            build_continuation=_continuation,
        )
    assert mismatch.value.repair["error_code"] == "FIELD_HANDLE_SCOPE_MISMATCH"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_new_descendant_handles_drive_hierarchy_order_and_batch_layout(
    version: str,
    tmp_path: Path,
) -> None:
    media = tmp_path / "step.wav"
    media.write_bytes(b"RIFF-step")
    session, parent, _bus = _session(version)
    session = session.with_new_declaration(
        declaration_id="footsteps",
        target=NewDescendantTarget(
            parent_handle=parent,
            name="Footsteps",
            kind="random-container",
        ),
        fields={},
    )
    planned_parent = session.declarations[0].result_handle
    assert planned_parent.startswith("bnh1-")
    session = session.with_new_declaration(
        declaration_id="footstep-grass",
        target=NewDescendantTarget(
            parent_handle=planned_parent,
            name="Grass",
            kind="sound-sfx",
        ),
        fields={"media_file": str(media), "language": "SFX"},
    )

    compiled = compile_audio_import_business(
        session,
        build_continuation=_continuation,
    )

    assert compiled.ordered_effect_ids == (
        "import:footsteps",
        "import:footstep-grass",
    )
    rows = compiled.request["arguments"]["imports"]
    assert rows[1]["object_path"] == (
        rows[0]["object_path"] + r"\<Sound SFX>Grass"
    )
    assert len(compiled.batches) == 1


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_live_field_handles_event_directive_and_batch_defaults_are_lossless(
    version: str,
    tmp_path: Path,
) -> None:
    media = tmp_path / "custom.wav"
    media.write_bytes(b"RIFF-custom")
    session, parent, bus = _session(version)
    event_parent = session.handles.bind_object(
        object_id=EVENT_PARENT_ID,
        name="Weather",
        object_type="Folder",
        path=r"\Events\Default Work Unit\Weather",
    )
    pitch = session.handles.bind_field(
        scope_kind="class",
        scope_value="Sound",
        token="Pitch",
        field_kind="property",
        value_type="number",
        restrictions={"minimum": -2400.0, "maximum": 2400.0},
        metadata_digest="a" * 64,
    )
    custom_bus = session.handles.bind_field(
        scope_kind="class",
        scope_value="Sound",
        token="CustomOutput",
        field_kind="reference",
        value_type="reference",
        restrictions={"allowed_target_types": ["Bus"]},
        metadata_digest="b" * 64,
    )
    session = session.with_settings(
        {
            "defaults": {
                "language": "SFX",
                "notes": "batch note",
                "volume_db": -2.0,
            }
        }
    ).with_new_declaration(
        declaration_id="custom",
        target=NewDescendantTarget(parent, "Custom", "sound-sfx"),
        fields={
            "media_file": str(media),
            "volume_db": -6.0,
            "field_values": {
                pitch.handle: -100.0,
                custom_bus.handle: bus,
            },
            "event": {
                "parent_handle": event_parent.handle,
                "name": "Play_Custom",
                "action": "Play",
            },
            "dialogue_event_directive": "Dialogue_Custom",
        },
    )

    compiled = compile_audio_import_business(
        session,
        build_continuation=_continuation,
    )
    row = compiled.request["arguments"]["imports"][0]
    assert row["import_language"] == "SFX"
    assert row["notes"] == "batch note"
    assert row["properties"] == [
        {"name": "Volume", "value": -6.0},
        {"name": "Pitch", "value": -100.0},
    ]
    assert row["references"] == [
        {"name": "CustomOutput", "target": {"kind": "id", "value": BUS_ID}}
    ]
    assert row["event"] == {
        "path": r"\Events\Default Work Unit\Weather\Play_Custom",
        "action": "Play",
    }
    assert row["dialogue_event"] == "Dialogue_Custom"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_source_control_version_boundary_and_implicit_existing_reimport(
    version: str,
    tmp_path: Path,
) -> None:
    media = tmp_path / "existing.wav"
    media.write_bytes(b"RIFF-existing")
    session, parent, _bus = _session(version)
    existing = session.handles.bind_object(
        object_id=SOUND_ID,
        name="Existing",
        object_type="Sound",
        path=session.handles.resolve_object(parent).path + r"\Existing",
    )
    session = session.with_existing_declaration(
        declaration_id="existing",
        target=ExistingObjectTarget(existing.handle),
        fields={"media_file": str(media), "language": "SFX"},
    )
    compiled = compile_audio_import_business(
        session,
        build_continuation=_continuation,
    )
    assert compiled.request["arguments"]["import_operation"] == "useExisting"

    checkout = session.with_settings({"check_out_from_source_control": True})
    if version in {"2023.1", "2024.1", "2025.1"}:
        checked = compile_audio_import_business(
            checkout,
            build_continuation=_continuation,
        )
        assert checked.request["arguments"]["auto_check_out_to_source_control"] is True
    else:
        with pytest.raises(BusinessDeclarationError) as unavailable:
            compile_audio_import_business(
                checkout,
                build_continuation=_continuation,
            )
        assert unavailable.value.repair["error_code"] == "VERSION_BEHAVIOR_BOUNDARY"

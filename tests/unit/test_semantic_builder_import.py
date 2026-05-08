from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.imports import (  # pyright: ignore[reportMissingImports]
    AUDIO_IMPORTED_TOPIC_URI,
    AUDIO_IMPORT_TAB_DELIMITED_URI,
    AUDIO_IMPORT_URI,
    ImportBuilder,
    ImportItem,
    build_object_path,
    expect_audio_imported_topic,
    tab_delimited_plan,
    write_tab_delimited_import_file,
)


class FakeSourceNoteChecker:
    def __init__(self, status: SourceNoteCheck | None = None) -> None:
        self.status = status or SourceNoteCheck(True, BuilderFamily.IMPORT.value, cited_fields=("audio.import", "audio.importTabDelimited"))
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        self.calls.append((family, version))
        return self.status


def builder(checker: FakeSourceNoteChecker | None = None) -> ImportBuilder:
    return ImportBuilder(source_note_checker=checker or FakeSourceNoteChecker())


def assert_import_preview(preview: Any, uri: str, args: dict[str, Any]) -> None:
    assert preview.source_note_family == BuilderFamily.IMPORT.value
    assert preview.requires_destructive_gate is True
    assert preview.raw_dispatch_allowed is False
    assert preview.dispatch_payload() == {"uri": uri, "args": args, "options": {"return": ["id", "name", "type", "path"]}}
    assert preview.to_dispatcher_request().dry_run is True
    assert preview.envelope.metadata["builder_family"] == BuilderFamily.IMPORT.value
    assert preview.envelope.metadata["schema_validation"]["uri"] == uri
    assert preview.readback_plan[0].uri == uri
    assert preview.readback_plan[1].uri == "ak.wwise.core.object.get"
    assert [plan["kind"] for plan in preview.as_dict()["evidence_plan"]] == [
        "source-note",
        "schema",
        "created-object-readback",
        "cleanup-source-immutability",
        "artifact-evidence",
    ]


def test_audio_import_envelope_supports_file_defaults_overrides_and_properties() -> None:
    checker = FakeSourceNoteChecker()
    object_path = build_object_path(r"\Actor-Mixer Hierarchy\Default Work Unit", ("Random Container", "Imported"), ("Sound", "Tone"))

    preview = ImportBuilder(source_note_checker=checker).audio_import(
        [
            ImportItem(
                object_path=object_path,
                object_type="Sound",
                audio_file=Path("/tmp/tone.wav"),
                import_language="SFX",
                originals_subfolder="Task7",
                notes="unit import",
                properties={"@Volume": -3, "@IsLoopingEnabled": True},
            )
        ],
        import_operation="createNew",
        defaults={"importLanguage": "SFX", "originalsSubFolder": "Defaults", "@Pitch": 0},
        auto_add_to_source_control=False,
    )

    expected_args = {
        "imports": [
            {
                "objectPath": r"\Actor-Mixer Hierarchy\Default Work Unit\<Random Container>Imported\<Sound>Tone",
                "objectType": "Sound",
                "audioFile": str(Path("/tmp/tone.wav")),
                "importLanguage": "SFX",
                "originalsSubFolder": "Task7",
                "notes": "unit import",
                "@Volume": -3,
                "@IsLoopingEnabled": True,
            }
        ],
        "importOperation": "createNew",
        "default": {"importLanguage": "SFX", "originalsSubFolder": "Defaults", "@Pitch": 0},
        "autoAddToSourceControl": False,
    }
    assert_import_preview(preview, AUDIO_IMPORT_URI, expected_args)
    assert checker.calls == [(BuilderFamily.IMPORT.value, "2022.1")]


def test_audio_import_envelope_supports_base64_source_and_mapping_items() -> None:
    preview = builder().audio_import(
        [
            {
                "objectPath": r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Encoded",
                "audioFileBase64": "Encoded.wav|UklGRg==",
                "objectType": "Sound",
                "@Volume": 1.5,
            }
        ],
        import_operation="useExisting",
    )

    assert_import_preview(
        preview,
        AUDIO_IMPORT_URI,
        {
            "imports": [
                {
                    "objectPath": r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Encoded",
                    "audioFileBase64": "Encoded.wav|UklGRg==",
                    "objectType": "Sound",
                    "@Volume": 1.5,
                }
            ],
            "importOperation": "useExisting",
        },
    )


def test_object_path_builder_is_deterministic_and_rejects_ambiguous_segments() -> None:
    assert build_object_path("Actor-Mixer Hierarchy", "Default Work Unit", ("Sound", "Tone")) == r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Tone"
    assert build_object_path(r"\Actor-Mixer Hierarchy\Default Work Unit") == r"\Actor-Mixer Hierarchy\Default Work Unit"

    with pytest.raises(SemanticValidationError) as exc:
        build_object_path(r"\Actor-Mixer Hierarchy", "Bad\\Segment")
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_tab_delimited_builder_emits_plan_without_file_write(tmp_path: Path) -> None:
    plan = tab_delimited_plan(
        [
            ImportItem(
                object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>TabTone",
                object_type="Sound",
                audio_file=tmp_path / "tab-tone.wav",
                import_language="SFX",
                originals_subfolder="Task7",
                notes="tab note",
            )
        ],
        filename="task7.tsv",
    )

    assert not (tmp_path / "task7.tsv").exists()
    assert plan.render() == (
        "Audio File\tObject Path\tObject Type\tImport Language\tOriginals Sub Folder\tNotes\n"
        f"{tmp_path / 'tab-tone.wav'}\t\\Actor-Mixer Hierarchy\\Default Work Unit\\<Sound>TabTone\tSound\tSFX\tTask7\ttab note\n"
    )

    preview = builder().import_tab_delimited(import_location=r"\Actor-Mixer Hierarchy\Default Work Unit", import_language="SFX", import_operation="createNew", plan=plan)

    assert_import_preview(
        preview,
        AUDIO_IMPORT_TAB_DELIMITED_URI,
        {
            "importLanguage": "SFX",
            "importOperation": "createNew",
            "importFile": "<materialize:task7.tsv>",
            "importLocation": r"\Actor-Mixer Hierarchy\Default Work Unit",
        },
    )
    assert preview.envelope.metadata["tab_delimited_plan"]["writes_file_by_default"] is False
    assert not (tmp_path / "task7.tsv").exists()


def test_tab_delimited_write_helper_is_explicit_and_temp_only() -> None:
    plan = tab_delimited_plan([{"objectPath": r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>TabTone", "audioFile": "/tmp/tab-tone.wav"}])

    with pytest.raises(SemanticValidationError) as exc:
        write_tab_delimited_import_file(plan, Path.cwd() / "not-temp-import-output")
    assert exc.value.error_code == SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED

    temp_dir = Path(tempfile.mkdtemp(prefix="waapi-import-plan-"))
    written = write_tab_delimited_import_file(plan, temp_dir)
    try:
        assert written.is_file()
        assert written.read_text(encoding="utf-8") == plan.render()
    finally:
        written.unlink(missing_ok=True)
        temp_dir.rmdir()


def test_audio_imported_topic_expectation_validates_options() -> None:
    checker = FakeSourceNoteChecker()
    preview = ImportBuilder(source_note_checker=checker).imported_topic(return_fields=("id", "name"))

    assert preview.dispatch_payload() == {"uri": AUDIO_IMPORTED_TOPIC_URI, "args": {}, "options": {"return": ["id", "name"]}}
    assert preview.requires_destructive_gate is True
    assert preview.envelope.metadata["return_expectation"]["shape"] == "topic-payload-with-objects-array"
    assert checker.calls == [(BuilderFamily.IMPORT.value, "2022.1")]

    alias = expect_audio_imported_topic(return_fields=("id",))
    assert alias.dispatch_payload()["uri"] == AUDIO_IMPORTED_TOPIC_URI


def test_source_note_must_unlock_before_import_preview() -> None:
    checker = FakeSourceNoteChecker(SourceNoteCheck(False, BuilderFamily.IMPORT.value, reason="missing import note", error_code=SemanticErrorCode.MISSING_SOURCE_NOTE))

    with pytest.raises(SemanticValidationError) as exc:
        ImportBuilder(source_note_checker=checker).audio_import([ImportItem(object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Blocked")])

    assert exc.value.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE
    assert checker.calls == [(BuilderFamily.IMPORT.value, "2022.1")]


def test_unsupported_switch_assignation_and_constrained_references_fail_closed() -> None:
    with pytest.raises(SemanticValidationError) as switch_assignation:
        builder().audio_import([{"objectPath": r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Tone", "switchAssignation": "State=Child"}])
    assert switch_assignation.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED

    with pytest.raises(SemanticValidationError) as constrained_reference:
        builder().audio_import([ImportItem(object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Tone", properties={"@@OutputBus": "Master Audio Bus"})])
    assert constrained_reference.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED


def test_import_tab_delimited_requires_file_or_plan_and_schema_fields() -> None:
    with pytest.raises(SemanticValidationError) as missing_file:
        builder().import_tab_delimited(import_location=None, import_language="SFX", import_operation="createNew")
    assert missing_file.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as bad_operation:
        builder().import_tab_delimited(import_location=None, import_language="SFX", import_operation="delete", import_file="/tmp/import.tsv")
    assert bad_operation.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_audio_import_rejects_root_level_object_path_and_suggests_default_work_unit() -> None:
    with pytest.raises(SemanticValidationError) as exc:
        builder().audio_import(
            [
                {
                    "objectPath": r"\Actor-Mixer Hierarchy\<Sound>Encoded",
                    "audioFileBase64": "Encoded.wav|UklGRg==",
                    "objectType": "Sound",
                }
            ],
            import_operation="useExisting",
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_CONTAINER_UNSUITABLE
    assert exc.value.details["candidate_writable_parent"] == r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Encoded"
    assert exc.value.details["requires_user_confirmation"] is True


def test_import_tab_delimited_rejects_root_level_import_location_and_suggests_default_work_unit() -> None:
    plan = tab_delimited_plan([{"objectPath": r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>TabTone", "audioFile": "/tmp/tab-tone.wav"}])

    with pytest.raises(SemanticValidationError) as exc:
        builder().import_tab_delimited(
            import_location=r"\Actor-Mixer Hierarchy",
            import_language="SFX",
            import_operation="createNew",
            plan=plan,
        )

    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_CONTAINER_UNSUITABLE
    assert exc.value.details["candidate_writable_parent"] == r"\Actor-Mixer Hierarchy\Default Work Unit"

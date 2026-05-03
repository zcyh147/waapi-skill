from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import BuilderFamily, SemanticErrorCode, SemanticPreview, SemanticValidationError  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.identity import ObjectIdentity  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.imports import AUDIO_IMPORT_URI, ImportItem, build_audio_import_preview  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.object_mutation import OBJECT_CREATE_URI, ObjectMutationBuilder  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.properties import SET_NAME_URI, build_set_name_preview  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.query import build_object_get_query  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.soundbank import CONVERT_EXTERNAL_SOURCES_URI, GENERATE_URI, ExternalSourceConversion, build_convert_external_sources_preview, build_generate_preview  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.switchcontainer import ADD_ASSIGNMENT_URI, build_add_assignment_preview  # pyright: ignore[reportMissingImports]


VERSION_2021 = "2021.1"
NOTEBOOK_ID_2021 = "wwise-2021.1.14-docs"
GUID_A = "{11111111-1111-1111-1111-111111111111}"
GUID_B = "{22222222-2222-2222-2222-222222222222}"
GUID_C = "{33333333-3333-3333-3333-333333333333}"
FAMILIES = (
    BuilderFamily.QUERY,
    BuilderFamily.OBJECT_MUTATION,
    BuilderFamily.PROPERTY_REFERENCE,
    BuilderFamily.IMPORT,
    BuilderFamily.SOUNDBANK,
    BuilderFamily.SWITCHCONTAINER,
)


def source_note_checker_2021() -> SemanticSourceNoteChecker:
    return SemanticSourceNoteChecker()


def assert_2021_preview(preview: SemanticPreview, *, family: BuilderFamily, uri: str, destructive: bool) -> None:
    payload = preview.as_dict()
    validation = preview.envelope.metadata["schema_validation"]

    assert payload["version"] == VERSION_2021
    assert payload["source_note_family"] == family.value
    assert payload["raw_dispatch_allowed"] is False
    assert payload["requires_destructive_gate"] is destructive
    assert preview.dispatch_payload()["uri"] == uri
    assert validation["uri"] == uri
    assert validation["version"] == VERSION_2021
    assert preview.envelope.metadata["source_note"]["version"] == VERSION_2021
    assert any(item.get("kind") == "source-note" for item in payload["evidence_plan"])
    assert any(item.get("kind") == "schema" for item in payload["evidence_plan"])


@pytest.mark.parametrize("family", FAMILIES)
def test_2021_source_note_gate_opens_for_each_semantic_family(family: BuilderFamily) -> None:
    status = source_note_checker_2021().check(family.value, VERSION_2021)

    assert status.allowed is True
    assert status.family == family.value
    assert status.version == VERSION_2021
    assert status.cited_fields


def test_2021_query_builder_uses_2021_source_notes_and_schema() -> None:
    preview = build_object_get_query(
        type="Sound",
        return_fields=("id", "name", "path"),
        source_note_checker=source_note_checker_2021(),
        version=VERSION_2021,
    )

    assert_2021_preview(preview, family=BuilderFamily.QUERY, uri="ak.wwise.core.object.get", destructive=False)
    assert preview.envelope.metadata["read_only"] is True
    assert preview.readback_plan[0].uri == "ak.wwise.core.object.get"


def test_2021_object_mutation_preview_is_gated_and_missing_uri_is_unsupported() -> None:
    builder = ObjectMutationBuilder(version=VERSION_2021, source_note_checker=source_note_checker_2021())
    preview = builder.create(parent=ObjectIdentity(id=GUID_A), type="ActorMixer", name="WAAPI_2021_Preview_Object")

    assert_2021_preview(preview, family=BuilderFamily.OBJECT_MUTATION, uri=OBJECT_CREATE_URI, destructive=True)
    assert preview.envelope.metadata["destructive_gate"]["required"] is True
    assert preview.envelope.metadata["cleanup_expectation"]["kind"] == "delete-created-object"

    with pytest.raises(SemanticValidationError) as exc:
        builder.paste_properties(source=ObjectIdentity(id=GUID_A), targets=(ObjectIdentity(id=GUID_B),))
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert exc.value.details["uri"] == "ak.wwise.core.object.pasteProperties"
    assert exc.value.details["version"] == VERSION_2021
    assert exc.value.details["status"] == "unsupported"
    assert exc.value.details["fallback_allowed"] is False


def test_2021_property_reference_helper_accepts_version_and_validates_schema() -> None:
    preview = build_set_name_preview(
        object=ObjectIdentity(id=GUID_A),
        value="Renamed 2021 Preview",
        source_note_checker=source_note_checker_2021(),
        version=VERSION_2021,
    )

    assert_2021_preview(preview, family=BuilderFamily.PROPERTY_REFERENCE, uri=SET_NAME_URI, destructive=True)
    assert preview.readback_plan[0].uri == "ak.wwise.core.object.get"
    assert preview.evidence_plan[2]["topic"] == "ak.wwise.core.object.nameChanged"


def test_2021_import_helper_accepts_version_and_requires_mutation_evidence() -> None:
    preview = build_audio_import_preview(
        [ImportItem(object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Preview", audio_file="/tmp/preview.wav")],
        import_operation="createNew",
        source_note_checker=source_note_checker_2021(),
        version=VERSION_2021,
    )

    assert_2021_preview(preview, family=BuilderFamily.IMPORT, uri=AUDIO_IMPORT_URI, destructive=True)
    assert preview.envelope.metadata["destructive_behavior"].startswith("preview-only")
    assert [plan.uri for plan in preview.readback_plan] == [AUDIO_IMPORT_URI, "ak.wwise.core.object.get"]


def test_2021_soundbank_helper_accepts_version_and_defers_absent_uris() -> None:
    preview = build_generate_preview(
        soundbanks=[{"name": "PreviewBank", "events": [GUID_A], "inclusions": ["event"]}],
        platforms=("Mac",),
        write_to_disk=True,
        source_note_checker=source_note_checker_2021(),
        version=VERSION_2021,
    )

    assert_2021_preview(preview, family=BuilderFamily.SOUNDBANK, uri=GENERATE_URI, destructive=True)
    assert preview.envelope.metadata["destructive_gate"]["required"] is True
    assert preview.envelope.metadata["artifact_evidence_plan"]["writes_files_by_preview"] is False

    with pytest.raises(SemanticValidationError) as exc:
        build_convert_external_sources_preview(
            sources=[ExternalSourceConversion(input="/tmp/unit.wsources", platform="Mac")],
            source_note_checker=source_note_checker_2021(),
            version=VERSION_2021,
        )
    assert exc.value.details["uri"] == CONVERT_EXTERNAL_SOURCES_URI
    assert exc.value.details["version"] == VERSION_2021
    assert exc.value.details["status"] == "unsupported"
    assert exc.value.details["fallback_allowed"] is False


def test_2021_switchcontainer_helper_accepts_version_and_requires_preflight_readback() -> None:
    preview = build_add_assignment_preview(
        switch_container=GUID_A,
        child=GUID_B,
        state_or_switch=GUID_C,
        existing_assignments=[],
        source_note_checker=source_note_checker_2021(),
        version=VERSION_2021,
    )

    assert_2021_preview(preview, family=BuilderFamily.SWITCHCONTAINER, uri=ADD_ASSIGNMENT_URI, destructive=True)
    assert preview.envelope.metadata["destructive_gate"]["required"] is True
    assert preview.envelope.metadata["preflight_plan"]["uri"] == "ak.wwise.core.switchContainer.getAssignments"
    assert preview.envelope.metadata["post_mutation_readback_plan"]["uri"] == "ak.wwise.core.switchContainer.getAssignments"
    assert [plan.uri for plan in preview.readback_plan] == ["ak.wwise.core.switchContainer.getAssignments", "ak.wwise.core.switchContainer.getAssignments"]


def test_2021_builders_never_load_newer_semantic_or_schema_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        text = path.as_posix()
        touched.append(text)
        if any(f"resources/semantic/{version}" in text or f"resources/manifest/{version}" in text for version in ("2022.1", "2023.1", "2024.1", "2025.1")):
            raise AssertionError(f"2021.1 semantic builder touched newer fallback resource: {path}")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    previews = (
        build_object_get_query(type="Sound", return_fields=("id",), source_note_checker=source_note_checker_2021(), version=VERSION_2021),
        ObjectMutationBuilder(version=VERSION_2021, source_note_checker=source_note_checker_2021()).create(parent=ObjectIdentity(id=GUID_A), type="ActorMixer", name="Preview"),
        build_set_name_preview(object=ObjectIdentity(id=GUID_A), value="Preview", source_note_checker=source_note_checker_2021(), version=VERSION_2021),
        build_audio_import_preview([ImportItem(object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Preview", audio_file="/tmp/preview.wav")], import_operation="createNew", source_note_checker=source_note_checker_2021(), version=VERSION_2021),
        build_generate_preview(soundbanks=[{"name": "PreviewBank"}], source_note_checker=source_note_checker_2021(), version=VERSION_2021),
        build_add_assignment_preview(switch_container=GUID_A, child=GUID_B, state_or_switch=GUID_C, existing_assignments=[], source_note_checker=source_note_checker_2021(), version=VERSION_2021),
    )

    assert {preview.version for preview in previews} == {VERSION_2021}
    assert any("resources/semantic/2021.1/source_notes.json" in path for path in touched)
    assert any("resources/manifest/2021.1/schemas.json" in path for path in touched)
    assert not any("resources/semantic/2022.1" in path or "resources/manifest/2022.1" in path for path in touched)

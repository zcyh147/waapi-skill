from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import BuilderFamily, SemanticPreview  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.identity import ObjectIdentity  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.metadata import PropertyInfoMetadataRecord  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.object_mutation import (  # pyright: ignore[reportMissingImports]
    OBJECT_CREATE_URI,
    ObjectMutationBuilder,
)
from wwise_waapi.builders.properties import SET_NAME_URI, build_set_name_preview  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.query import build_object_get_query  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.soundbank import GENERATE_URI, build_generate_preview  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.source_notes import SemanticSourceNoteChecker  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.switchcontainer import ADD_ASSIGNMENT_URI, build_add_assignment_preview  # pyright: ignore[reportMissingImports]


VERSION_2023 = "2023.1"
NOTEBOOK_ID_2023 = "wwise-2023.1-docs"
GUID_A = "{11111111-1111-1111-1111-111111111111}"
GUID_B = "{22222222-2222-2222-2222-222222222222}"
GUID_C = "{33333333-3333-3333-3333-333333333333}"


def source_note_checker_2023() -> SemanticSourceNoteChecker:
    return SemanticSourceNoteChecker()


def assert_2023_preview(preview: SemanticPreview, *, family: BuilderFamily, uri: str, destructive: bool) -> None:
    payload = preview.as_dict()
    validation = preview.envelope.metadata["schema_validation"]

    assert payload["version"] == VERSION_2023
    assert payload["source_note_family"] == family.value
    assert payload["raw_dispatch_allowed"] is False
    assert payload["requires_destructive_gate"] is destructive
    assert preview.dispatch_payload()["uri"] == uri
    assert validation["uri"] == uri
    assert validation["version"] == VERSION_2023
    assert preview.envelope.metadata["source_note"]["version"] == VERSION_2023


def assert_destructive_evidence(preview: SemanticPreview) -> None:
    assert preview.requires_destructive_gate is True
    assert preview.readback_plan or any(item["kind"] in {"readback", "created-object-readback", "artifact-evidence"} for item in preview.as_dict()["evidence_plan"])
    assert any(
        key in preview.envelope.metadata
        for key in ("destructive_gate", "destructive_behavior", "artifact_evidence_plan", "readback_expectation")
    )


def test_2023_query_builder_uses_2023_source_notes_and_schema() -> None:
    preview = build_object_get_query(
        type="Sound",
        return_fields=("id", "name", "path"),
        source_note_checker=source_note_checker_2023(),
        version=VERSION_2023,
    )

    assert_2023_preview(preview, family=BuilderFamily.QUERY, uri="ak.wwise.core.object.get", destructive=False)
    assert preview.envelope.metadata["read_only"] is True
    assert preview.readback_plan[0].uri == "ak.wwise.core.object.get"


def test_2023_object_mutation_preview_is_destructive_gated_with_readback() -> None:
    preview = ObjectMutationBuilder(version=VERSION_2023, source_note_checker=source_note_checker_2023()).create(
        parent=ObjectIdentity(id=GUID_A),
        type="ActorMixer",
        name="WAAPI_2023_Preview_Object",
    )

    assert_2023_preview(preview, family=BuilderFamily.OBJECT_MUTATION, uri=OBJECT_CREATE_URI, destructive=True)
    assert preview.envelope.metadata["destructive_gate"]["required"] is True
    assert preview.envelope.metadata["cleanup_expectation"]["kind"] == "delete-created-object"
    assert preview.readback_plan[0].uri == "ak.wwise.core.object.get"
    assert_destructive_evidence(preview)


def test_2023_property_reference_helper_accepts_version_and_validates_schema() -> None:
    preview = build_set_name_preview(
        object=ObjectIdentity(id=GUID_A),
        value="Renamed 2023 Preview",
        source_note_checker=source_note_checker_2023(),
        version=VERSION_2023,
    )

    assert_2023_preview(preview, family=BuilderFamily.PROPERTY_REFERENCE, uri=SET_NAME_URI, destructive=True)
    assert preview.readback_plan[0].uri == "ak.wwise.core.object.get"
    assert preview.evidence_plan[2]["topic"] == "ak.wwise.core.object.nameChanged"
    assert_destructive_evidence(preview)


def test_2023_soundbank_helper_accepts_version_and_keeps_artifact_evidence_only() -> None:
    preview = build_generate_preview(
        soundbanks=[{"name": "PreviewBank", "events": [GUID_A], "inclusions": ["event"]}],
        platforms=("Mac",),
        write_to_disk=True,
        source_note_checker=source_note_checker_2023(),
        version=VERSION_2023,
    )

    assert_2023_preview(preview, family=BuilderFamily.SOUNDBANK, uri=GENERATE_URI, destructive=True)
    assert preview.envelope.metadata["destructive_gate"]["required"] is True
    assert preview.envelope.metadata["artifact_evidence_plan"]["writes_files_by_preview"] is False
    assert preview.readback_plan == ()
    assert preview.evidence_plan[4]["hidden_subscription"] is False
    assert_destructive_evidence(preview)


def test_2023_switchcontainer_helper_accepts_version_and_requires_preflight_readback() -> None:
    preview = build_add_assignment_preview(
        switch_container=GUID_A,
        child=GUID_B,
        state_or_switch=GUID_C,
        existing_assignments=[],
        source_note_checker=source_note_checker_2023(),
        version=VERSION_2023,
    )

    assert_2023_preview(preview, family=BuilderFamily.SWITCHCONTAINER, uri=ADD_ASSIGNMENT_URI, destructive=True)
    assert preview.envelope.metadata["destructive_gate"]["required"] is True
    assert preview.envelope.metadata["preflight_plan"]["uri"] == "ak.wwise.core.switchContainer.getAssignments"
    assert preview.envelope.metadata["post_mutation_readback_plan"]["uri"] == "ak.wwise.core.switchContainer.getAssignments"
    assert [plan.uri for plan in preview.readback_plan] == ["ak.wwise.core.switchContainer.getAssignments", "ak.wwise.core.switchContainer.getAssignments"]
    assert_destructive_evidence(preview)


def test_2023_builders_never_load_2022_semantic_or_schema_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read_text: Callable[..., str] = Path.read_text
    touched: list[str] = []

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        text = path.as_posix()
        touched.append(text)
        if "resources/semantic/2022.1" in text or "resources/manifest/2022.1" in text or "references/semantic-builder-" in text:
            raise AssertionError(f"2023.1 semantic builder touched 2022.1/global fallback resource: {path}")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    previews = (
        build_object_get_query(type="Sound", return_fields=("id",), source_note_checker=source_note_checker_2023(), version=VERSION_2023),
        ObjectMutationBuilder(version=VERSION_2023, source_note_checker=source_note_checker_2023()).create(parent=ObjectIdentity(id=GUID_A), type="ActorMixer", name="Preview"),
        build_set_name_preview(object=ObjectIdentity(id=GUID_A), value="Preview", source_note_checker=source_note_checker_2023(), version=VERSION_2023),
        build_generate_preview(soundbanks=[{"name": "PreviewBank"}], source_note_checker=source_note_checker_2023(), version=VERSION_2023),
        build_add_assignment_preview(switch_container=GUID_A, child=GUID_B, state_or_switch=GUID_C, existing_assignments=[], source_note_checker=source_note_checker_2023(), version=VERSION_2023),
    )

    assert {preview.version for preview in previews} == {VERSION_2023}
    assert any("resources/semantic/2023.1/source_notes.json" in path for path in touched)
    assert any("resources/manifest/2023.1/schemas.json" in path for path in touched)
    assert not any("resources/semantic/2022.1" in path or "resources/manifest/2022.1" in path for path in touched)


def test_2023_source_notes_defer_unsupported_inflection_points_instead_of_new_builders() -> None:
    info = PropertyInfoMetadataRecord(name="OutputBus", type="Reference", supports={"reference": True, "constrained": True})

    with pytest.raises(Exception) as exc:
        build_set_name_preview(object=ObjectIdentity(waql="from type Sound"), value="Ambiguous", source_note_checker=source_note_checker_2023(), version=VERSION_2023)
    assert "exactly one row" in str(exc.value)

    with pytest.raises(Exception) as constrained:
        from wwise_waapi.builders.properties import build_set_reference_preview  # pyright: ignore[reportMissingImports]

        build_set_reference_preview(
            object=ObjectIdentity(id=GUID_A),
            reference="OutputBus",
            target=ObjectIdentity(id=GUID_B),
            reference_info=info,
            source_note_checker=source_note_checker_2023(),
            version=VERSION_2023,
        )
    assert "Constrained references" in str(constrained.value)

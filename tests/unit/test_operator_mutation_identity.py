from __future__ import annotations

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.identity import ObjectIdentity  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.imports import ImportBuilder, ImportItem, tab_delimited_plan  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.object_mutation import (  # pyright: ignore[reportMissingImports]
    ObjectMutationBuilder,
    confirm_preview_target_identity,
)


class FakeSourceNoteChecker:
    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        return SourceNoteCheck(True, family, version=version, cited_fields=(family,))


def test_object_mutation_preview_identity_handoff_reports_repreview_required_on_parent_mismatch() -> None:
    parent_path = r"\Actor-Mixer Hierarchy\Default Work Unit"
    preview = ObjectMutationBuilder(source_note_checker=FakeSourceNoteChecker()).create(
        parent=ObjectIdentity(path=parent_path),
        type="ActorMixer",
        name="Identity Guard",
    )

    target_metadata = preview.envelope.metadata["preview_target_identity"]
    assert target_metadata["roles"]["parent"]["target_key"] == [parent_path]
    assert target_metadata["roles"]["parent"]["container_suitability"]["reason"] == "writable-default-work-unit-target"
    assert target_metadata["confirmed_execution"]["mismatch_status"] == "repreview_required"

    confirmed = confirm_preview_target_identity(preview, {"parent": {"target_key": [parent_path]}})
    assert confirmed["status"] == "target_identity_confirmed"
    assert confirmed["repreview_required"] is False

    mismatch = confirm_preview_target_identity(preview, {"parent": {"target_key": [r"\Actor-Mixer Hierarchy\Other Work Unit"]}})
    assert mismatch["status"] == "repreview_required"
    assert mismatch["repreview_required"] is True
    assert mismatch["executed"] is False
    assert mismatch["verified"] is False
    assert mismatch["expected_target_identity"] == {"parent": (parent_path,)}


def test_import_preview_identity_handoff_uses_same_mismatch_guard() -> None:
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Tone"
    preview = ImportBuilder(source_note_checker=FakeSourceNoteChecker()).audio_import(
        [ImportItem(object_path=object_path, object_type="Sound", audio_file="/tmp/tone.wav")],
        import_operation="createNew",
    )

    role = "imports[0].objectPath"
    target_metadata = preview.envelope.metadata["preview_target_identity"]
    assert target_metadata["roles"][role]["target_key"] == [object_path]
    assert target_metadata["roles"][role]["container_suitability"]["reason"] == "writable-default-work-unit-target"
    assert target_metadata["confirmed_execution"]["mismatch_status"] == "repreview_required"

    confirmed = confirm_preview_target_identity(preview, {"roles": {role: {"target_key": [object_path]}}})
    assert confirmed["status"] == "target_identity_confirmed"

    mismatch = confirm_preview_target_identity(preview, {"roles": {role: {"target_key": [r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Other"]}}})
    assert mismatch["status"] == "repreview_required"
    assert mismatch["reason"] == "confirmed execution target identity differs from preview target identity"


def test_crud_and_import_invalid_root_details_share_service_semantics() -> None:
    checker = FakeSourceNoteChecker()
    root = r"\Master-Mixer Hierarchy"

    with pytest.raises(SemanticValidationError) as crud_error:
        ObjectMutationBuilder(source_note_checker=checker).create(parent=ObjectIdentity(path=root), type="Bus", name="Nope")

    plan = ImportItem(object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound>Tone", audio_file="/tmp/tone.wav")
    with pytest.raises(SemanticValidationError) as import_error:
        ImportBuilder(source_note_checker=checker).import_tab_delimited(
            import_location=root,
            import_language="SFX",
            import_operation="createNew",
            plan=tab_delimited_plan([plan]),
        )

    assert crud_error.value.details["reason_code"] == import_error.value.details["reason_code"] == "management-root-not-directly-writable"
    assert crud_error.value.details["candidate_targets"] == import_error.value.details["candidate_targets"] == [r"\Master-Mixer Hierarchy\Default Work Unit"]
    assert crud_error.value.details["requires_user_confirmation"] is import_error.value.details["requires_user_confirmation"] is True

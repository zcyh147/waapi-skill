"""Identity handoff tests for the retained packaged mutation builder."""

from __future__ import annotations

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    SourceNoteCheck,
)
from wwise_waapi.builders.identity import ObjectIdentity  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.object_mutation import (  # pyright: ignore[reportMissingImports]
    ObjectMutationBuilder,
    validate_preview_target_identity,
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
    assert target_metadata["authorized_execution"] == {
        "required": True,
        "abort_on_mismatch": True,
        "mismatch_status": "repreview_required",
        "reason": "authorized execution must reuse the preview-resolved target identity",
    }
    assert "confirmed_execution" not in target_metadata

    validated = validate_preview_target_identity(preview, {"parent": {"target_key": [parent_path]}})
    assert validated["status"] == "target_identity_validated"
    assert validated["repreview_required"] is False

    mismatch = validate_preview_target_identity(preview, {"parent": {"target_key": [r"\Actor-Mixer Hierarchy\Other Work Unit"]}})
    assert mismatch["status"] == "repreview_required"
    assert mismatch["repreview_required"] is True
    assert mismatch["executed"] is False
    assert mismatch["verified"] is False
    assert mismatch["expected_target_identity"] == {"parent": (parent_path,)}

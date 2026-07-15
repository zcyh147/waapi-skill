from __future__ import annotations

from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.identity import ObjectIdentity, ResolvedObject  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.object_mutation import (  # pyright: ignore[reportMissingImports]
    OBJECT_COPY_URI,
    OBJECT_CREATE_URI,
    OBJECT_DELETE_URI,
    OBJECT_DIFF_URI,
    OBJECT_MOVE_URI,
    OBJECT_PASTE_PROPERTIES_URI,
    OBJECT_SET_URI,
    UNDO_BEGIN_GROUP_URI,
    UNDO_END_GROUP_URI,
    UNDO_UNDO_URI,
    ObjectMutationBuilder,
    ObjectSetMutation,
    build_object_mutation_preview,
)


class FakeSourceNoteChecker:
    def __init__(self, status: SourceNoteCheck | None = None) -> None:
        self.status = status or SourceNoteCheck(True, BuilderFamily.OBJECT_MUTATION.value, cited_fields=("object mutation",))
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        self.calls.append((family, version))
        return self.status


def builder(checker: FakeSourceNoteChecker | None = None) -> ObjectMutationBuilder:
    return ObjectMutationBuilder(source_note_checker=checker or FakeSourceNoteChecker())


def exact_id(value: str) -> ObjectIdentity:
    return ObjectIdentity(id=value)


def assert_mutating_preview(preview: Any, uri: str, args: dict[str, Any], options: dict[str, Any]) -> None:
    assert preview.source_note_family == BuilderFamily.OBJECT_MUTATION.value
    assert preview.requires_destructive_gate is True
    assert preview.raw_dispatch_allowed is False
    assert preview.dispatch_payload() == {"uri": uri, "args": args, "options": options}
    assert preview.to_dispatcher_request().dry_run is True
    assert preview.envelope.metadata["builder_family"] == BuilderFamily.OBJECT_MUTATION.value
    assert preview.envelope.metadata["destructive_gate"]["required"] is True
    assert preview.envelope.metadata["schema_validation"]["uri"] == uri
    assert preview.evidence_plan[0]["kind"] == "source-note"
    assert preview.evidence_plan[3]["kind"] == "readback"
    assert preview.evidence_plan[4]["kind"] == "cleanup"


def test_create_preview_has_exact_payload_gate_readback_and_cleanup() -> None:
    checker = FakeSourceNoteChecker()

    preview = ObjectMutationBuilder(source_note_checker=checker).create(
        parent=exact_id("{parent}"),
        type="ActorMixer",
        name="WAAPI_TASK5_Object",
        on_name_conflict="fail",
        notes="created by semantic preview",
    )

    assert_mutating_preview(
        preview,
        OBJECT_CREATE_URI,
        {
            "parent": "{parent}",
            "type": "ActorMixer",
            "name": "WAAPI_TASK5_Object",
            "onNameConflict": "fail",
            "notes": "created by semantic preview",
        },
        {},
    )
    assert checker.calls == [(BuilderFamily.OBJECT_MUTATION.value, "2022.1")]
    assert preview.readback_plan[0].uri == "ak.wwise.core.object.get"
    assert preview.readback_plan[0].args == {
        "waql": 'from object "{parent}" select children where name = "WAAPI_TASK5_Object"'
    }
    assert preview.envelope.metadata["cleanup_expectation"]["kind"] == "delete-created-object"


def test_create_readback_preserves_path_separators_and_rejects_unproven_quotes() -> None:
    preview = builder().create(
        parent=ObjectIdentity(path=r"\Actor-Mixer Hierarchy\Default Work Unit"),
        type="ActorMixer",
        name="Child",
    )
    assert preview.readback_plan[0].args == {
        "waql": (
            r'from object "\Actor-Mixer Hierarchy\Default Work Unit" '
            'select children where name = "Child"'
        )
    }

    with pytest.raises(SemanticValidationError, match="embedded quotes") as exc:
        builder().create(parent=exact_id("{parent}"), type="ActorMixer", name='Child "quoted"')
    assert exc.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_set_batch_preview_represents_partial_success_risk_without_atomicity_claim() -> None:
    preview = builder().set(
        objects=(
            ObjectSetMutation(exact_id("{one}"), {"notes": "first"}),
            ObjectSetMutation(ResolvedObject(exact_id("{two}"), "{two}", "exact-id", {"id": "{two}"}), {"name": "Renamed"}),
        ),
        return_fields=("id", "name", "notes"),
    )

    assert_mutating_preview(
        preview,
        OBJECT_SET_URI,
        {"objects": [{"object": "{one}", "notes": "first"}, {"object": "{two}", "name": "Renamed"}]},
        {"return": ["id", "name", "notes"]},
    )
    assert preview.envelope.metadata["partial_success_risk"] is True
    assert preview.envelope.metadata["atomicity"] == "not-claimed"
    assert "batch previews are not atomic" in preview.evidence_plan[3]["expectation"]
    assert [plan.uri for plan in preview.readback_plan] == ["ak.wwise.core.object.get", "ak.wwise.core.object.get"]


def test_delete_copy_move_diff_and_paste_properties_payloads() -> None:
    assert_mutating_preview(builder().delete(object=exact_id("{delete-me}")), OBJECT_DELETE_URI, {"object": "{delete-me}"}, {})

    copy_preview = builder().copy(object=exact_id("{source}"), parent=exact_id("{parent}"), on_name_conflict="rename")
    assert_mutating_preview(copy_preview, OBJECT_COPY_URI, {"object": "{source}", "parent": "{parent}", "onNameConflict": "rename"}, {})

    move_preview = builder().move(object=exact_id("{source}"), parent=exact_id("{parent}"), on_name_conflict="fail")
    assert_mutating_preview(move_preview, OBJECT_MOVE_URI, {"object": "{source}", "parent": "{parent}", "onNameConflict": "fail"}, {})

    diff_preview = builder().diff(source=exact_id("{source}"), target=exact_id("{target}"))
    assert_mutating_preview(diff_preview, OBJECT_DIFF_URI, {"source": "{source}", "target": "{target}"}, {})
    assert diff_preview.readback_plan == ()

    paste_preview = builder().paste_properties(
        source=exact_id("{source}"),
        targets=(exact_id("{target-a}"), exact_id("{target-b}")),
        inclusion=("Volume", "OutputBus"),
        paste_mode="addReplace",
    )
    assert_mutating_preview(
        paste_preview,
        OBJECT_PASTE_PROPERTIES_URI,
        {"source": "{source}", "targets": ["{target-a}", "{target-b}"], "inclusion": ["Volume", "OutputBus"], "pasteMode": "addReplace"},
        {},
    )


def test_undo_previews_use_reflected_schema_payloads() -> None:
    assert_mutating_preview(builder().undo_begin_group(), UNDO_BEGIN_GROUP_URI, {}, {})
    assert_mutating_preview(builder().undo_end_group(display_name="Task 5 mutation group"), UNDO_END_GROUP_URI, {"displayName": "Task 5 mutation group"}, {})
    assert_mutating_preview(builder().undo_undo(), UNDO_UNDO_URI, {}, {})


def test_non_exact_identity_requires_pre_resolved_one_row_evidence() -> None:
    scoped = ObjectIdentity(name="Target", type="Sound", parent="{parent}")

    with pytest.raises(SemanticValidationError) as missing_rows:
        builder().delete(object=scoped)
    assert missing_rows.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY

    preview = builder().delete(
        object=scoped,
        object_rows={"return": [{"id": "{target}", "name": "Target", "type": "Sound", "parent": "{parent}"}]},
    )
    assert preview.dispatch_payload()["args"] == {"object": "{target}"}
    assert preview.envelope.metadata["resolved_identities"]["object"]["resolution"] == "scoped-name"

    with pytest.raises(SemanticValidationError) as ambiguous:
        builder().move(object=ObjectIdentity(id="{a}", path="\\Actor-Mixer Hierarchy\\A"), parent=exact_id("{parent}"))
    assert ambiguous.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY


def test_schema_and_source_note_fail_closed_before_preview() -> None:
    checker = FakeSourceNoteChecker(SourceNoteCheck(False, BuilderFamily.OBJECT_MUTATION.value, reason="missing", error_code=SemanticErrorCode.MISSING_SOURCE_NOTE))
    with pytest.raises(SemanticValidationError) as source_note:
        ObjectMutationBuilder(source_note_checker=checker).create(parent=exact_id("{parent}"), type="ActorMixer", name="Name")
    assert source_note.value.error_code == SemanticErrorCode.MISSING_SOURCE_NOTE

    with pytest.raises(SemanticValidationError) as empty_name:
        builder().create(parent=exact_id("{parent}"), type="ActorMixer", name=" ")
    assert empty_name.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as bad_conflict:
        builder().copy(object=exact_id("{source}"), parent=exact_id("{parent}"), on_name_conflict="merge")
    assert bad_conflict.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH

    with pytest.raises(SemanticValidationError) as hidden_object:
        builder().set(objects=(ObjectSetMutation(exact_id("{one}"), {"object": "{hidden}", "notes": "bad"}),))
    assert hidden_object.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_create_copy_and_move_reject_management_root_parent_paths() -> None:
    root_parent = ObjectIdentity(path=r"\Master-Mixer Hierarchy")

    with pytest.raises(SemanticValidationError) as create_error:
        builder().create(parent=root_parent, type="Bus", name="Temp_UI_Bus")
    assert create_error.value.error_code == SemanticErrorCode.SEMANTIC_CONTAINER_UNSUITABLE
    assert create_error.value.details["candidate_writable_parent"] == r"\Master-Mixer Hierarchy\Default Work Unit"
    assert create_error.value.details["requires_user_confirmation"] is True
    assert create_error.value.details["reason_code"] == "management-root-not-directly-writable"
    assert create_error.value.details["container_suitability"]["candidate_targets"] == [r"\Master-Mixer Hierarchy\Default Work Unit"]

    with pytest.raises(SemanticValidationError) as copy_error:
        builder().copy(object=exact_id("{source}"), parent=root_parent)
    assert copy_error.value.error_code == SemanticErrorCode.SEMANTIC_CONTAINER_UNSUITABLE
    assert copy_error.value.details["candidate_writable_parent"] == r"\Master-Mixer Hierarchy\Default Work Unit"
    assert copy_error.value.details["reason_code"] == "management-root-not-directly-writable"

    with pytest.raises(SemanticValidationError) as move_error:
        builder().move(object=exact_id("{source}"), parent=root_parent)
    assert move_error.value.error_code == SemanticErrorCode.SEMANTIC_CONTAINER_UNSUITABLE
    assert move_error.value.details["invalid_parent_path"] == r"\Master-Mixer Hierarchy"
    assert move_error.value.details["container_suitability"]["requires_user_confirmation"] is True


def test_preview_alias_accepts_uri_or_operation_name() -> None:
    preview = build_object_mutation_preview(
        "ak.wwise.core.object.delete",
        object=exact_id("{delete-me}"),
        source_note_checker=FakeSourceNoteChecker(),
    )

    assert preview.dispatch_payload() == {"uri": OBJECT_DELETE_URI, "args": {"object": "{delete-me}"}, "options": {}}

from __future__ import annotations

from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.common import (  # pyright: ignore[reportMissingImports]
    BuilderFamily,
    SemanticErrorCode,
    SemanticValidationError,
    SourceNoteCheck,
)
from wwise_waapi.builders.identity import ObjectIdentity  # pyright: ignore[reportMissingImports]
from wwise_waapi.builders.switchcontainer import (  # pyright: ignore[reportMissingImports]
    ADD_ASSIGNMENT_URI,
    ASSIGNMENT_ADDED_TOPIC_URI,
    ASSIGNMENT_REMOVED_TOPIC_URI,
    GET_ASSIGNMENTS_URI,
    REMOVE_ASSIGNMENT_URI,
    SwitchContainerAssignmentBuilder,
    build_add_assignment_preview,
    build_assignment_added_expectation,
    parse_get_assignments_result,
)


CONTAINER_ID = "{B5DB3AFA-044F-441E-BC4A-1397D20E2692}"
CHILD_ID = "{11111111-1111-1111-1111-111111111111}"
OTHER_CHILD_ID = "{22222222-2222-2222-2222-222222222222}"
STATE_ID = "{30D56DEF-DA40-45C9-A9EC-37FEBDF904E4}"
OTHER_STATE_ID = "{33333333-3333-3333-3333-333333333333}"


class FakeSourceNoteChecker:
    def __init__(self, status: SourceNoteCheck | None = None) -> None:
        self.status = status or SourceNoteCheck(True, BuilderFamily.SWITCHCONTAINER.value, cited_fields=("assignments",))
        self.calls: list[tuple[str, str]] = []

    def check(self, family: str, version: str = "2022.1") -> SourceNoteCheck:
        self.calls.append((family, version))
        return self.status


def builder(checker: FakeSourceNoteChecker | None = None) -> SwitchContainerAssignmentBuilder:
    return SwitchContainerAssignmentBuilder(source_note_checker=checker or FakeSourceNoteChecker())


def test_get_assignments_preview_requires_source_note_and_exact_container_payload() -> None:
    checker = FakeSourceNoteChecker()

    preview = SwitchContainerAssignmentBuilder(source_note_checker=checker).get_assignments(switch_container=ObjectIdentity(id=CONTAINER_ID))

    assert preview.dispatch_payload() == {"uri": GET_ASSIGNMENTS_URI, "args": {"id": CONTAINER_ID}, "options": {}}
    assert preview.source_note_family == BuilderFamily.SWITCHCONTAINER.value
    assert preview.requires_destructive_gate is False
    assert preview.raw_dispatch_allowed is False
    assert preview.envelope.metadata["builder_family"] == "switchcontainer"
    assert preview.envelope.metadata["read_only"] is True
    assert preview.envelope.metadata["schema_validation"]["uri"] == GET_ASSIGNMENTS_URI
    assert preview.envelope.metadata["return_expectation"] == {
        "parser": "parse_get_assignments_result",
        "shape": "object-with-return-assignment-array",
        "required_fields": ["return[].child", "return[].stateOrSwitch"],
    }
    assert preview.readback_plan[0].as_dict() == {
        "uri": GET_ASSIGNMENTS_URI,
        "args": {"id": CONTAINER_ID},
        "options": {},
        "description": "read back Switch Container assignment pairs",
    }
    assert checker.calls == [("switchcontainer", "2022.1")]


def test_add_assignment_preview_has_exact_payload_gate_preflight_and_post_readback() -> None:
    preview = builder().add_assignment(
        switch_container=ObjectIdentity(id=CONTAINER_ID),
        child=ObjectIdentity(id=CHILD_ID),
        state_or_switch=ObjectIdentity(id=STATE_ID),
        existing_assignments={"return": [{"child": OTHER_CHILD_ID, "stateOrSwitch": OTHER_STATE_ID}]},
    )

    assert preview.dispatch_payload() == {"uri": ADD_ASSIGNMENT_URI, "args": {"child": CHILD_ID, "stateOrSwitch": STATE_ID}, "options": {}}
    assert preview.to_dispatcher_request().dry_run is True
    assert preview.requires_destructive_gate is True
    assert preview.raw_dispatch_allowed is False
    assert preview.envelope.metadata["destructive_gate"] == {
        "required": True,
        "env": {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"},
        "allow_source_mutation": False,
    }
    assert preview.envelope.metadata["preflight_plan"] == {
        "uri": GET_ASSIGNMENTS_URI,
        "args": {"id": CONTAINER_ID},
        "options": {},
        "description": "preflight getAssignments must prove existing relationship state before mutation",
    }
    assert preview.envelope.metadata["post_mutation_readback_plan"] == {
        "uri": GET_ASSIGNMENTS_URI,
        "args": {"id": CONTAINER_ID},
        "options": {},
        "description": "post-addAssignment getAssignments readback must verify the assignment pair",
    }
    assert [plan.uri for plan in preview.readback_plan] == [GET_ASSIGNMENTS_URI, GET_ASSIGNMENTS_URI]
    assert preview.evidence_plan[2] == {"kind": "preflight", "uri": GET_ASSIGNMENTS_URI, "must_execute_before": ADD_ASSIGNMENT_URI}
    assert preview.evidence_plan[3] == {"kind": "readback", "uri": GET_ASSIGNMENTS_URI, "must_execute_after": ADD_ASSIGNMENT_URI}
    assert preview.envelope.metadata["schema_validation"]["uri"] == ADD_ASSIGNMENT_URI
    assert preview.envelope.metadata["no_op_allowed"] is False


def test_remove_assignment_preview_requires_pair_and_pins_payload() -> None:
    preview = builder().remove_assignment(
        switch_container=CONTAINER_ID,
        child=CHILD_ID,
        state_or_switch=STATE_ID,
        existing_assignments=[{"child": {"id": CHILD_ID}, "stateOrSwitch": {"id": STATE_ID}}],
    )

    assert preview.dispatch_payload() == {"uri": REMOVE_ASSIGNMENT_URI, "args": {"child": CHILD_ID, "stateOrSwitch": STATE_ID}, "options": {}}
    assert preview.requires_destructive_gate is True
    assert preview.envelope.metadata["post_mutation_readback_plan"] == {
        "uri": GET_ASSIGNMENTS_URI,
        "args": {"id": CONTAINER_ID},
        "options": {},
        "description": "post-removeAssignment getAssignments readback must verify the assignment pair",
    }
    assert preview.evidence_plan[2] == {"kind": "preflight", "uri": GET_ASSIGNMENTS_URI, "must_execute_before": REMOVE_ASSIGNMENT_URI}
    assert preview.evidence_plan[3] == {"kind": "readback", "uri": GET_ASSIGNMENTS_URI, "must_execute_after": REMOVE_ASSIGNMENT_URI}
    assert preview.envelope.metadata["schema_validation"]["uri"] == REMOVE_ASSIGNMENT_URI


def test_add_and_remove_fail_closed_when_assignment_state_is_unknown_or_noop() -> None:
    with pytest.raises(SemanticValidationError) as unknown:
        builder().add_assignment(switch_container=CONTAINER_ID, child=CHILD_ID, state_or_switch=STATE_ID, existing_assignments=None)
    assert unknown.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert unknown.value.details["missing"] == "existing_assignments"

    with pytest.raises(SemanticValidationError) as duplicate:
        builder().add_assignment(
            switch_container=CONTAINER_ID,
            child=CHILD_ID,
            state_or_switch=STATE_ID,
            existing_assignments=[{"child": CHILD_ID, "stateOrSwitch": STATE_ID}],
        )
    assert duplicate.value.error_code == SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED
    assert "no-op" in duplicate.value.message

    with pytest.raises(SemanticValidationError) as assigned_elsewhere:
        builder().add_assignment(
            switch_container=CONTAINER_ID,
            child=CHILD_ID,
            state_or_switch=STATE_ID,
            existing_assignments=[{"child": CHILD_ID, "stateOrSwitch": OTHER_STATE_ID}],
        )
    assert assigned_elsewhere.value.error_code == SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED

    with pytest.raises(SemanticValidationError) as missing_pair:
        builder().remove_assignment(
            switch_container=CONTAINER_ID,
            child=CHILD_ID,
            state_or_switch=STATE_ID,
            existing_assignments=[{"child": OTHER_CHILD_ID, "stateOrSwitch": STATE_ID}],
        )
    assert missing_pair.value.error_code == SemanticErrorCode.DESTRUCTIVE_GATE_REQUIRED
    assert "no-op removal" in missing_pair.value.message


def test_mutation_preview_rejects_missing_or_ambiguous_identities_before_schema_payload() -> None:
    with pytest.raises(SemanticValidationError) as missing_container:
        builder().add_assignment(
            switch_container=ObjectIdentity(),
            child=CHILD_ID,
            state_or_switch=STATE_ID,
            existing_assignments=[],
        )
    assert missing_container.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY

    with pytest.raises(SemanticValidationError) as non_exact_child:
        builder().add_assignment(
            switch_container=CONTAINER_ID,
            child=ObjectIdentity(waql="from type Sound"),
            state_or_switch=STATE_ID,
            existing_assignments=[],
        )
    assert non_exact_child.value.error_code == SemanticErrorCode.AMBIGUOUS_OBJECT_IDENTITY
    assert non_exact_child.value.details["identity"]["waql"] == "from type Sound"


def test_source_note_gate_runs_before_envelope_generation() -> None:
    checker = FakeSourceNoteChecker(
        SourceNoteCheck(False, BuilderFamily.SWITCHCONTAINER.value, missing_fields=("return_shape",), reason="incomplete note")
    )

    with pytest.raises(SemanticValidationError) as exc:
        SwitchContainerAssignmentBuilder(source_note_checker=checker).get_assignments(switch_container=CONTAINER_ID)

    assert exc.value.error_code == SemanticErrorCode.SOURCE_NOTE_INCOMPLETE
    assert checker.calls == [("switchcontainer", "2022.1")]


def test_topic_expectations_require_payload_identity_and_do_not_subscribe() -> None:
    added = builder().assignment_added_expectation(
        switch_container=CONTAINER_ID,
        child=CHILD_ID,
        state_or_switch=STATE_ID,
        assignment_id="assignment-123",
    )
    removed = builder().assignment_removed_expectation(switch_container=CONTAINER_ID, child=CHILD_ID, state_or_switch=STATE_ID)

    assert added.as_dict() == {
        "uri": ASSIGNMENT_ADDED_TOPIC_URI,
        "options": {"return": ["id", "name", "type", "path"]},
        "payload_identity": {"switchContainer": CONTAINER_ID, "child": CHILD_ID, "stateOrSwitch": STATE_ID, "assignment": "assignment-123"},
        "assignment_id_required_when_available": True,
        "hidden_subscription": False,
        "metadata": added.as_dict()["metadata"],
    }
    assert added.as_dict()["metadata"]["schema_validation"]["uri"] == ASSIGNMENT_ADDED_TOPIC_URI
    assert removed.as_dict()["uri"] == ASSIGNMENT_REMOVED_TOPIC_URI
    assert removed.as_dict()["payload_identity"] == {"switchContainer": CONTAINER_ID, "child": CHILD_ID, "stateOrSwitch": STATE_ID}
    assert removed.as_dict()["metadata"]["readback_required"].startswith("getAssignments must prove")


def test_topic_expectation_rejects_unsupported_topic_or_missing_return_fields() -> None:
    with pytest.raises(SemanticValidationError) as unsupported:
        builder().topic_expectation("ak.wwise.core.object.created", switch_container=CONTAINER_ID, child=CHILD_ID, state_or_switch=STATE_ID)
    assert unsupported.value.error_code == SemanticErrorCode.SEMANTIC_PROPERTY_UNSUPPORTED

    with pytest.raises(SemanticValidationError) as bad_return:
        builder().assignment_added_expectation(switch_container=CONTAINER_ID, child=CHILD_ID, state_or_switch=STATE_ID, return_fields=[])
    assert bad_return.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH


def test_parse_get_assignments_result_accepts_result_or_rows_and_rejects_malformed_rows() -> None:
    result_records = parse_get_assignments_result({"return": [{"child": {"id": CHILD_ID}, "stateOrSwitch": {"path": "\\Switches\\Running"}}]})
    row_records = parse_get_assignments_result([{"child": CHILD_ID, "stateOrSwitch": STATE_ID}])

    assert result_records[0].child == CHILD_ID
    assert result_records[0].state_or_switch == "\\Switches\\Running"
    assert row_records[0].as_dict()["stateOrSwitch"] == STATE_ID

    with pytest.raises(SemanticValidationError) as malformed:
        parse_get_assignments_result({"return": [{"child": CHILD_ID}]})
    assert malformed.value.error_code == SemanticErrorCode.SEMANTIC_SCHEMA_MISMATCH
    assert malformed.value.details["missing_fields"] == ["stateOrSwitch"]


def test_module_level_helpers_build_with_fake_source_note_checker() -> None:
    preview = build_add_assignment_preview(
        source_note_checker=FakeSourceNoteChecker(),
        switch_container=CONTAINER_ID,
        child=CHILD_ID,
        state_or_switch=STATE_ID,
        existing_assignments=[],
    )
    expectation = build_assignment_added_expectation(
        source_note_checker=FakeSourceNoteChecker(),
        switch_container=CONTAINER_ID,
        child=CHILD_ID,
        state_or_switch=STATE_ID,
    )

    assert preview.dispatch_payload()["uri"] == ADD_ASSIGNMENT_URI
    assert expectation.uri == ASSIGNMENT_ADDED_TOPIC_URI
    assert expectation.as_dict()["hidden_subscription"] is False

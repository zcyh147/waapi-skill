from __future__ import annotations

from collections.abc import Mapping

import pytest

from tests.semantic.support import typed_gateway_input
from tests.semantic.support.typed_gateway_input import (
    create_object_lifecycle_business_preview,
)
from wwise_waapi.business_adapters import (
    business_adapter,
    business_adapter_operations,
)
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    ExistingObjectTarget,
    SUPPORTED_WWISE_VERSIONS,
)
from wwise_waapi.core_business_contracts import core_business_draft_operations
from wwise_waapi.project_setting_business_contracts import (
    project_setting_business_operations,
)
from wwise_waapi.source_control_business_contracts import (
    source_control_business_draft_operations,
)
from wwise_waapi.runtime_inspection_business_contracts import (
    runtime_control_business_operations,
)
from wwise_waapi.soundengine_business_contracts import (
    soundengine_control_business_operations,
)
from wwise_waapi.object_lifecycle_business import (
    materialize_object_lifecycle_business_request,
)
from wwise_waapi.object_lifecycle_business_contracts import (
    object_lifecycle_business_contract_data,
)
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    OPERATION_INPUT_MODE_LANES,
)


OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"
PARENT_ID = "{22222222-2222-2222-2222-222222222222}"


def test_business_adapter_registry_selects_one_family_at_one_seam() -> None:
    audio = business_adapter("audio.import")
    lifecycle = {
        business_adapter(operation).family
        for operation in (
            "object.copy",
            "object.delete",
            "object.move",
            "object.setName",
            "object.setNotes",
        )
    }

    assert audio.family == "audio-import"
    assert lifecycle == {"object-lifecycle"}
    assert audio.accepts_update_command("draft-declare-new") is True
    assert audio.accepts_update_command("draft-declare-object-change") is False
    assert business_adapter("object.move").accepts_update_command(
        "draft-declare-object-change"
    ) is True
    assert business_adapter("object.setProperty").family == (
        "object-metadata-fields"
    )
    assert business_adapter("object.setProperty").supports_field_discovery is True
    assert business_adapter("object.setProperty").supports_field_binding is False


def test_every_business_input_lane_has_exactly_one_registered_adapter() -> None:
    assert business_adapter_operations() == (
        {
            lane.operation
            for lane in OPERATION_INPUT_MODE_LANES
            if lane.input_mode == BUSINESS_DECLARATION_INPUT_MODE
        }
        | core_business_draft_operations()
        | project_setting_business_operations()
        | source_control_business_draft_operations()
        | runtime_control_business_operations()
        | soundengine_control_business_operations()
    )


def test_object_lifecycle_adapter_rejects_audio_only_cleaned_file_replay() -> None:
    session, object_handle, _parent_handle = _session()
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(object_handle),
        fields={"notes": "closed"},
    )

    with pytest.raises(ValueError, match="cleaned file evidence"):
        business_adapter("object.setNotes").materialize(
            session,
            allow_cleaned_file_evidence=True,
        )


@pytest.mark.parametrize(
    ("operation", "business_fields"),
    [
        ("object.delete", {}),
        ("object.setName", {"new_name": "Renamed"}),
        ("object.setNotes", {"notes": "line 1\nline 2"}),
        (
            "object.copy",
            {"parent_id": PARENT_ID, "name_conflict": "rename"},
        ),
        (
            "object.move",
            {"parent_id": PARENT_ID, "name_conflict": "fail"},
        ),
    ],
)
def test_trusted_helper_closes_lifecycle_parameters_into_canonical_request(
    operation: str,
    business_fields: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_executor(
        gateway: object,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        captured["gateway"] = gateway
        captured["request"] = dict(request)
        return {"transaction_id": "tx1-test"}

    monkeypatch.setattr(
        typed_gateway_input,
        "create_typed_transaction_preview",
        fake_executor,
    )
    gateway = lambda _command: {}  # noqa: E731 - identity-bearing test double

    preview = create_object_lifecycle_business_preview(
        gateway,
        version="2022.1",
        operation=operation,
        object_id=OBJECT_ID,
        **business_fields,
    )

    assert preview["transaction_id"] == "tx1-test"
    assert captured["gateway"] is gateway
    request = captured["request"]
    assert isinstance(request, Mapping)
    assert request["operation"] == operation
    assert request["version"] == "2022.1"
    arguments = request["arguments"]
    assert isinstance(arguments, Mapping)
    assert arguments["object"] == {"kind": "id", "value": OBJECT_ID}
    if "parent_id" in business_fields:
        assert arguments["parent"] == {"kind": "id", "value": PARENT_ID}
    if "new_name" in business_fields:
        assert arguments["value"] == business_fields["new_name"]
    if "notes" in business_fields:
        assert arguments["value"] == business_fields["notes"]
    if "name_conflict" in business_fields:
        assert arguments["on_name_conflict"] == business_fields["name_conflict"]


def _session(
    version: str = "2022.1",
) -> tuple[BusinessDeclarationSession, str, str]:
    context = BusinessContext.create(
        task_authority="da1-" + "1" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    session = BusinessDeclarationSession.create(context)
    bound = session.handles.bind_object(
        object_id=OBJECT_ID,
        name="OldName",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\OldName",
    )
    parent = session.handles.bind_object(
        object_id=PARENT_ID,
        name="Destination",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Destination",
    )
    return session, bound.handle, parent.handle


def test_set_name_business_declaration_compiles_to_closed_canonical_request() -> None:
    session, object_handle, _parent_handle = _session()
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(object_handle),
        fields={"new_name": "新名称 & Rain"},
    )

    request = materialize_object_lifecycle_business_request(
        "object.setName",
        session,
    )

    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setName",
        "arguments": {
            "object": {"kind": "id", "value": OBJECT_ID},
            "value": "新名称 & Rain",
        },
    }


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize(
    ("operation", "business_fields", "native_fields"),
    [
        (
            "object.copy",
            {"parent_handle": "<parent>", "name_conflict": "rename"},
            {
                "parent": {"kind": "id", "value": PARENT_ID},
                "on_name_conflict": "rename",
            },
        ),
        ("object.delete", {}, {}),
        (
            "object.move",
            {"parent_handle": "<parent>", "name_conflict": "fail"},
            {
                "parent": {"kind": "id", "value": PARENT_ID},
                "on_name_conflict": "fail",
            },
        ),
        (
            "object.setName",
            {"new_name": "Storm \\ 風 & <Rain>"},
            {"value": "Storm \\ 風 & <Rain>"},
        ),
        (
            "object.setNotes",
            {"notes": 'line 1\n"quoted" & <tag>'},
            {"value": 'line 1\n"quoted" & <tag>'},
        ),
    ],
)
def test_every_object_lifecycle_lane_compiles_business_fields_only(
    version: str,
    operation: str,
    business_fields: dict[str, object],
    native_fields: dict[str, object],
) -> None:
    session, object_handle, parent_handle = _session(version)
    fields = {
        name: parent_handle if value == "<parent>" else value
        for name, value in business_fields.items()
    }
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(object_handle),
        fields=fields,
    )

    request = materialize_object_lifecycle_business_request(operation, session)

    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": operation,
        "arguments": {
            "object": {"kind": "id", "value": OBJECT_ID},
            **native_fields,
        },
    }


def test_native_request_fields_are_rejected_without_a_fallback() -> None:
    session, object_handle, _parent_handle = _session()
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(object_handle),
        fields={"new_name": "Allowed", "value": "native bypass"},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_lifecycle_business_request(
            "object.setName",
            session,
        )

    assert captured.value.error_code == "NATIVE_FIELD_FORBIDDEN"
    assert captured.value.repair["field"] == "value"


def test_missing_parent_handle_returns_one_closed_repair() -> None:
    session, object_handle, _parent_handle = _session()
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(object_handle),
        fields={"name_conflict": "fail"},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_lifecycle_business_request("object.move", session)

    assert captured.value.repair == {
        "contract": "waapi-skill.business-repair/v1",
        "error_code": "REQUIRED_FIELD_MISSING",
        "field": "parent_handle",
        "draft_changed": False,
        "missing": ["parent_handle"],
        "action": "submit one complete disclosed object-change declaration",
    }


def test_unknown_bound_parent_handle_repairs_parent_not_source_object() -> None:
    session, object_handle, parent_handle = _session()
    unknown_parent_handle = parent_handle[:-1] + (
        "0" if parent_handle[-1] != "0" else "1"
    )
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(object_handle),
        fields={"parent_handle": unknown_parent_handle},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_lifecycle_business_request("object.move", session)

    assert captured.value.error_code == "OBJECT_HANDLE_NOT_AVAILABLE"
    assert captured.value.repair["field"] == "parent_handle"
    assert captured.value.repair["draft_changed"] is False


@pytest.mark.parametrize(
    ("version", "source_control_available"),
    [
        ("2021.1", False),
        ("2022.1", False),
        ("2023.1", True),
        ("2024.1", True),
        ("2025.1", True),
    ],
)
@pytest.mark.parametrize(
    ("operation", "supports_add"),
    [
        ("object.copy", True),
        ("object.delete", False),
        ("object.move", False),
    ],
)
def test_source_control_business_fields_are_disclosed_only_when_available(
    version: str,
    source_control_available: bool,
    operation: str,
    supports_add: bool,
) -> None:
    contract = object_lifecycle_business_contract_data(operation, version)
    optional_fields = set(contract["declaration"]["optional_fields"])
    field_types = set(contract["declaration"]["field_types"])

    assert ("check_out_from_source_control" in optional_fields) is (
        source_control_available
    )
    assert ("check_out_from_source_control" in field_types) is (
        source_control_available
    )
    assert ("add_to_source_control" in optional_fields) is (
        source_control_available and supports_add
    )
    assert ("add_to_source_control" in field_types) is (
        source_control_available and supports_add
    )
    assert contract["version_features"] == {
        "add_to_source_control": source_control_available and supports_add,
        "check_out_from_source_control": source_control_available,
    }


def test_undisclosed_version_only_source_control_field_fails_before_live_call() -> None:
    session, object_handle, _parent_handle = _session("2022.1")
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(object_handle),
        fields={"check_out_from_source_control": True},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_lifecycle_business_request("object.delete", session)

    assert captured.value.error_code == "BUSINESS_FIELD_UNAVAILABLE"
    assert captured.value.repair["field"] == "check_out_from_source_control"


def test_multiple_object_changes_do_not_silently_batch() -> None:
    session, object_handle, parent_handle = _session()
    session = session.with_existing_declaration(
        declaration_id="first",
        target=ExistingObjectTarget(object_handle),
        fields={"notes": "first"},
    ).with_existing_declaration(
        declaration_id="second",
        target=ExistingObjectTarget(parent_handle),
        fields={"notes": "second"},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_lifecycle_business_request("object.setNotes", session)

    assert captured.value.error_code == "DECLARATION_COUNT_INVALID"
    assert captured.value.repair["count"] == 2

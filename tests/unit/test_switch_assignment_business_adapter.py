from __future__ import annotations

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    ExistingObjectTarget,
    SUPPORTED_WWISE_VERSIONS,
)
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    operation_input_mode,
)
from wwise_waapi.switch_assignment_business import (
    materialize_switch_assignment_business_request,
)
from wwise_waapi.switch_assignment_business_contracts import (
    switch_assignment_business_contract_data,
)


CONTAINER_ID = "{11111111-1111-1111-1111-111111111111}"
CHILD_ID = "{22222222-2222-2222-2222-222222222222}"
VALUE_ID = "{33333333-3333-3333-3333-333333333333}"
OPERATIONS = (
    "switchContainer.addAssignment",
    "switchContainer.removeAssignment",
)


def _session(
    version: str,
) -> tuple[BusinessDeclarationSession, str, str, str]:
    context = BusinessContext.create(
        task_authority="da1-" + "1" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    session = BusinessDeclarationSession.create(context)
    container = session.handles.bind_object(
        object_id=CONTAINER_ID,
        name="Footsteps",
        object_type="SwitchContainer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps",
    )
    child = session.handles.bind_object(
        object_id=CHILD_ID,
        name="Snow_Step",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps\Snow_Step",
    )
    value = session.handles.bind_object(
        object_id=VALUE_ID,
        name="Snow",
        object_type="Switch",
        path=r"\Switches\Default Work Unit\Surface\Snow",
    )
    return session, container.handle, child.handle, value.handle


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_switch_assignment_lane_compiles_three_business_handles(
    version: str,
    operation: str,
) -> None:
    session, container, child, value = _session(version)
    session = session.with_existing_declaration(
        declaration_id="assignment",
        target=ExistingObjectTarget(container),
        fields={
            "child_handle": child,
            "state_or_switch_handle": value,
        },
    )

    request = materialize_switch_assignment_business_request(operation, session)

    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": operation,
        "arguments": {
            "switch_container": {"kind": "id", "value": CONTAINER_ID},
            "child": {"kind": "id", "value": CHILD_ID},
            "state_or_switch": {"kind": "id", "value": VALUE_ID},
        },
    }
    assert operation_input_mode(operation, version) == (
        BUSINESS_DECLARATION_INPUT_MODE
    )
    adapter = business_adapter(operation)
    assert adapter.family == "switch-assignment"
    assert adapter.accepts_update_command(
        "draft-declare-switch-assignment"
    ) is True
    role_declaration = adapter.role_declaration
    assert role_declaration is not None
    assert role_declaration.roles == (
        "switch_container",
        "child",
        "state_or_switch",
    )
    assert role_declaration.required_fields == (
        "switch_container_handle",
        "child_handle",
        "state_or_switch_handle",
    )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize("operation", OPERATIONS)
def test_switch_assignment_contract_discloses_only_three_business_roles(
    version: str,
    operation: str,
) -> None:
    contract = switch_assignment_business_contract_data(operation, version)

    assert contract["input_mode"] == "business_declaration"
    assert contract["binding"]["roles"] == [
        "switch_container",
        "child",
        "state_or_switch",
    ]
    assert contract["declaration"] == {
        "subcommand": "draft-declare-switch-assignment",
        "required_fields": [
            "switch_container_handle",
            "child_handle",
            "state_or_switch_handle",
        ],
        "field_types": {
            "switch_container_handle": "bound_object_handle",
            "child_handle": "bound_object_handle",
            "state_or_switch_handle": "bound_object_handle",
        },
        "optional_fields": [],
        "outcome": "add" if operation.endswith("addAssignment") else "remove",
    }
    encoded = str(contract).casefold()
    assert "direct-child" not in encoded
    assert "scoped-name" not in encoded
    assert "native_request" in contract["gateway_derivations"]


def test_switch_assignment_business_rejects_native_fields_and_stale_handles() -> None:
    session, container, child, _value = _session("2025.1")
    native = session.with_existing_declaration(
        declaration_id="assignment",
        target=ExistingObjectTarget(container),
        fields={
            "child_handle": child,
            "state_or_switch_handle": "bobj1-does-not-exist",
            "state_or_switch": {"kind": "id", "value": VALUE_ID},
        },
    )

    with pytest.raises(BusinessDeclarationError) as native_error:
        materialize_switch_assignment_business_request(
            "switchContainer.addAssignment",
            native,
        )
    assert native_error.value.error_code == "NATIVE_FIELD_FORBIDDEN"

    stale = session.with_existing_declaration(
        declaration_id="assignment",
        target=ExistingObjectTarget(container),
        fields={
            "child_handle": child,
            "state_or_switch_handle": "bobj1-does-not-exist",
        },
    )
    with pytest.raises(BusinessDeclarationError) as stale_error:
        materialize_switch_assignment_business_request(
            "switchContainer.removeAssignment",
            stale,
        )
    assert stale_error.value.error_code == "OBJECT_HANDLE_NOT_AVAILABLE"
    assert stale_error.value.repair["field"] == "state_or_switch_handle"

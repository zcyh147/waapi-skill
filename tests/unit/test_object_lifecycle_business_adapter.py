from __future__ import annotations

import pytest

from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    ExistingObjectTarget,
    SUPPORTED_WWISE_VERSIONS,
)
from wwise_waapi.object_lifecycle_business import (
    materialize_object_lifecycle_business_request,
)


OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"
PARENT_ID = "{22222222-2222-2222-2222-222222222222}"


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

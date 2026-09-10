from __future__ import annotations

import pytest

from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    ExistingObjectTarget,
    SUPPORTED_WWISE_VERSIONS,
)
from wwise_waapi.object_metadata_business import (
    materialize_object_metadata_business_request,
)
from wwise_waapi.object_metadata_business_contracts import (
    object_metadata_business_contract_data,
)


OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"
TARGET_ID = "{22222222-2222-2222-2222-222222222222}"


def _session(
    *,
    version: str = "2022.1",
    token: str = "Volume",
    field_kind: str = "property",
    value_type: str = "number",
    platform: str | None = None,
    restrictions: dict[str, object] | None = None,
) -> tuple[BusinessDeclarationSession, str, str, str]:
    context = BusinessContext.create(
        task_authority="da1-" + "1" * 40,
        project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.fixture",
    )
    session = BusinessDeclarationSession.create(context)
    source = session.handles.bind_object(
        object_id=OBJECT_ID,
        name="Alarm",
        object_type="Sound",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Alarm",
    )
    target = session.handles.bind_object(
        object_id=TARGET_ID,
        name="Master Audio Bus",
        object_type="Bus",
        path=r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
    )
    field = session.handles.bind_field(
        scope_kind="object",
        scope_value=OBJECT_ID,
        token=token,
        field_kind=field_kind,
        value_type=value_type,
        platform=platform,
        restrictions=restrictions or {},
        metadata_digest="a" * 64,
    )
    return session, source.handle, field.handle, target.handle


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize(
    ("operation", "required_fields"),
    [
        (
            "object.setProperty",
            ["object_handle", "field_handle", "business_value"],
        ),
        (
            "object.setReference",
            ["object_handle", "field_handle", "reference_outcome"],
        ),
        (
            "object.setLinked",
            ["object_handle", "field_handle", "link_state"],
        ),
    ],
)
def test_metadata_business_contract_exposes_only_meaning_and_bound_handles(
    version: str,
    operation: str,
    required_fields: list[str],
) -> None:
    if operation == "object.setLinked" and version in {"2021.1", "2022.1"}:
        with pytest.raises(ValueError, match="unsupported"):
            object_metadata_business_contract_data(operation, version)
        return

    contract = object_metadata_business_contract_data(operation, version)

    assert contract["input_mode"] == "business_declaration"
    assert contract["field_discovery"]["input"] == "user_facing_meaning"
    assert contract["field_discovery"]["result"] == (
        "copy_one_gateway_returned_field_handle"
    )
    assert contract["declaration"]["required_fields"] == required_fields
    serialized = repr(contract)
    for leaked in (
        "exact-live-field-token",
        "metadata_scope",
        "wire_type",
        "waapi_args",
    ):
        assert leaked not in serialized


def test_property_business_value_compiles_through_bound_metadata_type() -> None:
    session, source_handle, field_handle, _target_handle = _session(
        platform="Windows"
    )
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": field_handle, "business_value": -4},
    )

    request = materialize_object_metadata_business_request(
        "object.setProperty",
        session,
    )

    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setProperty",
        "arguments": {
            "object": {"kind": "id", "value": OBJECT_ID},
            "property": "Volume",
            "value": -4.0,
            "platform": "Windows",
        },
    }


@pytest.mark.parametrize(
    ("fields", "expected_target"),
    [
        ({"reference_outcome": "<target>"}, TARGET_ID),
        ({"reference_outcome": "clear"}, None),
    ],
)
def test_reference_business_outcome_compiles_to_set_or_clear(
    fields: dict[str, str],
    expected_target: str | None,
) -> None:
    session, source_handle, field_handle, target_handle = _session(
        token="OutputBus",
        field_kind="reference",
        value_type="reference",
        restrictions={"allowed_target_types": ["Bus", "AuxBus"]},
    )
    outcome = target_handle if fields["reference_outcome"] == "<target>" else "clear"
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": field_handle, "reference_outcome": outcome},
    )

    request = materialize_object_metadata_business_request(
        "object.setReference",
        session,
    )

    assert request["arguments"] == {
        "object": {"kind": "id", "value": OBJECT_ID},
        "reference": "OutputBus",
        "target": (
            None
            if expected_target is None
            else {"kind": "id", "value": expected_target}
        ),
    }


def test_link_state_uses_platform_sealed_into_field_handle() -> None:
    session, source_handle, field_handle, _target_handle = _session(
        version="2025.1",
        platform="Windows",
    )
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": field_handle, "link_state": "unlinked"},
    )

    request = materialize_object_metadata_business_request(
        "object.setLinked",
        session,
    )

    assert request["arguments"] == {
        "object": {"kind": "id", "value": OBJECT_ID},
        "property": "Volume",
        "platform": "Windows",
        "linked": False,
    }


def test_field_handle_scope_mismatch_returns_bounded_repair() -> None:
    session, _source_handle, field_handle, target_handle = _session()
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(target_handle),
        fields={"field_handle": field_handle, "business_value": -4},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_metadata_business_request(
            "object.setProperty",
            session,
        )

    assert captured.value.error_code == "FIELD_HANDLE_SCOPE_MISMATCH"
    assert captured.value.repair["field"] == "field_handle"


def test_property_rejects_reference_handle_without_native_fallback() -> None:
    session, source_handle, field_handle, _target_handle = _session(
        token="OutputBus",
        field_kind="reference",
        value_type="reference",
        restrictions={"allowed_target_types": ["Bus"]},
    )
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": field_handle, "business_value": -4},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_metadata_business_request(
            "object.setProperty",
            session,
        )

    assert captured.value.error_code == "FIELD_HANDLE_KIND_MISMATCH"
    assert captured.value.repair["expected_kind"] == "property"


def test_link_state_requires_platform_sealed_by_live_discovery() -> None:
    session, source_handle, field_handle, _target_handle = _session(
        version="2025.1"
    )
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": field_handle, "link_state": "linked"},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_metadata_business_request(
            "object.setLinked",
            session,
        )

    assert captured.value.error_code == "FIELD_PLATFORM_REQUIRED"


def test_hostile_string_business_value_is_preserved_exactly() -> None:
    session, source_handle, field_handle, _target_handle = _session(
        token="CustomText",
        value_type="string",
    )
    value = 'line 1\n"quoted" & <tag> \\ --literal'
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": field_handle, "business_value": value},
    )

    request = materialize_object_metadata_business_request(
        "object.setProperty",
        session,
    )

    assert request["arguments"]["value"] == value


def test_out_of_range_business_value_returns_live_range_repair() -> None:
    session, source_handle, field_handle, _target_handle = _session(
        restrictions={"minimum": -12.0, "maximum": 12.0}
    )
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": field_handle, "business_value": -20},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_metadata_business_request(
            "object.setProperty",
            session,
        )

    assert captured.value.error_code == "FIELD_VALUE_OUT_OF_RANGE"
    assert captured.value.repair["valid_range"] == {
        "minimum": -12.0,
        "maximum": 12.0,
    }


def test_unknown_field_handle_returns_one_closed_repair() -> None:
    session, source_handle, field_handle, _target_handle = _session()
    unknown = field_handle[:-1] + ("0" if field_handle[-1] != "0" else "1")
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": unknown, "business_value": -4},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_metadata_business_request(
            "object.setProperty",
            session,
        )

    assert captured.value.error_code == "FIELD_HANDLE_NOT_AVAILABLE"
    assert captured.value.repair["draft_changed"] is False


@pytest.mark.parametrize(
    ("operation", "native_field"),
    [
        ("object.setProperty", "property"),
        ("object.setReference", "reference"),
        ("object.setLinked", "platform"),
    ],
)
def test_native_metadata_fields_have_no_business_fallback(
    operation: str,
    native_field: str,
) -> None:
    version = "2025.1" if operation == "object.setLinked" else "2022.1"
    session, source_handle, field_handle, _target_handle = _session(version=version)
    valid = (
        {"business_value": -4}
        if operation == "object.setProperty"
        else {"reference_outcome": "clear"}
        if operation == "object.setReference"
        else {"link_state": "linked"}
    )
    session = session.with_existing_declaration(
        declaration_id="change",
        target=ExistingObjectTarget(source_handle),
        fields={"field_handle": field_handle, **valid, native_field: "bypass"},
    )

    with pytest.raises(BusinessDeclarationError) as captured:
        materialize_object_metadata_business_request(operation, session)

    assert captured.value.error_code == "NATIVE_FIELD_FORBIDDEN"
    assert captured.value.repair["field"] == native_field

from __future__ import annotations

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import BusinessContext, BusinessDeclarationError
from wwise_waapi.compound_undo_business import (
    build_compound_undo_child_snapshot,
    materialize_compound_undo_business_request,
)
from wwise_waapi.compound_undo_business_contracts import (
    COMPOUND_UNDO_BUSINESS_CONTRACT,
    compound_undo_business_contract_data,
)
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    operation_input_mode,
    parse_operation_request,
)
from wwise_waapi.typed_operations import (
    compound_business_child_operations,
    compound_child_operations,
    draft_operation_request_contract,
)


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
OBJECT_GUID = "{11111111-1111-1111-1111-111111111111}"


def _session(version: str, children: list[dict[str, object]]) -> BusinessDeclarationSession:
    return BusinessDeclarationSession.create(
        BusinessContext.create(
            task_authority="da1-" + "1" * 40,
            project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            project_path="/fixtures/SampleProject.wproj",
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        )
    ).with_settings(
        {
            "undo_plan": {
                "display_name": "Reviewed batch",
                "children": children,
            }
        }
    )


def _child_request(version: str, *, notes: str) -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "object.setNotes",
        "arguments": {
            "object": {
                "kind": "id",
                "value": "{11111111-1111-1111-1111-111111111111}",
            },
            "value": notes,
        },
    }


def _native_child_request(version: str) -> dict[str, object]:
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.core.object.setRandomizer",
            "args": {
                "object": r"\Actor-Mixer Hierarchy\A",
                "property": "Volume",
                "enabled": True,
            },
            "options": {},
        },
    }


@pytest.mark.parametrize("version", VERSIONS)
def test_every_undo_lane_uses_one_ordered_business_plan(version: str) -> None:
    contract = compound_undo_business_contract_data(version)

    assert contract["contract"] == COMPOUND_UNDO_BUSINESS_CONTRACT
    assert operation_input_mode("waapi.undoGroup", version) == (
        BUSINESS_DECLARATION_INPUT_MODE
    )
    assert contract["declaration"]["subcommand"] == "draft-declare-undo-plan"
    assert contract["declaration"]["child_input"] == (
        "ordered_checked_closed_draft_snapshot"
    )
    assert contract["legacy_composer_public"] is False
    assert contract["legacy_child_schema_public"] is False
    assert contract["legacy_action_grammar_public"] is False
    assert contract["declaration"]["business_sequence"]["caller_owned"] is True
    assert contract["declaration"]["business_sequence"][
        "native_dependency_edges_input"
    ] == "forbidden"
    assert "native_phase_dependency_order" in contract["gateway_derivations"]
    assert "dependency_order" not in contract["gateway_derivations"]
    adapter = business_adapter("waapi.undoGroup")
    assert adapter.family == "compound-undo-business"
    assert adapter.accepts_update_command("draft-declare-undo-plan")
    with pytest.raises(ValueError, match="No typed Draft adapter"):
        draft_operation_request_contract("waapi.undoGroup", version)


@pytest.mark.parametrize("version", VERSIONS)
def test_every_eligible_child_family_has_one_checked_closed_draft_route(
    version: str,
) -> None:
    contract = compound_undo_business_contract_data(version)
    declaration = contract["declaration"]
    eligible = set(declaration["eligible_child_operations"])
    prohibited_generic = set(declaration["prohibited_generic_child_operations"])

    assert eligible == set(compound_business_child_operations(version))
    assert eligible | prohibited_generic == set(compound_child_operations(version))
    assert eligible.isdisjoint(prohibited_generic)
    assert all(not operation.startswith("ak.") for operation in eligible)
    assert all(operation.startswith("ak.") for operation in prohibited_generic)
    assert contract["safety"][
        "every_eligible_child_requires_business_state_verification"
    ] is True


@pytest.mark.parametrize("version", VERSIONS)
def test_checked_child_snapshots_materialize_in_exact_declared_order(version: str) -> None:
    first = build_compound_undo_child_snapshot(
        version=version,
        source_draft_id="od1-11111111111111111111111111111111",
        source_revision=4,
        request=_child_request(version, notes="first"),
    )
    second = build_compound_undo_child_snapshot(
        version=version,
        source_draft_id="od1-22222222222222222222222222222222",
        source_revision=7,
        request=_child_request(version, notes="second"),
    )
    request = materialize_compound_undo_business_request(
        "waapi.undoGroup",
        _session(version, [first, second]),
    )

    assert request["arguments"]["display_name"] == "Reviewed batch"
    calls = request["arguments"]["calls"]
    assert [row["request"]["operation"] for row in calls] == [
        "object.setNotes",
        "object.setNotes",
    ]
    assert all("handle" not in row for row in calls)
    parse_operation_request(request, expected_version=version)


def test_undo_business_rejects_non_allowlisted_native_child_requests() -> None:
    native = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "debug.testCrash",
        "arguments": {},
    }
    with pytest.raises(BusinessDeclarationError) as exc_info:
        build_compound_undo_child_snapshot(
            version="2025.1",
            source_draft_id="od1-11111111111111111111111111111111",
            source_revision=1,
            request=native,
        )

    assert exc_info.value.repair["error_code"] == "UNDO_CHILD_BUSINESS_REQUIRED"


@pytest.mark.parametrize("version", VERSIONS)
def test_undo_business_rejects_generic_children_until_business_verifier_parity(
    version: str,
) -> None:
    with pytest.raises(BusinessDeclarationError) as exc_info:
        build_compound_undo_child_snapshot(
            version=version,
            source_draft_id="od1-11111111111111111111111111111111",
            source_revision=1,
            request=_native_child_request(version),
        )

    assert exc_info.value.repair["error_code"] == "UNDO_CHILD_BUSINESS_REQUIRED"


def test_undo_plan_rejects_tampered_child_snapshot() -> None:
    child = build_compound_undo_child_snapshot(
        version="2025.1",
        source_draft_id="od1-11111111111111111111111111111111",
        source_revision=1,
        request=_child_request("2025.1", notes="original"),
    )
    child["request"]["arguments"]["value"] = "tampered"

    with pytest.raises(BusinessDeclarationError) as exc_info:
        materialize_compound_undo_business_request(
            "waapi.undoGroup",
            _session("2025.1", [child]),
        )

    assert exc_info.value.repair["error_code"] == "UNDO_CHILD_SNAPSHOT_STALE"


@pytest.mark.parametrize(
    "child_payload",
    (
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2025.1",
            "operation": "waapi.undoGroup",
            "arguments": {"display_name": "nested", "calls": []},
        },
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2025.1",
            "operation": "waapi.call",
            "arguments": {
                "api": "ak.wwise.core.object.setNotes",
                "args": {"object": OBJECT_GUID, "value": "bypass"},
                "options": {},
            },
        },
    ),
)
def test_undo_child_snapshot_rejects_nested_or_weaker_exact_name_bypass(
    child_payload: dict[str, object],
) -> None:
    with pytest.raises(BusinessDeclarationError):
        build_compound_undo_child_snapshot(
            version="2025.1",
            source_draft_id="od1-11111111111111111111111111111111",
            source_revision=1,
            request=child_payload,
        )


@pytest.mark.parametrize(
    "display_name,child_count",
    (("", 1), (" padded ", 1), ("x" * 257, 1), ("Batch", 0), ("Batch", 33)),
)
def test_undo_business_rejects_display_name_and_child_count_limits(
    display_name: str,
    child_count: int,
) -> None:
    children = [
        build_compound_undo_child_snapshot(
            version="2025.1",
            source_draft_id=f"od1-{index:032x}",
            source_revision=1,
            request=_child_request("2025.1", notes=str(index)),
        )
        for index in range(1, child_count + 1)
    ]
    session = _session("2025.1", children)
    session = session.with_settings(
        {"undo_plan": {"display_name": display_name, "children": children}}
    )

    with pytest.raises(BusinessDeclarationError):
        materialize_compound_undo_business_request("waapi.undoGroup", session)

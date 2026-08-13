from __future__ import annotations

from typing import Any, Mapping

import pytest

from tests.support.public_route_probes import (
    ProgramCallClient,
    ProgramTopicClient,
    PROBE_IO_ROOT,
    request_and_result_from_schema,
    synthesize_schema_value,
)
from wwise_waapi.builders.schema import (
    validate_semantic_event,
    validate_semantic_payload,
    validate_semantic_result,
)
from wwise_waapi.capabilities import CapabilityCatalog, CapabilityRecord
from wwise_waapi.dispatcher import WwiseDispatcher
from wwise_waapi.execution_contracts import ExecutionContractRegistry
from wwise_waapi.operation_registry import (
    OPERATION_REQUEST_CONTRACT,
    UNDO_GROUP_INNER_URIS_BY_VERSION,
    OperationContractError,
    parse_operation_request,
    prepare_operation,
    validate_prepared_roles,
    verify_prepared_operation,
)
from wwise_waapi.operation_composer import (
    OPERATION_DRAFT_ACTION_CONTRACT,
    apply_composer_action,
    materialize_operation_request,
    new_composition,
)
from wwise_waapi.typed_operations import compound_child_request_contract
from wwise_waapi.typed_requests import TypedRequestFact
from wwise_waapi.transaction_cleanup import CLEANUP_SPEC_CONTRACT
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


CATALOG = CapabilityCatalog()
PROGRAM_ROWS = tuple(
    entry
    for version in SUPPORTED_WWISE_VERSION_KEYS
    for entry in CATALOG.entries(version)
    if entry.execution_contract.get("executable") is True
)
BUSINESS_STATE_VERIFIED_APIS = frozenset(
    {
        "ak.wwise.core.remote.connect",
        "ak.wwise.core.remote.disconnect",
        "ak.wwise.core.transport.create",
        "ak.wwise.core.transport.destroy",
    }
)


def _row_id(entry: CapabilityRecord) -> str:
    return f"{entry.version}:{entry.item_type}:{entry.uri}"


@pytest.mark.parametrize("entry", PROGRAM_ROWS, ids=_row_id)
def test_every_public_route_executes_through_packaged_program_code(entry: CapabilityRecord) -> None:
    contract = entry.execution_contract
    assert contract["program_case"]
    assert contract["gateway_commands"]
    assert entry.preferred_route != "unsupported_boundary"

    if entry.item_type == "topic":
        publish_schema = entry.schema.get("publishSchema")
        event_payload: Any = synthesize_schema_value(
            publish_schema if isinstance(publish_schema, Mapping) else {},
            field_name="event",
        )
        client = ProgramTopicClient(event_payload)
        result = WwiseDispatcher(client=client).dispatch(
            entry.uri,
            version=entry.version,
            timeout=1.0,
            result_limit_bytes=int(contract["result_limit_bytes"]),
        )

        assert result["ok"] is True, result
        assert client.subscriptions == [entry.uri]
        assert client.handler.unsubscribe_count == 1
        assert result["result"]["topic"] == entry.uri
        event_validation = validate_semantic_event(
            entry.uri,
            result["result"]["payload"],
            version=entry.version,
        )
        assert event_validation.section == "event"
        return

    args, options, expected_result = request_and_result_from_schema(entry.schema)
    if entry.uri == "ak.wwise.core.transport.create":
        # The reflected result schema makes transport optional, but the packaged
        # business verifier deliberately requires a real non-zero uint32 ID.
        expected_result = {"transport": 1}
    if (
        entry.version in {"2024.1", "2025.1"}
        and entry.uri == "ak.wwise.core.audio.convert"
    ):
        # The reflected schema allows empty arrays and leaves external item
        # references unresolved.  Exercise the narrower reviewed product
        # contract with one canonical value in each required ordered array.
        args = {
            "objects": [
                r"\Actor-Mixer Hierarchy\Default Work Unit\Program Probe"
            ],
            "platforms": ["Mac"],
            "languages": ["SFX"],
        }
    request_validation = validate_semantic_payload(
        entry.uri,
        args,
        options,
        version=entry.version,
    )
    client = ProgramCallClient(expected_result)
    result = WwiseDispatcher(client=client).dispatch(
        entry.uri,
        version=entry.version,
        args=args,
        options=options,
        timeout=1.0,
        allow_destructive=True,
        result_limit_bytes=int(contract["result_limit_bytes"]),
    )

    assert request_validation.uri == entry.uri
    assert result["ok"] is True, result
    assert client.calls == [(entry.uri, args, options)]
    result_validation = validate_semantic_result(
        entry.uri,
        result["result"],
        version=entry.version,
    )
    assert result_validation.section == "result"

    if contract["route"] == "compound_transaction_member":
        assert entry.transaction_operations == ("waapi.undoGroup",)
        with pytest.raises(OperationContractError, match="waapi.undoGroup"):
            parse_operation_request(
                {
                    "contract": OPERATION_REQUEST_CONTRACT,
                    "version": entry.version,
                    "operation": "waapi.call",
                    "arguments": {"api": entry.uri, "args": args, "options": options},
                }
            )
        inner_operation = "ak.wwise.core.object.setRandomizer"
        inner_uri = inner_operation
        inner_capability = CATALOG.describe(entry.version, inner_uri)
        _inner_args, _inner_options, inner_result = request_and_result_from_schema(
            inner_capability.schema
        )
        child_contract = compound_child_request_contract(
            inner_operation, entry.version
        )
        # The reflected anyOf route is easiest to exercise with explicit
        # object/property/enabled facts and its disclosed object branch.
        object_field = next(
            field for field in child_contract.fields
            if field.path == ("object",) and field.shape == "scalar"
            and any(variant.get("pattern") == r"^\\" for variant in field.variants)
        )
        child_facts = [
            TypedRequestFact("choose", object_field.parent_handle, "branch", object_field.handle),
            TypedRequestFact("set", object_field.handle, "string", r"\ProgramObject"),
            TypedRequestFact("set", next(field.handle for field in child_contract.fields if field.path == ("property",) and field.shape == "scalar"), "string", "Volume"),
            TypedRequestFact("set", next(field.handle for field in child_contract.fields if field.path == ("enabled",)), "boolean", "true"),
        ]
        composition = new_composition("waapi.undoGroup", entry.version)
        for action, handle in (
            ({"action": "set_display_name", "display_name": "Program probe"}, "unused"),
            ({"action": "add_child_call", "child_operation": inner_operation}, "uch1-111111111111111111111111"),
        ):
            composition, _ = apply_composer_action(
                "waapi.undoGroup", entry.version, composition,
                {"contract": OPERATION_DRAFT_ACTION_CONTRACT, **action},
                handle_factory=lambda value=handle: value,
            )
        for index, fact in enumerate(child_facts):
            action = {
                "contract": OPERATION_DRAFT_ACTION_CONTRACT,
                "action": "add_child_typed_fact",
                "child_handle": "uch1-111111111111111111111111",
                "fact_action": fact.action,
                "field_handle": fact.handle,
                "value": fact.value,
            }
            if fact.action != "choose":
                action["value_type"] = fact.value_type
            composition, _ = apply_composer_action(
                "waapi.undoGroup", entry.version, composition, action,
                handle_factory=lambda index=index: f"tdh1-{index + 1:024x}",
            )
        undo_request = parse_operation_request(
            materialize_operation_request("waapi.undoGroup", entry.version, composition)
        )
        undo_prepared = prepare_operation(
            undo_request,
            read_call=lambda uri, call_args, call_options: {},
        ).as_dict()
        assert validate_prepared_roles(
            undo_prepared,
            read_call=lambda uri, call_args, call_options: {},
        )["ok"] is True
        phases = []
        for phase_uri, phase_result in (
            ("ak.wwise.core.undo.beginGroup", {}),
            (inner_uri, inner_result),
            ("ak.wwise.core.undo.endGroup", {}),
        ):
            phases.append(
                {
                    "uri": phase_uri,
                    "dispatch_result": {
                        "ok": True,
                        "api": phase_uri,
                        "version": entry.version,
                        "result": phase_result,
                    },
                }
            )
        undo_verification = verify_prepared_operation(
            undo_prepared,
            execution_result={"result": {"same_connection": True, "phases": phases}},
            read_call=lambda uri, call_args, call_options: {},
        )
        assert undo_verification.status == "result_schema_checked"
        assert undo_verification.business_state_verified is False
        return

    if contract["route"] not in {
        "transaction",
        "managed_transaction",
        "isolated_transaction",
    }:
        return

    if "waapi.call" not in entry.transaction_operations:
        assert entry.transaction_operations
        with pytest.raises(OperationContractError) as dedicated:
            parse_operation_request(
                {
                    "contract": OPERATION_REQUEST_CONTRACT,
                    "version": entry.version,
                    "operation": "waapi.call",
                    "arguments": {"api": entry.uri, "args": args, "options": options},
                },
                expected_version=entry.version,
            )
        assert dedicated.value.error_code == "DEDICATED_OPERATION_REQUIRED"
        assert dedicated.value.details["required_operations"] == list(entry.transaction_operations)
        return

    arguments: dict[str, Any] = {"api": entry.uri, "args": args, "options": options}
    if contract["route"] == "isolated_transaction":
        arguments["io_root"] = str(PROBE_IO_ROOT)
    operation_request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": entry.version,
            "operation": "waapi.call",
            "arguments": arguments,
        },
        expected_version=entry.version,
    )
    prepared = prepare_operation(operation_request, read_call=lambda uri, call_args, call_options: {})
    prepared_payload = prepared.as_dict()
    role_validation = validate_prepared_roles(
        prepared_payload,
        read_call=lambda uri, call_args, call_options: {},
    )
    def readback(uri: str, call_args: Mapping[str, Any], call_options: Mapping[str, Any]) -> Mapping[str, Any]:
        assert call_options == {}
        if uri == "ak.wwise.core.remote.getConnectionStatus":
            return {
                "isConnected": entry.uri == "ak.wwise.core.remote.connect",
                "status": "program fixture",
            }
        if uri == "ak.wwise.core.transport.getList":
            if entry.uri == "ak.wwise.core.transport.create":
                return {"list": [{"transport": 1}]}
            if entry.uri == "ak.wwise.core.transport.destroy":
                return {"list": []}
        if uri == "ak.wwise.core.transport.getState":
            assert call_args == {"transport": 1}
            return {"state": "stopped"}
        raise AssertionError(f"unexpected program verification readback: {uri}")

    verification = verify_prepared_operation(
        prepared_payload,
        execution_result=result,
        read_call=(
            readback
            if entry.uri in BUSINESS_STATE_VERIFIED_APIS
            else lambda uri, call_args, call_options: {}
        ),
    )

    assert prepared_payload["dispatch"] == {"uri": entry.uri, "args": args, "options": options}
    prepared_contract = prepared_payload["semantic_preview"]["envelope"]["metadata"]["execution_contract"]
    if contract["route"] == "isolated_transaction":
        assert prepared_contract["io_audit"]["ok"] is True
        assert prepared_contract["io_audit"]["confinement_scope"] == "explicit_write_paths_only"
        assert prepared_contract["io_audit"]["io_root"] == str(PROBE_IO_ROOT)
    if contract["companion_uris"]:
        cleanup = prepared_payload["cleanup"]
        assert cleanup["contract"] == CLEANUP_SPEC_CONTRACT
        assert cleanup["api"] == entry.uri
        assert cleanup["lifecycle_action"] == "opener"
        assert cleanup["lifecycle_strategy"] == contract["lifecycle_strategy"]
        assert cleanup["companion_request"]["api"] == contract["companion_uris"][0]
        assert cleanup["automatic_cleanup"] is False
        assert cleanup["automatic_retry"] is False
        assert len(cleanup["spec_sha256"]) == 64
    assert role_validation["ok"] is True
    assert verification.ok is True, verification.as_dict()
    if entry.uri in BUSINESS_STATE_VERIFIED_APIS:
        assert verification.status == "verified"
        assert verification.business_state_verified is True
        assert verification.verification_strength == "operation_specific_readback"
        assert verification.readbacks
        assert verification.message == (
            "The WAAPI result schema and operation-specific business-state readbacks passed."
        )
    else:
        assert verification.status == "result_schema_checked"
        assert verification.business_state_verified is False
        assert verification.verification_strength == (
            "partial_reflected_schema"
            if result_validation.unresolved_refs
            else "complete_reflected_schema"
        )
        assert verification.message == (
            "The returned WAAPI payload matches the packaged reflected result schema."
        )


def test_program_matrix_is_the_exact_808_row_contract() -> None:
    expected = {
        (entry.version, entry.item_type, entry.uri)
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for entry in ExecutionContractRegistry().executable_entries(version)
    }
    actual = {(entry.version, entry.item_type, entry.uri) for entry in PROGRAM_ROWS}

    assert actual == expected
    assert len(actual) == 808

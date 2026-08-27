from __future__ import annotations

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import BusinessContext, BusinessDeclarationError
from wwise_waapi.debug_business import materialize_debug_business_request
from wwise_waapi.debug_business_contracts import (
    DEBUG_BUSINESS_LANES,
    debug_business_contract_data,
)
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    operation_input_mode,
    parse_operation_request,
)
from wwise_waapi.typed_operations import (
    inline_operation_contract,
    materialize_inline_operation_request,
)


VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
OPERATIONS = {
    "debug.setAsserts": VERSIONS,
    "debug.setAutomationMode": VERSIONS,
    "debug.restartWaapiServers": ("2023.1", "2024.1", "2025.1"),
    "debug.testAssert": VERSIONS,
    "debug.testCrash": VERSIONS,
}


def _session(version: str, intent: dict[str, object]) -> BusinessDeclarationSession:
    return BusinessDeclarationSession.create(
        BusinessContext.create(
            task_authority="da1-" + "1" * 40,
            project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            project_path="/fixtures/SampleProject.wproj",
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        )
    ).with_settings({"debug_intent": intent})


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in OPERATIONS.items()
        for version in versions
    ],
)
def test_every_debug_lane_uses_one_gateway_owned_business_intent(
    operation: str,
    version: str,
) -> None:
    contract = debug_business_contract_data(operation, version)

    assert set(DEBUG_BUSINESS_LANES) == set(OPERATIONS)
    assert operation_input_mode(operation, version) == BUSINESS_DECLARATION_INPUT_MODE
    assert contract["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert contract["declaration"]["subcommand"] == "draft-declare-debug-intent"
    assert contract["legacy_inline_typed_public"] is False
    assert contract["legacy_composer_public"] is False
    assert "acknowledge" not in str(contract)
    adapter = business_adapter(operation)
    assert adapter.family == "debug-host-control"
    assert adapter.accepts_update_command("draft-declare-debug-intent")


@pytest.mark.parametrize("operation", OPERATIONS)
def test_retired_debug_inline_adapter_cannot_reopen_native_input(operation: str) -> None:
    version = OPERATIONS[operation][-1]
    with pytest.raises(ValueError, match="No inline typed adapter"):
        inline_operation_contract(operation, version)
    with pytest.raises(ValueError, match="No inline typed adapter"):
        materialize_inline_operation_request(operation, version, {})


@pytest.mark.parametrize(
    "operation",
    ("debug.setAsserts", "debug.setAutomationMode"),
)
@pytest.mark.parametrize("version", VERSIONS)
def test_boolean_debug_business_outcome_compiles_only_the_stable_boolean(
    operation: str,
    version: str,
) -> None:
    request = materialize_debug_business_request(
        operation,
        _session(version, {"enabled": False}),
    )

    assert request["arguments"] == {"enable": False}
    parse_operation_request(request, expected_version=version)


@pytest.mark.parametrize(
    ("operation", "version"),
    (
        ("debug.restartWaapiServers", "2025.1"),
        ("debug.testAssert", "2022.1"),
        ("debug.testCrash", "2022.1"),
    ),
)
def test_zero_value_debug_intent_compiles_without_public_acknowledgement(
    operation: str,
    version: str,
) -> None:
    request = materialize_debug_business_request(operation, _session(version, {}))

    assert request["arguments"] == {}
    assert "acknowledge" not in str(request)
    parse_operation_request(request, expected_version=version)


def test_debug_intent_rejects_model_authored_native_or_ack_fields() -> None:
    for intent in (
        {"acknowledge": "restart_waapi_servers"},
        {"args": {}},
        {"enable": True},
    ):
        with pytest.raises(BusinessDeclarationError):
            materialize_debug_business_request(
                "debug.restartWaapiServers",
                _session("2025.1", intent),
            )

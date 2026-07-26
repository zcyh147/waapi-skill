from __future__ import annotations

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.builders.common import SemanticValidationError
from wwise_waapi.builders.schema import (
    validate_semantic_event,
    validate_semantic_payload,
    validate_semantic_result,
)
from wwise_waapi.operation_registry import OPERATION_REQUEST_CONTRACT, OperationContractError, parse_operation_request
from wwise_waapi.operation_registry import prepare_operation, verify_prepared_operation
from tests.support.public_route_probes import request_and_result_from_schema
from wwise_waapi.capabilities import CapabilityCatalog


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_public_route_gateway_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


class FakeClient:
    def __init__(self, responses: Mapping[str, list[Any]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        return self.responses[uri].popleft()

    def disconnect(self) -> None:
        return None


def _live_info(version: str = "2022.1") -> dict[str, Any]:
    year, major = (int(value) for value in version.split("."))
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "version": {"year": year, "major": major, "minor": 0, "build": 1},
    }


def _env(tmp_path: Path, version: str = "2022.1") -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "preview_then_confirm",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_VERSION": version,
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_DESTRUCTIVE": "1",
    }


def test_bounded_call_returns_validated_business_result_to_agent(tmp_path: Path) -> None:
    state_result = {"id": "{00000000-0000-0000-0000-000000000001}", "name": "Gameplay"}
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_live_info()],
            "ak.soundengine.getState": [state_result],
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.soundengine.getState",
            "--args-json",
            '{"stateGroup":"Gameplay"}',
        ],
        env=_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == state_result
    assert payload["result_validation"]["section"] == "result"
    assert payload["result_validation"]["unresolved_refs"]
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo", "ak.soundengine.getState"]


@pytest.mark.parametrize(
    "api, expected_status",
    (
        ("ak.wwise.core.project.save", "transaction_required"),
        ("ak.wwise.debug.testCrash", "transaction_required"),
        ("ak.wwise.ui.commands.register", "transaction_required"),
        ("ak.wwise.ui.commands.execute", "transaction_required"),
        ("ak.wwise.ui.commands.unregister", "transaction_required"),
    ),
)
def test_call_cannot_bypass_transaction_or_exclusion_even_with_destructive_env(
    tmp_path: Path,
    api: str,
    expected_status: str,
) -> None:
    connected = False

    def factory(url: str) -> FakeClient:
        nonlocal connected
        connected = True
        raise AssertionError(f"preflight boundary must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", api, "--dry-run"],
        env=_env(tmp_path),
        client_factory=factory,
    )

    assert exit_code == 2
    assert payload["status"] == expected_status
    assert payload["executed"] is False
    assert connected is False


@pytest.mark.parametrize("api", ("ak.wwise.core.getInfo", "ak.wwise.debug.testCrash"))
def test_generic_transaction_accepts_only_registered_transaction_lanes(api: str) -> None:
    with pytest.raises(
        OperationContractError,
        match="route|transaction|dedicated operation",
    ):
        parse_operation_request(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": "2022.1",
                "operation": "waapi.call",
                "arguments": {"api": api, "args": {}, "options": {}},
            }
        )


@pytest.mark.parametrize(
    ("api", "required_operation"),
    (
        ("ak.wwise.core.object.create", "object.create"),
        ("ak.wwise.core.object.set", "object.set"),
        ("ak.wwise.core.audio.import", "audio.import"),
        ("ak.wwise.core.audio.importTabDelimited", "audio.importTabDelimited"),
        ("ak.wwise.core.soundbank.generate", "soundbank.generate"),
        ("ak.wwise.core.soundbank.convertExternalSources", "soundbank.convertExternalSources"),
        ("ak.wwise.core.soundbank.processDefinitionFiles", "soundbank.processDefinitionFiles"),
    ),
)
def test_generic_transaction_cannot_bypass_an_implemented_dedicated_operation(
    api: str,
    required_operation: str,
) -> None:
    with pytest.raises(OperationContractError) as blocked:
        parse_operation_request(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": "2022.1",
                "operation": "waapi.call",
                "arguments": {"api": api, "args": {}, "options": {}},
            }
        )

    assert blocked.value.error_code == "DEDICATED_OPERATION_REQUIRED"
    expected_operations = (
        ["object.createPlugin", "object.set", "object.setRTPC"]
        if api == "ak.wwise.core.object.set"
        else [required_operation]
    )
    assert blocked.value.details["required_operations"] == expected_operations


def test_recursive_schema_validation_rejects_nested_range_and_bad_result() -> None:
    with pytest.raises(SemanticValidationError, match="above the reflected maximum"):
        validate_semantic_payload(
            "ak.soundengine.executeActionOnEvent",
            {
                "event": "Event",
                "actionType": 999,
                "gameObject": 1,
                "transitionDuration": 0,
                "fadeCurve": 0,
            },
            {},
            version="2022.1",
        )

    with pytest.raises(SemanticValidationError, match="missing required members"):
        validate_semantic_result(
            "ak.wwise.core.getInfo",
            {},
            version="2022.1",
        )

    with pytest.raises(SemanticValidationError, match="missing required members"):
        validate_semantic_event(
            "ak.wwise.core.object.created",
            {},
            version="2022.1",
        )


@pytest.mark.parametrize(
    ("api", "args", "branch_keyword", "section", "required_policy"),
    (
        (
            "ak.wwise.core.profiler.moveCursor",
            {"position": "bogus"},
            "oneOf",
            "args.position",
            "exactly one",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"filters": [{"type": "bogus", "value": 1}]},
            "anyOf",
            "args.filters[0].type",
            "at least one",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"filters": [{"type": "field", "value": 1, "operator": "bogus"}]},
            "oneOf",
            "args.filters[0].operator",
            "exactly one",
        ),
        (
            "ak.wwise.core.object.move",
            {"object": "source", "parent": "destination", "onNameConflict": "bogus"},
            "oneOf",
            "args.onNameConflict",
            "exactly one",
        ),
    ),
)
def test_recursive_schema_validation_rejects_invalid_alternative_branch_values(
    api: str,
    args: Mapping[str, Any],
    branch_keyword: str,
    section: str,
    required_policy: str,
) -> None:
    with pytest.raises(SemanticValidationError) as caught:
        validate_semantic_payload(api, args, {}, version="2025.1")

    assert caught.value.details["branch_keyword"] == branch_keyword
    assert caught.value.details["section"] == section
    assert caught.value.details["required_policy"] == required_policy
    assert caught.value.details["matched_branch_indexes"] == []
    assert caught.value.details["unresolved_branch_indexes"] == []


@pytest.mark.parametrize(
    ("api", "field"),
    (
        ("ak.wwise.cli.generateSoundbank", "custom-pre-gen-cmd"),
        ("ak.wwise.cli.generateSoundbank", "custom-post-gen-cmd"),
        ("ak.wwise.cli.tabDelimitedImport", "custom-global-opening-cmd"),
    ),
)
def test_generic_transaction_rejects_model_authored_external_commands(
    api: str,
    field: str,
) -> None:
    with pytest.raises(OperationContractError) as caught:
        parse_operation_request(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": "2022.1",
                "operation": "waapi.call",
                "arguments": {
                    "api": api,
                    "args": {field: "python temporary-helper.py"},
                    "options": {},
                    "io_root": "/tmp/waapi-skill-program-probe",
                },
            }
        )

    assert caught.value.error_code == "MODEL_AUTHORED_COMMAND_BLOCKED"
    assert caught.value.details == {"api": api, "fields": [field]}


def test_generic_isolated_transaction_enforces_io_root_at_public_parser(tmp_path: Path) -> None:
    request = {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2025.1",
        "operation": "waapi.call",
        "arguments": {
            "api": "ak.wwise.debug.generateToneWAV",
            "args": {"path": str(tmp_path / "outside" / "tone.wav")},
            "options": {},
        },
    }

    with pytest.raises(OperationContractError) as missing:
        parse_operation_request(request)
    assert missing.value.error_code == "IO_ROOT_REQUIRED"

    request["arguments"]["io_root"] = str(tmp_path / "sandbox")
    with pytest.raises(OperationContractError) as outside:
        parse_operation_request(request)
    assert outside.value.error_code == "IO_PATH_OUTSIDE_ROOT"


def test_generic_non_isolated_transaction_rejects_fake_io_root(tmp_path: Path) -> None:
    with pytest.raises(OperationContractError) as caught:
        parse_operation_request(
            {
                "contract": OPERATION_REQUEST_CONTRACT,
                "version": "2022.1",
                "operation": "waapi.call",
                "arguments": {
                    "api": "ak.wwise.core.project.save",
                    "args": {},
                    "options": {},
                    "io_root": str(tmp_path),
                },
            }
        )

    assert caught.value.error_code == "IO_ROOT_NOT_APPLICABLE"


def test_unresolved_result_ref_is_reported_as_partial_schema_check_not_business_verified() -> None:
    capability = CapabilityCatalog().describe("2022.1", "ak.wwise.core.object.copy")
    args, options, _ = request_and_result_from_schema(capability.schema)
    request = parse_operation_request(
        {
            "contract": OPERATION_REQUEST_CONTRACT,
            "version": "2022.1",
            "operation": "waapi.call",
            "arguments": {
                "api": capability.uri,
                "args": args,
                "options": options,
            },
        }
    )
    prepared = prepare_operation(
        request,
        read_call=lambda uri, call_args, call_options: {},
    )

    verification = verify_prepared_operation(
        prepared.as_dict(),
        execution_result={"ok": True, "result": None},
        read_call=lambda uri, call_args, call_options: {},
    )

    assert verification.ok is True
    assert verification.status == "result_schema_checked"
    assert verification.business_state_verified is False
    assert verification.verification_strength == "partial_reflected_schema"
    evidence = verification.assertions[0]["evidence"]
    assert evidence["unresolved_refs"] == ["#/definitions/objectReturn"]


def test_transaction_default_deadline_preserves_isolated_contract_timeout(tmp_path: Path) -> None:
    env = _env(tmp_path)
    preview_args = waapi_gateway.build_parser().parse_args(
        ["preview", "--request-json", "{}"]
    )
    status_args = waapi_gateway.build_parser().parse_args(["status"])
    explicit_args = waapi_gateway.build_parser().parse_args(
        ["--timeout", "5", "execute", "tx-example"]
    )

    preview_connection = waapi_gateway.resolve_connection(preview_args, env=env)
    status_connection = waapi_gateway.resolve_connection(status_args, env=env)
    explicit_connection = waapi_gateway.resolve_connection(explicit_args, env=env)

    assert preview_connection.timeout == waapi_gateway.DEFAULT_TRANSACTION_TIMEOUT == 150.0
    assert preview_connection.timeout > 120.0
    assert status_connection.timeout == waapi_gateway.DEFAULT_TIMEOUT == 10.0
    assert explicit_connection.timeout == 5.0

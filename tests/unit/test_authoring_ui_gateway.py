from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest  # pyright: ignore[reportMissingImports]
from tests.support.canonical_preview import bind_canonical_preview_fixture

from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    OPERATION_REQUEST_CONTRACT,
)
from wwise_waapi.typed_operations import (  # pyright: ignore[reportMissingImports]
    draft_operation_request_contract,
    inline_operation_contract,
)
from wwise_waapi.typed_requests import (  # pyright: ignore[reportMissingImports]
    TypedRequestFact,
    dynamic_array_item_handle,
    dynamic_container_disclosure,
    dynamic_map_entry_handle,
)
from wwise_waapi.transactions import (  # pyright: ignore[reportMissingImports]
    TransactionState,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_authoring_ui_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)
gateway.execute_gateway = bind_canonical_preview_fixture(gateway)


PROJECT_GUID = "{11111111-1111-1111-1111-111111111111}"
GET_INFO_URI = "ak.wwise.core.getInfo"
GET_PROJECT_INFO_URI = "ak.wwise.core.getProjectInfo"
GET_COMMANDS_URI = "ak.wwise.ui.commands.getCommands"
EXECUTED_TOPIC = "ak.wwise.ui.commands.executed"


class FakeEventHandler:
    def __init__(self) -> None:
        self.unsubscribe_calls = 0

    def unsubscribe(self) -> bool:
        self.unsubscribe_calls += 1
        return True


class FakeClient:
    def __init__(
        self,
        responses: Mapping[str, Sequence[Any]],
        *,
        subscription_events: Mapping[str, Sequence[Any]] | None = None,
    ) -> None:
        self.responses = {
            uri: deque(values) for uri, values in responses.items()
        }
        self.subscription_events = {
            uri: list(values)
            for uri, values in (subscription_events or {}).items()
        }
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.handlers: list[FakeEventHandler] = []
        self.subscribe_calls: list[str] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(
                f"Unexpected or exhausted WAAPI call: {uri} {args!r} {options!r}"
            )
        return values.popleft()

    def subscribe(
        self,
        uri: str,
        callback: Any,
        options: Mapping[str, Any] | None = None,
    ) -> FakeEventHandler:
        del options
        self.subscribe_calls.append(uri)
        handler = FakeEventHandler()
        self.handlers.append(handler)
        for event in self.subscription_events.get(uri, ()):
            callback(event)
        return handler

    def disconnect(self) -> None:
        self.disconnected = True


def live_info(
    *,
    year: int = 2024,
    command_line: bool = False,
    platform: Any = "macosx",
) -> dict[str, Any]:
    return {
        "displayName": "Wwise" if not command_line else "WwiseConsole",
        "isCommandLine": command_line,
        "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "processId": 4242,
        "processPath": "/Applications/Audiokinetic/Wwise.app/Contents/MacOS/Wwise",
        "apiVersion": 1,
        "platform": platform,
        "configuration": "release",
        "version": {
            "year": year,
            "major": 1,
            "minor": 13,
            "build": 9056,
            "displayName": f"v{year}.1.13",
        },
    }


def project(tmp_path: Path) -> dict[str, Any]:
    project_path = tmp_path / "wwise-project" / "SampleProject.wproj"
    return {
        "id": PROJECT_GUID,
        "name": "SampleProject",
        "path": str(project_path),
    }


def gateway_env(
    tmp_path: Path,
    *,
    version: str,
    state_dir: Path | None = None,
) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "wwise_version": None,
                    "waapi_host": "127.0.0.1",
                    "waapi_port": None,
                    "project_modification_policy": "ask_before_changes",
                }
            ),
            encoding="utf-8",
        )
    env = {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": version,
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }
    if state_dir is not None:
        env["WAAPI_SKILL_STATE_DIR"] = str(state_dir)
    return env


def execute(
    argv: Sequence[str],
    *,
    tmp_path: Path,
    version: str,
    state_dir: Path | None = None,
    client: FakeClient | None = None,
) -> tuple[int, dict[str, Any]]:
    args = list(argv)
    if state_dir is not None:
        args = ["--state-dir", str(state_dir), *args]

    def factory(url: str) -> FakeClient:
        if client is None:
            raise AssertionError(f"offline command connected to {url}")
        return client

    return gateway.execute_gateway(
        args,
        env=gateway_env(tmp_path, version=version, state_dir=state_dir),
        client_factory=factory,
    )


def operation_request(
    operation: str,
    arguments: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": version,
        "operation": operation,
        "arguments": dict(arguments),
    }


def notification_descriptor_facts(operation: str) -> tuple[Any, list[TypedRequestFact]]:
    contract = draft_operation_request_contract(operation, "2024.1")
    commands = next(field for field in contract.fields if field.path == ("commands",))
    row = dynamic_array_item_handle(
        contract, array_handle=commands.handle, index=0, shape="object"
    )
    disclosure = dynamic_container_disclosure(
        contract,
        parent_handle=commands.handle,
        key="0",
        shape="object",
        child_handle=row,
    )
    choice = next(
        item["handle"]
        for branch in disclosure["branch_choices"]
        if branch["key"] == "handler"
        for item in branch["choices"]
        if item["constant_fields"] == {"kind": "notification"}
    )
    handler = dynamic_map_entry_handle(
        contract,
        map_handle=row,
        key="handler",
        shape="object",
        choice_handle=choice,
        parent_schema=disclosure["schema_lineage"],
    )
    return contract, [
        TypedRequestFact("append", commands.handle, "object", row),
        TypedRequestFact("map-put", row, "string", "example.notify", key="id"),
        TypedRequestFact("map-put", row, "string", "Notify", key="display_name"),
        TypedRequestFact("choose-dynamic", row, "choice", choice, key="handler"),
        TypedRequestFact("map-put", row, "object", handler, key="handler"),
        TypedRequestFact("map-put", handler, "string", "notification", key="kind"),
    ]


def apply_typed_draft_facts(
    *,
    tmp_path: Path,
    state_dir: Path,
    started: Mapping[str, Any],
    facts: Sequence[TypedRequestFact],
) -> int:
    revision = 1
    for fact in facts:
        argv = [
            "draft-apply",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(revision),
            "--compact",
            "--facts",
            "--action",
            "add_typed_fact",
            "--fact-action",
            fact.action,
            "--field-handle",
            fact.handle,
        ]
        if fact.key is not None:
            argv.extend(["--key", fact.key])
        if fact.action in {"choose", "choose-dynamic"}:
            argv.extend(["--fact-value", fact.value])
        elif fact.action != "present":
            argv.extend(["--value-type", fact.value_type, "--fact-value", fact.value])
        code, payload = execute(
            argv,
            tmp_path=tmp_path,
            version="2024.1",
            state_dir=state_dir,
        )
        assert code == 0, payload
        revision = payload["draft"]["revision"]
    return revision


def test_offline_capability_profile_is_explicit_and_defaults_to_console(
    tmp_path: Path,
) -> None:
    default_code, default_payload = execute(
        ["capabilities", "--all-versions", "--summary-only"],
        tmp_path=tmp_path,
        version="2022.1",
    )
    authoring_code, authoring_payload = execute(
        [
            "capabilities",
            "--all-versions",
            "--profile",
            "wwise-authoring-ui",
            "--summary-only",
        ],
        tmp_path=tmp_path,
        version="2022.1",
    )

    assert default_code == authoring_code == 0
    assert default_payload["profile"] == "wwise-console"
    assert default_payload["summary"]["profile"] == "wwise-console"
    assert default_payload["summary"]["totals"]["total"] == 814
    assert default_payload["summary"]["totals"]["interface_status"] == {
        "available": 268,
        "available_via_transaction": 540,
        "unsupported_by_skill_interface": 6,
    }
    assert authoring_payload["profile"] == "wwise-authoring-ui"
    assert authoring_payload["summary"]["profile"] == "wwise-authoring-ui"
    assert authoring_payload["summary"]["totals"]["total"] == 824
    assert authoring_payload["summary"]["totals"]["interface_status"] == {
        "available": 272,
        "available_via_transaction": 552,
    }
    assert authoring_payload["filters"]["profile"] == "wwise-authoring-ui"


def test_offline_describe_can_inspect_authoring_only_supplement(
    tmp_path: Path,
) -> None:
    default_code, default_payload = execute(
        [
            "describe",
            "ak.wwise.ui.commands.execute",
            "--profile",
            "wwise-console",
        ],
        tmp_path=tmp_path,
        version="2024.1",
    )
    authoring_code, authoring_payload = execute(
        [
            "describe",
            "ak.wwise.ui.commands.execute",
            "--profile",
            "wwise-authoring-ui",
        ],
        tmp_path=tmp_path,
        version="2024.1",
    )

    assert default_code == 2
    assert default_payload["error_code"] == "CapabilityNotFoundError"
    assert authoring_code == 0
    assert authoring_payload["profile"] == "wwise-authoring-ui"
    capability = authoring_payload["availability"]["2024.1"]["capability"]
    assert (
        capability["interface"]["manifest_runtime_profile"]
        == "console-with-authoring-ui-commands"
    )
    assert capability["interface"]["preferred_route"] == "transaction_operation"
    assert capability["interface"]["transaction_operations"] == [
        "ui.commands.execute"
    ]


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_get_commands_uses_authoring_overlay_and_schema(
    tmp_path: Path,
    version: str,
) -> None:
    schema_code, schema = execute(
        ["request-schema", GET_COMMANDS_URI],
        tmp_path=tmp_path,
        version=version,
    )
    assert schema_code == 0, schema
    client = FakeClient(
        {
            GET_INFO_URI: [live_info(year=int(version[:4]))],
            GET_COMMANDS_URI: [{"commands": ["Copy", "SaveProject"]}],
        }
    )
    code, payload = execute(
        [
            "typed-zero-call",
            GET_COMMANDS_URI,
            "--schema-digest",
            schema["schema_digest"],
        ],
        tmp_path=tmp_path,
        version=version,
        client=client,
    )

    assert code == 0, payload
    assert payload["ok"] is True
    assert payload["call"]["api"] == GET_COMMANDS_URI
    assert payload["typed_request"]["schema_digest"] == schema["schema_digest"]
    assert payload["agent_result"] == {"commands": ["Copy", "SaveProject"]}
    assert [row[0] for row in client.calls] == [
        GET_INFO_URI,
        GET_COMMANDS_URI,
    ]


def test_get_commands_console_boundary_dispatches_only_get_info(
    tmp_path: Path,
) -> None:
    schema_code, schema = execute(
        ["request-schema", GET_COMMANDS_URI],
        tmp_path=tmp_path,
        version="2024.1",
    )
    assert schema_code == 0, schema
    client = FakeClient(
        {GET_INFO_URI: [live_info(command_line=True)]}
    )
    code, payload = execute(
        [
            "typed-zero-call", GET_COMMANDS_URI,
            "--schema-digest", schema["schema_digest"],
        ],
        tmp_path=tmp_path,
        version="2024.1",
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert payload["executed"] is False
    assert [row[0] for row in client.calls] == [GET_INFO_URI]


def test_typed_zero_get_commands_is_discoverable_and_host_attested(
    tmp_path: Path,
) -> None:
    version = "2024.1"
    schema_code, schema = execute(
        ["request-schema", GET_COMMANDS_URI],
        tmp_path=tmp_path,
        version=version,
    )
    assert schema_code == 0, schema
    assert schema["input_shape"] == "zero"
    assert schema["continuation"]["subcommand"] == "typed-zero-call"

    console_client = FakeClient({GET_INFO_URI: [live_info(command_line=True)]})
    console_code, console = execute(
        [
            "typed-zero-call", GET_COMMANDS_URI,
            "--schema-digest", schema["schema_digest"],
        ],
        tmp_path=tmp_path,
        version=version,
        client=console_client,
    )
    assert console_code == 2
    assert console["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert [row[0] for row in console_client.calls] == [GET_INFO_URI]

    authoring_client = FakeClient(
        {
            GET_INFO_URI: [live_info(command_line=False)],
            GET_COMMANDS_URI: [{"commands": ["Copy", "SaveProject"]}],
        }
    )
    authoring_code, authoring = execute(
        [
            "typed-zero-call", GET_COMMANDS_URI,
            "--schema-digest", schema["schema_digest"],
        ],
        tmp_path=tmp_path,
        version=version,
        client=authoring_client,
    )
    assert authoring_code == 0, authoring
    assert authoring["agent_result"] == {"commands": ["Copy", "SaveProject"]}
    assert [row[0] for row in authoring_client.calls] == [
        GET_INFO_URI,
        GET_COMMANDS_URI,
    ]


def test_executed_topic_uses_authoring_overlay_and_unsubscribes(
    tmp_path: Path,
) -> None:
    schema_code, schema = execute(
        ["topic-schema", EXECUTED_TOPIC],
        tmp_path=tmp_path,
        version="2024.1",
    )
    assert schema_code == 0, schema
    bind = schema["continuation"]["bind"]
    event = {"command": "SaveProject", "objects": [], "platforms": []}
    client = FakeClient(
        {GET_INFO_URI: [live_info()]},
        subscription_events={EXECUTED_TOPIC: [event]},
    )
    code, payload = execute(
        [
            "--timeout", "5", "wait-topic", EXECUTED_TOPIC,
            "--options-schema-digest", bind["--options-schema-digest"],
            "--match-schema-digest", bind["--match-schema-digest"],
        ],
        tmp_path=tmp_path,
        version="2024.1",
        client=client,
    )

    assert code == 0, payload
    assert payload["event"] == event
    assert payload["event_validation"]["uri"] == EXECUTED_TOPIC
    assert payload["cleanup"] == "unsubscribed"
    assert client.subscribe_calls == [EXECUTED_TOPIC]
    assert client.handlers[0].unsubscribe_calls == 1


def test_executed_topic_console_boundary_never_subscribes(
    tmp_path: Path,
) -> None:
    schema_code, schema = execute(
        ["topic-schema", EXECUTED_TOPIC],
        tmp_path=tmp_path,
        version="2024.1",
    )
    assert schema_code == 0, schema
    bind = schema["continuation"]["bind"]
    client = FakeClient(
        {GET_INFO_URI: [live_info(command_line=True)]}
    )
    code, payload = execute(
        [
            "wait-topic", EXECUTED_TOPIC,
            "--options-schema-digest", bind["--options-schema-digest"],
            "--match-schema-digest", bind["--match-schema-digest"],
        ],
        tmp_path=tmp_path,
        version="2024.1",
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert payload["executed"] is False
    assert client.subscribe_calls == []
    assert [row[0] for row in client.calls] == [GET_INFO_URI]


@pytest.mark.parametrize(
    ("operation", "arguments"),
    (
        ("ui.commands.execute", {"command": "SaveProject"}),
        (
            "ui.commands.register",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
        ),
        (
            "ui.commands.unregister",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
        ),
        (
            "ui.commands.unregister",
            {
                "command_ids": ["example.notify"],
                "acknowledgement": (
                    "unregister_existing_commands_without_definition"
                ),
            },
        ),
    ),
)
def test_console_rejects_all_ui_command_previews_before_project_read(
    tmp_path: Path,
    operation: str,
    arguments: Mapping[str, Any],
) -> None:
    client = FakeClient(
        {GET_INFO_URI: [live_info(command_line=True)]}
    )
    code, payload = execute(
        [
            "legacy-preview",
            "--request-json",
            json.dumps(
                operation_request(
                    operation,
                    arguments,
                    version="2024.1",
                )
            ),
        ],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=tmp_path / "state",
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert payload["operation"] == operation
    assert payload["executed"] is False
    assert [row[0] for row in client.calls] == [GET_INFO_URI]


@pytest.mark.parametrize("operation", ("ui.captureScreen", "ui.commands.execute"))
def test_typed_inline_ui_operations_reject_console_before_project_read(
    tmp_path: Path,
    operation: str,
) -> None:
    contract = inline_operation_contract(operation, "2024.1")
    argv = [
        "typed-operation",
        operation,
        "--schema-digest",
        contract["schema_digest"],
        "--apply",
    ]
    if operation == "ui.commands.execute":
        argv.extend(["--command", "SaveProject"])
    client = FakeClient({GET_INFO_URI: [live_info(command_line=True)]})
    code, payload = execute(
        argv,
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=tmp_path / operation,
        client=client,
    )
    assert code == 2
    assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert [row[0] for row in client.calls] == [GET_INFO_URI]


def test_typed_register_draft_seals_preview_and_fresh_inventory_remains_authoritative(
    tmp_path: Path,
) -> None:
    operation = "ui.commands.register"
    state_dir = tmp_path / "typed-register"
    contract, facts = notification_descriptor_facts(operation)
    code, started = execute(
        ["draft-start", operation],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=state_dir,
    )
    assert code == 0, started
    revision = apply_typed_draft_facts(
        tmp_path=tmp_path,
        state_dir=state_dir,
        started=started,
        facts=facts,
    )
    info = live_info()
    preview_client = FakeClient(
        {
            GET_INFO_URI: [info, info],
            GET_PROJECT_INFO_URI: [project(tmp_path)],
        }
    )
    code, checked = execute(
        [
            "draft-check", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision),
        ],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=state_dir,
        client=preview_client,
    )
    assert code == 0, checked
    assert GET_COMMANDS_URI not in [row[0] for row in preview_client.calls]

    code, preview = execute(
        [
            "preview-from-draft", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(checked["draft"]["revision"]),
            "--apply",
        ],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=state_dir,
        client=FakeClient(
            {
                GET_INFO_URI: [info, info],
                GET_PROJECT_INFO_URI: [project(tmp_path)],
            }
        ),
    )
    assert code == 0, preview
    assert preview["agent_result"]["request"]["arguments"]["commands"][0]["id"] == (
        "example.notify"
    )
    assert preview["state"] == TransactionState.AWAITING_CONFIRMATION.value

    code, _confirmed = execute(
        ["confirm", preview["transaction_id"], "--artifact-hash", preview["artifact_hash"]],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=state_dir,
    )
    assert code == 0
    missing_inventory = FakeClient(
        {
            GET_INFO_URI: [info, info],
            GET_PROJECT_INFO_URI: [project(tmp_path)],
            GET_COMMANDS_URI: [{"commands": ["Copy", "example.notify"]}],
        }
    )
    code, rejected = execute(
        ["execute", preview["transaction_id"]],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=state_dir,
        client=missing_inventory,
    )
    assert code == 2
    assert rejected["executed"] is False
    assert "ak.wwise.ui.commands.register" not in [
        row[0] for row in missing_inventory.calls
    ]


def test_typed_capture_screen_finishes_as_result_schema_only(
    tmp_path: Path,
) -> None:
    version = "2024.1"
    operation = "ui.captureScreen"
    state_dir = tmp_path / "typed-capture"
    contract = inline_operation_contract(operation, version)
    info = live_info()
    code, preview = execute(
        [
            "typed-operation",
            operation,
            "--schema-digest",
            contract["schema_digest"],
            "--apply",
            "--view-name",
            "Project Explorer",
        ],
        tmp_path=tmp_path,
        version=version,
        state_dir=state_dir,
        client=FakeClient(
            {
                GET_INFO_URI: [info],
                GET_PROJECT_INFO_URI: [project(tmp_path)],
            }
        ),
    )
    assert code == 0, preview
    assert preview["state"] == TransactionState.AWAITING_CONFIRMATION.value

    code, confirmed = execute(
        [
            "confirm",
            preview["transaction_id"],
            "--artifact-hash",
            preview["artifact_hash"],
        ],
        tmp_path=tmp_path,
        version=version,
        state_dir=state_dir,
    )
    assert code == 0, confirmed
    encoded = "iVBORw0KGgo="
    code, executed = execute(
        ["execute", preview["transaction_id"]],
        tmp_path=tmp_path,
        version=version,
        state_dir=state_dir,
        client=FakeClient(
            {
                GET_INFO_URI: [info],
                GET_PROJECT_INFO_URI: [project(tmp_path)],
                "ak.wwise.ui.captureScreen": [
                    {"contentType": "image/png", "contentBase64": encoded}
                ],
            }
        ),
    )
    assert code == 0, json.dumps(executed, indent=2)
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value

    verify_client = FakeClient(
        {
            GET_INFO_URI: [info],
            GET_PROJECT_INFO_URI: [project(tmp_path)],
        }
    )
    code, verified = execute(
        ["verify", preview["transaction_id"]],
        tmp_path=tmp_path,
        version=version,
        state_dir=state_dir,
        client=verify_client,
    )
    assert code == 0, verified
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verified["result_schema_checked"] is True
    assert verified["verified"] is False
    assert verified["verification"]["verification_strength"] == "result_schema_only"
    assert verified["verification"]["business_state_verified"] is False
    assert [row[0] for row in verify_client.calls] == [
        GET_INFO_URI,
        GET_PROJECT_INFO_URI,
    ]


@pytest.mark.parametrize("platform", ("linux", None, "windows"))
def test_register_preview_rejects_unmapped_get_info_platform_before_project_read(
    tmp_path: Path,
    platform: Any,
) -> None:
    client = FakeClient(
        {GET_INFO_URI: [live_info(platform=platform)]}
    )
    code, payload = execute(
        [
            "legacy-preview",
            "--request-json",
            json.dumps(
                operation_request(
                    "ui.commands.register",
                    {
                        "commands": [
                            {
                                "id": "example.notify",
                                "display_name": "Notify",
                                "handler": {"kind": "notification"},
                            }
                        ]
                    },
                    version="2024.1",
                )
            ),
        ],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=tmp_path / "state",
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "HOST_PLATFORM_UNAVAILABLE"
    assert [row[0] for row in client.calls] == [GET_INFO_URI]


@pytest.mark.parametrize(
    ("host", "expected"),
    (
        ("127.0.0.1", True),
        ("127.23.45.67", True),
        ("::1", True),
        ("localhost", True),
        ("localhost.localdomain", False),
        ("localhost.example.com", False),
        ("192.0.2.10", False),
        ("wwise-studio", False),
    ),
)
def test_local_filesystem_boundary_accepts_only_explicit_loopback_hosts(
    host: str,
    expected: bool,
) -> None:
    assert gateway.is_loopback_waapi_host(host) is expected


def test_remote_ui_execute_files_fail_before_project_or_file_proof(
    tmp_path: Path,
) -> None:
    client = FakeClient({GET_INFO_URI: [live_info(year=2025)]})
    code, payload = execute(
        [
            "--host",
            "192.0.2.10",
            "legacy-preview",
            "--request-json",
            json.dumps(
                operation_request(
                    "ui.commands.execute",
                    {
                        "command": "ImportFiles",
                        "files": ["/remote-only/input.wav"],
                    },
                    version="2025.1",
                )
            ),
        ],
        tmp_path=tmp_path,
        version="2025.1",
        state_dir=tmp_path / "state",
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["details"]["path_roles"] == ["arguments.files"]
    assert payload["details"]["local_proof_is_remote_host_proof"] is False
    assert payload["executed"] is False
    assert [row[0] for row in client.calls] == [GET_INFO_URI]


def test_confirmed_ui_file_transaction_cannot_switch_to_remote_execute(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    source = tmp_path / "input.wav"
    source.write_bytes(b"RIFF")
    request = operation_request(
        "ui.commands.execute",
        {"command": "ImportFiles", "files": [str(source)]},
        version="2025.1",
    )
    preview_client = FakeClient(
        {
            GET_INFO_URI: [live_info(year=2025)],
            GET_PROJECT_INFO_URI: [project(tmp_path)],
        }
    )
    code, transaction = execute(
        ["legacy-preview", "--request-json", json.dumps(request)],
        tmp_path=tmp_path,
        version="2025.1",
        state_dir=state_dir,
        client=preview_client,
    )
    assert code == 0, transaction
    code, confirmed = execute(
        [
            "confirm",
            transaction["transaction_id"],
            "--artifact-hash",
            transaction["artifact_hash"],
        ],
        tmp_path=tmp_path,
        version="2025.1",
        state_dir=state_dir,
    )
    assert code == 0, confirmed

    remote_client = FakeClient({GET_INFO_URI: [live_info(year=2025)]})
    code, payload = execute(
        [
            "--host",
            "192.0.2.10",
            "execute",
            transaction["transaction_id"],
        ],
        tmp_path=tmp_path,
        version="2025.1",
        state_dir=state_dir,
        client=remote_client,
    )

    assert code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["command"] == "execute"
    assert payload["executed"] is False
    assert [row[0] for row in remote_client.calls] == [GET_INFO_URI]


@pytest.mark.parametrize(
    "operation",
    ("ui.commands.register", "ui.commands.unregister"),
)
def test_remote_ui_program_descriptors_fail_before_project_or_executable_proof(
    tmp_path: Path,
    operation: str,
) -> None:
    client = FakeClient({GET_INFO_URI: [live_info()]})
    code, payload = execute(
        [
            "--host",
            "wwise-studio",
            "legacy-preview",
            "--request-json",
            json.dumps(
                operation_request(
                    operation,
                    {
                        "commands": [
                            {
                                "id": "example.remote",
                                "display_name": "Remote program",
                                "handler": {
                                    "kind": "program",
                                    "program_path": "/remote-only/tool",
                                },
                            }
                        ],
                        "source_authority": "user_supplied_verbatim",
                    },
                    version="2024.1",
                )
            ),
        ],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=tmp_path / "state",
        client=client,
    )

    assert code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["details"]["path_roles"] == [
        "arguments.commands[].handler.program_path"
    ]
    assert [row[0] for row in client.calls] == [GET_INFO_URI]


@pytest.mark.parametrize(
    "operation",
    ("ui.commands.register", "ui.commands.unregister"),
)
def test_confirmed_ui_program_transaction_cannot_switch_to_remote_execute(
    tmp_path: Path,
    operation: str,
) -> None:
    state_dir = tmp_path / operation.replace(".", "-")
    program = tmp_path / "final-tool"
    program.write_bytes(b"final executable")
    program.chmod(0o700)
    request = operation_request(
        operation,
        {
            "commands": [
                {
                    "id": "example.local",
                    "display_name": "Local program",
                    "handler": {
                        "kind": "program",
                        "program_path": str(program),
                    },
                }
            ],
            "source_authority": "user_supplied_verbatim",
        },
        version="2024.1",
    )
    info = live_info()
    preview_client = FakeClient(
        {
            GET_INFO_URI: [info, info],
            GET_PROJECT_INFO_URI: [project(tmp_path)],
        }
    )
    code, transaction = execute(
        ["legacy-preview", "--request-json", json.dumps(request)],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=state_dir,
        client=preview_client,
    )
    assert code == 0, transaction
    code, confirmed = execute(
        [
            "confirm",
            transaction["transaction_id"],
            "--artifact-hash",
            transaction["artifact_hash"],
        ],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=state_dir,
    )
    assert code == 0, confirmed

    remote_client = FakeClient({GET_INFO_URI: [live_info()]})
    code, payload = execute(
        [
            "--host",
            "wwise-studio",
            "execute",
            transaction["transaction_id"],
        ],
        tmp_path=tmp_path,
        version="2024.1",
        state_dir=state_dir,
        client=remote_client,
    )

    assert code == 2
    assert payload["error_code"] == "LOCAL_WAAPI_HOST_REQUIRED"
    assert payload["command"] == "execute"
    assert [row[0] for row in remote_client.calls] == [GET_INFO_URI]


@pytest.mark.parametrize(
    ("operation", "arguments", "pre_commands", "post_commands", "final_state"),
    (
        (
            "ui.commands.execute",
            {"command": "SaveProject"},
            ["SaveProject"],
            None,
            TransactionState.RESULT_SCHEMA_CHECKED.value,
        ),
        (
            "ui.commands.register",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
            ["Copy"],
            ["Copy", "example.notify"],
            TransactionState.VERIFIED.value,
        ),
        (
            "ui.commands.unregister",
            {
                "commands": [
                    {
                        "id": "example.notify",
                        "display_name": "Notify",
                        "handler": {"kind": "notification"},
                    }
                ]
            },
            ["Copy", "example.notify"],
            ["Copy"],
            TransactionState.VERIFIED.value,
        ),
        (
            "ui.commands.unregister",
            {
                "command_ids": ["example.notify"],
                "acknowledgement": (
                    "unregister_existing_commands_without_definition"
                ),
            },
            ["Copy", "example.notify"],
            ["Copy"],
            TransactionState.VERIFIED.value,
        ),
    ),
)
def test_ui_command_transactions_run_full_fake_gateway_chain(
    tmp_path: Path,
    operation: str,
    arguments: Mapping[str, Any],
    pre_commands: Sequence[str],
    post_commands: Sequence[str] | None,
    final_state: str,
) -> None:
    version = "2024.1"
    state_dir = tmp_path / operation.replace(".", "-")
    request = operation_request(operation, arguments, version=version)
    needs_host_platform = operation == "ui.commands.register" or (
        operation == "ui.commands.unregister" and "commands" in arguments
    )
    preview_info = live_info()
    preview_responses: dict[str, Sequence[Any]] = {
        GET_INFO_URI: (
            [preview_info, preview_info]
            if needs_host_platform
            else [preview_info]
        ),
        GET_PROJECT_INFO_URI: [project(tmp_path)],
    }
    preview_client = FakeClient(preview_responses)
    code, preview = execute(
        [
                "legacy-preview",
            "--request-json",
            json.dumps(request),
        ],
        tmp_path=tmp_path,
        version=version,
        state_dir=state_dir,
        client=preview_client,
    )
    assert code == 0, preview
    assert preview["state"] == TransactionState.AWAITING_CONFIRMATION.value

    code, confirmed = execute(
        [
            "confirm",
            preview["transaction_id"],
            "--artifact-hash",
            preview["artifact_hash"],
        ],
        tmp_path=tmp_path,
        version=version,
        state_dir=state_dir,
    )
    assert code == 0, confirmed
    assert confirmed["state"] == TransactionState.CONFIRMED.value

    mutation_uri = {
        "ui.commands.execute": "ak.wwise.ui.commands.execute",
        "ui.commands.register": "ak.wwise.ui.commands.register",
        "ui.commands.unregister": "ak.wwise.ui.commands.unregister",
    }[operation]
    execute_info = live_info()
    execute_responses: dict[str, Sequence[Any]] = {
        GET_INFO_URI: (
            [execute_info, execute_info]
            if needs_host_platform
            else [execute_info]
        ),
        GET_PROJECT_INFO_URI: [project(tmp_path)],
        GET_COMMANDS_URI: [{"commands": list(pre_commands)}],
        mutation_uri: [{}],
    }
    execute_client = FakeClient(execute_responses)
    code, executed = execute(
        ["execute", preview["transaction_id"]],
        tmp_path=tmp_path,
        version=version,
        state_dir=state_dir,
        client=execute_client,
    )
    assert code == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert [row[0] for row in execute_client.calls].count(mutation_uri) == 1
    assert execute_client.calls[-1][0] == mutation_uri

    verify_responses: dict[str, Sequence[Any]] = {
        GET_INFO_URI: [live_info()],
        GET_PROJECT_INFO_URI: [project(tmp_path)],
    }
    if post_commands is not None:
        verify_responses[GET_COMMANDS_URI] = [
            {"commands": list(post_commands)}
        ]
    verify_client = FakeClient(verify_responses)
    code, verified = execute(
        ["verify", preview["transaction_id"]],
        tmp_path=tmp_path,
        version=version,
        state_dir=state_dir,
        client=verify_client,
    )

    assert code == 0, verified
    assert verified["state"] == final_state
    if operation == "ui.commands.execute":
        assert verified["result_schema_checked"] is True
        assert verified["verified"] is False
        assert GET_COMMANDS_URI not in [row[0] for row in verify_client.calls]
    else:
        assert verified["verified"] is True
        assert GET_COMMANDS_URI in [row[0] for row in verify_client.calls]

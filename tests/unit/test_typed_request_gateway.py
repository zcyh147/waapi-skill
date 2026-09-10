from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


INLINE_READ_URI = "ak.wwise.waapi.getSchema"


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_gateway_typed_request_tests",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


class FakeClient:
    def __init__(self, responses: Mapping[str, Any]) -> None:
        self.responses = dict(responses)
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        return self.responses[uri]

    def disconnect(self) -> None:
        pass


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_VERSION": version,
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }


def _live_info(version: str) -> dict[str, Any]:
    year, major = (int(item) for item in version.split("."))
    return {
        "displayName": "Wwise",
        "isCommandLine": False,
        "version": {
            "year": year,
            "major": major,
            "minor": 1,
            "build": 1,
            "displayName": f"v{version}.1",
        },
    }


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS[1:])
def test_request_schema_returns_one_business_continuation_for_schema_read(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["--version", version, "request-schema", INLINE_READ_URI],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )

    assert exit_code == 0, payload
    assert payload["input_shape"] == "business_declaration"
    assert payload["version"] == version
    assert payload["uri"] == INLINE_READ_URI
    assert payload["continuation"]["subcommand"] == "waapi-schema"
    assert payload["business_adapter"]["input_mode"] == "bounded_business_read"
    assert "args-json" not in json.dumps(payload)
    assert "options-json" not in json.dumps(payload)
    assert "fields" not in payload


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS[1:])
def test_waapi_schema_dispatches_without_preview(
    tmp_path: Path,
    version: str,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info(version),
            INLINE_READ_URI: {"argsSchema": {}},
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "waapi-schema",
            "ak.wwise.core.getInfo",
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {"argsSchema": {}}
    assert list(payload)[-1] == "agent_result"
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        (
            INLINE_READ_URI,
            {"uri": "ak.wwise.core.getInfo"},
            {},
        ),
    ]
    assert "transaction_id" not in payload
    assert "authorization" not in payload
    assert "transaction_state" not in payload


@pytest.mark.parametrize("digest", ("stale", "0" * 64))
def test_retired_schema_typed_facts_fail_before_connection(
    tmp_path: Path,
    digest: str,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-call",
            INLINE_READ_URI,
            "--schema-digest",
            digest,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("invalid facts must not connect"),
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert "business" in payload["message"].casefold()


def test_waapi_schema_rejects_configured_live_version_drift(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": _live_info("2024.1")})
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "waapi-schema",
            "ak.wwise.core.getInfo",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: client,
    )

    assert exit_code == 2
    assert "Connected Wwise is 2024.1" in payload["message"]
    assert client.calls == [("ak.wwise.core.getInfo", None, None)]


@pytest.mark.parametrize(
    "version,api,result",
    (
        (
            "2021.1",
            "ak.wwise.core.remote.getConnectionStatus",
            {"isConnected": False, "status": "Disconnected"},
        ),
        ("2024.1", "ak.wwise.core.ping", {"isAvailable": True}),
        ("2025.1", "ak.wwise.core.mediaPool.getFields", {"return": []}),
    ),
)
def test_zero_input_read_discloses_one_short_continuation_and_dispatches_directly(
    tmp_path: Path,
    version: str,
    api: str,
    result: Mapping[str, Any],
) -> None:
    exit_code, contract = waapi_gateway.execute_gateway(
        ["request-schema", api],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )
    assert exit_code == 0
    assert contract["input_shape"] == "zero"
    assert contract["fields"] == []
    assert contract["continuation"] == {
        "subcommand": "typed-zero-call",
        "uri": api,
        "schema_digest": contract["schema_digest"],
        "gateway_argv": [
            "typed-zero-call",
            api,
            "--schema-digest",
            contract["schema_digest"],
        ],
        "business_values_required": False,
    }
    assert "args" not in json.dumps(contract["continuation"])
    assert "options" not in json.dumps(contract["continuation"])

    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info(version),
            api: result,
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-zero-call", api,
            "--schema-digest", contract["schema_digest"],
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: client,
    )
    assert exit_code == 0, payload
    assert payload["typed_request"]["business_values_required"] is False
    assert payload["agent_result"] == result
    assert list(payload)[-1] == "agent_result"
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        (api, {}, {}),
    ]
    assert "transaction_id" not in payload


def test_get_info_request_schema_discloses_only_status_fixed_route(
    tmp_path: Path,
) -> None:
    exit_code, contract = waapi_gateway.execute_gateway(
        ["request-schema", "ak.wwise.core.getInfo"],
        env=_env(tmp_path, "2021.1"),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )

    assert exit_code == 0
    assert contract["input_shape"] == "fixed_business_command"
    assert contract["native_request_fields_disclosed"] is False
    assert contract["continuation"] == {
        "subcommand": "status",
        "arguments": [],
        "business_values_required": False,
    }


def test_zero_input_mutation_cannot_bypass_preview_before_connection(
    tmp_path: Path,
) -> None:
    api = "ak.wwise.core.profiler.startCapture"
    exit_code, contract = waapi_gateway.execute_gateway(
        ["request-schema", api],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )
    assert exit_code == 0
    assert contract["input_shape"] == "zero"

    assert contract["continuation"] == {
        "subcommand": "typed-zero-call",
        "uri": api,
        "schema_digest": contract["schema_digest"],
        "gateway_argv": [
            "typed-zero-call",
            api,
            "--schema-digest",
            contract["schema_digest"],
            "--apply",
        ],
        "business_values_required": False,
        "apply": True,
    }
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-zero-call", api,
            "--schema-digest", contract["schema_digest"],
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("mutation must fail before transport"),
    )
    assert exit_code == 2
    assert "requires --apply" in payload["message"]


def test_zero_input_reflection_read_preserves_bounded_inventory_projection(
    tmp_path: Path,
) -> None:
    version = "2022.1"
    api = "ak.wwise.waapi.getFunctions"
    exit_code, contract = waapi_gateway.execute_gateway(
        ["request-schema", api],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )
    assert exit_code == 0

    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info(version),
            api: {"functions": [api, "ak.wwise.core.getInfo"]},
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-zero-call",
            api,
            "--schema-digest",
            contract["schema_digest"],
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0, payload
    assert payload["inventory"]["kind"] == "function"
    assert payload["inventory"]["uris"] == [
        "ak.wwise.core.getInfo",
        api,
    ]
    assert payload["agent_result"] == payload["inventory"]
    assert list(payload)[-1] == "agent_result"


def test_zero_input_call_rejects_stale_digest_before_connection(tmp_path: Path) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-zero-call", "ak.wwise.core.ping",
            "--schema-digest", "0" * 64,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("stale input must remain offline"),
    )
    assert exit_code == 2
    assert payload["ok"] is False


def test_unmigrated_nonzero_function_does_not_disclose_a_broken_continuation(
    tmp_path: Path,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["request-schema", "ak.wwise.core.object.setName"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("boundary must remain offline"),
    )
    assert exit_code == 2
    assert "has not migrated to an executable typed adapter" in payload["message"]
    assert "continuation" not in payload


def test_soundengine_business_mutation_blocks_typed_bypass_before_connection(
    tmp_path: Path,
) -> None:
    api = "ak.soundengine.postMsgMonitor"
    version = "2021.1"
    exit_code, schema = waapi_gateway.execute_gateway(
        ["request-schema", api],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )
    assert exit_code == 0, schema
    assert schema["input_shape"] == "business_declaration"
    assert schema["continuation"]["subcommand"] == "draft-start"
    assert "fields" not in schema

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-call", api,
            "--schema-digest", "0" * 64,
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("mutation boundary must remain offline"),
    )
    assert exit_code == 2
    assert "closed Core business" in payload["message"]


def test_migrated_soundengine_read_rejects_retired_typed_optional_array(
    tmp_path: Path,
) -> None:
    version = "2025.1"
    api = "ak.soundengine.getState"
    exit_code, schema = waapi_gateway.execute_gateway(
        ["request-schema", api],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("schema must remain offline"),
    )
    assert exit_code == 0, schema
    assert schema["input_shape"] == "business_declaration"
    assert schema["continuation"]["subcommand"] == "core-call"

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-call", api,
            "--schema-digest", "0" * 64,
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("retired typed read must stay offline"),
    )
    assert exit_code == 2, payload
    assert "closed Core business" in payload["message"]


@pytest.mark.parametrize(
    "api,commands",
    (
        ("ak.wwise.core.getInfo", ["status"]),
        (
            "ak.wwise.core.object.getTypes",
            ["metadata types", "metadata discover"],
        ),
        ("ak.wwise.debug.getWalTree", ["debug-wal-tree"]),
    ),
)
def test_zero_input_fixed_route_discloses_only_its_existing_command(
    tmp_path: Path,
    api: str,
    commands: list[str],
) -> None:
    version = "2023.1"
    exit_code, contract = waapi_gateway.execute_gateway(
        ["request-schema", api],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )
    assert exit_code == 0, contract
    assert contract["input_shape"] == "fixed_business_command"
    assert contract["native_request_fields_disclosed"] is False
    expected_commands = [
        {
            "subcommand": command.split()[0],
            "arguments": command.split()[1:],
            "business_values_required": command not in {
                "status",
                "metadata types",
                "debug-wal-tree",
            },
        }
        for command in commands
    ]
    if len(expected_commands) == 1:
        assert contract["continuation"] == {
            **expected_commands[0],
        }
    else:
        assert contract["continuation"] == {
            "choose_by_business_intent": expected_commands,
            "business_values_required": "depends_on_command",
        }
    assert "typed-zero-call" not in json.dumps(contract)


@pytest.mark.parametrize(
    ("version", "api", "command"),
    (
        ("2025.1", "ak.wwise.core.object.get", "query-object"),
        (
            "2025.1",
            "ak.wwise.core.profiler.getVoiceContributions",
            "profiler-voice-contributions",
        ),
        ("2025.1", "ak.wwise.debug.validateCall", "debug-validate-call"),
    ),
)
def test_parameterized_fixed_routes_disclose_no_typed_request_escape(
    tmp_path: Path,
    version: str,
    api: str,
    command: str,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["request-schema", api],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("fixed route discovery is offline"),
    )

    assert exit_code == 0, payload
    assert payload["input_shape"] == "fixed_business_command"
    assert payload["native_request_fields_disclosed"] is False
    assert command in json.dumps(payload["commands"])
    assert "schema_digest" not in payload
    assert "fields" not in payload
    assert "typed-call" not in json.dumps(payload)

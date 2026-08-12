from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

from wwise_waapi.builders.stable_reads import GET_VOICE_CONTRIBUTIONS_URI
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


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


def _request_contract(tmp_path: Path, version: str = "2025.1") -> dict[str, Any]:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["--version", version, "request-schema", GET_VOICE_CONTRIBUTIONS_URI],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )
    assert exit_code == 0
    return payload


def _field_handles(payload: Mapping[str, Any]) -> dict[str, str]:
    return {str(field["name"]): str(field["handle"]) for field in payload["fields"]}


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_request_schema_returns_one_typed_continuation_for_tracer(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["--version", version, "request-schema", GET_VOICE_CONTRIBUTIONS_URI],
        env=_env(tmp_path, version),
        client_factory=lambda _url: pytest.fail("discovery must remain offline"),
    )

    assert exit_code == 0
    assert payload["input_shape"] == "inline"
    assert payload["version"] == version
    assert payload["uri"] == GET_VOICE_CONTRIBUTIONS_URI
    assert payload["continuation"]["subcommand"] == "typed-call"
    assert payload["continuation"]["schema_digest"] == payload["schema_digest"]
    assert "args-json" not in json.dumps(payload)
    assert "options-json" not in json.dumps(payload)
    assert {field["name"] for field in payload["fields"]} == {
        "time",
        "voicePipelineID",
        "bussesPipelineID",
    }
    assert all(str(field["handle"]).startswith("trh1-") for field in payload["fields"])


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_typed_call_materializes_and_dispatches_without_preview(
    tmp_path: Path,
    version: str,
) -> None:
    contract = _request_contract(tmp_path, version)
    handles = _field_handles(contract)
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info(version),
            GET_VOICE_CONTRIBUTIONS_URI: {
                "return": {
                    "volume": -3.0,
                    "LPF": 2.0,
                    "HPF": 1.0,
                    "objects": [],
                    **({"DSF": -0.5} if version == "2025.1" else {}),
                }
            },
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-call",
            GET_VOICE_CONTRIBUTIONS_URI,
            "--schema-digest",
            contract["schema_digest"],
            "--set",
            handles["time"],
            "integer",
            "1200",
            "--set",
            handles["voicePipelineID"],
            "integer",
            "17",
            "--append",
            handles["bussesPipelineID"],
            "integer",
            "21",
            "--append",
            handles["bussesPipelineID"],
            "integer",
            "22",
        ],
        env=_env(tmp_path, version),
        client_factory=lambda _url: client,
    )

    assert exit_code == 0
    assert payload["agent_result"]["dsf"] == (
        {"feature_available": True, "reported": True, "value": -0.5}
        if version == "2025.1"
        else {"feature_available": False, "reported": False, "value": None}
    )
    assert list(payload)[-1] == "agent_result"
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        (
            GET_VOICE_CONTRIBUTIONS_URI,
            {
                "voicePipelineID": 17,
                "bussesPipelineID": [21, 22],
                "time": 1200,
            },
            {},
        ),
    ]
    assert "transaction_id" not in payload
    assert "authorization" not in payload
    assert "transaction_state" not in payload


@pytest.mark.parametrize("case", ("missing", "unknown", "wrong_type", "stale_digest"))
def test_invalid_typed_facts_fail_before_connection(
    tmp_path: Path,
    case: str,
) -> None:
    contract = _request_contract(tmp_path)
    handles = _field_handles(contract)
    facts = [
        "--set",
        handles["time"],
        "integer",
        "1200",
    ]
    if case != "missing":
        facts.extend(
            [
                "--set",
                "trh1-not-a-packaged-handle" if case == "unknown" else handles["voicePipelineID"],
                "string" if case == "wrong_type" else "integer",
                "17",
            ]
        )
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-call",
            GET_VOICE_CONTRIBUTIONS_URI,
            "--schema-digest",
            "0" * 64 if case == "stale_digest" else contract["schema_digest"],
            *facts,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: pytest.fail("invalid facts must not connect"),
    )

    assert exit_code == 2
    assert payload["ok"] is False


def test_typed_call_rejects_configured_live_version_drift(tmp_path: Path) -> None:
    contract = _request_contract(tmp_path)
    handles = _field_handles(contract)
    client = FakeClient({"ak.wwise.core.getInfo": _live_info("2024.1")})
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "typed-call",
            GET_VOICE_CONTRIBUTIONS_URI,
            "--schema-digest",
            contract["schema_digest"],
            "--set",
            handles["time"],
            "string",
            "capture",
            "--set",
            handles["voicePipelineID"],
            "integer",
            "17",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: client,
    )

    assert exit_code == 2
    assert "Connected Wwise is 2024.1" in payload["message"]
    assert client.calls == [("ak.wwise.core.getInfo", None, None)]

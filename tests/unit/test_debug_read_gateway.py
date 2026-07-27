from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_gateway_debug_read_tests",
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
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        return self.responses[uri]

    def disconnect(self) -> None:
        self.disconnected = True


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


def _gateway_env(tmp_path: Path, version: str) -> dict[str, str]:
    config_path = tmp_path / "config.json"
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
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": version,
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }


def test_debug_wal_tree_dispatches_one_closed_bounded_request(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            "ak.wwise.debug.getWalTree": {
                "return": {
                    "nodes": {
                        "z": {"id": 3, "name": "Z", "type": "Sound"},
                        "a": {"id": 1, "name": "A", "type": "Bus"},
                    }
                }
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["debug-wal-tree", "--take", "1"],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["agent_result"] == {
        "nodes": [{"key": "a", "id": 1, "name": "A", "type": "Bus"}],
        "returned_count": 1,
        "total_count": 2,
        "possibly_truncated": True,
        "take": 1,
    }
    assert list(payload)[-1] == "agent_result"
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        ("ak.wwise.debug.getWalTree", {}, {}),
    ]
    assert client.disconnected is True


def test_debug_validate_call_sends_only_user_supplied_validation_sections(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            "ak.wwise.debug.validateCall": {},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "debug-validate-call",
            "ak.wwise.core.getInfo",
            "--args-json",
            "{}",
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["agent_result"] == {
        "validated_api": "ak.wwise.core.getInfo",
        "supplied_sections": ["args"],
        "accepted_by_wwise": True,
    }
    assert list(payload)[-1] == "agent_result"
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        (
            "ak.wwise.debug.validateCall",
            {"id": "ak.wwise.core.getInfo", "args": {}},
            {},
        ),
    ]


def test_debug_validate_call_fails_closed_when_absent_in_the_version(
    tmp_path: Path,
) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": _live_info("2023.1")})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["debug-validate-call", "ak.wwise.core.getInfo"],
        env=_gateway_env(tmp_path, "2023.1"),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["status"] == "unsupported_by_skill_interface"
    assert payload["api"] == "ak.wwise.debug.validateCall"
    assert client.calls == [("ak.wwise.core.getInfo", None, None)]
    assert client.disconnected is True

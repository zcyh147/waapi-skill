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
        ["debug-wal-tree", "--max-nodes", "1"],
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


def test_debug_parser_exposes_only_business_boundaries() -> None:
    parser = waapi_gateway.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if "debug-wal-tree" in (getattr(action, "choices", None) or {})
    )
    wal = subparsers.choices["debug-wal-tree"]
    validate = subparsers.choices["debug-validate-call"]
    wal_options = {
        option for action in wal._actions for option in action.option_strings
    }
    validate_options = {
        option for action in validate._actions for option in action.option_strings
    }

    assert "--max-nodes" in wal_options
    assert "--take" not in wal_options
    assert "--artifact-file" in validate_options
    assert not {
        "--schema-digest",
        "--set",
        "--map-put",
        "--args-json",
        "--options-json",
        "--result-json",
    } & validate_options


def test_debug_validate_call_validates_target_without_executing_it(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            "ak.wwise.debug.validateCall": {},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["debug-validate-call", "ak.wwise.core.getProjectInfo"],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {
        "validated_api": "ak.wwise.core.getProjectInfo",
        "supplied_sections": [],
        "accepted_by_wwise": True,
    }
    assert client.calls == [
        ("ak.wwise.core.getInfo", None, None),
        (
            "ak.wwise.debug.validateCall",
            {"id": "ak.wwise.core.getProjectInfo"},
            {},
        ),
    ]


def test_debug_validate_call_preserves_user_owned_exact_artifact(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "call.json"
    artifact.write_text(
        json.dumps(
            {
                "args": {"from": {"id": ["{11111111-1111-1111-1111-111111111111}"]}},
                "options": {"return": ["id", "name"]},
                "result": {"return": []},
            }
        ),
        encoding="utf-8",
    )
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": _live_info("2025.1"),
            "ak.wwise.debug.validateCall": {},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "debug-validate-call",
            "ak.wwise.core.object.get",
            "--artifact-file",
            str(artifact),
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["artifact"]["authority"] == "user_owned_exact_artifact"
    assert payload["agent_result"]["supplied_sections"] == [
        "args",
        "options",
        "result",
    ]
    assert client.calls[-1] == (
        "ak.wwise.debug.validateCall",
        {
            "id": "ak.wwise.core.object.get",
            "args": {"from": {"id": ["{11111111-1111-1111-1111-111111111111}"]}},
            "options": {"return": ["id", "name"]},
            "result": {"return": []},
        },
        {},
    )


def test_debug_validate_call_rejects_non_object_artifact_before_connect(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "call.json"
    artifact.write_text('{"args": []}', encoding="utf-8")
    connected = False

    def factory(url: str) -> FakeClient:
        nonlocal connected
        connected = True
        raise AssertionError("invalid exact artifact must fail before connect")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "debug-validate-call",
            "ak.wwise.core.object.get",
            "--artifact-file",
            str(artifact),
        ],
        env=_gateway_env(tmp_path, "2025.1"),
        client_factory=factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert connected is False

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
SCRIPT_PATH = SKILL_ROOT / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_gateway_session_context_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


PROJECT_GUID = "{11111111-1111-1111-1111-111111111111}"
POLICIES = ["never", "preview_then_confirm", "allow_with_notice"]


class FakeClient:
    def __init__(self, responses: Mapping[str, Any]) -> None:
        self.responses = dict(responses)
        self.calls: list[str] = []

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append(uri)
        return self.responses[uri]

    def disconnect(self) -> None:
        return None


def configured_env(
    tmp_path: Path,
    *,
    version: str | None = "2022.1",
    host: str = "127.0.0.1",
    port: int | None = 8080,
    policy: str = "preview_then_confirm",
) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "waapi_host": host,
                "waapi_port": port,
                "project_modification_policy": policy,
            }
        ),
        encoding="utf-8",
    )
    return {"WAAPI_SKILL_CONFIG_PATH": str(config_path)}


def expected_context(
    *,
    version: str = "2022.1",
    host: str = "127.0.0.1",
    port: int = 8080,
    policy: str = "preview_then_confirm",
    source: str = "configured",
    available: bool = True,
) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.session-context/v1",
        "available": available,
        "endpoint": {
            "host": host,
            "port": port,
            "url": f"ws://{host}:{port}/waapi",
        },
        "adapter_version": version,
        "adapter_version_source": source,
        "project_modification_policy": policy,
        "available_project_modification_policies": POLICIES,
    }


def test_offline_command_returns_session_context_without_opening_waapi(tmp_path: Path) -> None:
    called = False

    def fail_if_connected(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(url)

    exit_code, payload = waapi_gateway.execute_gateway(
        ["describe", "ak.soundengine.getState", "--all-versions"],
        env=configured_env(tmp_path),
        client_factory=fail_if_connected,
    )

    assert exit_code == 0
    assert called is False
    assert payload["session_context"] == expected_context()


def test_single_version_offline_command_reports_its_resolved_adapter_version(tmp_path: Path) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["describe", "ak.soundengine.getState"],
        env=configured_env(tmp_path, version=None),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["versions"] == ["2022.1"]
    assert payload["session_context"] == expected_context(
        source="command_resolution",
    )


def test_incomplete_config_marks_session_context_unavailable_without_guessing(tmp_path: Path) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["config-show"],
        env=configured_env(tmp_path, version=None, port=None),
    )

    assert exit_code == 0
    assert payload["session_context"] == {
        "contract": "waapi-skill.session-context/v1",
        "available": False,
        "endpoint": {"host": "127.0.0.1", "port": None, "url": None},
        "adapter_version": None,
        "adapter_version_source": "unavailable",
        "project_modification_policy": "preview_then_confirm",
        "available_project_modification_policies": POLICIES,
    }


def test_live_result_uses_the_actual_endpoint_and_detected_adapter_version(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": {
                "displayName": "Wwise",
                "isCommandLine": False,
                "version": {
                    "year": 2023,
                    "major": 1,
                    "minor": 5,
                    "build": 1,
                    "displayName": "v2023.1.5",
                },
            },
            "ak.wwise.core.getProjectInfo": {
                "id": PROJECT_GUID,
                "name": "SampleProject",
                "type": "Project",
                "path": "/tmp/SampleProject.wproj",
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=configured_env(tmp_path, version="2023.1", host="localhost", port=31337),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["session_context"] == expected_context(
        version="2023.1",
        host="localhost",
        port=31337,
        source="live_detection",
    )
    assert client.calls == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]


def test_connection_failure_keeps_configured_session_context_and_does_not_retry(tmp_path: Path) -> None:
    factory_calls: list[str] = []

    def unavailable(url: str) -> FakeClient:
        factory_calls.append(url)
        raise ConnectionRefusedError("offline")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["selected"],
        env=configured_env(tmp_path),
        client_factory=unavailable,
    )

    assert exit_code == 2
    assert payload["session_context"] == expected_context()
    assert factory_calls == ["ws://127.0.0.1:8080/waapi"]


def test_post_detection_failure_keeps_live_endpoint_and_adapter_version(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": {
                "displayName": "Wwise",
                "isCommandLine": False,
                "version": {
                    "year": 2023,
                    "major": 1,
                    "minor": 5,
                    "build": 1,
                    "displayName": "v2023.1.5",
                },
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["selected"],
        env=configured_env(tmp_path, version=None, host="localhost", port=31337),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["endpoint"] == {
        "host": "localhost",
        "port": 31337,
        "url": "ws://localhost:31337/waapi",
    }
    assert payload["detected_version"] == "2023.1"
    assert payload["session_context"] == expected_context(
        version="2023.1",
        host="localhost",
        port=31337,
        source="live_detection",
    )
    assert client.calls == [
        "ak.wwise.core.getInfo",
        "ak.wwise.ui.getSelectedObjects",
    ]


def test_explicit_gateway_flags_override_saved_session_context_without_connecting(tmp_path: Path) -> None:
    called = False

    def fail_if_connected(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(url)

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "--host",
            "localhost",
            "--port",
            "31337",
            "--version",
            "2024.1",
            "call",
            "ak.wwise.core.object.get",
        ],
        env=configured_env(tmp_path),
        client_factory=fail_if_connected,
    )

    assert exit_code == 2
    assert called is False
    assert payload["error_code"] == "QUERY_OBJECT_REQUIRED"
    assert payload["session_context"] == expected_context(
        version="2024.1",
        host="localhost",
        port=31337,
    )


def test_config_set_session_context_reflects_the_new_saved_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "config-set",
            "--wwise-version",
            "2025.1",
            "--waapi-host",
            "localhost",
            "--waapi-port",
            "32025",
            "--project-modification-policy",
            "allow_with_notice",
        ],
        env={"WAAPI_SKILL_CONFIG_PATH": str(config_path)},
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["session_context"] == expected_context(
        version="2025.1",
        host="localhost",
        port=32025,
        policy="allow_with_notice",
    )


def test_invalid_config_error_has_bounded_unavailable_session_context(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"project_modification_policy":"invalid"}', encoding="utf-8")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["config-show"],
        env={"WAAPI_SKILL_CONFIG_PATH": str(config_path)},
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert payload["session_context"] == {
        "contract": "waapi-skill.session-context/v1",
        "available": False,
        "endpoint": {"host": None, "port": None, "url": None},
        "adapter_version": None,
        "adapter_version_source": "unavailable",
        "project_modification_policy": None,
        "available_project_modification_policies": POLICIES,
    }


def test_result_ceiling_replacement_preserves_session_context() -> None:
    context = expected_context()
    exit_code, payload = waapi_gateway.constrain_live_gateway_result(
        0,
        {
            "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "selected",
            "session_context": context,
            "oversized": "x" * waapi_gateway.MAX_GATEWAY_RESULT_JSON_BYTES,
        },
    )

    assert exit_code == 2
    assert payload["error_code"] == "RESULT_TOO_LARGE"
    assert payload["session_context"] == context
    assert waapi_gateway.probe_gateway_json_document_size(
        payload,
        waapi_gateway.MAX_GATEWAY_RESULT_JSON_BYTES,
    ) == "ok"


def test_skill_contract_requests_one_natural_notice_without_an_extra_command() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    setup = (SKILL_ROOT / "references" / "waapi-setup.md").read_text(encoding="utf-8")

    for phrase in (
        "The first time this Skill is used in a conversation",
        "`waapi-skill` is loaded",
        "current WAAPI address",
        "WAAPI adapter version",
        "current project modification policy",
        "若有需要，可按需切换模式",
        "ordinary prose, not a status bar, table, field list, or rigid template",
        "Use the first gateway command already required by the user's task",
        "An offline task stays offline",
        "visible conversation does not already contain this introduction",
        "do not use memory to make that decision",
    ):
        assert phrase in skill
    assert "run exactly one offline `config-show` to obtain the introduction facts" in skill
    assert "never run `status` or open a live WAAPI connection only for the introduction" in skill
    assert "Do not add policy or implementation narration to a simple read-only result" not in setup

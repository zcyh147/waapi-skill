from __future__ import annotations

import importlib.util
import json
import shlex
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

import wwise_waapi.dispatcher as dispatcher_module
from wwise_waapi.safety import EXPLICIT_UNSUPPORTED_TOPIC_URIS, IMMEDIATE_UNSUPPORTED_CALL_URIS
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS, version_key_from_get_info


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_gateway_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


PROJECT_GUID = "{11111111-1111-1111-1111-111111111111}"
CAPABILITY_COMPACT_KEYS = {
    "version",
    "uri",
    "item_type",
    "category",
    "risk",
    "schema_status",
    "interface_status",
    "preferred_route",
    "gateway_commands",
    "transaction_operations",
    "transaction_boundaries",
    "read_only",
    "execution_contract",
}
EXPECTED_EXCLUDED_FUNCTION_URIS = frozenset(
    {
        "ak.wwise.cli.executeLuaScript",
        "ak.wwise.core.executeLuaScript",
        "ak.wwise.debug.enableAsserts",
        "ak.wwise.debug.enableAutomationMode",
        "ak.wwise.debug.getWalTree",
        "ak.wwise.debug.restartWaapiServers",
        "ak.wwise.debug.testAssert",
        "ak.wwise.debug.testCrash",
        "ak.wwise.debug.validateCall",
        "ak.wwise.ui.commands.register",
        "ak.wwise.ui.commands.execute",
    }
)
EXPECTED_EXCLUDED_TOPIC_URIS = frozenset({"ak.wwise.debug.assertFailed"})


class FakeEventHandler:
    def __init__(self) -> None:
        self.unsubscribe_calls = 0
        self.subscribe_thread_ident = threading.get_ident()
        self.unsubscribe_thread_ident: int | None = None

    def unsubscribe(self) -> bool:
        self.unsubscribe_calls += 1
        self.unsubscribe_thread_ident = threading.get_ident()
        return True


class FakeClient:
    def __init__(
        self,
        responses: Mapping[str, Any],
        errors: Mapping[str, Exception] | None = None,
        subscription_events: Mapping[str, list[Any]] | None = None,
    ) -> None:
        self.responses = dict(responses)
        self.errors = dict(errors or {})
        self.subscription_events = {key: list(value) for key, value in (subscription_events or {}).items()}
        self.calls: list[tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]] = []
        self.handlers: list[FakeEventHandler] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        if uri in self.errors:
            raise self.errors[uri]
        return self.responses[uri]

    def disconnect(self) -> None:
        self.disconnected = True

    def subscribe(self, uri: str, callback: Any, options: Mapping[str, Any] | None = None) -> FakeEventHandler:
        handler = FakeEventHandler()
        self.handlers.append(handler)
        for event in self.subscription_events.get(uri, []):
            callback(event)
        return handler


class WaapiRequestFailed(Exception):
    def __init__(self, uri: str, kwargs: Mapping[str, Any] | None = None) -> None:
        super().__init__("untrusted rendered application error")
        self.uri = uri
        self.kwargs = kwargs


def live_info(*, year: int = 2022, major: int = 1, command_line: bool = True) -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": command_line,
        "version": {"year": year, "major": major, "minor": 19, "build": 8584, "displayName": "v2022.1.19"},
    }


def gateway_env(tmp_path: Path) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "wwise_version": None,
                    "waapi_host": "127.0.0.1",
                    "waapi_port": None,
                    "project_modification_policy": "preview_then_confirm",
                }
            ),
            encoding="utf-8",
        )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": "2022.1",
        "WWISE_EVIDENCE_DIR": str(tmp_path / "evidence"),
    }


def test_status_uses_live_detection_and_dispatcher_evidence(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.getProjectInfo": {
                "id": PROJECT_GUID,
                "name": "SampleProject",
                "path": r"Y:\sandbox\SampleProject.wproj",
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["endpoint"]["port"] == 31337
    assert payload["detected_version"] == "2022.1"
    assert payload["project"]["name"] == "SampleProject"
    assert all("result" not in call for call in payload["calls"])
    assert payload["wwise"] == {
        "displayName": "Wwise",
        "isCommandLine": True,
        "version": {"year": 2022, "major": 1, "minor": 19, "build": 8584, "displayName": "v2022.1.19"},
    }
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    ]
    evidence = sorted((tmp_path / "evidence").glob("*.json"))
    assert len(evidence) == 2
    assert {json.loads(path.read_text())["api"] for path in evidence} == {
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
    }
    assert client.disconnected is True


def test_gateway_outer_exception_normalization_contains_broken_string_hook(tmp_path: Path) -> None:
    class BrokenStringError(RuntimeError):
        def __str__(self) -> str:
            raise RuntimeError("broken __str__ must not escape")

    client = FakeClient(
        {},
        errors={"ak.wwise.core.getInfo": BrokenStringError()},
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "ERROR_NORMALIZATION_FAILED"
    assert payload["message"] == "The underlying error could not be normalized safely"
    assert len(json.dumps(payload).encode("utf-8")) < 1024


def test_gateway_outer_exception_normalization_contains_broken_as_dict_hook(tmp_path: Path) -> None:
    class BrokenStructuredError(RuntimeError):
        error_code = "HOSTILE_STRUCTURED_ERROR"

        def as_dict(self) -> dict[str, Any]:
            raise RuntimeError("broken as_dict must not escape")

    client = FakeClient(
        {},
        errors={"ak.wwise.core.getInfo": BrokenStructuredError("safe primary message")},
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "HOSTILE_STRUCTURED_ERROR"
    assert payload["message"] == "safe primary message"
    assert payload["details"] is None
    assert len(json.dumps(payload).encode("utf-8")) < 1024


def test_status_uses_project_object_query_for_2021_1(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2021, major=1),
            "ak.wwise.core.object.get": {
                "return": [{"id": PROJECT_GUID, "name": "SampleProject", "type": "Project", "path": "\\"}]
            },
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2021.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["project"] == {"id": PROJECT_GUID, "name": "SampleProject", "type": "Project", "path": "\\"}
    assert all("result" not in call for call in payload["calls"])
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getInfo",
        "ak.wwise.core.object.get",
    ]
    assert client.calls[-1][1:] == (
        {"waql": "from type Project take 1"},
        {"return": ["id", "name", "type", "path"]},
    )
    evidence = sorted((tmp_path / "evidence").glob("*.json"))
    assert {json.loads(path.read_text())["api"] for path in evidence} == {
        "ak.wwise.core.getInfo",
        "ak.wwise.core.object.get",
    }


@pytest.mark.parametrize(
    "project_result",
    (
        None,
        [],
        {},
        {"id": PROJECT_GUID, "name": "P"},
        {"id": "{project}", "name": "SampleProject", "path": r"Y:\sandbox\SampleProject.wproj"},
    ),
)
def test_status_rejects_malformed_or_identity_free_modern_project_result(
    tmp_path: Path,
    project_result: object,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.getProjectInfo": project_result,
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_STATUS_RESULT"


def test_status_rejects_malformed_second_get_info_result(tmp_path: Path) -> None:
    class MalformedSecondInfoClient(FakeClient):
        def __init__(self) -> None:
            super().__init__({})
            self.get_info_count = 0

        def call(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
        ) -> Any:
            self.calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                self.get_info_count += 1
                return live_info() if self.get_info_count == 1 else {}
            if uri == "ak.wwise.core.getProjectInfo":
                return {"id": PROJECT_GUID, "name": "SampleProject", "path": r"Y:\sandbox\SampleProject.wproj"}
            raise AssertionError(uri)

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: MalformedSecondInfoClient(),
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_STATUS_RESULT"
    assert payload["details"]["invalid_fields"] == ["displayName", "isCommandLine", "version"]


def test_status_rejects_second_get_info_version_drift(tmp_path: Path) -> None:
    class DriftedSecondInfoClient(FakeClient):
        def __init__(self) -> None:
            super().__init__({})
            self.get_info_count = 0

        def call(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
        ) -> Any:
            self.calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                self.get_info_count += 1
                return live_info() if self.get_info_count == 1 else live_info(year=2023, major=1)
            if uri == "ak.wwise.core.getProjectInfo":
                return {"id": PROJECT_GUID, "name": "SampleProject", "path": r"Y:\sandbox\SampleProject.wproj"}
            raise AssertionError(uri)

    client = DriftedSecondInfoClient()
    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_STATUS_RESULT"
    assert payload["details"]["expected_version"] == "2022.1"
    assert payload["details"]["actual_version"] == "2023.1"


def test_status_2021_requires_exactly_one_identity_bound_project_row(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2021, major=1),
            "ak.wwise.core.object.get": {
                "return": [
                    {"id": PROJECT_GUID, "name": "One", "type": "Project", "path": "\\"},
                    {"id": "{22222222-2222-2222-2222-222222222222}", "name": "Two", "type": "Project", "path": "\\"},
                ]
            },
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2021.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_STATUS_RESULT"
    assert payload["details"]["maximum_rows"] == 1
    assert payload["details"]["actual_count"] == 2


def test_status_2021_rejects_noncanonical_nonempty_project_id(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2021, major=1),
            "ak.wwise.core.object.get": {
                "return": [{"id": "{project}", "name": "SampleProject", "type": "Project", "path": "\\"}]
            },
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2021.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_STATUS_RESULT"
    assert payload["details"]["invalid_fields"] == ["id"]
    assert payload["details"]["id_format"] == "{8-4-4-4-12}"


def test_buses_returns_structured_rows_through_object_get(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [
                    {
                        "id": "{bus-1}",
                        "name": "Master Audio Bus",
                        "type": "Bus",
                        "path": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
                    }
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["buses"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["count"] == 1
    assert payload["buses"][0]["name"] == "Master Audio Bus"
    assert payload["query_bound"] == {
        "mode": "take",
        "value": waapi_gateway.MAX_QUERY_TAKE,
        "source": "fixed-command-default",
    }
    assert payload["possibly_truncated"] is False
    assert "result" not in payload["call"]
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": f"from type Bus take {waapi_gateway.MAX_QUERY_TAKE}"},
        {"return": ["id", "name", "type", "path"]},
    )


def test_buses_rejects_rows_above_fixed_maximum(tmp_path: Path) -> None:
    rows = [
        {"id": f"{{bus-{index}}}", "name": f"Bus {index}", "type": "Bus", "path": f"\\Bus {index}"}
        for index in range(waapi_gateway.MAX_QUERY_TAKE + 1)
    ]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": rows},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["buses"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["maximum_rows"] == waapi_gateway.MAX_QUERY_TAKE
    assert payload["details"]["actual_count"] == waapi_gateway.MAX_QUERY_TAKE + 1


def test_buses_failure_does_not_look_like_an_empty_success(tmp_path: Path) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        errors={"ak.wwise.core.object.get": RuntimeError("read failed")},
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["buses"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["buses"] is None
    assert payload["count"] is None
    assert payload["possibly_truncated"] is None


def test_selected_headless_unavailable_is_a_successful_explicit_boundary(tmp_path: Path) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info(command_line=True)},
        errors={
            "ak.wwise.ui.getSelectedObjects": RuntimeError(
                "ApplicationError(error=<ak.wwise.unavailable>): Procedure not available for this type of Wwise instance."
            )
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["selected"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["status"] == "unsupported_boundary"
    assert payload["api_attempted"] == "ak.wwise.ui.getSelectedObjects"
    assert "command-line/headless" in payload["message"]
    evidence = json.loads(next((tmp_path / "evidence").glob("*.json")).read_text())
    assert evidence["api"] == "ak.wwise.ui.getSelectedObjects"
    assert evidence["ok"] is False


def test_selected_accepts_only_an_explicit_empty_objects_array(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(command_line=False),
            "ak.wwise.ui.getSelectedObjects": {"objects": []},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["selected"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["count"] == 0
    assert payload["objects"] == []


@pytest.mark.parametrize(
    "selected_result",
    (
        None,
        {},
        {"objects": {}},
        {"objects": ["not-an-object"]},
        {"objects": [{}]},
    ),
)
def test_selected_rejects_malformed_success_shapes(
    tmp_path: Path,
    selected_result: object,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(command_line=False),
            "ak.wwise.ui.getSelectedObjects": selected_result,
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["selected"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_SELECTION_RESULT"


def test_selected_does_not_swallow_network_unavailable_errors_in_headless_mode(tmp_path: Path) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info(command_line=True)},
        errors={
            "ak.wwise.ui.getSelectedObjects": RuntimeError(
                "NetworkUnavailableError: socket unavailable"
            )
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["selected"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["status"] == "error"
    assert payload["call"]["error_code"] == "RuntimeError"
    assert payload["objects"] is None


def test_generic_call_validates_json_before_dispatch(tmp_path: Path) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid JSON must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", "ak.wwise.waapi.getFunctions", "--args-json", "[]"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "JSON object" in payload["message"]
    assert called is False


def test_final_live_gateway_document_has_its_own_size_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(waapi_gateway, "MAX_GATEWAY_RESULT_JSON_BYTES", 2048)
    sentinel = "FINAL_GATEWAY_SENTINEL_MUST_NOT_ESCAPE"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.waapi.getFunctions": {
                "functions": [
                    "ak." + str(index) + "." + (sentinel if index == 0 else "entry") + ("x" * 170)
                    for index in range(12)
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", "ak.wwise.waapi.getFunctions"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    assert exit_code == 2
    assert payload["error_code"] == "RESULT_TOO_LARGE"
    assert payload["details"] == {
        "provenance": waapi_gateway.GATEWAY_RESULT_CEILING_PROVENANCE,
        "original_ok": True,
        "original_status": "ok",
        "limit_bytes": 2048,
        "observed_at_least_bytes": 2049,
    }
    assert len(rendered) <= 2048
    assert sentinel.encode("utf-8") not in rendered


def test_final_gateway_ceiling_preserves_transaction_state_context() -> None:
    huge = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "ok": True,
        "status": "executed_unverified",
        "command": "execute",
        "detected_version": "2022.1",
        "transaction_id": "tx-safe-context",
        "state": "executed_unverified",
        "artifact_hash": "a" * 64,
        "executed": True,
        "verified": False,
        "automatic_retry": False,
        "payload": "x" * (waapi_gateway.MAX_GATEWAY_RESULT_JSON_BYTES + 1),
    }

    exit_code, payload = waapi_gateway.constrain_live_gateway_result(0, huge)

    assert exit_code == 2
    assert payload["error_code"] == "RESULT_TOO_LARGE"
    assert payload["details"]["original_ok"] is True
    assert payload["details"]["original_status"] == "executed_unverified"
    assert payload["transaction_id"] == "tx-safe-context"
    assert payload["state"] == "executed_unverified"
    assert payload["artifact_hash"] == "a" * 64
    assert payload["executed"] is True
    assert payload["verified"] is False
    assert payload["automatic_retry"] is False


def test_final_gateway_ceiling_rejects_non_json_envelope() -> None:
    circular: dict[str, Any] = {}
    circular["self"] = circular

    exit_code, payload = waapi_gateway.constrain_live_gateway_result(
        0,
        {
            "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
            "ok": True,
            "status": "ok",
            "command": "status",
            "payload": circular,
        },
    )

    assert exit_code == 2
    assert payload["error_code"] == "RESULT_NOT_JSON"
    assert payload["details"]["original_ok"] is True


@pytest.mark.parametrize("command", ("preview", "verify"))
def test_main_preserves_top_level_order_and_prints_agent_result_last(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    payload = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "ok": True,
        "status": "awaiting_confirmation" if command == "preview" else "verified",
        "command": command,
        "evidence": {"large": "x" * 256},
        "agent_result": {"operation": "object.create", "executed": command == "verify"},
    }
    monkeypatch.setattr(waapi_gateway, "execute_gateway", lambda argv: (0, payload))

    exit_code = waapi_gateway.main([command])
    stdout = capsys.readouterr().out
    parsed = json.loads(
        stdout,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )

    assert exit_code == 0
    assert parsed == payload
    assert list(parsed) == list(payload)
    assert list(parsed)[-1] == "agent_result"
    assert stdout.rfind('"agent_result"') > stdout.rfind('"evidence"')
    exact_size = len(stdout.encode("utf-8"))
    assert waapi_gateway.probe_gateway_json_document_size(payload, exact_size) == "ok"
    assert waapi_gateway.probe_gateway_json_document_size(payload, exact_size - 1) == "too_large"


def test_main_keeps_non_transaction_output_strict_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    payload = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "ok": False,
        "status": "error",
        "command": "status",
        "details": {"message": "中文"},
    }
    monkeypatch.setattr(waapi_gateway, "execute_gateway", lambda argv: (2, payload))

    exit_code = waapi_gateway.main(["status"])
    stdout = capsys.readouterr().out

    assert exit_code == 2
    assert json.loads(
        stdout,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    ) == payload
    assert waapi_gateway.probe_gateway_json_document_size(
        payload,
        len(stdout.encode("utf-8")),
    ) == "ok"


def test_main_rejects_non_strict_json_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        waapi_gateway,
        "execute_gateway",
        lambda argv: (0, {"ok": True, "value": float("nan")}),
    )

    with pytest.raises(ValueError, match="Out of range float values"):
        waapi_gateway.main(["status"])


@pytest.mark.parametrize(
    ("document", "message"),
    (
        ('{"stateGroup":"{id}","stateGroup":"{other}"}', "duplicate JSON key"),
        ('{"value":NaN}', "strict JSON"),
        ('{"value":1e9999}', "strict JSON"),
        ('{"value":"' + ("x" * (64 * 1024 + 1)) + '"}', "string limit"),
        ('{"value":' + ("[" * 40) + "0" + ("]" * 40) + "}", "depth limit"),
        ('{"value":[' + ",".join("0" for _ in range(10_000)) + "]}", "node JSON input limit"),
        ('{"value":"' + ("x" * (256 * 1024)) + '"}', "JSON input limit"),
    ),
)
def test_generic_call_rejects_hostile_json_before_connecting(
    tmp_path: Path,
    document: str,
    message: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"hostile JSON must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", "ak.wwise.waapi.getFunctions", "--args-json", document],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert message in payload["message"]
    assert called is False


@pytest.mark.parametrize(
    "arguments",
    (
        ["wait-topic", "ak.wwise.core.object.created", "--match-json", '{"id":1,"id":2}'],
        ["preview", "--request-json", '{"operation":"object.create","operation":"object.delete"}'],
    ),
)
def test_all_live_json_commands_validate_before_connecting(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid JSON must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        arguments,
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "duplicate JSON key" in payload["message"]
    assert called is False


def test_explicit_version_mismatch_fails_closed(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info(year=2023, major=1)})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "Connected Wwise is 2023.1" in payload["message"]


@pytest.mark.parametrize("version_key", SUPPORTED_WWISE_VERSION_KEYS)
def test_get_info_version_detection_supports_all_packaged_year_major_keys(version_key: str) -> None:
    year, major = (int(part) for part in version_key.split("."))

    assert version_key_from_get_info({"version": {"year": year, "major": major}}) == version_key


def test_get_info_version_detection_rejects_unknown_versions() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        version_key_from_get_info({"version": {"year": 2030, "major": 1}})


def test_config_show_returns_defaults_offline_without_connecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    external_path = tmp_path / "user-config" / "config.json"
    monkeypatch.setattr(waapi_gateway, "SKILL_ROOT", skill_root)
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"config-show must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["config-show"],
        env={"WAAPI_SKILL_CONFIG_PATH": str(external_path)},
        client_factory=client_factory,
    )

    assert exit_code == 0
    assert called is False
    assert payload == {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "config_contract": "waapi-skill.config/v1",
        "ok": True,
        "status": "ok",
        "command": "config-show",
        "offline": True,
        "effective": {
            "wwise_version": None,
            "waapi_host": "127.0.0.1",
            "waapi_port": None,
            "project_modification_policy": "preview_then_confirm",
        },
        "source": "defaults",
        "external_path": str(external_path),
        "legacy_fallback_used": False,
    }
    assert not external_path.exists()


def test_config_set_roundtrips_atomically_outside_checkout(tmp_path: Path) -> None:
    external_path = tmp_path / "external" / "config.json"
    env = {"WAAPI_SKILL_CONFIG_PATH": str(external_path)}

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "config-set",
            "--wwise-version",
            "2025.1",
            "--waapi-host",
            "localhost",
            "--waapi-port",
            "31337",
            "--project-modification-policy",
            "allow_with_notice",
        ],
        env=env,
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["source"] == "external"
    assert payload["external_path"] == str(external_path)
    assert payload["changed_fields"] == [
        "wwise_version",
        "waapi_host",
        "waapi_port",
        "project_modification_policy",
    ]
    assert payload["effective"] == json.loads(external_path.read_text(encoding="utf-8"))
    assert not external_path.is_relative_to(waapi_gateway.SKILL_ROOT)
    assert list(external_path.parent.glob(f".{external_path.name}.*.tmp")) == []

    show_code, shown = waapi_gateway.execute_gateway(["config-show"], env=env)
    assert show_code == 0
    assert shown["effective"] == payload["effective"]
    assert shown["legacy_fallback_used"] is False

    clear_code, cleared = waapi_gateway.execute_gateway(
        ["config-set", "--clear-wwise-version", "--clear-waapi-port"],
        env=env,
    )
    assert clear_code == 0
    assert cleared["effective"]["wwise_version"] is None
    assert cleared["effective"]["waapi_port"] is None
    assert cleared["effective"]["waapi_host"] == "localhost"


def test_config_legacy_read_and_external_migration_never_rewrites_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_root = tmp_path / "skill"
    legacy_path = skill_root / "data" / "config.json"
    external_path = tmp_path / "external" / "config.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_payload = {
        "wwise_version": "2023.1",
        "waapi_host": "legacy-host",
        "waapi_port": 8123,
        "project_modification_policy": "preview_then_confirm",
        "use_current_selection_for_ambiguous_queries": False,
    }
    legacy_text = json.dumps(legacy_payload, indent=2, sort_keys=True) + "\n"
    legacy_path.write_text(legacy_text, encoding="utf-8")
    monkeypatch.setattr(waapi_gateway, "SKILL_ROOT", skill_root)
    env = {"WAAPI_SKILL_CONFIG_PATH": str(external_path)}

    show_code, shown = waapi_gateway.execute_gateway(["config-show"], env=env)
    assert show_code == 0
    assert shown["source"] == "legacy"
    assert shown["legacy_fallback_used"] is True
    assert shown["effective"]["waapi_host"] == "legacy-host"

    set_code, saved = waapi_gateway.execute_gateway(
        ["config-set", "--waapi-host", "external-host"],
        env=env,
    )
    assert set_code == 0
    assert saved["source"] == "external"
    assert saved["migrated_from_legacy"] is True
    assert json.loads(external_path.read_text(encoding="utf-8")) == {
        "wwise_version": "2023.1",
        "waapi_host": "external-host",
        "waapi_port": 8123,
        "project_modification_policy": "preview_then_confirm",
    }
    assert legacy_path.read_text(encoding="utf-8") == legacy_text


@pytest.mark.parametrize(
    ("arguments", "message"),
    (
        (["config-set"], "at least one"),
        (["config-set", "--wwise-version", "2030.1"], "wwise_version"),
        (["config-set", "--waapi-host", "http://localhost"], "waapi_host"),
        (["config-set", "--waapi-port", "0"], "waapi_port"),
        (["config-set", "--waapi-port", "not-an-int"], "waapi_port"),
        (["config-set", "--project-modification-policy", "always"], "project_modification_policy"),
        (
            ["config-set", "--wwise-version", "2022.1", "--clear-wwise-version"],
            "mutually exclusive",
        ),
    ),
)
def test_config_set_validation_fails_before_connect_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    message: str,
) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    external_path = tmp_path / "external" / "config.json"
    monkeypatch.setattr(waapi_gateway, "SKILL_ROOT", skill_root)
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(url)

    exit_code, payload = waapi_gateway.execute_gateway(
        arguments,
        env={"WAAPI_SKILL_CONFIG_PATH": str(external_path)},
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert message in payload["message"]
    assert called is False
    assert not external_path.exists()


def test_external_config_rejects_unknown_public_fields(tmp_path: Path) -> None:
    external_path = tmp_path / "config.json"
    external_path.write_text(
        json.dumps(
            {
                "wwise_version": "2022.1",
                "waapi_host": "127.0.0.1",
                "waapi_port": 8080,
                "project_modification_policy": "preview_then_confirm",
                "internal_escape_hatch": True,
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["config-show"],
        env={"WAAPI_SKILL_CONFIG_PATH": str(external_path)},
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "unsupported fields: internal_escape_hatch" in payload["message"]


def test_config_reset_recovers_invalid_external_config_without_reading_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_root = tmp_path / "skill"
    legacy_path = skill_root / "data" / "config.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(
        json.dumps(
            {
                "wwise_version": "2025.1",
                "waapi_host": "legacy-host",
                "waapi_port": 9000,
                "project_modification_policy": "never",
            }
        ),
        encoding="utf-8",
    )
    external_path = tmp_path / "external" / "config.json"
    external_path.parent.mkdir(parents=True)
    invalid_text = '{"waapi_host":"127.0.0.1","unknown":true}\n'
    external_path.write_text(invalid_text, encoding="utf-8")
    monkeypatch.setattr(waapi_gateway, "SKILL_ROOT", skill_root)
    env = {"WAAPI_SKILL_CONFIG_PATH": str(external_path)}
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"config recovery must remain offline: {url}")

    failed_code, failed = waapi_gateway.execute_gateway(
        ["config-set", "--waapi-port", "31337"],
        env=env,
        client_factory=client_factory,
    )
    assert failed_code == 2
    assert "unsupported fields" in failed["message"]
    assert external_path.read_text(encoding="utf-8") == invalid_text

    reset_code, reset = waapi_gateway.execute_gateway(
        ["config-set", "--reset", "--waapi-port", "31337"],
        env=env,
        client_factory=client_factory,
    )

    assert reset_code == 0
    assert called is False
    assert reset["source"] == "external"
    assert reset["reset"] is True
    assert reset["migrated_from_legacy"] is False
    assert reset["changed_fields"] == ["waapi_port"]
    assert reset["effective"] == {
        "wwise_version": None,
        "waapi_host": "127.0.0.1",
        "waapi_port": 31337,
        "project_modification_policy": "preview_then_confirm",
    }
    assert json.loads(external_path.read_text(encoding="utf-8")) == reset["effective"]
    assert json.loads(legacy_path.read_text(encoding="utf-8"))["waapi_host"] == "legacy-host"


def test_config_reset_alone_writes_validated_defaults(tmp_path: Path) -> None:
    external_path = tmp_path / "external" / "config.json"
    external_path.parent.mkdir(parents=True)
    external_path.write_text("not-json\n", encoding="utf-8")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["config-set", "--reset"],
        env={"WAAPI_SKILL_CONFIG_PATH": str(external_path)},
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["reset"] is True
    assert payload["changed_fields"] == []
    assert payload["effective"] == {
        "wwise_version": None,
        "waapi_host": "127.0.0.1",
        "waapi_port": None,
        "project_modification_policy": "preview_then_confirm",
    }


def test_saved_version_hint_mismatch_fails_closed(tmp_path: Path) -> None:
    external_path = tmp_path / "config.json"
    external_path.write_text(
        json.dumps(
            {
                "wwise_version": "2024.1",
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "preview_then_confirm",
            }
        ),
        encoding="utf-8",
    )
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env={"WAAPI_SKILL_CONFIG_PATH": str(external_path)},
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert "requested version is 2024.1" in payload["message"]
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]
    assert client.disconnected is True


def test_connection_cli_then_env_then_saved_config_precedence(tmp_path: Path) -> None:
    external_path = tmp_path / "config.json"
    external_path.write_text(
        json.dumps(
            {
                "wwise_version": "2023.1",
                "waapi_host": "saved-host",
                "waapi_port": 1111,
                "project_modification_policy": "preview_then_confirm",
            }
        ),
        encoding="utf-8",
    )
    env = {
        "WAAPI_SKILL_CONFIG_PATH": str(external_path),
        "WWISE_WAAPI_HOST": "env-host",
        "WWISE_WAAPI_PORT": "2222",
        "WWISE_VERSION": "2024.1",
    }

    cli_args = waapi_gateway.build_parser().parse_args(
        ["--host", "cli-host", "--port", "3333", "--version", "2025.1", "status"]
    )
    cli = waapi_gateway.resolve_connection(cli_args, env=env)
    assert (cli.host, cli.port, cli.version_hint) == ("cli-host", 3333, "2025.1")

    alias_args = waapi_gateway.build_parser().parse_args(
        ["--wwise-version", "2025.1", "status"]
    )
    alias = waapi_gateway.resolve_connection(alias_args, env=env)
    assert (alias.host, alias.port, alias.version_hint) == ("env-host", 2222, "2025.1")

    env_args = waapi_gateway.build_parser().parse_args(["status"])
    from_env = waapi_gateway.resolve_connection(env_args, env=env)
    assert (from_env.host, from_env.port, from_env.version_hint) == (
        "env-host",
        2222,
        "2024.1",
    )

    saved = waapi_gateway.resolve_connection(
        env_args,
        env={"WAAPI_SKILL_CONFIG_PATH": str(external_path)},
    )
    assert (saved.host, saved.port, saved.version_hint) == ("saved-host", 1111, "2023.1")


@pytest.mark.parametrize("configured", ("relative/evidence", "~/evidence"))
def test_evidence_directory_requires_an_absolute_path_before_connecting(
    tmp_path: Path,
    configured: str,
) -> None:
    env = gateway_env(tmp_path)
    env["WWISE_EVIDENCE_DIR"] = configured
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid evidence path must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=env,
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "must be an absolute path" in payload["message"]
    assert called is False


def test_evidence_directory_inside_skill_checkout_is_rejected_before_connecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    env = gateway_env(tmp_path)
    env["WWISE_EVIDENCE_DIR"] = str(skill_root / "evidence")
    monkeypatch.setattr(waapi_gateway, "SKILL_ROOT", skill_root)
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"checkout evidence path must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["status"],
        env=env,
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "outside the Skill checkout" in payload["message"]
    assert called is False


@pytest.mark.parametrize("configured", ("relative/state", "~/state"))
def test_transaction_state_directory_requires_an_absolute_path_without_writing(
    tmp_path: Path,
    configured: str,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["--state-dir", configured, "transaction-show", "tx-missing"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "must be an absolute path" in payload["message"]


def test_transaction_state_directory_inside_skill_checkout_is_rejected_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    state_dir = skill_root / "state"
    monkeypatch.setattr(waapi_gateway, "SKILL_ROOT", skill_root)

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--state-dir", str(state_dir), "transaction-show", "tx-missing"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "outside the Skill checkout" in payload["message"]
    assert not state_dir.exists()


def test_external_never_policy_blocks_confirm_without_connecting(tmp_path: Path) -> None:
    external_path = tmp_path / "config.json"
    external_path.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": "never",
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "confirm",
            "missing-transaction",
            "--artifact-hash",
            "deadbeef",
        ],
        env={"WAAPI_SKILL_CONFIG_PATH": str(external_path)},
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 2
    assert payload["message"] == "project_modification_policy=never blocks transaction confirmation"


def test_capability_matrix_is_available_offline_without_config_or_client(tmp_path: Path) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"offline catalog must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["capabilities", "--all-versions", "--summary-only"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 0
    assert called is False
    assert payload["offline"] is True
    assert payload["summary"]["totals"]["total"] == 814
    assert payload["summary"]["totals"]["schema_status"] == {"ok": 814}
    assert payload["summary"]["totals"]["interface_status"] == {
        "available": 247,
        "available_via_transaction": 522,
        "unsupported_by_skill_interface": 45,
    }
    assert payload["summary"]["totals"]["preferred_routes"] == {
        "bounded_topic_wait": 147,
        "fixed_command": 42,
        "manifest_dispatch": 58,
        "transaction_operation": 522,
        "unsupported_boundary": 45,
    }
    assert payload["match_count"] == 814
    assert payload["returned_count"] == 0
    assert payload["truncated"] is False
    assert "capabilities" not in payload


def test_capabilities_default_to_fifty_compact_rows_and_explicit_zero_returns_all(tmp_path: Path) -> None:
    no_client = lambda url: (_ for _ in ()).throw(AssertionError(url))

    exit_code, default_payload = waapi_gateway.execute_gateway(
        ["capabilities", "--all-versions"],
        env=gateway_env(tmp_path),
        client_factory=no_client,
    )

    assert exit_code == 0
    assert default_payload["match_count"] == 814
    assert default_payload["returned_count"] == 50
    assert default_payload["truncated"] is True
    assert len(default_payload["capabilities"]) == 50
    assert all(set(row) == CAPABILITY_COMPACT_KEYS for row in default_payload["capabilities"])
    default_json = json.dumps(default_payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    assert len(default_json) < 70_000

    exit_code, all_payload = waapi_gateway.execute_gateway(
        ["capabilities", "--all-versions", "--limit", "0"],
        env=gateway_env(tmp_path),
        client_factory=no_client,
    )

    assert exit_code == 0
    assert all_payload["match_count"] == 814
    assert all_payload["returned_count"] == 814
    assert all_payload["truncated"] is False
    assert len(all_payload["capabilities"]) == 814
    all_json = json.dumps(all_payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    assert len(all_json) < 1_000_000


def test_capabilities_detail_is_explicit_and_compact_rows_keep_transaction_boundaries(tmp_path: Path) -> None:
    no_client = lambda url: (_ for _ in ()).throw(AssertionError(url))
    filters = ["--all-versions", "--query", "ak.wwise.core.object.copy", "--limit", "1"]

    exit_code, compact_payload = waapi_gateway.execute_gateway(
        ["capabilities", *filters],
        env=gateway_env(tmp_path),
        client_factory=no_client,
    )

    assert exit_code == 0
    compact = compact_payload["capabilities"][0]
    assert set(compact) == CAPABILITY_COMPACT_KEYS
    assert compact["transaction_boundaries"][0]["operation"] == "object.copy"
    assert compact["execution_contract"]["contract"] == "waapi-skill.public-execution-contract/v1"
    assert compact["execution_contract"]["route"] == "transaction"
    assert compact["execution_contract"]["executable"] is True

    exit_code, detail_payload = waapi_gateway.execute_gateway(
        ["capabilities", *filters, "--detail"],
        env=gateway_env(tmp_path),
        client_factory=no_client,
    )

    assert exit_code == 0
    detail = detail_payload["capabilities"][0]
    assert {"risk_level", "interface", "execution_contract", "schema", "policy", "behavioral_evidence"} <= set(detail)
    assert "risk" not in detail
    assert detail["interface"]["transaction_boundaries"][0]["operation"] == "object.copy"
    assert detail["schema"]["status"] == "ok"
    assert "full" not in detail["schema"]


@pytest.mark.parametrize(
    ("command", "expected"),
    (
        (
            "capabilities",
            ("Start with --summary-only", "--detail", "defaults to 50", "explicitly returns every match"),
        ),
        ("operations", ("named operation", "operation-schema <name>", "--detail", "nested request contracts")),
    ),
)
def test_inventory_help_explains_compact_defaults(command: str, expected: tuple[str, ...], capsys: Any) -> None:
    with pytest.raises(SystemExit) as exc_info:
        waapi_gateway.build_parser().parse_args([command, "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert all(fragment in output for fragment in expected)


def test_describe_defaults_to_compact_cross_version_schema_offline(tmp_path: Path) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["describe", "ak.wwise.core.getProjectInfo", "--all-versions"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["availability"]["2021.1"] == {
        "available": False,
        "status": "absent_from_version_manifest",
        "fallback_allowed": False,
    }
    capability = payload["availability"]["2025.1"]["capability"]
    assert capability["interface"]["preferred_route"] == "fixed_command"
    assert capability["interface"]["gateway_commands"] == ["status"]
    assert "semantic_builder_ref" not in capability["interface"]
    assert capability["schema"]["status"] == "ok"
    assert "full" not in capability["schema"]
    assert payload["schema_detail"] == "summary"


def test_describe_full_schema_is_explicit_offline_opt_in(tmp_path: Path) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["describe", "ak.wwise.core.object.get", "--all-versions", "--full-schema"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["schema_detail"] == "full"
    for row in payload["availability"].values():
        if row["available"]:
            assert isinstance(row["capability"]["schema"]["full"], dict)


def test_selected_manifest_absence_is_an_explicit_boundary_for_newer_versions(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info(year=2025, major=1)})
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        ["selected"],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["status"] == "unsupported_boundary"
    assert payload["call"]["error_code"] == "API_NOT_FOUND"
    assert "absent from this version's packaged manifest" in payload["message"]


def test_generic_reflection_call_is_schema_validated_and_normalized(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.waapi.getFunctions": {
                "functions": [
                    "ak.wwise.waapi.getTopics",
                    "ak.wwise.waapi.getFunctions",
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", "ak.wwise.waapi.getFunctions"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["contract"] == "waapi-skill.gateway-result/v1"
    assert payload["schema_validation"]["uri"] == "ak.wwise.waapi.getFunctions"
    assert payload["call"]["ok"] is True
    assert "result" not in payload["call"]
    assert payload["inventory"]["kind"] == "function"
    assert payload["inventory"]["uris"] == [
        "ak.wwise.waapi.getFunctions",
        "ak.wwise.waapi.getTopics",
    ]
    assert payload["inventory"]["packaged_manifest"]["matches"] is False
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.waapi.getFunctions",
    ]


@pytest.mark.parametrize(
    ("result", "expected_error"),
    (
        (None, "SemanticValidationError"),
        ({}, "INVALID_REFLECTION_RESULT"),
        ({"functions": "ak.wwise.core.getInfo"}, "SemanticValidationError"),
        ({"functions": [1]}, "SemanticValidationError"),
        ({"functions": ["not-a-waapi-uri"]}, "INVALID_REFLECTION_RESULT"),
        ({"functions": ["ak.duplicate", "ak.duplicate"]}, "INVALID_REFLECTION_RESULT"),
        ({"functions": [], "unexpected": []}, "SemanticValidationError"),
        ({"functions": ["ak." + ("x" * 513)]}, "INVALID_REFLECTION_RESULT"),
        ({"functions": [f"ak.test.{index}" for index in range(4097)]}, "INVALID_REFLECTION_RESULT"),
    ),
)
def test_generic_reflection_call_rejects_shape_drift(
    tmp_path: Path,
    result: Any,
    expected_error: str,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.waapi.getFunctions": result,
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", "ak.wwise.waapi.getFunctions"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error_code"] == expected_error
    if expected_error == "SemanticValidationError":
        assert payload["details"]["uri"] == "ak.wwise.waapi.getFunctions"
        assert payload["details"]["section"].startswith("result")
    else:
        assert payload["details"]["api"] == "ak.wwise.waapi.getFunctions"


@pytest.mark.parametrize("command", ("call", "wait-topic"))
def test_unreflected_uri_is_structured_unsupported_before_connecting_when_version_is_known(
    tmp_path: Path,
    command: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"unreflected URI boundary must not connect to {url}")

    api = "ak.wwise.future.notInManifest"
    exit_code, payload = waapi_gateway.execute_gateway(
        [command, api],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "unsupported_by_skill_interface"
    assert payload["error_code"] == "UNSUPPORTED_BY_SKILL_INTERFACE"
    assert payload["api"] == api
    assert payload["command"] == command
    assert payload["executed"] is False
    assert "not reflected by Wwise 2022.1" in payload["message"]
    assert "no packaged executable route" in payload["message"]
    assert called is False


@pytest.mark.parametrize("command", ("call", "wait-topic"))
def test_version_specific_topic_manifest_absence_preempts_cross_version_route_advice(
    tmp_path: Path,
    command: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"version-specific manifest boundary must not connect to {url}")

    # structureChanged is reviewed for its 2025.1 route, but it is absent from
    # the packaged 2022.1 manifest. The cross-version topic allowlist must not
    # advise a 2022.1 caller to try wait-topic.
    api = "ak.wwise.core.object.structureChanged"
    exit_code, payload = waapi_gateway.execute_gateway(
        [command, api],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "unsupported_by_skill_interface"
    assert payload["error_code"] == "UNSUPPORTED_BY_SKILL_INTERFACE"
    assert payload["api"] == api
    assert payload["command"] == command
    assert payload["executed"] is False
    assert "not reflected by Wwise 2022.1" in payload["message"]
    assert "required_command" not in payload
    assert called is False


def test_unknown_version_reviewed_topic_keeps_static_wait_topic_bootstrap(
    tmp_path: Path,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"generic call topic redirect must not connect to {url}")

    env = gateway_env(tmp_path)
    env.pop("WWISE_VERSION")
    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", "ak.wwise.core.object.structureChanged"],
        env=env,
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "wait_topic_required"
    assert payload["error_code"] == "WAIT_TOPIC_REQUIRED"
    assert payload["required_command"] == "wait-topic"
    assert called is False


@pytest.mark.parametrize("command", ("call", "wait-topic"))
def test_unreflected_uri_is_structured_unsupported_after_live_version_detection(
    tmp_path: Path,
    command: str,
) -> None:
    env = gateway_env(tmp_path)
    env.pop("WWISE_VERSION")
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})
    api = "ak.wwise.future.notInManifest"

    exit_code, payload = waapi_gateway.execute_gateway(
        [command, api],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["status"] == "unsupported_by_skill_interface"
    assert payload["error_code"] == "UNSUPPORTED_BY_SKILL_INTERFACE"
    assert payload["api"] == api
    assert payload["detected_version"] == "2022.1"
    assert payload["executed"] is False
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]
    assert client.disconnected is True


@pytest.mark.parametrize("api", sorted(EXPECTED_EXCLUDED_FUNCTION_URIS))
def test_all_eleven_excluded_functions_are_rejected_before_connecting(
    tmp_path: Path,
    api: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"excluded function must not connect to {url}")

    assert IMMEDIATE_UNSUPPORTED_CALL_URIS == EXPECTED_EXCLUDED_FUNCTION_URIS

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", api, "--dry-run"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "unsupported_by_skill_interface"
    assert payload["error_code"] == "UNSUPPORTED_BY_SKILL_INTERFACE"
    assert payload["executed"] is False
    assert called is False


def test_public_generic_call_requires_fixed_command_before_connecting(tmp_path: Path) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"fixed route rejection must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", "ak.wwise.core.getInfo", "--dry-run"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "fixed_command_required"
    assert payload["error_code"] == "FIXED_COMMAND_REQUIRED"
    assert payload["required_command"] == "status"
    assert payload["executed"] is False
    assert called is False


def test_public_generic_call_rejects_object_get_and_points_to_query_object(tmp_path: Path) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"object.get route rejection must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.object.get",
            "--args-json",
            '{"waql":"from type Event"}',
            "--options-json",
            '{"return":["id","name"]}',
        ],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "query_object_required"
    assert payload["error_code"] == "QUERY_OBJECT_REQUIRED"
    assert payload["required_command"] == "query-object"
    assert payload["executed"] is False
    assert "query-object" in payload["message"]
    assert called is False


@pytest.mark.parametrize(
    ("version", "api", "execution_mode"),
    (
        ("2022.1", "ak.wwise.cli.dumpObjects", "isolated_transaction"),
        ("2022.1", "ak.wwise.cli.verify", "isolated_transaction"),
        ("2025.1", "ak.wwise.core.mediaPool.get", "transaction"),
        ("2023.1", "ak.wwise.core.sourceControl.getSourceFiles", "isolated_transaction"),
        ("2023.1", "ak.wwise.core.sourceControl.getStatus", "isolated_transaction"),
    ),
)
def test_public_generic_call_redirects_guarded_apis_to_transaction_before_connecting(
    tmp_path: Path,
    version: str,
    api: str,
    execution_mode: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"transaction redirect must not connect to {url}")

    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = version

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            api,
            "--args-json",
            "{}",
            "--dry-run",
        ],
        env=env,
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "transaction_required"
    assert payload["error_code"] == "TRANSACTION_REQUIRED"
    assert payload["executed"] is False
    assert payload["verified"] is False
    assert payload["capability"]["interface"]["transaction_operations"] == ["waapi.call"]
    assert payload["capability"]["execution_contract"]["route"] == execution_mode
    assert called is False


@pytest.mark.parametrize(
    "api",
    (
        "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion",
        "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInTrimmedRegion",
    ),
)
def test_bounded_direct_calls_reject_invalid_payload_without_business_dispatch(
    tmp_path: Path,
    api: str,
) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", api, "--args-json", "{}", "--dry-run"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["error_code"] == "SemanticValidationError"
    assert payload["details"]["uri"] == api
    assert payload["details"]["missing_args"]
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]


def test_generic_call_rejects_schema_mismatch_before_business_dispatch(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.waapi.getFunctions",
            "--args-json",
            '{"unexpected":true}',
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "SemanticValidationError"
    assert payload["details"]["unknown_fields"] == ["unexpected"]
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize("extra_flag", ("--allow-destructive", "--dry-run"))
def test_public_generic_call_cannot_bypass_closed_transaction_route(
    tmp_path: Path,
    extra_flag: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"transaction route rejection must not connect to {url}")

    env = gateway_env(tmp_path)
    env["WWISE_DESTRUCTIVE"] = "1"

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.object.delete",
            "--args-json",
            '{"object":"{fixture}"}',
            extra_flag,
        ],
        env=env,
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "transaction_required"
    assert payload["error_code"] == "TRANSACTION_REQUIRED"
    assert payload["executed"] is False
    assert payload["verified"] is False
    assert called is False


def test_public_generic_call_redirects_generic_soundbank_mutation_to_transaction(tmp_path: Path) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"transaction-only mutation must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.soundbank.generate",
            "--args-json",
            '{"soundbanks":[]}',
            "--dry-run",
        ],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "transaction_required"
    assert payload["error_code"] == "TRANSACTION_REQUIRED"
    assert payload["executed"] is False
    assert payload["verified"] is False
    assert payload["capability"]["interface"]["transaction_operations"] == ["waapi.call"]
    assert payload["capability"]["execution_contract"]["route"] == "isolated_transaction"
    assert called is False


def test_query_object_uses_semantic_builder_and_returns_normalized_rows(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [{"id": "{sound}", "name": "UI_Click", "type": "Sound", "path": "\\Actor-Mixer Hierarchy\\UI_Click"}]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--where-json", '{"field":"name","operator":":","value":"UI"}', "--take", "10"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["count"] == 1
    assert payload["objects"][0]["name"] == "UI_Click"
    assert payload["semantic_preview"]["source_note_family"] == "query"
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": 'from type Sound where name : "UI" take 10'},
        {"return": ["id", "name", "type", "path"]},
    )


@pytest.mark.parametrize(
    ("argv", "expected_error"),
    (
        (("query-object", "--type", "Sound"), "GatewayInputError"),
        (
            (
                "query-object",
                "--type",
                "Sound",
                "--take",
                str(waapi_gateway.MAX_QUERY_TAKE + 1),
            ),
            "SemanticValidationError",
        ),
        (("query-object", "--query", "from type Sound"), "SemanticValidationError"),
        (("query-object", "--object-id", "not-a-guid"), "SemanticValidationError"),
        (
            (
                "query-object",
                "--path",
                r"\Events\Default Work Unit",
                "--return-field",
                "id",
            ),
            "GatewayInputError",
        ),
        (
            (
                "query-object",
                "--object-id",
                "{11111111-1111-1111-1111-111111111111}",
                "--return-field",
                "path",
            ),
            "GatewayInputError",
        ),
        (
            (
                "query-object",
                "--type",
                "Sound",
                "--where-json",
                "3",
                "--take",
                "1",
            ),
            "SemanticValidationError",
        ),
    ),
)
def test_query_input_errors_fail_before_opening_transport(
    tmp_path: Path,
    argv: tuple[str, ...],
    expected_error: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid query input must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == expected_error
    assert called is False


@pytest.mark.parametrize(
    ("response", "expected_message"),
    (
        (None, "result to be a JSON object"),
        ({"return": {}}, "result.return to be an array"),
        ({"return": [{"id": "{ok}"}, "not-an-object"]}, "every object.get result.return row"),
    ),
)
def test_query_object_rejects_malformed_success_result_shape(
    tmp_path: Path,
    response: object,
    expected_message: str,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": response,
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--take", "1"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert expected_message in payload["message"]
    assert payload["details"]["command"] == "query-object"
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.object.get",
    ]


def test_query_object_rejects_rows_above_requested_take(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [
                    {"id": "{one}"},
                    {"id": "{two}"},
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--take", "1", "--return-field", "id"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["maximum_rows"] == 1
    assert payload["details"]["actual_count"] == 2


def test_query_object_rejects_multiple_rows_for_untransformed_exact_source(tmp_path: Path) -> None:
    path = r"\Events\Wanted"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [
                    {"path": path},
                    {"path": path},
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--path", path, "--return-field", "path"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["maximum_rows"] == 1
    assert payload["details"]["actual_count"] == 2


def test_query_object_all_results_remains_unbounded(tmp_path: Path) -> None:
    rows = [{"id": "{one}"}, {"id": "{two}"}]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": rows},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--all-results", "--return-field", "id"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["objects"] == rows
    assert payload["query_bound"] == {"mode": "all-results-explicit"}


def test_query_object_exact_path_uses_from_object_without_doubled_separators(
    tmp_path: Path,
) -> None:
    path = r"\Actor-Mixer Hierarchy\Default Work Unit\Leaf"
    row = {"id": "{leaf}", "name": "Leaf", "type": "ActorMixer", "path": path}
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": [row]},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--path",
            path,
            "--return-field",
            "id",
            "--return-field",
            "name",
            "--return-field",
            "type",
            "--return-field",
            "path",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["objects"] == [row]
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": r'from object "\Actor-Mixer Hierarchy\Default Work Unit\Leaf"'},
        {"return": ["id", "name", "type", "path"]},
    )


@pytest.mark.parametrize(
    ("argv", "row"),
    (
        (
            ("query-object", "--path", r"\Events\Wanted", "--return-field", "path"),
            {"path": r"/events//WANTED/"},
        ),
        (
            (
                "query-object",
                "--object-id",
                "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "--return-field",
                "id",
            ),
            {"id": "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"},
        ),
    ),
)
def test_exact_query_identity_comparison_normalizes_path_and_guid_case(
    tmp_path: Path,
    argv: tuple[str, ...],
    row: Mapping[str, Any],
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": [row]},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["objects"] == [dict(row)]


@pytest.mark.parametrize(
    ("argv", "row", "identity_field"),
    (
        (
            ("query-object", "--path", r"\Events\Wanted", "--return-field", "path"),
            {"path": r"\Events\Other"},
            "path",
        ),
        (
            (
                "query-object",
                "--object-id",
                "{11111111-1111-1111-1111-111111111111}",
                "--return-field",
                "id",
            ),
            {"id": "{22222222-2222-2222-2222-222222222222}"},
            "id",
        ),
    ),
)
def test_exact_query_rejects_mismatched_returned_identity(
    tmp_path: Path,
    argv: tuple[str, ...],
    row: Mapping[str, Any],
    identity_field: str,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": [row]},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["identity_field"] == identity_field


@pytest.mark.parametrize(
    ("query", "expected_waql"),
    (
        (
            "{22222222-2222-2222-2222-222222222222}",
            'from query "{22222222-2222-2222-2222-222222222222}"',
        ),
        (
            r"\Queries\Shared Queries\Events With Play Actions",
            r'from query "\Queries\Shared Queries\Events With Play Actions"',
        ),
    ),
)
def test_query_object_accepts_only_query_editor_path_or_guid(
    tmp_path: Path,
    query: str,
    expected_waql: str,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": []},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--query", query, "--take", "1", "--return-field", "id"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    bounded_waql = expected_waql + " take 1"
    assert payload["semantic_preview"]["envelope"]["args"] == {"waql": bounded_waql}
    assert payload["query_bound"] == {"mode": "take", "value": 1}
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": bounded_waql},
        {"return": ["id"]},
    )


def test_query_object_help_names_closed_query_editor_specifier_and_selects() -> None:
    parser = waapi_gateway.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if "query-object" in (getattr(action, "choices", None) or {})
    )
    query_parser = subparsers.choices["query-object"]
    help_text = query_parser.format_help()

    assert "QUERY_PATH_OR_GUID" in help_text
    assert "Query Editor object specifier" in help_text
    assert "raw WAQL is not accepted" in help_text
    assert "--all-results" in help_text
    select_action = next(action for action in query_parser._actions if action.dest == "select")
    assert tuple(select_action.choices) == (
        "descendants",
        "ancestors",
        "referencesTo",
        "children",
        "parent",
    )


def test_query_take_and_all_results_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        waapi_gateway.build_parser().parse_args(
            [
                "query-object",
                "--type",
                "Sound",
                "--take",
                "1",
                "--all-results",
            ]
        )


def test_documented_single_quoted_path_reaches_preview_with_single_separators(
    tmp_path: Path,
) -> None:
    query_reference = SCRIPT_PATH.parent.parent / "references" / "waapi-query.md"
    command = next(
        line
        for line in query_reference.read_text(encoding="utf-8").splitlines()
        if "gateway.py query-object --path" in line
    )
    tokens = shlex.split(command)
    argv = tokens[tokens.index("gateway.py") + 1 :]
    documented_path = r"\Events\Default Work Unit"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": []},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert argv[argv.index("--path") + 1] == documented_path
    assert payload["semantic_preview"]["envelope"]["args"] == {
        "waql": r'from object "\Events\Default Work Unit"'
    }


def test_metadata_types_uses_fixed_builder_and_result_parser(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.getTypes": {
                "return": [{"classId": 1, "name": "Sound", "type": "Sound", "extra": "preserved"}]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["metadata", "types"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["operation"] == "types"
    assert payload["normalized"][0]["name"] == "Sound"
    assert payload["normalized"][0]["raw"]["extra"] == "preserved"
    assert "summary_only" not in payload
    assert "agent_result" not in payload
    assert client.calls[-1][0] == "ak.wwise.core.object.getTypes"


def test_metadata_types_summary_only_returns_tail_agent_result_without_inventory(
    tmp_path: Path,
) -> None:
    raw_only_sentinel = "must-not-reach-model-facing-summary"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.getTypes": {
                "return": [
                    {
                        "classId": 1,
                        "name": "ActorMixer",
                        "type": "WObject",
                        "extra": raw_only_sentinel,
                    },
                    {"classId": 2, "name": "Sound", "type": "WObject"},
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["metadata", "types", "--summary-only"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["operation"] == "types"
    assert payload["summary_only"] is True
    assert "normalized" not in payload
    assert payload["semantic_preview"]["envelope"]["uri"] == "ak.wwise.core.object.getTypes"
    assert payload["call"]["api"] == "ak.wwise.core.object.getTypes"
    assert payload["agent_result"] == {
        "count": 2,
        "contains_actor_mixer": True,
    }
    assert list(payload)[-1] == "agent_result"
    assert raw_only_sentinel not in waapi_gateway.gateway_stdout_json_encoder().encode(payload)
    assert client.calls[-1][0] == "ak.wwise.core.object.getTypes"


def test_metadata_types_summary_only_actor_mixer_match_is_case_sensitive(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.getTypes": {
                "return": [
                    {"classId": 1, "name": "actormixer", "type": "WObject"},
                    {"classId": 2, "name": "Sound", "type": "ACTORMIXER"},
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["metadata", "types", "--summary-only"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["agent_result"] == {
        "count": 2,
        "contains_actor_mixer": False,
    }


def test_metadata_types_summary_only_matches_actor_mixer_type_field(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.getTypes": {
                "return": [{"classId": 1, "name": "ActorMixerPlugin", "type": "ActorMixer"}]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["metadata", "types", "--summary-only"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["agent_result"] == {
        "count": 1,
        "contains_actor_mixer": True,
    }


def test_metadata_types_summary_only_still_validates_every_return_row(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.getTypes": {
                "return": [
                    {"classId": 1, "name": "ActorMixer", "type": "WObject"},
                    {"classId": 2, "name": "MalformedWithoutType"},
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["metadata", "types", "--summary-only"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert "agent_result" not in payload
    assert "normalized" not in payload
    assert client.calls[-1][0] == "ak.wwise.core.object.getTypes"


def test_metadata_summary_only_rejects_non_types_before_connecting(tmp_path: Path) -> None:
    client = FakeClient({})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["metadata", "names", "--class-id", "1", "--summary-only"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["command"] == "metadata"
    assert payload["message"] == "metadata --summary-only is supported only for the types operation"
    assert client.calls == []


@pytest.mark.parametrize(
    ("error_message", "expected_source"),
    (
        (
            "ApplicationError(error=<ak.wwise.query.unknown_object>, message='from id object is unknown')",
            "ak.wwise.query.unknown_object",
        ),
        (
            "ApplicationError(error=<ak.wwise.query.invalid_query>, message='Object not found (13)')",
            "ak.wwise.query.invalid_query:object-not-found",
        ),
    ),
)
def test_exact_missing_object_is_normalized_to_empty_rows(
    tmp_path: Path,
    error_message: str,
    expected_source: str,
) -> None:
    missing_id = "{99999999-9999-9999-9999-999999999999}"
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        errors={
            "ak.wwise.core.object.get": WaapiRequestFailed(
                "ak.wwise.query.unknown_object"
                if expected_source == "ak.wwise.query.unknown_object"
                else "ak.wwise.query.invalid_query",
                {"message": "Object not found (13)"},
            )
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--object-id", missing_id, "--return-field", "id"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["count"] == 0
    assert payload["objects"] == []
    assert payload["call"]["ok"] is True
    assert payload["call"]["result"] == {"return": []}
    assert payload["call"]["normalization"]["source"] == expected_source
    assert payload["call"]["normalization"]["original"]["error_code"] == "WaapiRequestFailed"


def test_exact_missing_path_is_normalized_but_transformed_path_is_not() -> None:
    path_query = {"waql": r'from object "\Actor-Mixer Hierarchy\Missing"'}
    transformed = {
        "waql": r'from object "\Actor-Mixer Hierarchy" select descendants'
    }

    assert waapi_gateway._single_exact_lookup(path_query) is False
    assert waapi_gateway._single_exact_lookup(transformed) is False

    normalized = waapi_gateway.normalize_exact_object_absence(
        api="ak.wwise.core.object.get",
        args=path_query,
        result={
            "ok": False,
            "error_code": "WaapiRequestFailed",
            "message": "untrusted rendered application error",
            "waapi_error_uri": "ak.wwise.query.invalid_query",
            "waapi_error_details": {"message": "Object not found (1)"},
        },
        exact_object_lookup=True,
    )
    assert normalized["ok"] is True
    assert normalized["result"] == {"return": []}
    assert normalized["normalization"]["source"] == (
        "ak.wwise.query.invalid_query:object-not-found"
    )


def test_unknown_object_error_is_not_normalized_for_broad_waql(tmp_path: Path) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        errors={
            "ak.wwise.core.object.get": WaapiRequestFailed("ak.wwise.query.unknown_object")
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--take", "1"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["ok"] is False
    assert "normalization" not in payload["call"]


def test_query_object_rejects_raw_waql_before_dispatch(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--query", "from type Sound"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "SemanticValidationError"
    assert payload["details"]["boundary"] == "query-editor-object-specifier"
    assert "raw WAQL is not accepted" in payload["message"]
    assert client.calls == []


@pytest.mark.parametrize("constant", ("NaN", "Infinity", "-Infinity"))
def test_query_object_where_json_rejects_non_json_numbers(tmp_path: Path, constant: str) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--type",
            "Sound",
            "--where-json",
            '{"field":"childrenCount","operator":">","value":' + constant + "}",
            "--take",
            "1",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "strict JSON" in payload["message"]
    assert client.calls == []


def test_query_object_broad_sources_require_explicit_bound_or_all_results(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": []},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )
    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "--take" in payload["message"] and "--all-results" in payload["message"]
    assert client.calls == []

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--all-results"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )
    assert exit_code == 0
    assert payload["query_bound"] == {"mode": "all-results-explicit"}
    assert client.calls[-1][1] == {"waql": "from type Sound"}


def test_exact_absence_requires_structured_waapi_failure_and_canonical_cli_source() -> None:
    exact_args = {"waql": r'from object "\Actor-Mixer Hierarchy\Missing"'}
    impostors = (
        {
            "ok": False,
            "error_code": "RuntimeError",
            "message": "ak.wwise.query.unknown_object Object not found",
            "waapi_error_uri": "ak.wwise.query.unknown_object",
        },
        {
            "ok": False,
            "error_code": "WaapiRequestFailed",
            "message": "Object not found",
            "waapi_error_uri": "ak.wwise.query.invalid_query",
            "waapi_error_details": {"message": "Invalid query syntax"},
        },
        {
            "ok": False,
            "error_code": "WaapiRequestFailed",
            "message": "ak.wwise.query.unknown_object Object not found",
        },
    )
    for result in impostors:
        unchanged = waapi_gateway.normalize_exact_object_absence(
            api="ak.wwise.core.object.get",
            args=exact_args,
            result=result,
            exact_object_lookup=True,
        )
        assert unchanged["ok"] is False
        assert "normalization" not in unchanged

    assert waapi_gateway._canonical_wwise_path(r"\Actor-Mixer Hierarchy\Leaf") is True
    assert waapi_gateway._canonical_wwise_path(r"\\Actor-Mixer Hierarchy\\Leaf") is False
    assert waapi_gateway._canonical_wwise_path("\\Actor-Mixer Hierarchy\nLeaf") is False
    assert waapi_gateway._canonical_guid("{11111111-1111-1111-1111-111111111111}") is True
    assert waapi_gateway._canonical_guid("11111111-1111-1111-1111-111111111111") is False

    legacy_exact = {"from": {"path": [r"\Missing"]}}
    assert waapi_gateway._single_exact_lookup(legacy_exact) is True
    assert waapi_gateway._single_exact_lookup(
        {"from": {"id": ["{11111111-1111-1111-1111-111111111111}"]}}
    ) is True
    assert waapi_gateway._single_exact_lookup({"from": {"path": [r"\One", r"\Two"]}}) is False
    assert waapi_gateway._single_exact_lookup({"from": {"id": [123]}}) is False
    assert waapi_gateway._single_exact_lookup({"from": {"id": ["garbage"]}}) is False
    assert waapi_gateway._single_exact_lookup({"from": {"path": ["relative"]}}) is False
    assert waapi_gateway._single_exact_lookup(
        {"from": {"path": [r"\\Actor-Mixer Hierarchy\\Leaf"]}}
    ) is False


@pytest.mark.parametrize(
    "error_details",
    (
        "Object not found in an untrusted bare string",
        {
            "message": "Invalid query syntax",
            "request_echo": {"note": "object not found"},
        },
        {"details": {"message": "Object not found"}},
    ),
)
def test_exact_absence_does_not_scan_untrusted_nested_or_bare_error_text(
    error_details: object,
) -> None:
    result = {
        "ok": False,
        "error_code": "WaapiRequestFailed",
        "message": "untrusted rendered application error",
        "waapi_error_uri": "ak.wwise.query.invalid_query",
        "waapi_error_details": error_details,
    }

    unchanged = waapi_gateway.normalize_exact_object_absence(
        api="ak.wwise.core.object.get",
        args={"waql": r'from object "\Events\Missing"'},
        result=result,
        exact_object_lookup=True,
    )

    assert unchanged["ok"] is False
    assert "normalization" not in unchanged


def test_wait_topic_uses_payload_match_and_unsubscribes(tmp_path: Path) -> None:
    topic = "ak.wwise.core.object.created"
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        subscription_events={
            topic: [
                {"object": {"id": "wrong", "name": "Ignore"}},
                {"object": {"id": "wanted", "name": "UI"}},
            ]
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "wait-topic", topic, "--match-json", '{"object":{"id":"wanted"}}'],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["event"]["object"]["name"] == "UI"
    assert payload["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1
    assert client.handlers[0].unsubscribe_thread_ident == client.handlers[0].subscribe_thread_ident
    assert client.handlers[0].unsubscribe_thread_ident != threading.get_ident()


def test_wait_topic_accepts_waapi_client_kwargs_only_callback_shape(tmp_path: Path) -> None:
    topic = "ak.wwise.core.object.created"

    class KwargsOnlyEventClient(FakeClient):
        def subscribe(
            self,
            uri: str,
            callback: Any,
            options: Mapping[str, Any] | None = None,
        ) -> FakeEventHandler:
            handler = FakeEventHandler()
            self.handlers.append(handler)
            callback(object={"id": "wrong", "name": "Ignore"})
            callback(object={"id": "wanted", "name": "UI"})
            return handler

    client = KwargsOnlyEventClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "wait-topic", topic, "--match-json", '{"object":{"id":"wanted"}}'],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["event"] == {"object": {"id": "wanted", "name": "UI"}}
    assert payload["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1


def test_wait_topic_oversized_event_reports_completed_unsubscribe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = "ak.wwise.core.object.created"
    sentinel = "OVERSIZED_TOPIC_PAYLOAD_MUST_NOT_ESCAPE"
    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", 2048)

    class OversizedEventClient(FakeClient):
        def subscribe(
            self,
            uri: str,
            callback: Any,
            options: Mapping[str, Any] | None = None,
        ) -> FakeEventHandler:
            handler = FakeEventHandler()
            self.handlers.append(handler)
            callback(blob=sentinel + ("x" * 4096))
            return handler

    client = OversizedEventClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["error_code"] == "RESULT_TOO_LARGE"
    assert payload["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1
    assert sentinel not in json.dumps(payload)


@pytest.mark.parametrize(
    "result",
    (
        {"result": None},
        {
            "result": {
                "topic": "ak.wwise.core.object.created",
                "payload": {"object": {"id": "{wanted}"}},
                "args": (),
                "kwargs": {"object": {"id": "{wanted}"}},
                "unexpected": True,
            }
        },
        {
            "result": {
                "topic": "ak.wwise.core.object.renamed",
                "payload": {"object": {"id": "{wanted}"}},
                "args": (),
                "kwargs": {"object": {"id": "{wanted}"}},
            }
        },
        {
            "result": {
                "topic": "ak.wwise.core.object.created",
                "payload": {"object": {"id": "{different}"}},
                "args": (),
                "kwargs": {"object": {"id": "{wanted}"}},
            }
        },
    ),
)
def test_wait_topic_rejects_malformed_dispatcher_event_envelope(result: Mapping[str, Any]) -> None:
    with pytest.raises(waapi_gateway.GatewayResultShapeError) as caught:
        waapi_gateway.normalize_topic_event_result(
            result,
            expected_topic="ak.wwise.core.object.created",
        )

    assert caught.value.error_code == "INVALID_TOPIC_RESULT"


def test_public_generic_call_routes_reviewed_topics_to_wait_topic_before_connecting(tmp_path: Path) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"topic route rejection must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", "ak.wwise.core.object.created", "--dry-run"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "wait_topic_required"
    assert payload["error_code"] == "WAIT_TOPIC_REQUIRED"
    assert payload["required_command"] == "wait-topic"
    assert payload["executed"] is False
    assert called is False


def test_wait_topic_rejects_debug_assert_topic_before_connecting_or_subscribing(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.debug.assertFailed"
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"excluded topic must not connect or subscribe to {url}")

    assert frozenset(EXPLICIT_UNSUPPORTED_TOPIC_URIS) == EXPECTED_EXCLUDED_TOPIC_URIS

    exit_code, payload = waapi_gateway.execute_gateway(
        ["wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "unsupported_by_skill_interface"
    assert payload["error_code"] == "UNSUPPORTED_BY_SKILL_INTERFACE"
    assert payload["executed"] is False
    assert called is False


@pytest.mark.parametrize(
    ("topic", "event"),
    (
        (
            "ak.wwise.ui.commands.executed",
            {"command": "project.save", "objects": [], "platforms": []},
        ),
        ("ak.wwise.ui.selectionChanged", {"objects": []}),
    ),
)
def test_wait_topic_executes_reviewed_ui_topics_and_unsubscribes(
    tmp_path: Path,
    topic: str,
    event: Mapping[str, Any],
) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        subscription_events={topic: [event]},
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["topic"] == topic
    assert payload["event"] == event
    assert payload["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1


def test_wait_topic_timeout_unsubscribes_on_transport_owner_thread(tmp_path: Path) -> None:
    topic = "ak.wwise.core.object.created"
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.1", "wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["error_code"] == "TIMEOUT"
    assert payload["call"]["details"]["cleanup_pending"] is False
    assert payload["call"]["details"]["deadline_exhausted"] is False
    assert 0 < payload["call"]["details"]["operation_timeout_seconds"] < 0.1
    assert payload["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1
    assert client.handlers[0].unsubscribe_thread_ident == client.handlers[0].subscribe_thread_ident
    assert client.handlers[0].unsubscribe_thread_ident != threading.get_ident()
    assert client.disconnected is True


def test_disconnect_failure_does_not_mask_returned_wait_topic_timeout(tmp_path: Path) -> None:
    topic = "ak.wwise.core.object.created"

    class DisconnectFailureClient(FakeClient):
        def disconnect(self) -> None:
            raise RuntimeError("disconnect must remain secondary")

    client = DisconnectFailureClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.1", "wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["command"] == "wait-topic"
    assert payload["call"]["error_code"] == "TIMEOUT"
    assert payload["cleanup"] == "unsubscribed"
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "RuntimeError",
        "message": "disconnect must remain secondary",
    }
    assert client.handlers[0].unsubscribe_calls == 1


def test_gateway_transport_close_unsubscribes_residual_handlers_on_owner_thread() -> None:
    topic = "ak.wwise.core.object.created"
    client = FakeClient({})
    transport = waapi_gateway.GatewayTransport("ws://127.0.0.1:31337/waapi", lambda url: client)

    subscription = transport.subscribe(topic, lambda event: None)
    assert not hasattr(subscription, "unsubscribe")
    transport.close()

    assert client.handlers[0].unsubscribe_calls == 1
    assert client.handlers[0].unsubscribe_thread_ident == client.handlers[0].subscribe_thread_ident
    assert client.handlers[0].unsubscribe_thread_ident != threading.get_ident()
    assert client.disconnected is True


def test_transport_connect_timeout_returns_within_wall_budget_and_late_factory_cleans_up() -> None:
    release_factory = threading.Event()
    disconnected = threading.Event()

    class LateClient:
        def disconnect(self) -> None:
            disconnected.set()

    def slow_factory(url: str) -> LateClient:
        del url
        release_factory.wait(timeout=2)
        return LateClient()

    deadline = waapi_gateway.GatewayDeadline.start(0.03)
    started_at = time.monotonic()
    with pytest.raises(waapi_gateway.GatewayTimeoutError) as caught:
        waapi_gateway.GatewayTransport(
            "ws://127.0.0.1:31337/waapi",
            slow_factory,
            deadline=deadline,
        )
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.15
    assert caught.value.as_dict()["error_code"] == "TIMEOUT"
    assert caught.value.as_dict()["details"]["phase"] == "transport.connect"
    assert caught.value.as_dict()["details"]["provenance"] == (
        waapi_gateway.GATEWAY_DEADLINE_PROVENANCE
    )
    assert caught.value.as_dict()["details"]["cleanup_pending"] is True

    release_factory.set()
    assert disconnected.wait(timeout=1)


def test_get_info_timeout_is_end_to_end_bounded_and_owner_reaps_after_late_release(tmp_path: Path) -> None:
    entered_call = threading.Event()
    release_call = threading.Event()
    disconnected = threading.Event()

    class BlockingGetInfoClient(FakeClient):
        def call(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
        ) -> Any:
            self.calls.append((uri, args, options))
            entered_call.set()
            release_call.wait(timeout=2)
            return live_info()

        def disconnect(self) -> None:
            super().disconnect()
            disconnected.set()

    client = BlockingGetInfoClient({})
    started_at = time.monotonic()
    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.03", "status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )
    elapsed = time.monotonic() - started_at

    assert entered_call.is_set()
    assert elapsed < 0.2
    assert exit_code == 2
    assert payload["error_code"] == "TIMEOUT"
    assert payload["details"]["phase"] == "version_detection.getInfo"
    assert payload["details"]["cleanup_pending"] is True

    release_call.set()
    assert disconnected.wait(timeout=1)
    deadline = time.monotonic() + 1
    while any(thread.name.startswith("waapi-gateway-owner:") for thread in threading.enumerate()):
        if time.monotonic() >= deadline:
            pytest.fail("gateway owner thread did not reap after the late getInfo call was released")
        time.sleep(0.005)


def test_transport_timeout_discards_late_result_before_next_request() -> None:
    first_entered = threading.Event()
    release_first = threading.Event()

    class OrderedClient(FakeClient):
        def call(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
        ) -> Any:
            self.calls.append((uri, args, options))
            if uri == "first":
                first_entered.set()
                release_first.wait(timeout=2)
                return {"request": "late-first"}
            return {"request": "second"}

    client = OrderedClient({})
    transport = waapi_gateway.GatewayTransport(
        "ws://127.0.0.1:31337/waapi",
        lambda url: client,
        deadline=waapi_gateway.GatewayDeadline.start(1.0),
    )

    with pytest.raises(waapi_gateway.GatewayTimeoutError):
        transport.call_with_timeout("first", timeout=0.02)
    assert first_entered.is_set()

    second_result: list[Any] = []
    second_error: list[BaseException] = []

    def call_second() -> None:
        try:
            second_result.append(transport.call_with_timeout("second", timeout=0.5))
        except BaseException as exc:  # pragma: no cover - asserted through second_error
            second_error.append(exc)

    second_thread = threading.Thread(target=call_second)
    second_thread.start()
    release_first.set()
    second_thread.join(timeout=1)
    transport.close()

    assert not second_thread.is_alive()
    assert second_error == []
    assert second_result == [{"request": "second"}]
    assert client.calls == [("first", None, None), ("second", None, None)]
    assert not transport._thread.is_alive()


def test_timeout_payload_marks_cleanup_complete_when_late_call_releases_in_grace(tmp_path: Path) -> None:
    object_call_entered = threading.Event()
    release_object_call = threading.Event()
    disconnected = threading.Event()

    class GraceReleaseClient(FakeClient):
        def call(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
        ) -> Any:
            self.calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                return live_info()
            object_call_entered.set()
            release_object_call.wait(timeout=2)
            return {"return": [{"id": "late-result-must-be-discarded"}]}

        def disconnect(self) -> None:
            super().disconnect()
            disconnected.set()

    client = GraceReleaseClient({})

    def release_during_cleanup_grace() -> None:
        assert object_call_entered.wait(timeout=1)
        time.sleep(0.04)
        release_object_call.set()

    releaser = threading.Thread(target=release_during_cleanup_grace)
    releaser.start()
    started_at = time.monotonic()
    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.03", "buses"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )
    elapsed = time.monotonic() - started_at
    releaser.join(timeout=1)

    assert not releaser.is_alive()
    assert elapsed < 0.15
    assert exit_code == 2
    assert payload["call"]["error_code"] == "TIMEOUT"
    assert payload["call"]["details"]["provenance"] == (
        waapi_gateway.GATEWAY_DEADLINE_PROVENANCE
    )
    assert payload["call"]["details"]["cleanup_pending"] is False
    assert disconnected.is_set()
    assert "late-result-must-be-discarded" not in json.dumps(payload)


def test_successful_transport_close_does_not_rewrite_third_party_timeout_cleanup(
    tmp_path: Path,
) -> None:
    class LaneTimeout(TimeoutError):
        def as_dict(self) -> dict[str, Any]:
            return {
                "error_code": "TIMEOUT",
                "message": "lane timed out",
                "details": {
                    "phase": "lane.wait",
                    "configured_timeout_seconds": 123.0,
                    "elapsed_seconds": 1.0,
                    "deadline_exhausted": False,
                    "cleanup_pending": True,
                    "abort_requested": True,
                    "lane_marker": "must-preserve",
                },
            }

    class LaneTimeoutClient(FakeClient):
        def __init__(self) -> None:
            super().__init__({})
            self.call_count = 0

        def call(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
        ) -> Any:
            self.calls.append((uri, args, options))
            self.call_count += 1
            if self.call_count == 1:
                return live_info()
            raise LaneTimeout("lane timed out")

    client = LaneTimeoutClient()
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.waapi.getFunctions",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    details = payload["call"]["details"]
    assert details["phase"] == "lane.wait"
    assert details["lane_marker"] == "must-preserve"
    assert details["cleanup_pending"] is True
    assert "provenance" not in details
    assert client.disconnected is True


def test_disconnect_failure_is_attached_without_masking_primary_result_error(
    tmp_path: Path,
) -> None:
    class DisconnectFailureClient(FakeClient):
        def disconnect(self) -> None:
            raise RuntimeError("disconnect failed")

    client = DisconnectFailureClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": {}},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--take", "1"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert "result.return to be an array" in payload["message"]
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "RuntimeError",
        "message": "disconnect failed",
    }


def test_hostile_disconnect_exception_is_safely_attached_to_primary_result_error(
    tmp_path: Path,
) -> None:
    class HostileCleanupError(RuntimeError):
        def __str__(self) -> str:
            raise RuntimeError("cleanup __str__ must not escape")

    class DisconnectFailureClient(FakeClient):
        def disconnect(self) -> None:
            raise HostileCleanupError()

    client = DisconnectFailureClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": {}},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--take", "1"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "ERROR_NORMALIZATION_FAILED",
        "message": "The underlying error could not be normalized safely",
    }


def test_disconnect_failure_does_not_mask_returned_dispatch_error(tmp_path: Path) -> None:
    class DisconnectFailureClient(FakeClient):
        def disconnect(self) -> None:
            raise RuntimeError("disconnect must remain secondary")

    api = "ak.wwise.waapi.getFunctions"
    client = DisconnectFailureClient(
        {"ak.wwise.core.getInfo": live_info()},
        errors={api: WaapiRequestFailed("ak.wwise.transport.closed")},
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", api],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["error_code"] == "WaapiRequestFailed"
    assert payload["call"]["message"] == "untrusted rendered application error"
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "RuntimeError",
        "message": "disconnect must remain secondary",
    }


def test_successful_mutation_result_survives_baseexception_disconnect_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CleanupBaseException(BaseException):
        pass

    class DisconnectFailureClient(FakeClient):
        def disconnect(self) -> None:
            raise CleanupBaseException("disconnect failed after mutation completed")

    transaction_id = "tx-success-close-failure"
    artifact_hash = "a" * 64
    business_result = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "ok": True,
        "status": "executed_unverified",
        "command": "execute",
        "transaction_id": transaction_id,
        "state": "executed_unverified",
        "artifact_hash": artifact_hash,
        "executed": True,
        "verified": False,
        "automatic_retry": False,
        "execution_evidence": {"dispatch_completed": True},
    }

    def completed_mutation(args: Any, **kwargs: Any) -> dict[str, Any]:
        assert args.command == "execute"
        return dict(business_result)

    monkeypatch.setattr(waapi_gateway, "dispatch_command", completed_mutation)
    client = DisconnectFailureClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["execute", transaction_id],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is True
    assert payload["status"] == "executed_unverified"
    assert payload["transaction_id"] == transaction_id
    assert payload["state"] == "executed_unverified"
    assert payload["artifact_hash"] == artifact_hash
    assert payload["executed"] is True
    assert payload["verified"] is False
    assert payload["automatic_retry"] is False
    assert payload["execution_evidence"] == {"dispatch_completed": True}
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "CleanupBaseException",
        "message": "disconnect failed after mutation completed",
    }


def test_baseexception_disconnect_failure_does_not_mask_primary_result_error(
    tmp_path: Path,
) -> None:
    class CleanupBaseException(BaseException):
        pass

    class DisconnectFailureClient(FakeClient):
        def disconnect(self) -> None:
            raise CleanupBaseException("fatal-looking cleanup signal")

    client = DisconnectFailureClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": {}},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--take", "1"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert "result.return to be an array" in payload["message"]
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "CleanupBaseException",
        "message": "fatal-looking cleanup signal",
    }


@pytest.mark.parametrize("timeout", ("nan", "inf", "-inf"))
def test_gateway_rejects_non_finite_timeout_before_transport(tmp_path: Path, timeout: str) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        [f"--timeout={timeout}", "status"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "finite and greater than zero" in payload["message"]
    assert client.calls == []


def test_wait_topic_rejects_function_uri_before_subscription(tmp_path: Path) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["wait-topic", "ak.wwise.core.object.get"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "requires a reflected topic URI" in payload["message"]
    assert client.handlers == []

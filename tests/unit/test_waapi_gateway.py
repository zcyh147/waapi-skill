from __future__ import annotations

import importlib.util
import json
import math
import queue
import shlex
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.semantic.support.codex_filesystem_security import (
    path_is_link_or_reparse,
    private_posix_mode_is_valid,
)

import wwise_waapi.dispatcher as dispatcher_module
from wwise_waapi.builders.query import (  # pyright: ignore[reportMissingImports]
    MAX_ADVANCED_RETURN_EXPRESSION_BYTES,
    MAX_ADVANCED_WAQL_BYTES,
)
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
        "ak.wwise.ui.commands.register",
        "ak.wwise.ui.commands.execute",
    }
)
EXPECTED_EXCLUDED_TOPIC_URIS = frozenset()


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
                    "project_modification_policy": "ask_before_changes",
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
    assert len(json.dumps(payload).encode("utf-8")) < 1536


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
    assert len(json.dumps(payload).encode("utf-8")) < 1536


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


def test_selected_adds_bounded_manifest_validated_return_fields(tmp_path: Path) -> None:
    selected_row = {
        "id": "{11111111-1111-1111-1111-111111111111}",
        "name": "Selected Sound",
        "type": "Sound",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Selected Sound",
        "@Volume": -6.0,
        "parent.name": "Default Work Unit",
    }
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(command_line=False),
            "ak.wwise.ui.getSelectedObjects": {"objects": [selected_row]},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "selected",
            "--return-field",
            "@Volume",
            "--return-field",
            "parent.name",
            "--return-field",
            "@Volume",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["return_fields"] == [
        "id",
        "name",
        "type",
        "path",
        "@Volume",
        "parent.name",
    ]
    assert payload["objects"] == [selected_row]
    assert payload["schema_validation"]["request"]["uri"] == (
        "ak.wwise.ui.getSelectedObjects"
    )
    assert payload["schema_validation"]["result"]["uri"] == (
        "ak.wwise.ui.getSelectedObjects"
    )
    assert client.calls[-1] == (
        "ak.wwise.ui.getSelectedObjects",
        {},
        {
            "return": [
                "id",
                "name",
                "type",
                "path",
                "@Volume",
                "parent.name",
            ]
        },
    )


@pytest.mark.parametrize("return_field", ("", " Volume", "Volume ", "bad\nfield"))
def test_selected_rejects_invalid_return_fields_before_connecting(
    tmp_path: Path,
    return_field: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(url)

    exit_code, payload = waapi_gateway.execute_gateway(
        ["selected", "--return-field", return_field],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert called is False


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
    assert stdout.startswith('{\n  "contract":')
    assert '\n  "details": {\n    "message": "中文"\n  }\n}\n' in stdout
    assert waapi_gateway.gateway_json_document_size(payload) == len(
        stdout.encode("utf-8")
    )
    assert waapi_gateway.probe_gateway_json_document_size(
        payload,
        len(stdout.encode("utf-8")),
    ) == "ok"


def test_main_prints_object_set_operation_schema_as_bounded_compact_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    expected_exit_code, payload = waapi_gateway.execute_gateway(
        ["operation-schema", "object.set"],
        env=env,
    )
    monkeypatch.setattr(
        waapi_gateway,
        "execute_gateway",
        lambda argv: (expected_exit_code, payload),
    )

    exit_code = waapi_gateway.main(["operation-schema", "object.set"])
    stdout = capsys.readouterr().out
    stdout_size = len(stdout.encode("utf-8"))
    parsed = json.loads(
        stdout,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )

    assert exit_code == 0
    assert parsed == payload
    assert list(parsed) == list(payload)
    shell_transport = parsed["request_envelope_policy"]["shell_transport"]
    assert shell_transport == {
        "outer_quoting": "single_quote_entire_compact_json",
        "json_string_serialization": "exactly_once",
        "decoded_value_rules": {
            "embedded_quotes": (
                "ordinary quotation marks with no preceding backslash"
            ),
            "wwise_path_separator": "one backslash",
        },
        "forbidden": [
            "double_escape_json_string_contents",
            "leave_json_escape_backslashes_in_decoded_values",
            "repair_or_retry_invalid_json_in_the_same_turn",
        ],
    }
    assert stdout.count("\n") == 1
    assert stdout == (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
            allow_nan=False,
        )
        + "\n"
    )
    assert stdout_size < 32 * 1024
    assert waapi_gateway.gateway_json_document_size(payload) == stdout_size
    assert (
        waapi_gateway.probe_gateway_json_document_size(payload, stdout_size)
        == "ok"
    )
    assert (
        waapi_gateway.probe_gateway_json_document_size(payload, stdout_size - 1)
        == "too_large"
    )


def test_gateway_import_schemas_share_semantic_import_operation_contract(
    tmp_path: Path,
) -> None:
    env = gateway_env(tmp_path)
    direct_exit_code, direct_payload = waapi_gateway.execute_gateway(
        ["--version", "2022.1", "operation-schema", "audio.import"],
        env=env,
    )
    tab_exit_code, tab_payload = waapi_gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "operation-schema",
            "audio.importTabDelimited",
        ],
        env=env,
    )

    assert direct_exit_code == 0
    assert tab_exit_code == 0
    direct_operation = direct_payload["operation"]
    tab_operation = tab_payload["operation"]
    direct_contract = direct_operation["argument_contract"][
        "request_composition_contract"
    ]["import_operation"]
    dependency_contract = direct_operation["argument_contract"][
        "request_composition_contract"
    ]["metadata_dependency_closure"]
    tab_argument_contract = tab_operation["argument_contract"]

    assert tab_operation["file_read_policy"] == "pass_path_without_reading"
    assert "import_operation" in tab_operation["optional_arguments"]
    assert tab_argument_contract["properties"]["import_operation"][
        "default"
    ] == "createNew"
    assert tab_argument_contract["import_operation_contract"] == direct_contract
    assert direct_contract["contract"] == (
        "waapi-skill.import-operation-intent/v1"
    )
    assert direct_contract["required_when_user_intent_is_explicit"] is True
    assert direct_contract["omission_value_when_user_intent_is_unstated"] == (
        "createNew"
    )
    assert dependency_contract["contract"] == (
        "waapi-skill.live-metadata-dependency-closure/v1"
    )
    assert dependency_contract["selection"]["selected_fields_only"] is True
    assert dependency_contract["metadata_source"]["same_result_required"] is True
    assert dependency_contract["traversal"]["recursive"] is True
    ordinary = dependency_contract["materialization"][
        "ordinary_dependencies"
    ]
    activation = dependency_contract["materialization"][
        "supported_reference_activation"
    ]
    assert ordinary["owner"] == "request"
    assert ordinary["required_values_count"] == 1
    assert ordinary["scope"] == {
        "inherit_selected_owner_scope": True,
        "defaults": "$.arguments.defaults.properties",
        "row": "$.arguments.imports[owner_row_index].properties",
    }
    assert activation["owner"] == "gateway"
    assert activation["supported_shape"] == {
        "dependency_type": "override",
        "action": "Enable",
        "context": "Self",
        "property_type": ["bool", "boolean"],
        "required_value": True,
    }
    assert activation["request_forms"] == {
        "omitted": "accepted_and_derived_before_dispatch",
        "explicit_required_value": "accepted_and_deduplicated",
        "explicit_conflict": "rejected",
    }
    assert activation["scope"] == "same_object_as_reference"
    assert dependency_contract["failure_policy"]["action"] == "stop"
    assert dependency_contract["failure_policy"]["guessing_allowed"] is False
    encoded_contract = json.dumps(
        dependency_contract,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "OutputBus" not in encoded_contract
    assert "OverrideOutput" not in encoded_contract


def test_all_versioned_operation_schemas_fit_complete_compact_output_budget(
    tmp_path: Path,
) -> None:
    operations = tuple(waapi_gateway.list_operation_specs())
    assert operations

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        env = gateway_env(tmp_path / version.replace(".", "-"))
        for operation in operations:
            exit_code, payload = waapi_gateway.execute_gateway(
                [
                    "--version",
                    version,
                    "operation-schema",
                    operation.name,
                ],
                env=env,
            )
            encoded = (
                waapi_gateway.gateway_stdout_json_encoder(payload).encode(payload)
                + "\n"
            )
            encoded_size = len(encoded.encode("utf-8"))

            assert exit_code == 0, (version, operation.name)
            assert encoded.count("\n") == 1, (version, operation.name)
            assert json.loads(encoded) == payload, (version, operation.name)
            assert encoded_size < 32 * 1024, (
                version,
                operation.name,
                encoded_size,
            )
            assert (
                waapi_gateway.gateway_json_document_size(payload) == encoded_size
            ), (version, operation.name)


def test_main_prints_stream_records_as_compact_json_lines(
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    started = {
        "contract": waapi_gateway.TOPIC_STREAM_RECORD_CONTRACT,
        "record_type": "started",
        "topic": "ak.wwise.core.object.created",
    }
    terminal = {
        "contract": waapi_gateway.TOPIC_STREAM_RECORD_CONTRACT,
        "record_type": "terminal",
        "command": "stream-topic",
        "ok": True,
        "status": "completed",
    }

    def fake_execute(
        argv: Any,
        *,
        stream_sink: Any,
    ) -> tuple[int, dict[str, Any]]:
        stream_sink(started)
        return 0, terminal

    monkeypatch.setattr(waapi_gateway, "execute_gateway", fake_execute)

    exit_code = waapi_gateway.main(
        ["stream-topic", "ak.wwise.core.object.created"]
    )
    lines = capsys.readouterr().out.splitlines()

    assert exit_code == 0
    assert [json.loads(line) for line in lines] == [started, terminal]
    assert all("\n" not in line and ": " not in line for line in lines)


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
    ids=(
        "duplicate-key",
        "nan",
        "infinite-number",
        "oversized-string",
        "excessive-depth",
        "excessive-nodes",
        "oversized-document",
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


def test_preview_request_json_has_inline_audio_specific_bounded_limits() -> None:
    inline_value = "x" * (200 * 1024)
    parsed = waapi_gateway.parse_preview_request_object(
        json.dumps({"audio_file_base64": inline_value})
    )
    assert parsed["audio_file_base64"] == inline_value

    with pytest.raises(waapi_gateway.GatewayInputError, match="262144-byte string limit"):
        waapi_gateway.parse_preview_request_object(
            json.dumps({"audio_file_base64": "x" * (256 * 1024 + 1)})
        )

    with pytest.raises(waapi_gateway.GatewayInputError, match="393216-byte JSON input limit"):
        waapi_gateway.parse_preview_request_object(
            json.dumps({"first": "x" * (200 * 1024), "second": "y" * (200 * 1024)})
        )


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
        "config_contract": "waapi-skill.config/v2",
        "ok": True,
        "status": "ok",
        "command": "config-show",
        "offline": True,
        "effective": {
            "wwise_version": None,
            "waapi_host": "127.0.0.1",
            "waapi_port": None,
            "project_modification_policy": "ask_before_changes",
        },
        "source": "defaults",
        "external_path": str(external_path),
        "legacy_fallback_used": False,
        "session_context": {
            "contract": "waapi-skill.session-context/v2",
            "available": False,
            "endpoint": {"host": "127.0.0.1", "port": None, "url": None},
            "adapter_version": None,
            "adapter_version_source": "unavailable",
            "project_modification_policy": "ask_before_changes",
            "available_project_modification_policies": [
                "read_only",
                "ask_before_changes",
                "allow_changes",
            ],
            "one_time_introduction": {
                "contract": "waapi-skill.session-introduction/v2",
                "emit_condition": "visible_conversation_intro_absent",
                "emit_timing": "first_agent_message_after_gateway_result",
                "atomic": True,
                "style": "natural_prose_in_user_language",
                "facts": {
                    "skill_name": "waapi-skill",
                    "endpoint_url": None,
                    "adapter_version": None,
                    "project_modification_policy": "ask_before_changes",
                    "available_project_modification_policies": [
                        "read_only",
                        "ask_before_changes",
                        "allow_changes",
                    ],
                },
                "machine_readable_result_policy": "separate_progress_message",
            },
        },
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
            "allow_changes",
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


@pytest.mark.parametrize(
    ("legacy_policy", "canonical_policy"),
    (
        ("never", "read_only"),
        ("preview_then_confirm", "ask_before_changes"),
        ("allow_with_notice", "allow_changes"),
    ),
)
def test_config_legacy_read_normalizes_policy_alias_and_never_rewrites_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_policy: str,
    canonical_policy: str,
) -> None:
    skill_root = tmp_path / "skill"
    legacy_path = skill_root / "data" / "config.json"
    external_path = tmp_path / "external" / "config.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_payload = {
        "wwise_version": "2023.1",
        "waapi_host": "legacy-host",
        "waapi_port": 8123,
        "project_modification_policy": legacy_policy,
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
    assert shown["effective"]["project_modification_policy"] == canonical_policy
    assert (
        shown["session_context"]["one_time_introduction"]["facts"][
            "project_modification_policy"
        ]
        == canonical_policy
    )

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
        "project_modification_policy": canonical_policy,
    }
    assert legacy_path.read_text(encoding="utf-8") == legacy_text


@pytest.mark.parametrize(
    ("legacy_policy", "canonical_policy"),
    (
        ("never", "read_only"),
        ("preview_then_confirm", "ask_before_changes"),
        ("allow_with_notice", "allow_changes"),
    ),
)
def test_config_set_normalizes_legacy_policy_alias_before_saving(
    tmp_path: Path,
    legacy_policy: str,
    canonical_policy: str,
) -> None:
    external_path = tmp_path / "external" / "config.json"
    env = {"WAAPI_SKILL_CONFIG_PATH": str(external_path)}

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "config-set",
            "--project-modification-policy",
            legacy_policy,
        ],
        env=env,
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["config_contract"] == "waapi-skill.config/v2"
    assert payload["effective"]["project_modification_policy"] == canonical_policy
    assert (
        json.loads(external_path.read_text(encoding="utf-8"))[
            "project_modification_policy"
        ]
        == canonical_policy
    )
    assert (
        payload["session_context"]["one_time_introduction"]["facts"][
            "available_project_modification_policies"
        ]
        == ["read_only", "ask_before_changes", "allow_changes"]
    )


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
                "project_modification_policy": "ask_before_changes",
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
                "project_modification_policy": "read_only",
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
        "project_modification_policy": "ask_before_changes",
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
        "project_modification_policy": "ask_before_changes",
    }


def test_saved_version_hint_mismatch_fails_closed(tmp_path: Path) -> None:
    external_path = tmp_path / "config.json"
    external_path.write_text(
        json.dumps(
            {
                "wwise_version": "2024.1",
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
                "project_modification_policy": "ask_before_changes",
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
                "project_modification_policy": "ask_before_changes",
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


def test_transaction_state_directory_defaults_to_xdg_state_home(
    tmp_path: Path,
) -> None:
    env = gateway_env(tmp_path)
    state_home = tmp_path / "xdg-state"
    env["XDG_STATE_HOME"] = str(state_home)
    env["HOME"] = str(tmp_path / "home")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["transaction-show", "tx-missing"],
        env=env,
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 2
    assert payload["error_code"] == "TransactionNotFound"
    assert (state_home / "waapi-skill" / "transactions").is_dir()
    assert not (tmp_path / "home" / ".local" / "state" / "waapi-skill").exists()


def test_transaction_state_directory_falls_back_to_home(
    tmp_path: Path,
) -> None:
    env = gateway_env(tmp_path)
    home = tmp_path / "home"
    env["HOME"] = str(home)

    exit_code, payload = waapi_gateway.execute_gateway(
        ["transaction-show", "tx-missing"],
        env=env,
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 2
    assert payload["error_code"] == "TransactionNotFound"
    state_dir = home / ".local" / "state" / "waapi-skill"
    assert (state_dir / "transactions").is_dir()
    metadata = state_dir.lstat()
    assert state_dir.is_dir()
    assert path_is_link_or_reparse(state_dir, metadata=metadata) is False
    assert private_posix_mode_is_valid(metadata) is True


def test_relative_xdg_state_home_fails_closed_without_writing(
    tmp_path: Path,
) -> None:
    env = gateway_env(tmp_path)
    env["XDG_STATE_HOME"] = "relative-state"
    env["HOME"] = str(tmp_path / "home")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["transaction-show", "tx-missing"],
        env=env,
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "$XDG_STATE_HOME/waapi-skill must be an absolute path" in payload["message"]
    assert not (tmp_path / "home" / ".local" / "state" / "waapi-skill").exists()


@pytest.mark.parametrize(
    ("argv", "configured_env", "expected_label"),
    (
        (
            ["--state-dir", "", "transaction-show", "tx-missing"],
            None,
            "--state-dir",
        ),
        (
            ["transaction-show", "tx-missing"],
            "",
            "$WAAPI_SKILL_STATE_DIR",
        ),
    ),
)
def test_explicit_empty_transaction_state_override_fails_closed(
    tmp_path: Path,
    argv: list[str],
    configured_env: str | None,
    expected_label: str,
) -> None:
    env = gateway_env(tmp_path)
    env["HOME"] = str(tmp_path / "home")
    if configured_env is not None:
        env["WAAPI_SKILL_STATE_DIR"] = configured_env

    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=env,
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert f"{expected_label} must be a non-empty absolute path" in payload["message"]
    assert not (tmp_path / "home" / ".local" / "state" / "waapi-skill").exists()


def test_transaction_state_directory_precedence_is_flag_env_xdg_home(
    tmp_path: Path,
) -> None:
    env = gateway_env(tmp_path)
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_STATE_HOME": str(tmp_path / "xdg"),
            "WAAPI_SKILL_STATE_DIR": str(tmp_path / "env-state"),
        }
    )
    with_flag = waapi_gateway.build_parser().parse_args(
        [
            "--state-dir",
            str(tmp_path / "flag-state"),
            "transaction-show",
            "tx-missing",
        ]
    )
    without_flag = waapi_gateway.build_parser().parse_args(
        ["transaction-show", "tx-missing"]
    )

    assert waapi_gateway.resolve_transaction_state_directory(
        with_flag,
        env=env,
    ) == (tmp_path / "flag-state").resolve()
    assert waapi_gateway.resolve_transaction_state_directory(
        without_flag,
        env=env,
    ) == (tmp_path / "env-state").resolve()
    env_without_override = {
        key: value
        for key, value in env.items()
        if key != "WAAPI_SKILL_STATE_DIR"
    }
    assert waapi_gateway.resolve_transaction_state_directory(
        without_flag,
        env=env_without_override,
    ) == (tmp_path / "xdg" / "waapi-skill").resolve()
    env_without_xdg = {
        key: value
        for key, value in env_without_override.items()
        if key != "XDG_STATE_HOME"
    }
    assert waapi_gateway.resolve_transaction_state_directory(
        without_flag,
        env=env_without_xdg,
    ) == (tmp_path / "home" / ".local" / "state" / "waapi-skill").resolve()


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


def test_legacy_never_policy_normalizes_to_read_only_and_blocks_confirm_without_connecting(
    tmp_path: Path,
) -> None:
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
    assert payload["message"] == (
        "project_modification_policy=read_only blocks transaction confirmation"
    )


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
        "available": 268,
        "available_via_transaction": 540,
        "unsupported_by_skill_interface": 6,
    }
    assert payload["summary"]["totals"]["preferred_routes"] == {
        "bounded_topic_wait": 152,
        "fixed_command": 56,
        "manifest_dispatch": 60,
        "transaction_operation": 540,
        "unsupported_boundary": 6,
    }
    assert payload["match_count"] == 814
    assert payload["returned_count"] == 0
    assert payload["truncated"] is False
    assert "capabilities" not in payload


def test_object_types_searches_packaged_catalog_without_connecting(
    tmp_path: Path,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"offline object type catalog must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "--version",
            "2022.1",
            "object-types",
            "--query",
            "audio source",
            "--object-type",
            "WObject",
            "--limit",
            "5",
        ],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 0
    assert called is False
    assert payload["offline"] is True
    assert payload["versions"] == ["2022.1"]
    catalog = payload["catalogs"]["2022.1"]
    assert catalog["row_count"] == 107
    assert catalog["types"][0]["name"] == "AudioFileSource"
    assert catalog["returned_count"] <= 5
    assert len(json.dumps(payload).encode("utf-8")) < 8_000

    for filtered_summary in (
        ["--query", "Sound"],
        ["--object-type", "WObject"],
    ):
        exit_code, rejected = waapi_gateway.execute_gateway(
            [
                "--version",
                "2022.1",
                "object-types",
                "--summary-only",
                *filtered_summary,
            ],
            env=gateway_env(tmp_path),
            client_factory=client_factory,
        )
        assert exit_code == 2
        assert rejected["error_code"] == "GatewayInputError"
        assert "--summary-only cannot be combined" in rejected["message"]
        assert called is False


def test_metadata_transaction_cache_is_bound_to_exact_live_session(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        calls.append((uri, args, options))
        return {
            "name": "Volume",
            "type": "Real32",
            "restriction": {"min": -96.3, "max": 12.0},
        }

    connection = waapi_gateway.GatewayConnection(
        host="127.0.0.1",
        port=8080,
        version_hint="2022.1",
        evidence_dir=None,
        timeout=10.0,
        deadline=waapi_gateway.GatewayDeadline.start(10.0),
    )
    info = {
        "processId": 4242,
        "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "version": {
            "build": 8584,
            "major": 1,
            "minor": 19,
            "schema": 110,
            "year": 2022,
        },
    }
    project = {"id": PROJECT_GUID}
    waapi_gateway._METADATA_SESSION_CACHE.clear()
    cached = waapi_gateway.metadata_cached_transaction_read_call(
        read,
        connection=connection,
        version="2022.1",
        live_info=info,
        project=project,
        state_dir=tmp_path,
    )
    call_args = {"classId": 65552, "property": "Volume"}

    assert cached("ak.wwise.core.object.getPropertyInfo", call_args, {})[
        "name"
    ] == "Volume"
    assert cached("ak.wwise.core.object.getPropertyInfo", call_args, {})[
        "name"
    ] == "Volume"
    assert len(calls) == 1

    # A fresh in-memory layer simulates the next gateway CLI process.  The
    # exact live-session identity still reuses the validated durable entry.
    waapi_gateway._METADATA_SESSION_CACHE.clear()
    next_process = waapi_gateway.metadata_cached_transaction_read_call(
        read,
        connection=connection,
        version="2022.1",
        live_info=info,
        project=project,
        state_dir=tmp_path,
    )
    assert next_process(
        "ak.wwise.core.object.getPropertyInfo",
        call_args,
        {},
    )["name"] == "Volume"
    assert len(calls) == 1

    changed_session = dict(info)
    changed_session["sessionId"] = "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}"
    other = waapi_gateway.metadata_cached_transaction_read_call(
        read,
        connection=connection,
        version="2022.1",
        live_info=changed_session,
        project=project,
        state_dir=tmp_path,
    )
    other("ak.wwise.core.object.getPropertyInfo", call_args, {})
    assert len(calls) == 2

    invalid_calls = 0

    def invalid_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        nonlocal invalid_calls
        invalid_calls += 1
        return {"name": "DifferentProperty", "type": "Real32"}

    invalid_args = {"classId": 65552, "property": "Pitch"}
    for _ in range(2):
        waapi_gateway._METADATA_SESSION_CACHE.clear()
        invalid = waapi_gateway.metadata_cached_transaction_read_call(
            invalid_read,
            connection=connection,
            version="2022.1",
            live_info=info,
            project=project,
            state_dir=tmp_path,
        )
        invalid(
            "ak.wwise.core.object.getPropertyInfo",
            invalid_args,
            {},
        )
    assert invalid_calls == 2

    object_calls = 0

    def object_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        nonlocal object_calls
        object_calls += 1
        return {"name": "Volume", "type": "Real32"}

    object_args = {
        "object": r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
        "property": "Volume",
    }
    object_preview = waapi_gateway.metadata_cached_transaction_read_call(
        object_read,
        connection=connection,
        version="2022.1",
        live_info=info,
        project=project,
        state_dir=tmp_path,
    )
    object_preview(
        "ak.wwise.core.object.getPropertyInfo",
        object_args,
        {},
    )
    object_preview(
        "ak.wwise.core.object.getPropertyInfo",
        object_args,
        {},
    )
    assert object_calls == 1
    next_object_preview = waapi_gateway.metadata_cached_transaction_read_call(
        object_read,
        connection=connection,
        version="2022.1",
        live_info=info,
        project=project,
        state_dir=tmp_path,
    )
    next_object_preview(
        "ak.wwise.core.object.getPropertyInfo",
        object_args,
        {},
    )
    assert object_calls == 2
    waapi_gateway._METADATA_SESSION_CACHE.clear()


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
    assert compact["execution_contract"]["contract"] == "waapi-skill.public-execution-contract/v2"
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
    assert capability["interface"]["gateway_commands"] == [
        "status",
        "project-default-work-units",
    ]
    assert "semantic_builder_ref" not in capability["interface"]
    assert capability["schema"]["status"] == "ok"
    assert "full" not in capability["schema"]
    assert payload["schema_detail"] == "summary"


def test_describe_returns_uri_specific_selection_guidance_without_connecting(
    tmp_path: Path,
) -> None:
    connections: list[str] = []

    def fail_if_connected(url: str) -> Any:
        connections.append(url)
        raise AssertionError(url)

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "describe",
            "ak.soundengine.setRTPCValue",
        ],
        env=gateway_env(tmp_path),
        client_factory=fail_if_connected,
    )

    assert exit_code == 0
    assert connections == []
    guidance = payload["availability"]["2025.1"]["capability"]["interface"][
        "selection_guidance"
    ]
    assert guidance["domain"] == "runtime_soundengine"
    assert guidance["choose_instead"][0]["target"] == "object.setRTPC"
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) < 16_000


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
def test_legacy_ui_command_exclusions_now_route_to_named_transactions_before_connecting(
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
    assert payload["status"] == "transaction_required"
    assert payload["error_code"] == "TRANSACTION_REQUIRED"
    assert payload["capability"]["interface"]["transaction_operations"] == [
        {
            "ak.wwise.ui.commands.execute": "ui.commands.execute",
            "ak.wwise.ui.commands.register": "ui.commands.register",
        }[api]
    ]
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


def test_media_pool_get_is_a_bounded_direct_read(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.mediaPool.get": {"return": []},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.mediaPool.get",
            "--args-json",
            '{"databases":["\\\\Databases\\\\Project Originals"],"maxResults":20}',
            "--options-json",
            '{"return":["Path","FileId","Db"]}',
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["agent_result"] == {"return": []}
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.mediaPool.get",
    ]


def test_media_pool_post_filter_is_case_sensitive_bounded_and_preserves_order(
    tmp_path: Path,
) -> None:
    rows = [
        {"Filename": "footstep_gravel.wav", "FileId": "first"},
        {"Filename": "Footstep_case_decoy.wav", "FileId": "decoy"},
        {"Filename": "short_footstep_wood.wav", "FileId": "second"},
        {"Filename": "footstep_metal.wav", "FileId": "third"},
    ]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.mediaPool.get": {"return": rows},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    request = {
        "databases": [r"\Databases\Project Originals"],
        "filters": [
            {
                "type": "field",
                "field": "Filename",
                "operator": "contains",
                "value": "footstep",
            }
        ],
        "maxResults": 5,
    }
    post_filter = {
        "field": "Filename",
        "operator": "containsCaseSensitive",
        "value": "footstep",
        "limit": 2,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.mediaPool.get",
            "--args-json",
            json.dumps(request),
            "--options-json",
            json.dumps({"return": ["Filename", "FileId"]}),
            "--post-filter-json",
            json.dumps(post_filter),
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"] == {"return": [rows[0], rows[2]]}
    assert list(payload)[-1] == "agent_result"
    assert client.calls[-1][1] == request
    assert client.calls[-1][2] == {"return": ["Filename", "FileId"]}
    audit = payload["post_filter"]
    assert audit == {
        "contract": "waapi-skill.media-pool-post-filter/v1",
        "status": "applied",
        "field": "Filename",
        "operator": "containsCaseSensitive",
        "value_sha256": audit["value_sha256"],
        "value_code_points": len("footstep"),
        "value_utf8_bytes": len("footstep".encode("utf-8")),
        "limit": 2,
        "request_max_results": 5,
        "raw_count": 4,
        "matched_count": 3,
        "returned_count": 2,
        "truncated_to_limit": True,
    }
    assert len(audit["value_sha256"]) == 64
    assert "value" not in audit


def test_media_pool_post_filter_fails_closed_when_candidate_result_reaches_ceiling(
    tmp_path: Path,
) -> None:
    rows = [
        {"Filename": "footstep_gravel.wav", "FileId": "first"},
        {"Filename": "unrelated.wav", "FileId": "second"},
        {"Filename": "Footstep_case_decoy.wav", "FileId": "third"},
    ]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.mediaPool.get": {"return": rows},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    request = {
        "filters": [
            {
                "type": "field",
                "field": "Filename",
                "operator": "contains",
                "value": "footstep",
            }
        ],
        "maxResults": 3,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.mediaPool.get",
            "--args-json",
            json.dumps(request),
            "--options-json",
            json.dumps({"return": ["Filename", "FileId"]}),
            "--post-filter-json",
            json.dumps(
                {
                    "field": "Filename",
                    "operator": "containsCaseSensitive",
                    "value": "footstep",
                    "limit": 2,
                }
            ),
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["status"] == "incomplete_boundary"
    assert payload["error_code"] == "MEDIA_POOL_POST_FILTER_INCOMPLETE"
    assert payload["details"]["raw_count"] == 3
    assert payload["details"]["request_max_results"] == 3
    assert payload["call"]["ok"] is True
    assert payload["post_filter"]["status"] == "incomplete"
    assert payload["post_filter"]["raw_count"] == 3
    assert payload["post_filter"]["matched_count"] is None
    assert payload["post_filter"]["truncated_to_limit"] is None
    assert "agent_result" not in payload


def test_media_pool_post_filter_does_not_project_agent_result_when_waapi_fails(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info(year=2025, major=1)},
        errors={"ak.wwise.core.mediaPool.get": RuntimeError("synthetic read failure")},
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.mediaPool.get",
            "--args-json",
            json.dumps(
                {
                    "filters": [
                        {
                            "type": "field",
                            "field": "Filename",
                            "operator": "contains",
                            "value": "footstep",
                        }
                    ],
                    "maxResults": 20,
                }
            ),
            "--options-json",
            json.dumps({"return": ["Filename", "FileId"]}),
            "--post-filter-json",
            json.dumps(
                {
                    "field": "Filename",
                    "operator": "containsCaseSensitive",
                    "value": "footstep",
                    "limit": 2,
                }
            ),
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["call"]["ok"] is False
    assert payload["post_filter"]["status"] == "not_applied"
    assert payload["post_filter"]["truncated_to_limit"] is None
    assert "agent_result" not in payload


@pytest.mark.parametrize(
    ("api", "post_filter", "request_args", "options", "extra_argv", "message_fragment"),
    (
        (
            "ak.wwise.waapi.getFunctions",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "footstep", "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 20},
            {"return": ["Filename"]},
            (),
            "supported only",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Path", "operator": "containsCaseSensitive", "value": "footstep", "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 20},
            {"return": ["Filename"]},
            (),
            "field must be exactly",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "matchesRegex", "value": "footstep", "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 20},
            {"return": ["Filename"]},
            (),
            "operator must be exactly",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "footstep", "limit": 2, "code": "malicious"},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 20},
            {"return": ["Filename"]},
            (),
            "extra keys",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "", "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": ""}], "maxResults": 20},
            {"return": ["Filename"]},
            (),
            "nonempty string",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "footstep", "limit": True},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 20},
            {"return": ["Filename"]},
            (),
            "limit must be an integer",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "footstep", "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "other"}], "maxResults": 20},
            {"return": ["Filename"]},
            (),
            "matching Filename contains",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "footstep", "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 20},
            {"return": ["FileId"]},
            (),
            "return to include",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "footstep", "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 20},
            {},
            (),
            "return to include",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "x" * 1025, "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "x" * 1025}], "maxResults": 20},
            {"return": ["Filename"]},
            (),
            "code-point literal limit",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "footstep", "limit": 3},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 2},
            {"return": ["Filename"]},
            (),
            "greater than or equal",
        ),
        (
            "ak.wwise.core.mediaPool.get",
            {"field": "Filename", "operator": "containsCaseSensitive", "value": "footstep", "limit": 2},
            {"filters": [{"type": "field", "field": "Filename", "operator": "contains", "value": "footstep"}], "maxResults": 20},
            {"return": ["Filename"]},
            ("--dry-run",),
            "cannot be combined",
        ),
    ),
    ids=(
        "other-api",
        "wrong-field",
        "wrong-operator",
        "extra-key",
        "empty-value",
        "boolean-limit",
        "unbound-filter",
        "missing-return-field",
        "missing-return-mapping",
        "oversized-literal",
        "limit-exceeds-max-results",
        "dry-run",
    ),
)
def test_media_pool_post_filter_rejects_invalid_or_unbound_input_before_connection(
    tmp_path: Path,
    api: str,
    post_filter: Mapping[str, Any],
    request_args: Mapping[str, Any],
    options: Mapping[str, Any],
    extra_argv: tuple[str, ...],
    message_fragment: str,
) -> None:
    factory_calls: list[str] = []

    def forbidden_factory(url: str) -> FakeClient:
        factory_calls.append(url)
        raise AssertionError("invalid post-filter input must not open a WAAPI transport")

    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            api,
            "--args-json",
            json.dumps(request_args),
            "--options-json",
            json.dumps(options),
            "--post-filter-json",
            json.dumps(post_filter),
            *extra_argv,
        ],
        env=env,
        client_factory=forbidden_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert message_fragment in payload["message"]
    assert factory_calls == []


@pytest.mark.parametrize(
    ("post_filter_json", "message_fragment"),
    (
        ("[]", "must decode to a JSON object"),
        (
            '{"field":"Filename","field":"Path","operator":"containsCaseSensitive",'
            '"value":"footstep","limit":2}',
            "duplicate JSON key",
        ),
    ),
    ids=("non-object", "duplicate-key"),
)
def test_media_pool_post_filter_rejects_malformed_documents_before_connection(
    tmp_path: Path,
    post_filter_json: str,
    message_fragment: str,
) -> None:
    factory_calls: list[str] = []

    def forbidden_factory(url: str) -> FakeClient:
        factory_calls.append(url)
        raise AssertionError("malformed post-filter input must not connect")

    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.mediaPool.get",
            "--args-json",
            json.dumps(
                {
                    "filters": [
                        {
                            "type": "field",
                            "field": "Filename",
                            "operator": "contains",
                            "value": "footstep",
                        }
                    ],
                    "maxResults": 20,
                }
            ),
            "--options-json",
            json.dumps({"return": ["Filename"]}),
            "--post-filter-json",
            post_filter_json,
        ],
        env=env,
        client_factory=forbidden_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert message_fragment in payload["message"]
    assert factory_calls == []


@pytest.mark.parametrize(
    "raw_result",
    (
        {},
        {"return": {}},
        {"return": [[]]},
        {"return": [{"Filename": 7}]},
        {"return": [], "unexpected": True},
    ),
    ids=(
        "missing-return",
        "return-not-array",
        "row-not-object",
        "filename-not-string",
        "extra-top-level-key",
    ),
)
def test_media_pool_post_filter_rejects_invalid_success_result_shapes(raw_result: Any) -> None:
    with pytest.raises(waapi_gateway.GatewayResultShapeError) as exc_info:
        waapi_gateway.apply_media_pool_post_filter(
            raw_result,
            spec={
                "field": "Filename",
                "operator": "containsCaseSensitive",
                "value": "footstep",
                "limit": 2,
            },
            request_max_results=20,
            evidence_path="evidence.json",
        )

    assert exc_info.value.error_code == "INVALID_MEDIA_POOL_POST_FILTER_RESULT"


def test_media_pool_get_canonicalizes_only_duration_whole_seconds_before_dispatch(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.mediaPool.get": {"return": []},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    request = {
        "databases": [r"\Databases\Project Originals"],
        "filters": [
            {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "lessThanOrEqual",
                "value": 8,
            },
            {
                "type": "field",
                "field": "WAV/Sample Rate",
                "operator": "equals",
                "value": 48000,
            },
            {
                "type": "field",
                "field": "WAV/Channels",
                "operator": "equals",
                "value": 1,
            },
            {
                "type": "field",
                "field": "WAV/Bit Depth",
                "operator": "equals",
                "value": 24,
            },
        ],
        "maxResults": 40,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.mediaPool.get",
            "--args-json",
            json.dumps(request),
            "--options-json",
            json.dumps({"return": ["Path", "WAV/Duration"]}),
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    dispatched = client.calls[-1][1]
    assert dispatched is not None
    dispatched_filters = dispatched["filters"]
    assert type(dispatched_filters[0]["value"]) is float
    assert dispatched_filters[0]["value"] == 8.0
    assert [type(item["value"]) for item in dispatched_filters[1:]] == [int, int, int]
    assert type(dispatched["maxResults"]) is int


def test_media_pool_duration_canonicalizer_is_exactly_scoped_and_does_not_mutate_input() -> None:
    request = {
        "filters": [
            {"type": "field", "field": "WAV/Duration", "operator": "equals", "value": 8},
            {"type": "field", "field": "WAV/Sample Rate", "operator": "equals", "value": 48000},
            {"type": "field", "field": "WAV/Channels", "operator": "equals", "value": 1},
            {"type": "field", "field": "WAV/Bit Depth", "operator": "equals", "value": 24},
            {"type": "field", "field": "wav/duration", "operator": "equals", "value": 8},
            {"type": "audioDescription", "field": "WAV/Duration", "value": 8},
        ],
        "maxResults": 40,
    }
    original = json.loads(json.dumps(request))

    normalized = waapi_gateway.canonicalize_bounded_direct_call_request(
        "ak.wwise.core.mediaPool.get",
        "2025.1",
        request,
    )

    assert request == original
    assert type(request["filters"][0]["value"]) is int
    assert type(normalized["filters"][0]["value"]) is float
    assert [type(item["value"]) for item in normalized["filters"][1:]] == [
        int,
        int,
        int,
        int,
        int,
    ]
    assert type(normalized["maxResults"]) is int

    wrong_version = waapi_gateway.canonicalize_bounded_direct_call_request(
        "ak.wwise.core.mediaPool.get",
        "2024.1",
        request,
    )
    other_api = waapi_gateway.canonicalize_bounded_direct_call_request(
        "ak.wwise.core.object.diff",
        "2025.1",
        request,
    )
    assert type(wrong_version["filters"][0]["value"]) is int
    assert type(other_api["filters"][0]["value"]) is int


def test_media_pool_filter_families_use_closed_practical_shapes(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

    waapi_gateway.validate_bounded_direct_call_request(
        "ak.wwise.core.mediaPool.get",
        {
            "filters": [
                {
                    "type": "field",
                    "field": "WAV/Duration",
                    "operator": "lessThanOrEqual",
                    "value": 8.0,
                },
                {
                    "type": "audioDescription",
                    "value": "short dry stone footstep",
                    # The Wwise 2025 SDK's type-specific example uses this shape.
                    "weight": 0.8,
                },
                {
                    "type": "audioSimilarity",
                    "value": str(reference),
                    "weight": 0.75,
                },
            ],
            "databases": [r"\Databases\Project Originals"],
            "maxResults": 40,
        },
        {"return": ["Path", "Filename", "WAV/Duration"]},
    )


@pytest.mark.parametrize("weight", (0.0, 0.8, 1.0))
def test_media_pool_audio_description_accepts_finite_weight_boundaries(
    weight: float,
) -> None:
    waapi_gateway.validate_bounded_direct_call_request(
        "ak.wwise.core.mediaPool.get",
        {
            "filters": [
                {
                    "type": "audioDescription",
                    "value": "short dry stone footstep",
                    "weight": weight,
                }
            ],
            "maxResults": 40,
        },
        {"return": ["Path"]},
    )


@pytest.mark.parametrize(
    ("filter_factory", "message"),
    [
        (
            lambda path: {
                "type": "field",
                "field": "Filename",
                "operator": "contains",
                "value": "footstep",
                "weight": 0.5,
            },
            "closed field filter shape",
        ),
        (
            lambda path: {
                "type": "audioDescription",
                "value": "footstep",
                "field": "Filename",
            },
            "closed audioDescription filter shape",
        ),
        (
            lambda path: {
                "type": "audioSimilarity",
                "value": str(path),
                "field": "Filename",
            },
            "closed audioSimilarity filter shape",
        ),
        (
            lambda path: {
                "type": "audioSimilarity",
                "value": str(path),
                "weight": 1.01,
            },
            "from 0 through 1",
        ),
        (
            lambda path: {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "equals",
                "value": 2**1024,
            },
            "finite number",
        ),
        (
            lambda path: {
                "type": "audioSimilarity",
                "value": str(path),
                "weight": 2**1024,
            },
            "finite number from 0 through 1",
        ),
        (
            lambda path: {
                "type": "audioSimilarity",
                "value": "relative.wav",
            },
            "absolute regular audio-file path",
        ),
    ],
)
def test_media_pool_filter_shapes_fail_closed(
    tmp_path: Path,
    filter_factory: Any,
    message: str,
) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    with pytest.raises(waapi_gateway.GatewayInputError, match=message):
        waapi_gateway.validate_bounded_direct_call_request(
            "ak.wwise.core.mediaPool.get",
            {
                "filters": [filter_factory(reference)],
                "maxResults": 40,
            },
            {"return": ["Path"]},
        )


@pytest.mark.parametrize(
    "weight",
    (
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(2**1024, id="double-overflow-integer"),
        pytest.param(-0.01, id="below-range"),
        pytest.param(1.01, id="above-range"),
    ),
)
def test_media_pool_audio_description_rejects_invalid_weight(
    weight: float | int,
) -> None:
    with pytest.raises(
        waapi_gateway.GatewayInputError,
        match="finite number from 0 through 1",
    ):
        waapi_gateway.validate_bounded_direct_call_request(
            "ak.wwise.core.mediaPool.get",
            {
                "filters": [
                    {
                        "type": "audioDescription",
                        "value": "short dry stone footstep",
                        "weight": weight,
                    }
                ],
                "maxResults": 40,
            },
            {"return": ["Path"]},
        )


def test_media_pool_audio_similarity_rejects_symlink_and_missing_file(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    link = tmp_path / "reference-link.wav"
    create_symlink_or_skip(link, reference)

    for value in (link, tmp_path / "missing.wav"):
        with pytest.raises(waapi_gateway.GatewayInputError):
            waapi_gateway.validate_bounded_direct_call_request(
                "ak.wwise.core.mediaPool.get",
                {
                    "filters": [
                        {
                            "type": "audioSimilarity",
                            "value": str(value),
                        }
                    ],
                    "maxResults": 40,
                },
                {"return": ["Path"]},
            )


@pytest.mark.parametrize(
    "duration",
    (2**53 + 1, 2**1024),
    ids=("precision-loss", "double-overflow"),
)
def test_media_pool_duration_canonicalization_fails_closed_before_business_dispatch(
    tmp_path: Path,
    duration: int,
) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info(year=2025, major=1)})
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    request = {
        "filters": [
            {
                "type": "field",
                "field": "WAV/Duration",
                "operator": "lessThanOrEqual",
                "value": duration,
            }
        ],
        "maxResults": 40,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.mediaPool.get",
            "--args-json",
            json.dumps(request),
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "exactly representable as a finite WAAPI double" in payload["message"]
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize("max_results", (None, 0, 201, True))
def test_media_pool_get_rejects_an_unbounded_result_request_before_business_dispatch(
    tmp_path: Path,
    max_results: Any,
) -> None:
    client = FakeClient({"ak.wwise.core.getInfo": live_info(year=2025, major=1)})
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    request = {} if max_results is None else {"maxResults": max_results}

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "call",
            "ak.wwise.core.mediaPool.get",
            "--args-json",
            json.dumps(request),
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] in {"GatewayInputError", "SemanticValidationError"}
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
    assert payload["capability"]["interface"]["transaction_operations"] == [
        "soundbank.generate",
    ]
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
    assert payload["query_bound"] == {"mode": "take", "value": 10}
    assert "semantic_preview" not in payload
    assert "call" not in payload
    assert list(payload)[-1] == "session_context"
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": 'from type Sound where name : "UI" take 10'},
        {"return": ["id", "name", "type", "path"]},
    )


def test_query_object_detail_restores_compiler_and_dispatch_evidence(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": []},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--take", "1", "--detail"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["semantic_preview"]["source_note_family"] == "query"
    assert payload["semantic_preview"]["envelope"]["args"] == {
        "waql": "from type Sound take 1"
    }
    assert payload["call"]["api"] == "ak.wwise.core.object.get"
    assert payload["call"]["ok"] is True


def test_query_object_success_projection_preserves_terminal_agent_result_exactly() -> None:
    agent_result = {"contract": "example/v1", "objects": [{"id": "{one}"}]}
    full = {
        "contract": waapi_gateway.GATEWAY_RESULT_CONTRACT,
        "ok": True,
        "status": "ok",
        "command": "query-object",
        "detected_version": "2022.1",
        "query_bound": {"mode": "take", "value": 1},
        "semantic_preview": {"compiled": "private-detail"},
        "call": {"evidence_path": "/private/evidence.json"},
        "count": 1,
        "objects": [{"id": "{one}"}],
        "agent_result": agent_result,
    }

    compact = waapi_gateway.project_successful_query_object_payload(
        full,
        detail=False,
    )

    assert "semantic_preview" not in compact
    assert "call" not in compact
    assert compact["agent_result"] is agent_result
    assert list(compact)[-1] == "agent_result"
    assert waapi_gateway.project_successful_query_object_payload(
        full,
        detail=True,
    ) == full


def test_query_object_cleanup_failure_keeps_complete_success_evidence(
    tmp_path: Path,
) -> None:
    class DisconnectFailureClient(FakeClient):
        def disconnect(self) -> None:
            raise RuntimeError("disconnect failed after query")

    client = DisconnectFailureClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": []},
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--type", "Sound", "--take", "1"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is True
    assert payload["semantic_preview"]["source_note_family"] == "query"
    assert payload["call"]["ok"] is True
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "RuntimeError",
        "message": "disconnect failed after query",
    }


def test_query_schema_returns_five_version_closed_contract_without_connecting(
    tmp_path: Path,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"offline query-schema must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-schema", "--all-versions"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 0
    assert called is False
    assert payload["query_contract"] == "waapi-skill.object-query/v1"
    assert tuple(payload["versions"]) == tuple(SUPPORTED_WWISE_VERSION_KEYS)
    assert set(payload["schemas"]) == set(SUPPORTED_WWISE_VERSION_KEYS)
    assert {
        schema["x-wwise-version"]
        for schema in payload["schemas"].values()
    } == set(SUPPORTED_WWISE_VERSION_KEYS)
    serialized = json.dumps(payload["schemas"], sort_keys=True)
    assert '"waql"' not in serialized
    assert '"raw"' not in serialized
    assert payload["boundary"]["raw_waql_accepted"] is False


def test_query_schema_advanced_discloses_bounded_native_contract_offline(
    tmp_path: Path,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"offline advanced query schema must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-schema", "--advanced", "--all-versions"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 0
    assert called is False
    assert payload["query_layer"] == "advanced-native-waql"
    assert payload["query_contract"] == "waapi-skill.advanced-object-query/v1"
    assert tuple(payload["versions"]) == tuple(SUPPORTED_WWISE_VERSION_KEYS)
    assert set(payload["schemas"]) == set(SUPPORTED_WWISE_VERSION_KEYS)
    assert payload["boundary"] == {
        "fixed_api": "ak.wwise.core.object.get",
        "read_only": True,
        "native_waql_accepted": True,
        "gateway_appends_final_take": True,
        "all_results_available": False,
        "arbitrary_uri_args_or_options_accepted": False,
        "gateway_json_input_bytes": waapi_gateway.MAX_GATEWAY_JSON_INPUT_BYTES,
        "gateway_result_bytes": waapi_gateway.MAX_GATEWAY_RESULT_JSON_BYTES,
        "version_specific_syntax_validated_by": "connected Wwise",
        "fallback_or_retry_on_invalid_query": False,
    }
    for schema in payload["schemas"].values():
        waql = schema["properties"]["waql"]
        expression = schema["properties"]["return"]["items"]
        assert waql["x-maxUtf8Bytes"] == MAX_ADVANCED_WAQL_BYTES
        assert waql["x-framing"] == {
            "trimmed": True,
            "singleLine": True,
            "queryEditorDollarPrefix": False,
            "comments": False,
            "statementSeparators": False,
            "balancedDoubleQuotedStrings": True,
            "balancedSlashRegexLiterals": True,
        }
        assert expression["x-maxUtf8Bytes"] == MAX_ADVANCED_RETURN_EXPRESSION_BYTES
        assert expression["x-framing"] == {
            "trimmed": True,
            "singleLine": True,
            "comments": False,
            "statementSeparators": False,
            "balancedDoubleQuotedStrings": True,
            "balancedSlashRegexLiterals": True,
        }


def test_query_object_advanced_dispatches_fixed_bounded_waql_once(
    tmp_path: Path,
) -> None:
    object_id = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [
                    {
                        "id": object_id,
                        "name": "UI_Click",
                        "EffectNames": ["Compressor"],
                    }
                ]
            },
        }
    )
    request = {
        "contract": "waapi-skill.advanced-object-query/v1",
        "waql": (
            'from type Sound where effects.any(effect.name = "Compressor") '
            "orderby name"
        ),
        "return": ["id", "name", "effects.name as EffectNames"],
        "max_results": 2,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--advanced-request-json",
            json.dumps(request, separators=(",", ":")),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["query_layer"] == "advanced-native-waql"
    assert payload["query_contract"] == "waapi-skill.advanced-object-query/v1"
    assert payload["query_bound"] == {
        "mode": "gateway-appended-take",
        "value": 2,
    }
    assert payload["count"] == 1
    assert payload["limit_reached"] is False
    assert "identity_handoff" not in payload
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {
            "waql": (
                'from type Sound where effects.any(effect.name = "Compressor") '
                "orderby name take 2"
            )
        },
        {"return": ["id", "name", "effects.name as EffectNames"]},
    )
    assert [call[0] for call in client.calls].count(
        "ak.wwise.core.object.get"
    ) == 1


@pytest.mark.parametrize(
    "query_request",
    (
        {
            "contract": "waapi-skill.advanced-object-query/v1",
            "waql": "from type Sound; from type Event",
            "return": ["id"],
            "max_results": 2,
        },
        {
            "contract": "waapi-skill.advanced-object-query/v1",
            "waql": "from type Sound",
            "return": ["id"],
            "max_results": 0,
        },
        {
            "contract": "waapi-skill.advanced-object-query/v1",
            "waql": "from type Sound",
            "return": ["id"],
            "max_results": 2,
            "uri": "ak.wwise.core.object.set",
        },
    ),
)
def test_query_object_advanced_invalid_contract_fails_before_connection(
    tmp_path: Path,
    query_request: Mapping[str, Any],
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid advanced query must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--advanced-request-json", json.dumps(query_request)],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "SemanticValidationError"
    assert called is False


@pytest.mark.parametrize(
    "conflicting_args",
    (
        ("--take", "1"),
        ("--where-json", "{}"),
        ("--match-original-file-path", "/tmp/candidate.wav"),
        ("--select", "children"),
        ("--all-results",),
        ("--return-field", "id"),
    ),
)
def test_query_object_advanced_rejects_split_option_ownership_before_connection(
    tmp_path: Path,
    conflicting_args: tuple[str, ...],
) -> None:
    called = False
    request = {
        "contract": "waapi-skill.advanced-object-query/v1",
        "waql": "from type Sound",
        "return": ["id"],
        "max_results": 2,
    }

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"split advanced query must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--advanced-request-json",
            json.dumps(request),
            *conflicting_args,
        ],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert conflicting_args[0] in payload["message"]
    assert called is False


def test_query_object_advanced_rejects_result_count_above_gateway_cap(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [{"id": "{one}"}, {"id": "{two}"}]
            },
        }
    )
    request = {
        "contract": "waapi-skill.advanced-object-query/v1",
        "waql": "from type Sound",
        "return": ["id"],
        "max_results": 1,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--advanced-request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["maximum_rows"] == 1
    assert payload["details"]["actual_count"] == 2


def test_query_object_advanced_invalid_waql_is_not_retried_or_normalized(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        errors={
            "ak.wwise.core.object.get": WaapiRequestFailed(
                "ak.wwise.query.invalid_query",
                {"message": "Unsupported WAQL syntax"},
            )
        },
    )
    request = {
        "contract": "waapi-skill.advanced-object-query/v1",
        "waql": "from type Sound orderby unsupportedAccessor",
        "return": ["id"],
        "max_results": 2,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--advanced-request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["ok"] is False
    assert payload["call"]["waapi_error_uri"] == "ak.wwise.query.invalid_query"
    assert "normalization" not in payload["call"]
    assert [call[0] for call in client.calls].count(
        "ak.wwise.core.object.get"
    ) == 1


def test_query_object_advanced_exact_looking_unknown_object_is_not_normalized(
    tmp_path: Path,
) -> None:
    object_id = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        errors={
            "ak.wwise.core.object.get": WaapiRequestFailed(
                "ak.wwise.query.unknown_object",
                {"message": "Object not found"},
            )
        },
    )
    request = {
        "contract": "waapi-skill.advanced-object-query/v1",
        "waql": f'from object "{object_id}"',
        "return": ["id"],
        "max_results": 2,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--advanced-request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["waapi_error_uri"] == "ak.wwise.query.unknown_object"
    assert "normalization" not in payload["call"]
    assert [call[0] for call in client.calls].count(
        "ak.wwise.core.object.get"
    ) == 1


def test_query_object_advanced_keeps_dispatcher_result_byte_ceiling(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [{"id": "{one}", "blob": "x" * (1024 * 1024)}]
            },
        }
    )
    request = {
        "contract": "waapi-skill.advanced-object-query/v1",
        "waql": "from type Sound",
        "return": ["id", "blob"],
        "max_results": 2,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--advanced-request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["error_code"] == "RESULT_TOO_LARGE"
    assert payload["objects"] is None
    assert "identity_handoff" not in payload


def test_advanced_query_with_caller_take_and_id_alias_stays_read_only(
    tmp_path: Path,
) -> None:
    canonical = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {"return": [{"id": canonical}]},
        }
    )
    request = {
        "contract": "waapi-skill.advanced-object-query/v1",
        "waql": 'from type Sound where name = "Duplicate" take 1',
        "return": ["id", "parent.id as id"],
        "max_results": 2,
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--advanced-request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["count"] == 1
    assert "identity_handoff" not in payload
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": 'from type Sound where name = "Duplicate" take 1 take 2'},
        {"return": ["id", "parent.id as id"]},
    )


def test_query_object_structured_request_compiles_and_dispatches_once(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [
                    {
                        "id": "{sound}",
                        "name": "UI_Click",
                        "type": "Sound",
                        "path": r"\Actor-Mixer Hierarchy\UI_Click",
                    }
                ]
            },
        }
    )
    request = {
        "contract": "waapi-skill.object-query/v1",
        "source": {"kind": "type", "types": ["Event"]},
        "transforms": [
            {"kind": "select", "expressions": [["children"]]},
            {
                "kind": "where",
                "predicate": {
                    "kind": "all",
                    "operands": [
                        {
                            "kind": "compare",
                            "path": ["type"],
                            "operator": "=",
                            "value": "Action",
                        },
                        {
                            "kind": "any",
                            "operands": [
                                {
                                    "kind": "compare",
                                    "path": ["name"],
                                    "operator": ":",
                                    "value": "Play",
                                },
                                {
                                    "kind": "not",
                                    "operand": {
                                        "kind": "truthy",
                                        "path": ["isIncluded"],
                                    },
                                },
                            ],
                        },
                    ],
                },
            },
            {
                "kind": "select",
                "expressions": [["Target"], ["this"], ["descendants"]],
            },
            {"kind": "take", "value": 25},
        ],
        "return": ["id", "name", "type", "path", "@Volume"],
    }

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--request-json",
            json.dumps(request, separators=(",", ":")),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["query_contract"] == "waapi-skill.object-query/v1"
    assert payload["query_bound"] == {"mode": "take", "value": 25}
    assert payload["count"] == 1
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {
            "waql": (
                "from type Event select children where type = \"Action\" and "
                "(name : \"Play\" or ! (isIncluded)) "
                "select Target, this, descendants take 25"
            )
        },
        {"return": ["id", "name", "type", "path", "@Volume"]},
    )


@pytest.mark.parametrize(
    "query_request",
    (
        {
            "contract": "waapi-skill.object-query/v1",
            "source": {"kind": "type", "types": ["Sound"]},
            "transforms": [],
            "return": ["id"],
            "waql": "from type Sound",
        },
        {
            "contract": "waapi-skill.object-query/v1",
            "source": {"kind": "type", "types": ["Sound"]},
            "transforms": [
                {
                    "kind": "where",
                    "predicate": {
                        "kind": "raw",
                        "value": "name = \"Dummy\"",
                    },
                },
                {"kind": "take", "value": 1},
            ],
            "return": ["id"],
        },
    ),
)
def test_query_object_structured_raw_fragments_fail_before_connection(
    tmp_path: Path,
    query_request: Mapping[str, Any],
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid structured query must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--request-json", json.dumps(query_request)],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "SemanticValidationError"
    assert called is False


def test_query_object_structured_request_rejects_split_option_ownership(
    tmp_path: Path,
) -> None:
    request = {
        "contract": "waapi-skill.object-query/v1",
        "source": {
            "kind": "object",
            "objects": [
                {
                    "kind": "id",
                    "value": "{11111111-1111-1111-1111-111111111111}",
                }
            ],
        },
        "transforms": [],
        "return": ["id"],
    }
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"conflicting structured query must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--request-json",
            json.dumps(request),
            "--return-field",
            "name",
        ],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "--return-field" in payload["message"]
    assert called is False


def test_query_object_structured_exact_identity_requires_and_verifies_return_field(
    tmp_path: Path,
) -> None:
    object_id = "{11111111-1111-1111-1111-111111111111}"
    request = {
        "contract": "waapi-skill.object-query/v1",
        "source": {
            "kind": "object",
            "objects": [{"kind": "id", "value": object_id}],
        },
        "transforms": [],
        "return": ["name"],
    }
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"unverifiable exact query must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )
    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "'id'" in payload["message"]
    assert called is False

    request["return"] = ["id", "name"]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [
                    {
                        "id": "{22222222-2222-2222-2222-222222222222}",
                        "name": "Wrong",
                    }
                ]
            },
        }
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )
    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["identity_field"] == "id"


def test_query_object_structured_rejects_rows_above_compiled_take(
    tmp_path: Path,
) -> None:
    request = {
        "contract": "waapi-skill.object-query/v1",
        "source": {"kind": "type", "types": ["Sound"]},
        "transforms": [{"kind": "take", "value": 1}],
        "return": ["id"],
    }
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [
                    {"id": "{11111111-1111-1111-1111-111111111111}"},
                    {"id": "{22222222-2222-2222-2222-222222222222}"},
                ]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["maximum_rows"] == 1
    assert payload["details"]["actual_count"] == 2


def test_query_object_structured_exact_path_success_uses_identity_bound(
    tmp_path: Path,
) -> None:
    path = r"\Events\Default Work Unit\Play_UI"
    request = {
        "contract": "waapi-skill.object-query/v1",
        "source": {
            "kind": "object",
            "objects": [{"kind": "path", "value": path}],
        },
        "transforms": [],
        "return": ["path", "name"],
    }
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [{"path": path, "name": "Play_UI"}]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["query_bound"] == {"mode": "exact-object", "value": 1}
    assert payload["objects"] == [{"path": path, "name": "Play_UI"}]
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": f'from object "{path}"'},
        {"return": ["path", "name"]},
    )


def test_query_object_structured_exact_path_rejects_identity_drift(
    tmp_path: Path,
) -> None:
    expected_path = r"\Events\Default Work Unit\Play_UI"
    request = {
        "contract": "waapi-skill.object-query/v1",
        "source": {
            "kind": "object",
            "objects": [{"kind": "path", "value": expected_path}],
        },
        "transforms": [],
        "return": ["path"],
    }
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(),
            "ak.wwise.core.object.get": {
                "return": [{"path": r"\Events\Default Work Unit\Play_Other"}]
            },
        }
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--request-json", json.dumps(request)],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_QUERY_RESULT"
    assert payload["details"]["identity_field"] == "path"
    assert payload["details"]["expected"] == expected_path


def test_query_object_structured_exact_missing_object_is_normalized(
    tmp_path: Path,
) -> None:
    missing_id = "{99999999-9999-9999-9999-999999999999}"
    request = {
        "contract": "waapi-skill.object-query/v1",
        "source": {
            "kind": "object",
            "objects": [{"kind": "id", "value": missing_id}],
        },
        "transforms": [],
        "return": ["id"],
    }
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        errors={
            "ak.wwise.core.object.get": WaapiRequestFailed(
                "ak.wwise.query.unknown_object",
                {"message": "Object not found (13)"},
            )
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["query-object", "--request-json", json.dumps(request), "--detail"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["count"] == 0
    assert payload["objects"] == []
    assert payload["query_bound"] == {"mode": "exact-object", "value": 1}
    assert payload["call"]["normalization"]["kind"] == "exact-object-absence"
    assert payload["call"]["normalization"]["source"] == (
        "ak.wwise.query.unknown_object"
    )


def test_query_object_original_file_reference_match_returns_closed_candidate_records(
    tmp_path: Path,
) -> None:
    footstep = r"Y:\Sandbox\Originals\Footstep.wav"
    unused = "Y:/Sandbox/Originals/Unused.wav"
    voice = "/Users/xiye/Sandbox/Voice.wav"
    network = r"\\StudioNas\Originals\Network.wav"
    rows = [
        {
            "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBB2}",
            "path": r"\Actor-Mixer Hierarchy\Footstep Source B",
            "originalFilePath": "y:/sandbox/originals/FOOTSTEP.wav",
        },
        {
            "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAA1}",
            "path": r"\Actor-Mixer Hierarchy\Footstep Source A",
            "originalFilePath": r"Y:\SANDBOX\ORIGINALS\footstep.wav",
        },
        {
            "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCC3}",
            "path": r"\Actor-Mixer Hierarchy\Voice Source",
            "originalFilePath": voice,
        },
        {
            "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDD4}",
            "path": r"\Actor-Mixer Hierarchy\Network Source",
            "originalFilePath": r"\\studionas\originals\NETWORK.wav",
        },
        {
            "id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEE5}",
            "path": r"\Actor-Mixer Hierarchy\Unrelated Source",
            "originalFilePath": r"Y:\Sandbox\Originals\Unrelated.wav",
        },
    ]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.object.get": {"return": rows},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--type",
            "AudioFileSource",
            "--take",
            "1000",
            "--match-original-file-path",
            footstep,
            "--match-original-file-path",
            unused,
            "--match-original-file-path",
            voice,
            "--match-original-file-path",
            network,
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"waql": "from type AudioFileSource take 1000"},
        {"return": ["id", "path", "originalFilePath"]},
    )
    assert payload["agent_result"] == {
        "contract": "waapi-skill.original-file-reference-match/v1",
        "scan_complete": True,
        "scanned_audio_source_count": 5,
        "scan_limit": 1000,
        "candidates": [
            {
                "originalFilePath": footstep,
                "classification": "referenced",
                "reference_count": 2,
                "references": [
                    {
                        "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAA1}",
                        "path": r"\Actor-Mixer Hierarchy\Footstep Source A",
                    },
                    {
                        "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBB2}",
                        "path": r"\Actor-Mixer Hierarchy\Footstep Source B",
                    },
                ],
                "references_truncated": False,
            },
            {
                "originalFilePath": unused,
                "classification": "unreferenced",
                "reference_count": 0,
                "references": [],
                "references_truncated": False,
            },
            {
                "originalFilePath": voice,
                "classification": "referenced",
                "reference_count": 1,
                "references": [
                    {
                        "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCC3}",
                        "path": r"\Actor-Mixer Hierarchy\Voice Source",
                    }
                ],
                "references_truncated": False,
            },
            {
                "originalFilePath": network,
                "classification": "referenced",
                "reference_count": 1,
                "references": [
                    {
                        "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDD4}",
                        "path": r"\Actor-Mixer Hierarchy\Network Source",
                    }
                ],
                "references_truncated": False,
            },
        ],
    }
    assert list(payload)[-1] == "agent_result"
    audit = payload["original_file_reference_match"]
    assert audit["status"] == "complete"
    assert audit["candidate_count"] == 4
    assert audit["scan_count"] == 5
    assert audit["reference_count"] == 4
    assert audit["returned_reference_detail_count"] == 4
    assert audit["reference_detail_limit_per_candidate"] == 4
    assert audit["reference_detail_limit"] == 256


def test_original_file_path_normalization_uses_the_paths_own_flavor() -> None:
    assert waapi_gateway.normalize_original_file_system_path(
        r"C:\Originals\Mix.wav"
    ) == waapi_gateway.normalize_original_file_system_path(
        "c:/originals/MIX.WAV"
    )
    assert waapi_gateway.normalize_original_file_system_path(
        r"\\StudioNas\Originals\Mix.wav"
    ) == waapi_gateway.normalize_original_file_system_path(
        "//studionas/originals/MIX.WAV"
    )
    assert waapi_gateway.normalize_original_file_system_path(
        "/Originals/Mix.wav"
    ) != waapi_gateway.normalize_original_file_system_path(
        "/Originals/mix.wav"
    )
    assert waapi_gateway.normalize_original_file_system_path(
        r"/Originals/a\b.wav"
    ) != waapi_gateway.normalize_original_file_system_path(
        "/Originals/a/b.wav"
    )


def test_query_object_original_file_reference_match_sorts_and_truncates_details(
    tmp_path: Path,
) -> None:
    candidate = r"Y:\Sandbox\Originals\Shared.wav"
    rows = [
        {
            "id": f"{{00000000-0000-0000-0000-{index:012X}}}",
            "path": rf"\Actor-Mixer Hierarchy\Source {path_index}",
            "originalFilePath": candidate,
        }
        for index, path_index in enumerate((5, 1, 4, 2, 3), start=1)
    ]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.object.get": {"return": rows},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--type",
            "AudioFileSource",
            "--take",
            "1000",
            "--match-original-file-path",
            candidate,
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    result = payload["agent_result"]["candidates"][0]
    assert result["reference_count"] == 5
    assert result["references_truncated"] is True
    assert [reference["path"] for reference in result["references"]] == [
        r"\Actor-Mixer Hierarchy\Source 1",
        r"\Actor-Mixer Hierarchy\Source 2",
        r"\Actor-Mixer Hierarchy\Source 3",
        r"\Actor-Mixer Hierarchy\Source 4",
    ]
    audit = payload["original_file_reference_match"]
    assert audit["reference_count"] == 5
    assert audit["returned_reference_detail_count"] == 4


def test_query_object_original_file_reference_match_maximum_shape_stays_below_gateway_ceiling(
    tmp_path: Path,
) -> None:
    candidates: list[str] = []
    rows: list[dict[str, str]] = []
    for candidate_index in range(64):
        candidate_prefix = f"/pool/{candidate_index:02d}/"
        candidate = candidate_prefix + "\"" * (
            waapi_gateway.MAX_ORIGINAL_FILE_PATH_BYTES
            - len(candidate_prefix.encode("utf-8"))
        )
        assert len(candidate.encode("utf-8")) == 1024
        candidates.append(candidate)
        for detail_index in range(4):
            row_index = candidate_index * 4 + detail_index
            path_prefix = rf"\R{candidate_index:02d}-{detail_index}"
            remaining = (
                waapi_gateway.MAX_ORIGINAL_FILE_REFERENCE_PATH_BYTES
                - len(path_prefix.encode("utf-8"))
            )
            hierarchy_path = path_prefix + r"\a" * (remaining // 2)
            if len(hierarchy_path.encode("utf-8")) < 512:
                hierarchy_path += "b"
            assert len(hierarchy_path.encode("utf-8")) == 512
            rows.append(
                {
                    "id": f"{{00000000-0000-0000-0000-{row_index:012X}}}",
                    "path": hierarchy_path,
                    "originalFilePath": candidate,
                }
            )
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.object.get": {"return": rows},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    argv = [
        "query-object",
        "--type",
        "AudioFileSource",
        "--take",
        "1000",
    ]
    for candidate in candidates:
        argv.extend(("--match-original-file-path", candidate))

    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 0, payload
    assert payload["agent_result"]["scan_complete"] is True
    assert len(payload["agent_result"]["candidates"]) == 64
    assert all(
        candidate["references_truncated"] is False
        for candidate in payload["agent_result"]["candidates"]
    )
    assert waapi_gateway.probe_gateway_json_document_size(
        payload,
        waapi_gateway.MAX_GATEWAY_RESULT_JSON_BYTES,
    ) == "ok"
    observed_size = waapi_gateway.gateway_json_document_size(payload)
    assert observed_size < waapi_gateway.MAX_GATEWAY_RESULT_JSON_BYTES // 2


@pytest.mark.parametrize(
    ("argv", "message"),
    (
        (
            (
                "query-object",
                "--type",
                "Sound",
                "--take",
                "1000",
                "--match-original-file-path",
                r"Y:\Sandbox\Originals\source.wav",
            ),
            "requires exactly --type AudioFileSource",
        ),
        (
            (
                "query-object",
                "--type",
                "AudioFileSource",
                "--take",
                "1000",
                "--where-json",
                "{}",
                "--match-original-file-path",
                r"Y:\Sandbox\Originals\source.wav",
            ),
            "cannot be combined with --where-json",
        ),
        (
            (
                "query-object",
                "--type",
                "AudioFileSource",
                "--take",
                "1000",
                "--select",
                "parent",
                "--match-original-file-path",
                r"Y:\Sandbox\Originals\source.wav",
            ),
            "cannot be combined with --select",
        ),
        (
            (
                "query-object",
                "--type",
                "AudioFileSource",
                "--all-results",
                "--match-original-file-path",
                r"Y:\Sandbox\Originals\source.wav",
            ),
            "cannot be combined with --all-results",
        ),
        (
            (
                "query-object",
                "--type",
                "AudioFileSource",
                "--take",
                "1000",
                "--return-field",
                "id",
                "--match-original-file-path",
                r"Y:\Sandbox\Originals\source.wav",
            ),
            "cannot be combined with --return-field",
        ),
        (
            (
                "query-object",
                "--type",
                "AudioFileSource",
                "--take",
                "999",
                "--match-original-file-path",
                r"Y:\Sandbox\Originals\source.wav",
            ),
            "requires exactly --take 1000",
        ),
        (
            (
                "query-object",
                "--path",
                r"\Actor-Mixer Hierarchy",
                "--take",
                "1000",
                "--match-original-file-path",
                r"Y:\Sandbox\Originals\source.wav",
            ),
            "requires exactly --type AudioFileSource",
        ),
    ),
)
def test_query_object_original_file_reference_match_rejects_open_query_combinations(
    tmp_path: Path,
    argv: tuple[str, ...],
    message: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid closed match input must not connect to {url}")

    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=env,
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert message in payload["message"]
    assert called is False


@pytest.mark.parametrize(
    ("candidates", "message"),
    (
        (("relative/source.wav",), "expected an absolute"),
        ((r"Y:\Sandbox\..\source.wav",), "non-traversing components"),
        ((r"\\server\share",), "server, share, and file"),
        ((r"\\?\C:\source.wav",), "extended or device UNC"),
        (("",), "nonempty absolute path"),
        (
            (
                r"Y:\Sandbox\Originals\source.wav",
                "y:/sandbox/originals/SOURCE.wav",
            ),
            "remain unique after normalization",
        ),
        (
            (
                r"\\StudioNas\Originals\source.wav",
                "//studionas/originals/SOURCE.wav",
            ),
            "remain unique after normalization",
        ),
    ),
)
def test_query_object_original_file_reference_match_rejects_invalid_candidates(
    tmp_path: Path,
    candidates: tuple[str, ...],
    message: str,
) -> None:
    argv = [
        "query-object",
        "--type",
        "AudioFileSource",
        "--take",
        "1000",
    ]
    for candidate in candidates:
        argv.extend(("--match-original-file-path", candidate))
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid candidate must not connect to {url}")

    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=env,
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert message in payload["message"]
    assert called is False


def test_query_object_original_file_reference_match_is_strictly_2025_1(
    tmp_path: Path,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"wrong version must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--type",
            "AudioFileSource",
            "--take",
            "1000",
            "--match-original-file-path",
            r"Y:\Sandbox\Originals\source.wav",
        ],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "only for Wwise 2025.1" in payload["message"]
    assert called is False


def test_query_object_original_file_reference_match_enforces_candidate_limit(
    tmp_path: Path,
) -> None:
    candidates = [rf"Y:\Sandbox\Originals\source-{index}.wav" for index in range(65)]
    argv = [
        "query-object",
        "--type",
        "AudioFileSource",
        "--take",
        "1000",
    ]
    for candidate in candidates:
        argv.extend(("--match-original-file-path", candidate))
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"too many candidates must not connect to {url}")

    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=env,
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "between 1 and 64 times" in payload["message"]
    assert called is False


@pytest.mark.parametrize(
    "rows",
    (
        [
            {
                "id": "not-a-guid",
                "path": r"\Actor-Mixer Hierarchy\Source",
                "originalFilePath": r"Y:\Sandbox\Originals\source.wav",
            }
        ],
        [
            {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "path": "relative/path",
                "originalFilePath": r"Y:\Sandbox\Originals\source.wav",
            }
        ],
        [
            {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "path": r"\Actor-Mixer Hierarchy\Source",
                "originalFilePath": "relative/source.wav",
            }
        ],
        [
            {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "path": r"\Actor-Mixer Hierarchy\Source",
            }
        ],
        [
            {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "path": r"\Actor-Mixer Hierarchy\Source A",
                "originalFilePath": r"Y:\Sandbox\Originals\source-a.wav",
            },
            {
                "id": "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}",
                "path": r"\Actor-Mixer Hierarchy\Source B",
                "originalFilePath": r"Y:\Sandbox\Originals\source-b.wav",
            },
        ],
    ),
)
def test_query_object_original_file_reference_match_rejects_malformed_or_duplicate_rows(
    tmp_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.object.get": {"return": rows},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--type",
            "AudioFileSource",
            "--take",
            "1000",
            "--match-original-file-path",
            r"Y:\Sandbox\Originals\source.wav",
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["error_code"] == "INVALID_ORIGINAL_FILE_REFERENCE_RESULT"
    assert "agent_result" not in payload


def test_query_object_original_file_reference_match_rejects_scan_at_take_limit(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "id": f"{{00000000-0000-0000-0000-{index:012X}}}",
            "path": rf"\Actor-Mixer Hierarchy\Source {index}",
            "originalFilePath": rf"Y:\Sandbox\Originals\source-{index}.wav",
        }
        for index in range(1000)
    ]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": live_info(year=2025, major=1),
            "ak.wwise.core.object.get": {"return": rows},
        }
    )
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "query-object",
            "--type",
            "AudioFileSource",
            "--take",
            "1000",
            "--match-original-file-path",
            r"Y:\Sandbox\Originals\source-0.wav",
        ],
        env=env,
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["status"] == "incomplete_boundary"
    assert payload["error_code"] == "ORIGINAL_FILE_REFERENCE_SCAN_INCOMPLETE"
    assert payload["details"]["scan_count"] == 1000
    assert payload["original_file_reference_match"]["scan_complete"] is False
    assert "agent_result" not in payload


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
        [
            "query-object",
            "--query",
            query,
            "--take",
            "1",
            "--return-field",
            "id",
            "--detail",
        ],
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
    assert "--detail" in help_text
    assert "failures skip compact projection but still obey the global result ceiling" in " ".join(
        help_text.split()
    )
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


def test_structured_and_advanced_query_documents_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        waapi_gateway.build_parser().parse_args(
            [
                "query-object",
                "--request-json",
                "{}",
                "--advanced-request-json",
                "{}",
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
    assert "semantic_preview" not in payload
    assert client.calls[-1][1] == {
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
    assert "raw" not in payload["normalized"][0]
    assert "extra" not in payload["normalized"][0]
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
        [
            "query-object",
            "--object-id",
            missing_id,
            "--return-field",
            "id",
            "--detail",
        ],
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


def test_replace_absence_normalization_requires_one_exact_old_guid_per_lookup() -> None:
    old_ids = (
        "{4AB57FDF-0640-4806-98BE-A3E0C5FB1B91}",
        "{93814B94-06C8-403B-ABB9-BE085BDF3AFB}",
        "{341F0462-8024-4E23-B22B-B147D98E0F59}",
    )
    unknown_object = {
        "ok": False,
        "error_code": "WaapiRequestFailed",
        "message": "untrusted rendered application error",
        "waapi_error_uri": "ak.wwise.query.unknown_object",
        "waapi_error_details": {
            "message": "from id object is unknown",
            "details": {"procedureUri": "ak.wwise.core.object.get"},
        },
    }

    bulk = waapi_gateway.normalize_exact_object_absence(
        api="ak.wwise.core.object.get",
        args={"from": {"id": list(old_ids)}},
        result=unknown_object,
    )
    assert bulk["ok"] is False
    assert "normalization" not in bulk

    for old_id in old_ids:
        singleton = waapi_gateway.normalize_exact_object_absence(
            api="ak.wwise.core.object.get",
            args={"from": {"id": [old_id]}},
            result=unknown_object,
        )
        assert singleton["ok"] is True
        assert singleton["result"] == {"return": []}
        assert singleton["normalization"]["source"] == "ak.wwise.query.unknown_object"

    unrelated = waapi_gateway.normalize_exact_object_absence(
        api="ak.wwise.core.object.get",
        args={"from": {"id": [old_ids[0]]}},
        result={
            **unknown_object,
            "waapi_error_uri": "ak.wwise.transport.closed",
        },
    )
    assert unrelated["ok"] is False
    assert "normalization" not in unrelated


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
    assert "events" not in payload
    assert "requested_event_count" not in payload
    assert payload["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1
    assert client.handlers[0].unsubscribe_thread_ident == client.handlers[0].subscribe_thread_ident
    assert client.handlers[0].unsubscribe_thread_ident != threading.get_ident()


def test_stream_topic_emits_matching_events_immediately_from_one_subscription(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        subscription_events={
            topic: [
                {"object": {"id": "wrong", "name": "Ignore"}},
                {"object": {"id": "wanted", "name": "UI_1"}},
                {"object": {"id": "wanted", "name": "UI_2"}},
            ]
        },
    )
    records: list[Mapping[str, Any]] = []

    exit_code, terminal = waapi_gateway.execute_gateway(
        [
            "--timeout",
            "0.5",
            "stream-topic",
            topic,
            "--match-json",
            '{"object":{"id":"wanted"}}',
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
        stream_sink=records.append,
    )

    assert exit_code == 0
    assert [record["record_type"] for record in records] == [
        "started",
        "event",
        "event",
    ]
    assert [record["sequence"] for record in records[1:]] == [1, 2]
    assert [record["event"]["object"]["name"] for record in records[1:]] == [
        "UI_1",
        "UI_2",
    ]
    assert records[0]["session_context"]["available"] is True
    assert terminal["contract"] == waapi_gateway.TOPIC_STREAM_RECORD_CONTRACT
    assert terminal["record_type"] == "terminal"
    assert terminal["status"] == "completed"
    assert terminal["completion_reason"] == "duration_elapsed"
    assert terminal["event_count"] == 2
    assert terminal["cleanup"] == "unsubscribed"
    assert len(client.handlers) == 1
    assert client.handlers[0].unsubscribe_calls == 1
    assert client.disconnected is True


def test_stream_topic_defaults_to_continuous_until_cancelled(
    tmp_path: Path,
) -> None:
    args = waapi_gateway.build_parser().parse_args(
        ["stream-topic", "ak.wwise.core.object.created"]
    )

    connection = waapi_gateway.resolve_connection(
        args,
        env=gateway_env(tmp_path),
    )

    assert connection.timeout == math.inf


def test_stream_topic_without_record_sink_fails_before_connecting(
    tmp_path: Path,
) -> None:
    connected = False

    def client_factory(url: str) -> FakeClient:
        nonlocal connected
        connected = True
        raise AssertionError(url)

    exit_code, payload = waapi_gateway.execute_gateway(
        ["stream-topic", "ak.wwise.core.object.created"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["contract"] == waapi_gateway.TOPIC_STREAM_RECORD_CONTRACT
    assert payload["record_type"] == "terminal"
    assert payload["error_code"] == "GatewayInputError"
    assert "requires a live record sink" in payload["message"]
    assert connected is False


def test_stream_topic_queue_overflow_fails_closed_without_emitting_partial_events(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"
    events = [
        {"object": {"id": f"object-{index}", "name": f"Object_{index}"}}
        for index in range(waapi_gateway.DEFAULT_LISTENER_QUEUE_SIZE + 1)
    ]
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        subscription_events={topic: events},
    )
    records: list[Mapping[str, Any]] = []

    exit_code, terminal = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "stream-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
        stream_sink=records.append,
    )

    assert exit_code == 2
    assert [record["record_type"] for record in records] == ["started"]
    assert terminal["error_code"] == "SUBSCRIPTION_STREAM_OVERFLOW"
    assert terminal["event_count"] == 0
    assert terminal["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1


def test_stream_topic_rejects_oversized_event_before_buffering(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        subscription_events={
            topic: [{"object": {"id": "wanted", "name": "x" * (300 * 1024)}}]
        },
    )
    records: list[Mapping[str, Any]] = []

    exit_code, terminal = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "stream-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
        stream_sink=records.append,
    )

    assert exit_code == 2
    assert [record["record_type"] for record in records] == ["started"]
    assert terminal["error_code"] == "RESULT_TOO_LARGE"
    assert terminal["details"]["limit_bytes"] == 256 * 1024
    assert terminal["event_count"] == 0
    assert terminal["cleanup"] == "unsubscribed"


def test_stream_topic_health_check_terminates_after_connection_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = "ak.wwise.core.object.created"

    class DisconnectingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__({"ak.wwise.core.getInfo": live_info()})
            self.get_info_calls = 0

        def call(
            self,
            uri: str,
            args: Mapping[str, Any] | None = None,
            options: Mapping[str, Any] | None = None,
        ) -> Any:
            if uri == "ak.wwise.core.getInfo":
                self.get_info_calls += 1
                if self.get_info_calls > 1:
                    raise ConnectionError("synthetic WAAPI disconnect")
            return super().call(uri, args, options)

    monkeypatch.setattr(
        waapi_gateway,
        "TOPIC_STREAM_HEALTH_INTERVAL_SECONDS",
        0.01,
    )
    client = DisconnectingClient()
    records: list[Mapping[str, Any]] = []

    exit_code, terminal = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "stream-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
        stream_sink=records.append,
    )

    assert exit_code == 2
    assert [record["record_type"] for record in records] == ["started"]
    assert terminal["error_code"] == "ConnectionError"
    assert terminal["event_count"] == 0
    assert terminal["cleanup"] == "unsubscribed"
    assert client.get_info_calls == 2
    assert client.handlers[0].unsubscribe_calls == 1


def test_wait_topic_false_unsubscribe_is_retained_and_close_retries(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"

    class RetryHandler(FakeEventHandler):
        def __init__(self) -> None:
            super().__init__()
            self.results = [False, True]

        def unsubscribe(self) -> bool:
            self.unsubscribe_calls += 1
            self.unsubscribe_thread_ident = threading.get_ident()
            return self.results.pop(0)

    class RetryClient(FakeClient):
        def subscribe(
            self,
            uri: str,
            callback: Any,
            options: Mapping[str, Any] | None = None,
        ) -> RetryHandler:
            del uri, options
            handler = RetryHandler()
            self.handlers.append(handler)
            callback({"object": {"id": "wanted"}})
            return handler

    client = RetryClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["ok"] is False
    assert payload["call"]["error_code"] == "SUBSCRIPTION_CLEANUP_FAILED"
    assert payload["cleanup"] == "unsubscribed_after_retry"
    assert payload["call"]["details"]["subscription_cleanup"] == {
        "status": "unsubscribed_after_retry",
        "reason": "unsubscribe_returned_false",
    }
    assert client.handlers[0].unsubscribe_calls == 2
    assert client.disconnected is True


def test_wait_topic_repeated_false_unsubscribe_never_claims_cleanup(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"

    class FalseHandler(FakeEventHandler):
        def unsubscribe(self) -> bool:
            self.unsubscribe_calls += 1
            self.unsubscribe_thread_ident = threading.get_ident()
            return False

    class FalseClient(FakeClient):
        def subscribe(
            self,
            uri: str,
            callback: Any,
            options: Mapping[str, Any] | None = None,
        ) -> FalseHandler:
            del uri, options
            handler = FalseHandler()
            self.handlers.append(handler)
            callback({"object": {"id": "wanted"}})
            return handler

    client = FalseClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["cleanup"] == "unsubscribe_failed"
    assert payload["call"]["details"]["subscription_cleanup"]["status"] == (
        "unsubscribe_failed"
    )
    assert payload["details"]["cleanup_failure"] == {
        "error_code": "SUBSCRIPTION_CLEANUP_FAILED",
        "message": "WAAPI subscription cleanup did not explicitly succeed",
        "details": {
            "subscription_token": 1,
            "reason": "unsubscribe_returned_false",
        },
    }
    assert client.handlers[0].unsubscribe_calls == 2


@pytest.mark.parametrize(
    "result",
    (
        {"ok": True},
        {"ok": False, "error_code": "TIMEOUT"},
        {"ok": False, "error_code": "RESULT_TOO_LARGE"},
    ),
)
def test_topic_cleanup_projection_never_infers_from_dispatch_outcome(
    result: Mapping[str, Any],
) -> None:
    assert waapi_gateway.topic_subscription_cleanup_status(result) == "unknown"


def test_soundbank_generated_wait_is_not_silently_capped_at_ten_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = "ak.wwise.core.soundbank.generated"
    captured: dict[str, float] = {}

    def record_dispatch(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
        operation_timeout = float(kwargs["operation_timeout"])
        captured["operation_timeout"] = operation_timeout
        return {
            "api": topic,
            "item_type": "topic",
            "category": None,
            "version": "2022.1",
            "ok": False,
            "risk_level": "read",
            "error_code": "TIMEOUT",
            "message": "synthetic timeout without waiting",
            "details": {"operation_timeout_seconds": operation_timeout},
        }

    monkeypatch.setattr(waapi_gateway, "dispatch", record_dispatch)
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "120", "wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["error_code"] == "TIMEOUT"
    assert 119.0 < captured["operation_timeout"] < 120.0


def test_ordinary_wait_topic_honors_explicit_long_timeout_without_contract_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = "ak.wwise.core.object.created"
    captured: dict[str, float] = {}

    def record_dispatch(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
        operation_timeout = float(kwargs["operation_timeout"])
        captured["operation_timeout"] = operation_timeout
        return {
            "api": topic,
            "item_type": "topic",
            "category": None,
            "version": "2022.1",
            "ok": False,
            "risk_level": "read",
            "error_code": "TIMEOUT",
            "message": "synthetic timeout without waiting",
            "details": {"operation_timeout_seconds": operation_timeout},
        }

    monkeypatch.setattr(waapi_gateway, "dispatch", record_dispatch)
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "3600", "wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert 3599.0 < captured["operation_timeout"] < 3600.0
    assert payload["subscription_timeout"] == {
        "mode": "finite",
        "seconds": 3600.0,
        "source": "explicit",
    }


def test_ordinary_wait_topic_reports_default_ten_second_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = "ak.wwise.core.object.created"
    captured: dict[str, float] = {}

    def record_dispatch(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
        operation_timeout = float(kwargs["operation_timeout"])
        captured["operation_timeout"] = operation_timeout
        return {
            "api": topic,
            "item_type": "topic",
            "category": None,
            "version": "2022.1",
            "ok": False,
            "risk_level": "read",
            "error_code": "TIMEOUT",
            "message": "synthetic timeout without waiting",
            "details": {"operation_timeout_seconds": operation_timeout},
        }

    monkeypatch.setattr(waapi_gateway, "dispatch", record_dispatch)
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["wait-topic", topic],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert 9.0 < captured["operation_timeout"] < 10.0
    assert payload["subscription_timeout"] == {
        "mode": "finite",
        "seconds": 10.0,
        "source": "default",
    }


def test_wait_topic_no_timeout_returns_strict_bounded_json(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.core.object.created"
    event = {"object": {"id": "wanted", "name": "UI"}}
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        subscription_events={topic: [event]},
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["wait-topic", topic, "--no-timeout"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["event"] == event
    assert payload["subscription_timeout"] == {
        "mode": "unbounded",
        "seconds": None,
        "source": "explicit_no_timeout",
    }
    assert payload["call"]["timeout"] == "unbounded"
    assert payload["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize(
    "argv",
    (
        [
            "--timeout",
            "60",
            "wait-topic",
            "ak.wwise.core.object.created",
            "--no-timeout",
        ],
        ["--timeout", "inf", "wait-topic", "ak.wwise.core.object.created"],
    ),
)
def test_wait_topic_rejects_ambiguous_or_implicit_unbounded_timeout_before_connecting(
    tmp_path: Path,
    argv: list[str],
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid timeout must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        argv,
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert called is False


def test_wait_topic_keyboard_interrupt_closes_transport_subscription(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = "ak.wwise.core.object.created"

    def interrupt_after_subscribe(
        manager: Any,
        subscribed_topic: str,
        *,
        event_count: int,
        timeout: float,
        options: Mapping[str, Any] | None,
        queue_size: int,
        predicate: Any,
    ) -> tuple[Any, ...]:
        del event_count, timeout, queue_size, predicate
        handle = manager.subscribe(
            subscribed_topic,
            callback=lambda *args, **kwargs: None,
            options=dict(options or {}),
        )
        assert handle is not None
        raise KeyboardInterrupt

    monkeypatch.setattr(
        dispatcher_module.SubscriptionManager,
        "_wait_for_events",
        interrupt_after_subscribe,
    )
    client = FakeClient({"ak.wwise.core.getInfo": live_info()})

    exit_code, payload = waapi_gateway.execute_gateway(
        ["wait-topic", topic, "--no-timeout"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 130
    assert payload["status"] == "cancelled"
    assert payload["error_code"] == "CANCELLED"
    assert payload["cleanup"] == {"status": "transport_closed"}
    assert payload["subscription_timeout"]["mode"] == "unbounded"
    assert client.handlers[0].unsubscribe_calls == 1
    assert client.disconnected is True


def test_wait_topic_collects_bounded_matching_events_in_order(tmp_path: Path) -> None:
    topic = "ak.wwise.core.object.created"
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        subscription_events={
            topic: [
                {"object": {"id": "wrong", "name": "Ignore"}},
                {"object": {"id": "wanted", "name": "UI_1"}},
                {"object": {"id": "wanted", "name": "UI_2"}},
                {"object": {"id": "wanted", "name": "UI_3"}},
            ]
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        [
            "--timeout",
            "0.5",
            "wait-topic",
            topic,
            "--event-count",
            "3",
            "--match-json",
            '{"object":{"id":"wanted"}}',
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 0
    assert payload["requested_event_count"] == 3
    assert payload["event_count"] == 3
    assert [event["object"]["name"] for event in payload["events"]] == ["UI_1", "UI_2", "UI_3"]
    assert len(payload["event_validations"]) == 3
    assert "event" not in payload
    assert payload["cleanup"] == "unsubscribed"
    assert client.handlers[0].unsubscribe_calls == 1


@pytest.mark.parametrize("event_count", ("0", "65"))
def test_wait_topic_rejects_invalid_event_count_before_connecting(
    tmp_path: Path,
    event_count: str,
) -> None:
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"invalid event count must not connect to {url}")

    exit_code, payload = waapi_gateway.execute_gateway(
        ["wait-topic", "ak.wwise.core.object.created", "--event-count", event_count],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["error_code"] == "GatewayInputError"
    assert "--event-count must be between 1 and 64" in payload["message"]
    assert called is False


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


def test_wait_topic_multi_event_aggregate_respects_result_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic = "ak.wwise.core.object.created"
    sentinel = "OVERSIZED_MULTI_TOPIC_PAYLOAD_MUST_NOT_ESCAPE"
    monkeypatch.setattr(dispatcher_module, "MAX_LIVE_RESULT_JSON_BYTES", 2048)
    client = FakeClient(
        {"ak.wwise.core.getInfo": live_info()},
        subscription_events={
            topic: [
                {"object": {"id": f"wanted-{index}", "name": sentinel + ("x" * 900)}}
                for index in range(3)
            ]
        },
    )

    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", "0.5", "wait-topic", topic, "--event-count", "3"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )

    assert exit_code == 2
    assert payload["call"]["error_code"] == "RESULT_TOO_LARGE"
    assert payload["requested_event_count"] == 3
    assert payload["events"] is None
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


def test_debug_assert_topic_is_routed_to_bounded_wait_before_connecting(
    tmp_path: Path,
) -> None:
    topic = "ak.wwise.debug.assertFailed"
    called = False

    def client_factory(url: str) -> FakeClient:
        nonlocal called
        called = True
        raise AssertionError(f"topic route boundary must not connect to {url}")

    assert frozenset(EXPLICIT_UNSUPPORTED_TOPIC_URIS) == EXPECTED_EXCLUDED_TOPIC_URIS

    exit_code, payload = waapi_gateway.execute_gateway(
        ["call", topic, "--dry-run"],
        env=gateway_env(tmp_path),
        client_factory=client_factory,
    )

    assert exit_code == 2
    assert payload["status"] == "wait_topic_required"
    assert payload["error_code"] == "WAIT_TOPIC_REQUIRED"
    assert payload["required_command"] == "wait-topic"
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
        {
            "ak.wwise.core.getInfo": live_info(
                command_line=topic != "ak.wwise.ui.commands.executed"
            )
        },
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
    details = payload["call"]["details"]
    assert details["cleanup_pending"] is False
    # The dispatch reserves time for unsubscribe, but an overloaded scheduler
    # may resume the waiter after the outer 100 ms deadline.  Preserve the
    # truthful wall-clock flag instead of treating that scheduling variance as
    # a cleanup failure.
    assert details["deadline_exhausted"] is (
        details["elapsed_seconds"] >= details["configured_timeout_seconds"]
    )
    assert 0 < details["operation_timeout_seconds"] < 0.1
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


def test_wait_topic_no_timeout_keeps_transport_connect_finitely_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_factory = threading.Event()
    disconnected = threading.Event()

    class LateClient:
        def disconnect(self) -> None:
            disconnected.set()

    def slow_factory(url: str) -> LateClient:
        del url
        release_factory.wait(timeout=2)
        return LateClient()

    monkeypatch.setattr(waapi_gateway, "DEFAULT_TIMEOUT", 0.03)
    started_at = time.monotonic()
    try:
        exit_code, payload = waapi_gateway.execute_gateway(
            [
                "wait-topic",
                "ak.wwise.core.object.created",
                "--no-timeout",
            ],
            env=gateway_env(tmp_path),
            client_factory=slow_factory,
        )
    finally:
        release_factory.set()
    elapsed = time.monotonic() - started_at

    assert exit_code == 2
    assert elapsed < 0.15
    assert payload["error_code"] == "TIMEOUT"
    assert payload["details"]["phase"] == "transport.connect"
    assert payload["details"]["timeout_mode"] == "unbounded"
    assert payload["details"]["deadline_exhausted"] is False
    assert payload["details"]["cleanup_pending"] is True
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


def test_transport_producer_drops_result_completed_after_monotonic_deadline() -> None:
    response: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
    request = waapi_gateway._TransportRequest(
        request_id="expired-request",
        phase="WAAPI call expired",
        operation="call",
        args=("expired", None),
        kwargs={},
        response=response,
        expires_at=time.monotonic() - 1.0,
        cancelled=threading.Event(),
    )

    waapi_gateway.GatewayTransport._deliver(request, (True, {"late": True}))

    assert request.cancelled.is_set()
    with pytest.raises(queue.Empty):
        response.get_nowait()


def test_transport_producer_preserves_completed_close_result_after_deadline() -> None:
    response: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
    request = waapi_gateway._TransportRequest(
        request_id="completed-close",
        phase="transport.close",
        operation="close",
        args=(),
        kwargs={},
        response=response,
        expires_at=time.monotonic() - 1.0,
        cancelled=threading.Event(),
    )

    waapi_gateway.GatewayTransport._deliver(request, (True, None))

    assert request.cancelled.is_set() is False
    assert response.get_nowait() == (True, None)


def test_timeout_payload_marks_cleanup_complete_when_late_call_releases_in_grace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_call_entered = threading.Event()
    release_object_call = threading.Event()
    disconnected = threading.Event()
    configured_timeout = 0.2
    captured_connections: list[waapi_gateway.GatewayConnection] = []
    resolve_connection = waapi_gateway.resolve_connection

    def capture_connection(
        args: Any,
        *,
        env: Mapping[str, str],
    ) -> waapi_gateway.GatewayConnection:
        connection = resolve_connection(args, env=env)
        captured_connections.append(connection)
        return connection

    monkeypatch.setattr(waapi_gateway, "resolve_connection", capture_connection)

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

    started_at = time.monotonic()

    def release_during_cleanup_grace() -> None:
        assert object_call_entered.wait(timeout=1)
        assert len(captured_connections) == 1
        release_at = (
            captured_connections[0].deadline.expires_at
            + waapi_gateway.TRANSPORT_CLEANUP_GRACE_SECONDS / 2
        )
        remaining = release_at - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        release_object_call.set()

    releaser = threading.Thread(target=release_during_cleanup_grace)
    releaser.start()
    exit_code, payload = waapi_gateway.execute_gateway(
        ["--timeout", str(configured_timeout), "buses"],
        env=gateway_env(tmp_path),
        client_factory=lambda url: client,
    )
    elapsed = time.monotonic() - started_at
    releaser.join(timeout=1)

    assert not releaser.is_alive()
    assert elapsed < configured_timeout + waapi_gateway.TRANSPORT_CLEANUP_GRACE_SECONDS + 0.1
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

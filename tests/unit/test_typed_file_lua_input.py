from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.exact_artifact_business_cli import (
    ExactArtifactBusinessCliError,
    add_exact_artifact_plan_arguments,
    exact_artifact_plan_from_namespace,
)
from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.typed_operations import (
    TypedOperationInputError,
    draft_operation_request_contract,
    materialize_inline_operation_request,
)
from wwise_waapi.transactions import TransactionState, TransactionStore


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_exact_artifact_gateway",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path, version: str = "2025.1") -> dict[str, str]:
    config = tmp_path / f"config-{version}.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": version,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_PORT": "8080",
    }


class _LuaClient:
    def __init__(self, tmp_path: Path) -> None:
        self.project = tmp_path / "project" / "SampleProject.wproj"
        self.project.parent.mkdir(exist_ok=True)
        self.project.write_text("<Project/>", encoding="utf-8")
        self.calls: list[str] = []

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append(uri)
        if uri == "ak.wwise.core.getInfo":
            return {
                "displayName": "WwiseConsole",
                "isCommandLine": True,
                "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "processId": 42,
                "processPath": "/Applications/WwiseConsole",
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {
                    "year": 2025,
                    "major": 1,
                    "minor": 0,
                    "build": 1,
                    "displayName": "v2025.1.0.1",
                },
            }
        if uri == "ak.wwise.core.getProjectInfo":
            return {
                "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "name": "SampleProject",
                "path": str(self.project),
            }
        if uri == "ak.wwise.cli.executeLuaScript":
            return {"result": 0}
        raise AssertionError((uri, args, options))

    def disconnect(self) -> None:
        pass


class _TabClient(_LuaClient):
    location_id = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if uri == "ak.wwise.core.object.get":
            self.calls.append(uri)
            return {
                "return": [
                    {
                        "id": self.location_id,
                        "name": "Default Work Unit",
                        "type": "WorkUnit",
                        "path": r"\Containers\Default Work Unit",
                    }
                ]
            }
        return super().call(uri, args, options)


class _AuthoringLuaClient(_LuaClient):
    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        result = super().call(uri, args, options)
        if uri == "ak.wwise.core.getInfo":
            return {**result, "displayName": "Wwise", "isCommandLine": False}
        return result


@pytest.mark.parametrize(
    "version",
    ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
)
def test_tab_delimited_import_has_one_public_business_entry(
    tmp_path: Path,
    version: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "operation-schema", "audio.importTabDelimited"],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["operation"]["input_mode"] == "business_declaration"
    assert payload["business_adapter"]["declaration"]["subcommand"] == (
        "draft-declare-artifact-plan"
    )
    assert payload["business_adapter"]["legacy_inline_typed_public"] is False
    assert payload["business_adapter"]["binding"]["role_required"] is True
    assert "typed_operation" not in payload


@pytest.mark.parametrize(
    ("operation", "versions"),
    (
        ("lua.executeCliFile", ("2023.1", "2024.1", "2025.1")),
        ("lua.executeCoreFile", ("2023.1", "2024.1", "2025.1")),
        ("lua.executeCoreInline", ("2025.1",)),
    ),
)
def test_lua_lanes_have_one_public_business_draft(
    tmp_path: Path,
    operation: str,
    versions: tuple[str, ...],
) -> None:
    for version in versions:
        code, payload = gateway.execute_gateway(
            ["--version", version, "operation-schema", operation],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
        )
        assert code == 0, payload
        assert payload["operation"]["input_mode"] == "business_declaration"
        adapter = payload["business_adapter"]
        assert adapter["start"]["next_command"]["gateway_argv"] == [
            "draft-start",
            operation,
        ]
        assert adapter["declaration"]["subcommand"] == (
            "draft-declare-artifact-plan"
        )
        assert adapter["legacy_composer_public"] is False
        assert "source_authority" not in adapter["declaration"]["public_fields"]
        assert "composer" not in payload
        assert "bind-object" not in business_adapter(operation).projection_actions(
            session_bound=False
        )


def test_tab_lane_retains_its_required_object_binding_action(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", "2025.1", "operation-schema", "audio.importTabDelimited"],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )

    assert code == 0, payload
    assert "bind-object" in business_adapter(
        "audio.importTabDelimited"
    ).projection_actions(session_bound=False)


def test_retired_typed_ingresses_are_not_callable() -> None:
    with pytest.raises(TypedOperationInputError, match="No inline typed adapter"):
        materialize_inline_operation_request(
            "audio.importTabDelimited",
            "2025.1",
            {},
        )
    with pytest.raises(TypedOperationInputError, match="No typed Draft adapter"):
        draft_operation_request_contract("lua.executeCoreInline", "2025.1")


def test_tab_business_draft_binds_the_disclosed_import_location_role(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "tab-business-state"
    start_code, started = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            "audio.importTabDelimited",
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started
    client = _TabClient(tmp_path)

    missing_role_code, missing_role = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--object-id",
            client.location_id,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert missing_role_code == 2, missing_role
    assert "requires one disclosed role: import_location" in missing_role["message"]

    bind_code, bound = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--role",
            "import_location",
            "--object-id",
            client.location_id,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert bind_code == 0, bound
    assert bound["bound_object"]["role"] == "import_location"
    assert bound["bound_object"]["type"] == "WorkUnit"
    declaration = bound["draft"]["next_action_binding"]["declaration"]
    assert declaration["business_value_choices"]["mode"] == {
        "create": "Wwise createNew",
        "reimport": "Wwise useExisting",
        "replace": "Wwise replaceExisting",
    }


def test_lua_business_draft_rejects_roleless_object_binding(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "lua-no-object-state"
    start_code, started = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            "lua.executeCoreFile",
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started
    client = _LuaClient(tmp_path)

    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--object-id",
            "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 2, payload
    assert "roles are unavailable" in payload["message"]
    assert "ak.wwise.core.object.get" not in client.calls


def test_cli_lua_declaration_rejects_authoring_before_project_read(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "cli-authoring-boundary"
    script = tmp_path / "script.lua"
    script.write_text("return true\n", encoding="utf-8")
    start_code, started = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            "lua.executeCliFile",
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started
    client = _AuthoringLuaClient(tmp_path)

    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-declare-artifact-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--script-file",
            str(script),
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 2, payload
    assert payload["error_code"] == "COMMAND_LINE_HOST_REQUIRED"
    assert payload["details"]["required_host"] == "wwise-console"
    assert client.calls == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize("command", ("preview-from-draft", "execute"))
def test_cli_lua_preview_and_dispatch_require_console_host(command: str) -> None:
    payload = gateway.live_authoring_transaction_boundary(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2025.1",
            "operation": "lua.executeCliFile",
            "arguments": {},
        },
        command=command,
        live_info={"isCommandLine": False},
        common={"offline": False},
    )

    assert payload is not None
    assert payload["error_code"] == "COMMAND_LINE_HOST_REQUIRED"
    assert payload["command"] == command
    assert payload["executed"] is False
    assert payload["verified"] is False


def test_lua_continuation_discloses_one_bounded_typed_argument_at_a_time(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "lua-null-continuation"
    code, payload = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            "lua.executeCoreInline",
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )

    assert code == 0, payload
    append = payload["draft"]["next_action_binding"]["declaration"]["append"]
    assert any("--argument <key> <type> <value>" in row for row in append)
    assert all("alternative:" not in row for row in append)
    assert all("--arguments-json" not in row for row in append)


def test_lua_artifact_plan_accepts_repeated_typed_business_arguments(
    tmp_path: Path,
) -> None:
    operation = "lua.executeCoreFile"
    state_dir = tmp_path / "lua-complete-args-state"
    script = tmp_path / "script.lua"
    script.write_text("return wa_args.count\n", encoding="utf-8")
    start_code, started = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started

    declaration_code, declared = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-declare-artifact-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--script-file",
            str(script),
            "--argument",
            "count",
            "integer",
            "3",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: _LuaClient(tmp_path),
    )

    assert declaration_code == 0, declared
    request = OperationDraftStore(state_dir).materialize_request(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
        expected_revision=declared["draft"]["revision"],
        schema_digest=gateway.operation_draft_schema_digest(
            operation,
            "2025.1",
        ),
        composer_digest=operation_composer_digest(operation, "2025.1"),
    ).request
    assert request["arguments"]["wa_args"] == {"count": 3}


def test_lua_artifact_cli_has_no_complete_json_map_input() -> None:
    parser = argparse.ArgumentParser()
    add_exact_artifact_plan_arguments(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--script-file",
                "/tmp/user.lua",
                "--arguments-json",
                '{"count":3}',
            ]
        )


def _preview_public_cli_lua_file(
    tmp_path: Path,
    *,
    state_name: str,
) -> tuple[Path, Mapping[str, Any], Mapping[str, Any], Path]:
    operation = "lua.executeCliFile"
    state_dir = tmp_path / state_name
    io_root = tmp_path / "lua-io"
    io_root.mkdir(exist_ok=True)
    script = io_root / f"{state_name}.lua"
    script.write_bytes(b"return wa_args.request_id\n")
    start_code, started = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    declaration_code, declared = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-declare-artifact-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--script-file",
            str(script),
            "--argument",
            "request_id",
            "string",
            "draft-chain",
            "--watchdog-seconds",
            "15",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: _LuaClient(tmp_path),
    )
    assert declaration_code == 0, declared
    declaration_revision = declared["draft"]["revision"]
    expected = OperationDraftStore(state_dir).materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=declaration_revision,
        schema_digest=gateway.operation_draft_schema_digest(
            operation,
            "2025.1",
        ),
        composer_digest=operation_composer_digest(operation, "2025.1"),
    ).request

    check_code, checked = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(declaration_revision),
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: _LuaClient(tmp_path),
    )
    assert check_code == 0, checked
    preview_code, previewed = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: _LuaClient(tmp_path),
    )
    assert preview_code == 0, previewed
    assert previewed["agent_result"]["request"] == expected
    return state_dir, started, previewed, script


def test_public_lua_business_draft_executes_once_and_ends_result_schema_only(
    tmp_path: Path,
) -> None:
    state_dir, _started, previewed, script = _preview_public_cli_lua_file(
        tmp_path,
        state_name="lua-business-state",
    )
    store = TransactionStore(state_dir)
    confirm_code, confirmed = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "confirm",
            previewed["transaction_id"],
            "--confirmation-token",
            store.load_snapshot(previewed["transaction_id"]).confirmation_token,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"confirm connected to {url}"),
    )
    assert confirm_code == 0, confirmed
    execution_client = _LuaClient(tmp_path)
    execute_code, executed = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "execute",
            previewed["transaction_id"],
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: execution_client,
    )
    assert execute_code == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert execution_client.calls.count("ak.wwise.cli.executeLuaScript") == 1

    verify_client = _LuaClient(tmp_path)
    verify_code, verified = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "verify",
            previewed["transaction_id"],
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: verify_client,
    )
    assert verify_code == 0, verified
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verified["verified"] is False
    assert script.read_bytes() == b"return wa_args.request_id\n"


def test_public_lua_business_draft_rejects_source_drift_before_dispatch(
    tmp_path: Path,
) -> None:
    state_dir, _started, previewed, script = _preview_public_cli_lua_file(
        tmp_path,
        state_name="lua-drift-state",
    )
    store = TransactionStore(state_dir)
    confirm_code, confirmed = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "confirm",
            previewed["transaction_id"],
            "--confirmation-token",
            store.load_snapshot(previewed["transaction_id"]).confirmation_token,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"confirm connected to {url}"),
    )
    assert confirm_code == 0, confirmed
    script.write_bytes(b"return 'changed-after-preview'\n")
    execution_client = _LuaClient(tmp_path)
    execute_code, rejected = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(state_dir),
            "execute",
            previewed["transaction_id"],
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: execution_client,
    )
    assert execute_code == 2, rejected
    assert rejected["status"] == "repreview_required"
    assert "ak.wwise.cli.executeLuaScript" not in execution_client.calls

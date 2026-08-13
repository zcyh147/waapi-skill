from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest

from wwise_waapi.builders.debug_lua import LUA_SOURCE_AUTHORITY
from wwise_waapi.operation_composer import materialize_operation_request
from wwise_waapi.operation_registry import parse_operation_request
from wwise_waapi.typed_operations import (
    draft_operation_request_contract,
    inline_operation_contract,
    materialize_inline_operation_request,
)
from wwise_waapi.typed_requests import TypedRequestFact, materialize_typed_request
from wwise_waapi.transactions import TransactionStore
from wwise_waapi.transactions import TransactionState


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_file_lua_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / f"config-{version}.json"
    config.write_text(
        json.dumps({"wwise_version": version, "project_modification_policy": "ask_before_changes"}),
        encoding="utf-8",
    )
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_WAAPI_PORT": "8080"}


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_tab_delimited_import_has_one_public_inline_entry(tmp_path: Path, version: str) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "operation-schema", "audio.importTabDelimited"],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )
    assert code == 0, payload
    assert payload["operation"]["input_mode"] == "inline_typed"
    assert payload["typed_operation"]["continuation"]["subcommand"] == "typed-operation"
    assert "request-json" not in json.dumps(payload["typed_operation"])


@pytest.mark.parametrize(
    ("operation", "versions"),
    (
        ("lua.executeCliFile", ("2023.1", "2024.1", "2025.1")),
        ("lua.executeCoreFile", ("2023.1", "2024.1", "2025.1")),
        ("lua.executeCoreInline", ("2025.1",)),
    ),
)
def test_lua_lanes_have_one_public_typed_draft(
    tmp_path: Path, operation: str, versions: tuple[str, ...]
) -> None:
    for version in versions:
        code, payload = gateway.execute_gateway(
            ["--version", version, "operation-schema", operation],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
        )
        assert code == 0, payload
        assert payload["operation"]["input_mode"] == "composer"
        assert payload["composer"]["start"]["subcommand"] == "draft-start"
        assert payload["composer"]["complete_request_authored_by_gateway"] is True


def test_tab_delimited_materializes_exact_user_file_and_typed_options(tmp_path: Path) -> None:
    source = tmp_path / "Import 表.tsv"
    source.write_bytes(b"Audio File\tObject Path\nvoice.wav\t\\Actor-Mixer Hierarchy\\Voice\n")
    request = materialize_inline_operation_request(
        "audio.importTabDelimited",
        "2025.1",
        {
            "import_file": str(source),
            "import_location": ("path", r"\Actor-Mixer Hierarchy\Default Work Unit"),
            "import_language": "English(US)",
            "import_operation": "replaceExisting",
            "auto_add_to_source_control": "true",
            "auto_check_out_to_source_control": "false",
        },
    )
    assert request["arguments"] == {
        "import_file": str(source),
        "import_location": {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit"},
        "import_language": "English(US)",
        "import_operation": "replaceExisting",
        "auto_add_to_source_control": True,
        "auto_check_out_to_source_control": False,
    }
    assert source.read_bytes().startswith(b"Audio File\tObject Path")
    parse_operation_request(request, expected_version="2025.1")


def _field(contract: object, path: tuple[str, ...], *, shape: str | None = None):
    return next(
        field
        for field in contract.fields
        if field.path == path and (shape is None or field.shape == shape)
    )


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
                "displayName": "Wwise",
                "isCommandLine": True,
                "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "processId": 42,
                "processPath": "/Applications/Wwise.app/Contents/MacOS/Wwise",
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {"year": 2025, "major": 1, "minor": 0, "build": 1},
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


def _apply_facts(
    tmp_path: Path,
    *,
    state_dir: Path,
    started: Mapping[str, Any],
    facts: tuple[TypedRequestFact, ...],
) -> int:
    revision = 1
    for fact in facts:
        argv = [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision), "--facts",
            "--action", "add_typed_fact", "--fact-action", fact.action,
            "--field-handle", fact.handle,
        ]
        if fact.action in {"choose", "choose-dynamic"}:
            argv += ["--fact-value", fact.value]
        elif fact.action != "present":
            argv += ["--value-type", fact.value_type, "--fact-value", fact.value]
        if fact.key is not None:
            argv += ["--key", fact.key]
        code, payload = gateway.execute_gateway(
            argv,
            env=_env(tmp_path, "2025.1"),
            client_factory=lambda url: pytest.fail(f"draft-apply connected to {url}"),
        )
        assert code == 0, payload
        revision = payload["draft"]["revision"]
    return revision


def test_lua_open_map_and_inline_source_materialize_without_json_input(tmp_path: Path) -> None:
    contract = draft_operation_request_contract("lua.executeCoreInline", "2025.1")
    facts = (
        TypedRequestFact("set", _field(contract, ("lua_code",)).handle, "string", "return wa_args.request_id\n"),
        TypedRequestFact("set", _field(contract, ("io_root",)).handle, "string", str(tmp_path)),
        TypedRequestFact("set", _field(contract, ("source_authority",)).handle, "string", LUA_SOURCE_AUTHORITY),
        TypedRequestFact(
            "map-put",
            _field(contract, ("wa_args",), shape="map").handle,
            "string",
            "request_id",
            key="request_id",
        ),
    )
    materialized = materialize_typed_request(
        contract, schema_digest=contract.schema_digest, facts=facts
    )
    assert materialized.args == {
        "lua_code": "return wa_args.request_id\n",
        "io_root": str(tmp_path),
        "source_authority": LUA_SOURCE_AUTHORITY,
        "wa_args": {"request_id": "request_id"},
    }
    parse_operation_request(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": "2025.1",
            "operation": "lua.executeCoreInline",
            "arguments": materialized.args,
        },
        expected_version="2025.1",
    )


def _preview_public_cli_lua_file(
    tmp_path: Path,
    *,
    state_name: str,
) -> tuple[Path, Mapping[str, Any], int, Mapping[str, Any], Path]:
    operation = "lua.executeCliFile"
    state_dir = tmp_path / state_name
    io_root = tmp_path / "lua-io"
    io_root.mkdir(exist_ok=True)
    script = io_root / f"{state_name}.lua"
    script.write_text("return wa_args.request_id\n", encoding="utf-8")
    contract = draft_operation_request_contract(operation, "2025.1")
    start_code, started = gateway.execute_gateway(
        ["--version", "2025.1", "--state-dir", str(state_dir), "draft-start", operation],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"draft-start connected to {url}"),
    )
    assert start_code == 0, started
    facts = (
        TypedRequestFact(
            "set", _field(contract, ("script_file",)).handle, "string", str(script)
        ),
        TypedRequestFact("set", _field(contract, ("io_root",)).handle, "string", str(io_root)),
        TypedRequestFact(
            "set", _field(contract, ("source_authority",)).handle, "string", LUA_SOURCE_AUTHORITY
        ),
        TypedRequestFact(
            "map-put",
            _field(contract, ("wa_args",), shape="map").handle,
            "string",
            "draft-chain",
            key="request_id",
        ),
        TypedRequestFact(
            "set", _field(contract, ("watchdog_seconds",)).handle, "integer", "15"
        ),
    )
    revision = _apply_facts(
        tmp_path, state_dir=state_dir, started=started, facts=facts
    )
    inspected = gateway.OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"], task_authority=started["task_authority"]
    )
    expected = materialize_operation_request(
        operation, "2025.1", inspected.composition
    )

    check_code, checked = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-check", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision),
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: _LuaClient(tmp_path),
    )
    assert check_code == 0, checked
    checked_revision = checked["draft"]["revision"]

    preview_code, previewed = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "preview-from-draft", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(checked_revision), "--apply",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: _LuaClient(tmp_path),
    )
    assert preview_code == 0, previewed
    assert previewed["agent_result"]["request"] == expected
    store = TransactionStore(state_dir)
    assert store.load_preview(previewed["transaction_id"]).artifact["request"] == expected
    source_proof = store.load_preview(previewed["transaction_id"]).artifact[
        "prepared_operation"
    ]["pre_state"]["lua_source_proof"]
    assert source_proof["file"]["path"] == str(script.resolve())
    assert source_proof["file"]["size"] == len(script.read_bytes())
    return state_dir, started, checked_revision, previewed, script


def test_public_lua_draft_runs_once_and_finishes_at_result_schema_only(
    tmp_path: Path,
) -> None:
    state_dir, started, checked_revision, previewed, script = (
        _preview_public_cli_lua_file(tmp_path, state_name="lua-draft-state")
    )
    store = TransactionStore(state_dir)
    events = store.read_events(previewed["transaction_id"])

    replay_code, replayed = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "preview-from-draft", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(checked_revision), "--apply",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: _LuaClient(tmp_path),
    )
    assert replay_code == 0, replayed
    assert replayed["transaction_id"] == previewed["transaction_id"]
    assert store.read_events(previewed["transaction_id"]) == events

    confirm_code, confirmed = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "confirm", previewed["transaction_id"],
            "--confirmation-token",
            store.load_snapshot(previewed["transaction_id"]).confirmation_token,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"confirm connected to {url}"),
    )
    assert confirm_code == 0, confirmed
    assert confirmed["state"] == TransactionState.CONFIRMED.value

    execution_client = _LuaClient(tmp_path)
    execute_code, executed = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "execute", previewed["transaction_id"],
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: execution_client,
    )
    assert execute_code == 0, executed
    assert executed["state"] == TransactionState.EXECUTED_UNVERIFIED.value
    assert execution_client.calls.count("ak.wwise.cli.executeLuaScript") == 1

    verify_client = _LuaClient(tmp_path)
    verify_code, verified = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "verify", previewed["transaction_id"],
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: verify_client,
    )
    assert verify_code == 0, verified
    assert verified["state"] == TransactionState.RESULT_SCHEMA_CHECKED.value
    assert verified["status"] == "result_schema_checked"
    assert verified["verified"] is False
    assert verified["verification"]["business_state_verified"] is False
    assert "ak.wwise.cli.executeLuaScript" not in verify_client.calls
    assert script.read_text(encoding="utf-8") == "return wa_args.request_id\n"
    final_events = store.read_events(previewed["transaction_id"])
    assert [event["event_type"] for event in final_events].count("execution_started") == 1
    assert [event["event_type"] for event in final_events].count("execution_completed") == 1


def test_public_lua_draft_rejects_source_drift_before_dispatch(tmp_path: Path) -> None:
    state_dir, _started, _checked_revision, previewed, script = (
        _preview_public_cli_lua_file(tmp_path, state_name="lua-drift-state")
    )
    store = TransactionStore(state_dir)
    confirm_code, confirmed = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "confirm", previewed["transaction_id"],
            "--confirmation-token",
            store.load_snapshot(previewed["transaction_id"]).confirmation_token,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"confirm connected to {url}"),
    )
    assert confirm_code == 0, confirmed
    script.write_text("return 'changed-after-preview'\n", encoding="utf-8")
    execution_client = _LuaClient(tmp_path)
    execute_code, rejected = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "execute", previewed["transaction_id"],
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: execution_client,
    )
    assert execute_code == 2, rejected
    assert rejected["status"] == "repreview_required"
    assert rejected["executed"] is False
    assert "ak.wwise.cli.executeLuaScript" not in execution_client.calls


def test_cli_watchdog_is_disclosed_only_in_supported_lanes() -> None:
    old = draft_operation_request_contract("lua.executeCliFile", "2023.1")
    new = draft_operation_request_contract("lua.executeCliFile", "2024.1")
    assert not any(field.path == ("watchdog_seconds",) for field in old.fields)
    assert any(field.path == ("watchdog_seconds",) for field in new.fields)


def test_lua_open_map_discloses_and_enforces_exact_packaged_bounds() -> None:
    contract = draft_operation_request_contract("lua.executeCoreInline", "2025.1")
    wa_args = _field(contract, ("wa_args",), shape="map")
    disclosed = wa_args.as_dict()
    assert disclosed["maximum_properties"] == 64
    assert disclosed["maximum_bytes"] == 64 * 1024
    assert disclosed["maximum_key_bytes"] == 128

    facts = tuple(
        TypedRequestFact("map-put", wa_args.handle, "string", str(index), key=f"k{index}")
        for index in range(65)
    )
    with pytest.raises(Exception, match="at most 64 properties"):
        materialize_typed_request(
            contract, schema_digest=contract.schema_digest, facts=facts
        )
    with pytest.raises(Exception, match="key exceeds"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(
                TypedRequestFact(
                    "map-put", wa_args.handle, "string", "value", key="x" * 129
                ),
            ),
        )


@pytest.mark.parametrize("reserved", ("luaScript", "doFiles", "requires"))
def test_lua_reserved_loader_fields_fail_closed(reserved: str, tmp_path: Path) -> None:
    operation = "lua.executeCoreInline"
    contract = draft_operation_request_contract(operation, "2025.1")
    wa_args = _field(contract, ("wa_args",), shape="map")
    materialized = materialize_typed_request(
        contract,
        schema_digest=contract.schema_digest,
        facts=(
            TypedRequestFact("set", _field(contract, ("lua_code",)).handle, "string", "return true"),
            TypedRequestFact("set", _field(contract, ("io_root",)).handle, "string", str(tmp_path)),
            TypedRequestFact("set", _field(contract, ("source_authority",)).handle, "string", LUA_SOURCE_AUTHORITY),
            TypedRequestFact("map-put", wa_args.handle, "string", "blocked", key=reserved),
        ),
    )
    with pytest.raises(Exception, match="source or loader field"):
        parse_operation_request(
            {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2025.1",
                "operation": operation,
                "arguments": materialized.args,
            },
            expected_version="2025.1",
        )

from __future__ import annotations

import copy
import json
import os
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.semantic.support import codex_eval_fixtures as fixture_support
from tests.semantic.support.codex_eval_fixtures import (
    AudioOracleSnapshot,
    FieldOracleSnapshot,
    FixtureContractError,
    MissingPathOracleSnapshot,
    ObjectRowsOracleSnapshot,
    ObjectPresenceOracleSnapshot,
    PackagedGatewayBinding,
    PathOracleSnapshot,
    ReferenceOracleSnapshot,
    RenameOracleSnapshot,
    SoundBankOracleSnapshot,
    SwitchOracleSnapshot,
    create_shared_fixture_bundle,
    normalize_typed_import_object_path,
)
from wwise_waapi.transactions import confirmation_token_for
from wwise_waapi.platform_commands import (
    PlatformCommandError,
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    encode_windows_model_argv,
    encode_windows_powershell_argv,
)


GATEWAY_CONTRACT = "waapi-skill.gateway-result/v1"
ROOT_PATH_IDS = {
    r"\Actor-Mixer Hierarchy\Default Work Unit": "{actor-parent}",
    r"\Containers\Default Work Unit": "{containers-parent}",
    r"\SoundBanks\Default Work Unit": "{soundbank-parent}",
    r"\Switches\Default Work Unit": "{switch-parent}",
}
FACTORY_QUERY_ID = "{52F6FBC8-499A-411D-A790-CB4FACBE6F6D}"
FACTORY_QUERY_PATH = r"\Queries\Factory Queries\Sound = SFX"
FAKE_TRUSTED_GATEWAY_RUNNER = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "fake-waapi-skill"
    / "scripts"
    / "run.py"
)


def _fake_trusted_next_command(
    command: str,
    gateway_argv: tuple[str, ...],
    *,
    requires_explicit_user_confirmation: bool = False,
    platform_name: str | None = None,
) -> dict[str, Any]:
    full_argv = (
        "python",
        str(FAKE_TRUSTED_GATEWAY_RUNNER),
        "gateway.py",
        *gateway_argv,
    )
    result: dict[str, Any] = {
        "contract": "waapi-skill.gateway-next-command/v2",
        "command": command,
        "gateway_argv": list(gateway_argv),
        "full_argv": list(full_argv),
        "copy_exactly": True,
    }
    if requires_explicit_user_confirmation:
        result["requires_explicit_user_confirmation"] = True
    model_command: str | None = None
    active_platform = os.name if platform_name is None else platform_name
    if active_platform == "nt":
        result["shell_family"] = WINDOWS_POWERSHELL_ENCODED_FAMILY
        shell_command = encode_windows_powershell_argv(full_argv)
        try:
            model_command = encode_windows_model_argv(full_argv)
        except PlatformCommandError:
            model_command = None
    else:
        result["shell_family"] = "posix-sh"
        shell_command = shlex.join(full_argv)
    if model_command is not None:
        result["shell_command"] = shell_command
        result["model_shell_family"] = WINDOWS_MODEL_COMMAND_FAMILY
    result["copy_instruction"] = {
        "contract": "waapi-skill.gateway-command-copy-instruction/v2",
        "source_field": (
            "model_command" if model_command is not None else "shell_command"
        ),
        "action": "execute_verbatim_as_one_shell_tool_call",
        "forbidden_transformations": [
            "reconstruct",
            "shorten",
            "normalize",
            "substitute_path_segments",
            "select_another_field",
        ],
    }
    if model_command is not None:
        result["model_command"] = model_command
    else:
        result["shell_command"] = shell_command
    return result


class FakeTrustedWwise:
    def __init__(self, *, actor_mixer_reflected_type: str = "ActorMixer") -> None:
        self.actor_mixer_reflected_type = actor_mixer_reflected_type
        self.objects: dict[str, dict[str, Any]] = {}
        self.transactions: dict[str, dict[str, Any]] = {}
        self.inclusions: list[dict[str, Any]] = []
        self.assignments: list[dict[str, Any]] = []
        self.references: dict[str, str] = {}
        self.requests: list[dict[str, Any]] = []
        self.delete_order: list[str] = []
        self._next_id = 1
        self._next_tx = 1

    def gateway(self, argv: Sequence[str], env: Mapping[str, str]) -> Mapping[str, Any]:
        parsed = _parse_gateway_argv(argv)
        command = parsed["command"]
        command_args = parsed["command_args"]
        self.requests.append({**parsed, "env": dict(env)})
        common = {"contract": GATEWAY_CONTRACT, "ok": True, "command": command}
        if command == "preview":
            request = json.loads(command_args[command_args.index("--request-json") + 1])
            tx = f"tx-{self._next_tx}"
            self._next_tx += 1
            artifact_hash = f"{self._next_tx:064x}"[-64:]
            event_sequence = 2
            last_event_hash = "b" * 64
            self.transactions[tx] = {
                "request": copy.deepcopy(request),
                "artifact_hash": artifact_hash,
                "confirmation_token": confirmation_token_for(
                    transaction_id=tx,
                    artifact_hash=artifact_hash,
                    state="awaiting_confirmation",
                    event_sequence=event_sequence,
                    last_event_hash=last_event_hash,
                ),
                "event_sequence": event_sequence,
                "last_event_hash": last_event_hash,
                "state": "awaiting_confirmation",
            }
            return {
                **common,
                "state": "awaiting_confirmation",
                "status": "awaiting_confirmation",
                "transaction_id": tx,
                "artifact_hash": artifact_hash,
                "preview_summary": {"request": request},
                "executed": False,
                "verified": False,
            }
        transaction_id = command_args[0]
        transaction = self.transactions[transaction_id]
        if command == "transaction-show":
            assert command_args == (transaction_id, "--summary-only")
            confirmation_token = transaction["confirmation_token"]
            return {
                **common,
                "state": transaction["state"],
                "transaction_id": transaction_id,
                "artifact_hash": transaction["artifact_hash"],
                "confirmation": {
                    "contract": "waapi-skill.confirmation-binding/v1",
                    "token": confirmation_token,
                    "binding": {
                        "material_contract": "waapi-skill.confirmation-token-material/v1",
                        "transaction_id": transaction_id,
                        "artifact_hash": transaction["artifact_hash"],
                        "state": "awaiting_confirmation",
                        "event_sequence": transaction["event_sequence"],
                        "last_event_hash": transaction["last_event_hash"],
                    },
                },
                "next_command": _fake_trusted_next_command(
                    "confirm",
                    (
                        "confirm",
                        transaction_id,
                        "--confirmation-token",
                        confirmation_token,
                    ),
                    requires_explicit_user_confirmation=True,
                ),
            }
        if command == "confirm":
            assert command_args == (
                transaction_id,
                "--confirmation-token",
                transaction["confirmation_token"],
            )
            transaction["state"] = "confirmed"
            return {
                **common,
                "state": "confirmed",
                "transaction_id": transaction_id,
                "artifact_hash": transaction["artifact_hash"],
            }
        if command == "execute":
            transaction["state"] = "executed_unverified"
            result = self._execute(transaction["request"])
            return {
                **common,
                "state": "executed_unverified",
                "status": "executed_unverified",
                "transaction_id": transaction_id,
                "artifact_hash": transaction["artifact_hash"],
                "executed": True,
                "verified": False,
                "dispatch_result": {"result": result},
            }
        if command == "verify":
            transaction["state"] = "verified"
            return {
                **common,
                "state": "verified",
                "status": "verified",
                "transaction_id": transaction_id,
                "artifact_hash": transaction["artifact_hash"],
                "executed": True,
                "verified": True,
                "verification": {
                    "assertions": [{"name": "fake direct readback", "passed": True}]
                },
            }
        raise AssertionError(command)

    def read(self, uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        if uri == "ak.wwise.core.object.get":
            rows: list[dict[str, Any]] = []
            waql = args.get("waql")
            if waql == 'from type Query where name = "Sound = SFX" take 2':
                rows = [
                    {
                        "id": FACTORY_QUERY_ID,
                        "name": "Sound = SFX",
                        "type": "Query",
                        "path": FACTORY_QUERY_PATH,
                    }
                ]
            elif waql == f'from query "{FACTORY_QUERY_ID}" take 10':
                rows = [
                    copy.deepcopy(row)
                    for row in self.objects.values()
                    if row["type"] == "Sound"
                ][:10]
            else:
                source = args.get("from")
                assert isinstance(source, Mapping)
                if "id" in source:
                    values = source["id"]
                    assert isinstance(values, list)
                    rows = [copy.deepcopy(self.objects[value]) for value in values if value in self.objects]
                elif "path" in source:
                    values = source["path"]
                    assert isinstance(values, list)
                    wanted = set(values)
                    rows = [copy.deepcopy(row) for row in self.objects.values() if row["path"] in wanted]
                else:
                    raise AssertionError(source)
            fields = options.get("return", [])
            assert isinstance(fields, list)
            projected = []
            for row in rows:
                value = {field: row.get(field) for field in fields if field in row}
                if "SwitchGroupOrStateGroup" in fields:
                    target = self.references.get(row["id"])
                    value["SwitchGroupOrStateGroup"] = {"id": target} if target else None
                projected.append(value)
            return {"return": projected}
        if uri == "ak.wwise.core.soundbank.getInclusions":
            return {"inclusions": copy.deepcopy(self.inclusions)}
        if uri == "ak.wwise.core.switchContainer.getAssignments":
            container_id = args["id"]
            return {
                "return": [
                    {key: copy.deepcopy(value) for key, value in row.items() if key != "__container"}
                    for row in self.assignments
                    if row.get("__container", container_id) == container_id
                ]
            }
        raise AssertionError(uri)

    def add_imported_audio(self, *, path: str, notes: str) -> str:
        object_id = self._id()
        parent_path = path.rsplit("\\", 1)[0]
        self.objects[object_id] = {
            "id": object_id,
            "name": path.rsplit("\\", 1)[-1],
            "type": "Sound",
            "path": path,
            "notes": notes,
            "parent": {"id": ROOT_PATH_IDS[parent_path]},
        }
        return object_id

    def _execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        operation = request["operation"]
        arguments = request["arguments"]
        if operation == "object.create":
            object_id = self._id()
            parent = arguments["parent"]
            parent_id = parent["value"] if parent["kind"] == "id" else ROOT_PATH_IDS[parent["value"]]
            parent_path = (
                self.objects[parent_id]["path"]
                if parent_id in self.objects
                else next(path for path, root_id in ROOT_PATH_IDS.items() if root_id == parent_id)
            )
            path = f"{parent_path}\\{arguments['name']}"
            self.objects[object_id] = {
                "id": object_id,
                "name": arguments["name"],
                "type": (
                    self.actor_mixer_reflected_type
                    if arguments["type"] == "ActorMixer"
                    else arguments["type"]
                ),
                "path": path,
                "notes": arguments.get("notes", ""),
                "parent": {"id": parent_id},
            }
            return {"id": object_id}
        if operation == "object.setReference":
            self.references[arguments["object"]["value"]] = arguments["target"]["value"]
            return {"return": True}
        if operation == "object.setProperty":
            self.objects[arguments["object"]["value"]][arguments["property"]] = arguments["value"]
            return {"return": True}
        if operation == "object.setName":
            row = self.objects[arguments["object"]["value"]]
            row["name"] = arguments["value"]
            row["path"] = row["path"].rsplit("\\", 1)[0] + "\\" + arguments["value"]
            return {"return": True}
        if operation == "object.setNotes":
            self.objects[arguments["object"]["value"]]["notes"] = arguments["value"]
            return {"return": True}
        if operation == "switchContainer.addAssignment":
            self.assignments.append(
                {
                    "__container": arguments["switch_container"]["value"],
                    "child": {"id": arguments["child"]["value"]},
                    "stateOrSwitch": {"id": arguments["state_or_switch"]["value"]},
                }
            )
            return {"return": True}
        if operation == "switchContainer.removeAssignment":
            container = arguments["switch_container"]["value"]
            child = arguments["child"]["value"]
            state = arguments["state_or_switch"]["value"]
            self.assignments = [
                row
                for row in self.assignments
                if row.get("__container", container) != container
                or _identity(row["child"]) != child
                or _identity(row["stateOrSwitch"]) != state
            ]
            return {"return": True}
        if operation == "object.delete":
            object_id = arguments["object"]["value"]
            self.delete_order.append(object_id)
            self.objects.pop(object_id, None)
            self.references.pop(object_id, None)
            self.assignments = [
                row
                for row in self.assignments
                if _identity(row["child"]) != object_id
                and _identity(row["stateOrSwitch"]) != object_id
            ]
            return {"return": True}
        raise AssertionError(operation)

    def _id(self) -> str:
        value = f"{{fixture-{self._next_id:04d}}}"
        self._next_id += 1
        return value


@pytest.fixture
def fake_runtime(tmp_path: Path) -> tuple[FakeTrustedWwise, dict[str, Any]]:
    sandbox = tmp_path / "sandbox"
    private = tmp_path / "private"
    sandbox.mkdir()
    fake = FakeTrustedWwise()
    kwargs = {
        "version": "2022.1",
        "host": "127.0.0.1",
        "port": 8122,
        "sandbox_path": sandbox,
        "private_root": private,
        "runner_env": {
            "PATH": "/usr/bin:/bin",
            "WAAPI_CODEX_GATEWAY_BROKER_TOKEN": "must-not-reach-trusted-runner",
            "WAAPI_CODEX_GATEWAY_REQUIRED": "1",
            "BASH_ENV": "/model/writable/bash-env",
        },
        "trusted_gateway": fake.gateway,
        "read_call": fake.read,
        "fixture_token": "fixed-token",
    }
    return fake, kwargs


def test_fake_trusted_wwise_show_returns_exact_token_continuation() -> None:
    fake = FakeTrustedWwise()
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.setNotes",
        "arguments": {"target": {"id": "{fixture}"}, "value": "notes"},
    }
    preview = fake.gateway(
        (
            "preview",
            "--request-json",
            json.dumps(request, ensure_ascii=False, separators=(",", ":")),
        ),
        {},
    )
    transaction_id = str(preview["transaction_id"])
    transaction = fake.transactions[transaction_id]

    shown = fake.gateway(
        ("transaction-show", transaction_id, "--summary-only"),
        {},
    )

    assert shown["confirmation"] == {
        "contract": "waapi-skill.confirmation-binding/v1",
        "token": transaction["confirmation_token"],
        "binding": {
            "material_contract": "waapi-skill.confirmation-token-material/v1",
            "transaction_id": transaction_id,
            "artifact_hash": transaction["artifact_hash"],
            "state": "awaiting_confirmation",
            "event_sequence": transaction["event_sequence"],
            "last_event_hash": transaction["last_event_hash"],
        },
    }
    assert shown["next_command"] == _fake_trusted_next_command(
        "confirm",
        (
            "confirm",
            transaction_id,
            "--confirmation-token",
            transaction["confirmation_token"],
        ),
        requires_explicit_user_confirmation=True,
    )


def test_fake_trusted_windows_response_selects_model_command_not_fallback() -> None:
    next_command = _fake_trusted_next_command(
        "confirm",
        (
            "confirm",
            "tx-response-binding",
            "--confirmation-token",
            f"ct1-{'0' * 24}",
        ),
        requires_explicit_user_confirmation=True,
        platform_name="nt",
    )

    source_field = next_command["copy_instruction"]["source_field"]
    assert source_field == "model_command"
    assert next_command[source_field] == next_command["model_command"]
    assert next_command[source_field] != next_command["shell_command"]
    assert tuple(next_command)[-4:] == (
        "shell_command",
        "model_shell_family",
        "copy_instruction",
        "model_command",
    )


def test_packaged_gateway_binding_derives_exact_runner_and_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_source = tmp_path / "custom-skill"
    runner = skill_source / "scripts" / "run.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# trusted test runner\n", encoding="utf-8")
    binding = PackagedGatewayBinding(skill_source)
    observed: dict[str, Any] = {}

    def fake_run(argv: Sequence[str], **kwargs: Any) -> SimpleNamespace:
        observed["argv"] = list(argv)
        observed.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"contract": GATEWAY_CONTRACT, "ok": True}),
            stderr="",
        )

    monkeypatch.setattr(fixture_support.subprocess, "run", fake_run)
    gateway = fixture_support._PackagedGateway(binding=binding, timeout_seconds=2.0)

    assert gateway(("status",), {"PATH": "/usr/bin"})["ok"] is True
    assert binding.skill_root == skill_source.resolve()
    assert binding.runner_path == runner.resolve()
    assert observed["argv"] == [
        fixture_support.sys.executable,
        str(runner.resolve()),
        "gateway.py",
        "status",
    ]
    assert observed["cwd"] == skill_source.resolve()
    assert observed["env"] == {"PATH": "/usr/bin"}


@pytest.mark.parametrize("runner_kind", ["missing", "directory", "symlink"])
def test_packaged_gateway_binding_rejects_non_regular_runner(
    tmp_path: Path,
    runner_kind: str,
) -> None:
    skill_source = tmp_path / runner_kind
    scripts = skill_source / "scripts"
    scripts.mkdir(parents=True)
    runner = scripts / "run.py"
    if runner_kind == "directory":
        runner.mkdir()
    elif runner_kind == "symlink":
        target = tmp_path / "outside-run.py"
        target.write_text("# outside\n", encoding="utf-8")
        create_symlink_or_skip(runner, target)

    with pytest.raises(FixtureContractError, match="runner (does not exist|must be a regular file)"):
        PackagedGatewayBinding(skill_source)


def test_packaged_binding_cannot_be_combined_with_injected_gateway(
    fake_runtime: tuple[FakeTrustedWwise, dict[str, Any]],
) -> None:
    _, kwargs = fake_runtime

    with pytest.raises(FixtureContractError, match="mutually exclusive"):
        create_shared_fixture_bundle(
            **kwargs,
            packaged_gateway_binding=PackagedGatewayBinding(fixture_support.SKILL_ROOT),
        )


def test_owned_oracle_client_normalizes_only_known_single_exact_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, bool]] = []
    pending_errors: list[BaseException] = []

    class FakeWaapiRequestFailed(Exception):
        def __init__(self, uri: str, kwargs: Any = None) -> None:
            super().__init__("untrusted exception text")
            self.uri = uri
            self.kwargs = kwargs

    class OpaqueObjectNotFoundText:
        def __repr__(self) -> str:
            return "OpaqueObject(object not found)"

    class FakeWaapiClient:
        def __init__(self, *, url: str, allow_exception: bool) -> None:
            created.append((url, allow_exception))

        def call(self, uri: str, args: Mapping[str, Any], *, options: Mapping[str, Any]) -> Any:
            del uri, args, options
            if pending_errors:
                raise pending_errors.pop(0)
            return {"return": []}

        def disconnect(self) -> None:
            pass

    monkeypatch.setitem(
        fixture_support.sys.modules,
        "waapi",
        SimpleNamespace(
            WaapiClient=FakeWaapiClient,
            WaapiRequestFailed=FakeWaapiRequestFailed,
        ),
    )
    reader = fixture_support._OwnedDirectReadCall(host="127.0.0.1", port=54321)
    options = {"return": ["id"]}

    assert created == [("ws://127.0.0.1:54321/waapi", True)]

    pending_errors.append(
        FakeWaapiRequestFailed(
            "ak.wwise.query.unknown_object",
            {"message": "from path cannot be resolved"},
        )
    )
    assert reader(
        "ak.wwise.core.object.get",
        {"from": {"path": [r"\Missing"]}},
        options,
    ) == {"return": []}

    pending_errors.append(
        FakeWaapiRequestFailed(
            "ak.wwise.query.unknown_object",
            {"message": "from id cannot be resolved"},
        )
    )
    assert reader(
        "ak.wwise.core.object.get",
        {"from": {"id": ["{missing-id}"]}},
        options,
    ) == {"return": []}

    pending_errors.append(
        FakeWaapiRequestFailed(
            "ak.wwise.query.invalid_query",
            {
                "message": "Object not found for exact path.",
                "details": {"procedureUri": "ak.wwise.core.object.get"},
            },
        )
    )
    assert reader(
        "ak.wwise.core.object.get",
        {"from": {"path": [r"\MissingLegacy"]}},
        options,
    ) == {"return": []}

    rejected_calls: list[tuple[Mapping[str, Any], BaseException]] = [
        (
            {"from": {"path": [r"\BadSyntax"]}},
            FakeWaapiRequestFailed(
                "ak.wwise.query.invalid_query",
                {"message": "Invalid query syntax near from."},
            ),
        ),
        (
            {"from": {"path": [r"\RequestEcho"]}},
            FakeWaapiRequestFailed(
                "ak.wwise.query.invalid_query",
                {
                    "message": "Invalid query syntax near from.",
                    "request_echo": {"note": "object not found is untrusted request text"},
                },
            ),
        ),
        (
            {"from": {"path": [r"\NestedDetails"]}},
            FakeWaapiRequestFailed(
                "ak.wwise.query.invalid_query",
                {
                    "message": "Invalid query syntax near from.",
                    "details": {"message": "Object not found in unrelated nested details."},
                },
            ),
        ),
        (
            {"from": {"path": [r"\BareString"]}},
            FakeWaapiRequestFailed(
                "ak.wwise.query.invalid_query",
                "Object not found in an unstructured exception payload.",
            ),
        ),
        (
            {"from": {"path": [r"\OpaqueRepr"]}},
            FakeWaapiRequestFailed(
                "ak.wwise.query.invalid_query",
                {
                    "message": "Invalid query syntax near from.",
                    "opaque": OpaqueObjectNotFoundText(),
                },
            ),
        ),
        (
            {"from": {"path": [r"\Impostor"]}},
            RuntimeError(
                "ApplicationError(error=<ak.wwise.query.unknown_object>, object not found)"
            ),
        ),
        (
            {"from": {"path": [r"\One", r"\Two"]}},
            FakeWaapiRequestFailed("ak.wwise.query.unknown_object"),
        ),
        (
            {"waql": "$ from object \"\\Missing\""},
            FakeWaapiRequestFailed("ak.wwise.query.unknown_object"),
        ),
        (
            {"from": {"path": [r"\Missing"], "ofType": ["Sound"]}},
            FakeWaapiRequestFailed("ak.wwise.query.unknown_object"),
        ),
        (
            {"from": {"path": [""]}},
            FakeWaapiRequestFailed("ak.wwise.query.unknown_object"),
        ),
        (
            {"from": {"id": [123]}},
            FakeWaapiRequestFailed("ak.wwise.query.unknown_object"),
        ),
    ]
    for args, error in rejected_calls:
        pending_errors.append(error)
        with pytest.raises(type(error)):
            reader("ak.wwise.core.object.get", args, options)

    pending_errors.append(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        reader(
            "ak.wwise.core.object.get",
            {"from": {"path": [r"\Interrupt"]}},
            options,
        )
    reader.close()


def test_fixture_namespace_preflight_reads_each_exact_path_and_detects_occupancy() -> None:
    calls: list[str] = []

    def read_call(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        assert uri == "ak.wwise.core.object.get"
        assert options == {"return": ["id", "name", "type", "path"]}
        source = args["from"]
        assert isinstance(source, Mapping)
        paths = source["path"]
        assert isinstance(paths, list) and len(paths) == 1
        path = str(paths[0])
        calls.append(path)
        if path == r"\Occupied":
            return {
                "return": [
                    {"id": "{occupied}", "name": "Occupied", "type": "Sound", "path": path}
                ]
            }
        return {"return": []}

    fixture_support._assert_fixture_paths_absent(read_call, (r"\First", r"\Second"))
    assert calls == [r"\First", r"\Second"]

    calls.clear()
    with pytest.raises(FixtureContractError, match=r"\\Occupied"):
        fixture_support._assert_fixture_paths_absent(read_call, (r"\First", r"\Occupied"))
    assert calls == [r"\First", r"\Occupied"]


def test_query_editor_discovery_is_runner_owned_and_fails_closed_on_ambiguity() -> None:
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def read_call(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        calls.append((uri, args, options))
        row = {
            "id": FACTORY_QUERY_ID,
            "name": "Sound = SFX",
            "type": "Query",
            "path": FACTORY_QUERY_PATH,
        }
        return {"return": [row, dict(row)]}

    with pytest.raises(FixtureContractError, match="resolve exactly once"):
        fixture_support._discover_sound_sfx_query(read_call)
    assert calls == [
        (
            "ak.wwise.core.object.get",
            {"waql": 'from type Query where name = "Sound = SFX" take 2'},
            {"return": ["id", "name", "type", "path"]},
        )
    ]


def test_shared_bundle_setup_order_prompt_values_and_private_transactions(
    fake_runtime: tuple[FakeTrustedWwise, dict[str, Any]],
) -> None:
    fake, kwargs = fake_runtime
    bundle = create_shared_fixture_bundle(**kwargs)
    try:
        setup_operations = [
            request["request"]["operation"]
            for request in fake.transactions.values()
            if request["request"]["operation"] != "object.delete"
        ]
        assert setup_operations == [
            "object.create",
            "object.create",
            "object.create",
            "object.create",
            "object.create",
            "object.create",
            "object.create",
            "object.create",
            "object.setReference",
            "object.create",
            "object.create",
            "object.create",
            "object.create",
            "object.setProperty",
            "object.create",
            "object.create",
            "object.setReference",
            "object.create",
            "object.setReference",
            "object.create",
            "switchContainer.addAssignment",
        ]
        assert len(bundle.hidden.setup_created_ids) == len(set(bundle.hidden.setup_created_ids)) == 16
        assert bundle.prompt_values("Q1") == {"query_path": bundle.hidden.query_notes_path}
        assert bundle.prompt_values("Q2") == {"parent_path": bundle.hidden.switch_container_path}
        assert bundle.prompt_values("Q3") == {
            "search_name": bundle.hidden.query_notes_path.rsplit("\\", 1)[-1]
        }
        assert bundle.prompt_values("Q4") == {"query_path": FACTORY_QUERY_PATH}
        assert bundle.prompt_values("Q5") == {"missing_path": bundle.hidden.missing_query_path}
        assert bundle.hidden.query_editor_id == FACTORY_QUERY_ID
        assert bundle.prompt_values("C1") == {}
        assert bundle.prompt_values("R1") == {}
        assert bundle.prompt_values("R2") == {}
        assert bundle.prompt_values("R3") == {}
        assert bundle.prompt_values("R4") == {}
        assert bundle.prompt_values("R6") == {}
        assert bundle.prompt_values("R5") == {
            "topic_probe_name": "WAAPI_SEM_TOPIC_2022_1_fixed-token",
            "topic_probe_event_type": "ActorMixer",
        }
        assert set(bundle.prompt_values("I1")) == {
            "audio_file",
            "import_object_path",
            "import_object_type",
            "import_notes",
        }
        for case_id in (
            "Q1",
            "Q2",
            "Q3",
            "Q4",
            "Q5",
            "C1",
            "M1",
            "M2",
            "M3",
            "M4",
            "M5",
            "M6",
            "M7",
            "B1",
            "B2",
            "B3",
            "B4",
            "B5",
            "B6",
            "B7",
            "I1",
            "S1",
            "W1",
            "W2",
            "R1",
            "R2",
            "R3",
            "R4",
            "R5",
            "R6",
        ):
            assert all("_id" not in key and "guid" not in key.casefold() for key in bundle.prompt_values(case_id))

        setup_records = [record for record in bundle.transactions if record.lane == "setup"]
        assert len(setup_records) == 21
        assert len({record.state_dir for record in setup_records}) == 21
        assert len({record.evidence_dir for record in setup_records}) == 21
        assert all(str(record.state_dir).startswith(str(kwargs["private_root"])) for record in setup_records)
        assert all("WAAPI_CODEX_GATEWAY_BROKER_TOKEN" not in request["env"] for request in fake.requests)
        assert all("WAAPI_CODEX_GATEWAY_REQUIRED" not in request["env"] for request in fake.requests)
        assert all("BASH_ENV" not in request["env"] for request in fake.requests)
    finally:
        bundle.cleanup()


def test_topic_probe_uses_packaged_create_and_delete_transactions(
    fake_runtime: tuple[FakeTrustedWwise, dict[str, Any]],
) -> None:
    fake, kwargs = fake_runtime
    bundle = create_shared_fixture_bundle(**kwargs)
    try:
        name = bundle.prompt_values("R5")["topic_probe_name"]
        before_transactions = len(bundle.transactions)

        evidence = bundle.publish_object_created_probe(name)

        assert evidence == {
            "name": name,
            "path": f"{bundle.hidden.create_parent_path}\\{name}",
            "object_id": evidence["object_id"],
            "created": True,
            "deleted": True,
        }
        assert evidence["object_id"] not in fake.objects
        added = bundle.transactions[before_transactions:]
        assert [(item.lane, item.operation) for item in added] == [
            ("setup", "object.create"),
            ("cleanup", "object.delete"),
        ]
    finally:
        bundle.cleanup()


@pytest.mark.parametrize(
    ("version", "expected_parent", "expected_reflected_type"),
    [
        ("2021.1", r"\Actor-Mixer Hierarchy\Default Work Unit", "ActorMixer"),
        ("2025.1", r"\Containers\Default Work Unit", "PropertyContainer"),
    ],
)
def test_version_specific_parent_is_closed(
    tmp_path: Path,
    version: str,
    expected_parent: str,
    expected_reflected_type: str,
) -> None:
    fake = FakeTrustedWwise(actor_mixer_reflected_type=expected_reflected_type)
    sandbox = tmp_path / version / "sandbox"
    private = tmp_path / version / "private"
    sandbox.mkdir(parents=True)
    bundle = create_shared_fixture_bundle(
        version=version,
        host="localhost",
        port=8000,
        sandbox_path=sandbox,
        private_root=private,
        runner_env={"PATH": "/usr/bin"},
        trusted_gateway=fake.gateway,
        read_call=fake.read,
        fixture_token=f"case-{version.replace('.', '-')}",
    )
    try:
        assert bundle.hidden.query_notes_path.startswith(expected_parent + "\\")
        query = bundle.baseline("Q1")
        assert isinstance(query.payload, PathOracleSnapshot)
        assert query.payload.object.type == expected_reflected_type
        assert bundle.prompt_values("M3")["create_parent_path"] == expected_parent
        assert bundle.prompt_values("R5")["topic_probe_event_type"] == expected_reflected_type
        create_requests = [
            tx["request"]
            for tx in fake.transactions.values()
            if tx["request"]["operation"] == "object.create"
        ]
        assert create_requests[0]["arguments"]["parent"] == {
            "kind": "path",
            "value": expected_parent,
        }

        create_before = bundle.snapshot("M3")
        fake._execute(
            {
                "operation": "object.create",
                "arguments": {
                    "parent": {"kind": "path", "value": bundle.hidden.create_parent_path},
                    "type": "ActorMixer",
                    "name": bundle.hidden.create_name,
                    "notes": bundle.hidden.create_notes,
                },
            }
        )
        create_after = bundle.snapshot("M3")
        assert bundle.compare("M3", create_before, create_after, expectation="applied").passed

        topic_name = bundle.prompt_values("R5")["topic_probe_name"]
        topic_evidence = bundle.publish_object_created_probe(topic_name)
        assert topic_evidence["created"] is True
        assert topic_evidence["deleted"] is True
    finally:
        bundle.cleanup()


def test_2025_fixture_rejects_legacy_actor_mixer_readback(tmp_path: Path) -> None:
    fake = FakeTrustedWwise()
    sandbox = tmp_path / "2025.1" / "sandbox"
    private = tmp_path / "2025.1" / "private"
    sandbox.mkdir(parents=True)

    with pytest.raises(FixtureContractError, match="query/notes fixture readback"):
        create_shared_fixture_bundle(
            version="2025.1",
            host="localhost",
            port=8000,
            sandbox_path=sandbox,
            private_root=private,
            runner_env={"PATH": "/usr/bin"},
            trusted_gateway=fake.gateway,
            read_call=fake.read,
            fixture_token="legacy-type",
        )


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_recursive_query_versions_reuse_only_the_validated_live_q4_baseline(
    tmp_path: Path,
    version: str,
) -> None:
    fake = FakeTrustedWwise(
        actor_mixer_reflected_type=(
            "PropertyContainer" if version == "2025.1" else "ActorMixer"
        )
    )
    sandbox = tmp_path / version / "sandbox"
    private = tmp_path / version / "private"
    sandbox.mkdir(parents=True)
    q4_reads = 0

    def read_once(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        nonlocal q4_reads
        if args.get("waql") == f'from query "{FACTORY_QUERY_ID}" take 10':
            q4_reads += 1
            if q4_reads > 1:
                raise RuntimeError("Recursive loop detected in query")
        return fake.read(uri, args, options)

    bundle = create_shared_fixture_bundle(
        version=version,
        host="localhost",
        port=8000,
        sandbox_path=sandbox,
        private_root=private,
        runner_env={"PATH": "/usr/bin"},
        trusted_gateway=fake.gateway,
        read_call=read_once,
        fixture_token=f"q4-single-read-{version.replace('.', '-')}",
    )
    try:
        baseline = bundle.baseline("Q4")
        assert q4_reads == 1
        assert bundle.snapshot("Q4") is baseline
        assert bundle.compare(
            "Q4",
            baseline,
            bundle.snapshot("Q4"),
            expectation="unchanged",
        ).passed
        assert q4_reads == 1

        removed = bundle._baselines.pop("Q4")
        with pytest.raises(FixtureContractError, match="live, validated baseline"):
            bundle.snapshot("Q4")
        assert q4_reads == 1
        bundle._baselines["Q4"] = removed

        with pytest.raises(FixtureContractError, match="may only be captured once"):
            bundle.capture_baselines()
        assert q4_reads == 1
    finally:
        bundle.cleanup()


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_recursive_query_versions_reject_an_unvalidated_first_live_q4_result(
    tmp_path: Path,
    version: str,
) -> None:
    fake = FakeTrustedWwise(
        actor_mixer_reflected_type=(
            "PropertyContainer" if version == "2025.1" else "ActorMixer"
        )
    )
    sandbox = tmp_path / f"{version}-invalid" / "sandbox"
    private = tmp_path / f"{version}-invalid" / "private"
    sandbox.mkdir(parents=True)
    q4_reads = 0

    def empty_q4_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        nonlocal q4_reads
        if args.get("waql") == f'from query "{FACTORY_QUERY_ID}" take 10':
            q4_reads += 1
            return {"return": []}
        return fake.read(uri, args, options)

    with pytest.raises(FixtureContractError, match="invalid bounded result set"):
        create_shared_fixture_bundle(
            version=version,
            host="localhost",
            port=8000,
            sandbox_path=sandbox,
            private_root=private,
            runner_env={"PATH": "/usr/bin"},
            trusted_gateway=fake.gateway,
            read_call=empty_q4_read,
            fixture_token=f"q4-invalid-{version.replace('.', '-')}",
        )

    assert q4_reads == 1
    assert fake.objects == {}


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1"])
def test_non_recursive_query_versions_keep_live_q4_snapshot_reads(
    tmp_path: Path,
    version: str,
) -> None:
    fake = FakeTrustedWwise()
    sandbox = tmp_path / version / "sandbox"
    private = tmp_path / version / "private"
    sandbox.mkdir(parents=True)
    q4_reads = 0

    def counted_read(
        uri: str,
        args: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Any:
        nonlocal q4_reads
        if args.get("waql") == f'from query "{FACTORY_QUERY_ID}" take 10':
            q4_reads += 1
        return fake.read(uri, args, options)

    bundle = create_shared_fixture_bundle(
        version=version,
        host="localhost",
        port=8000,
        sandbox_path=sandbox,
        private_root=private,
        runner_env={"PATH": "/usr/bin"},
        trusted_gateway=fake.gateway,
        read_call=counted_read,
        fixture_token=f"q4-live-{version.replace('.', '-')}",
    )
    try:
        baseline = bundle.baseline("Q4")
        assert q4_reads == 1
        current = bundle.snapshot("Q4")
        assert current == baseline
        assert q4_reads == 2
    finally:
        bundle.cleanup()


def test_query_editor_oracle_mode_fails_closed_for_an_unknown_version() -> None:
    with pytest.raises(
        FixtureContractError,
        match="Query Editor oracle contract is unavailable for Wwise 2026.1",
    ):
        fixture_support._query_editor_oracle_mode("2026.1")


def test_typed_import_path_normalization_and_reserved_target(
    fake_runtime: tuple[FakeTrustedWwise, dict[str, Any]],
) -> None:
    _, kwargs = fake_runtime
    bundle = create_shared_fixture_bundle(**kwargs)
    try:
        values = bundle.prompt_values("I1")
        assert "\\<Sound>" in values["import_object_path"]
        assert normalize_typed_import_object_path(values["import_object_path"]) == bundle.hidden.normalized_import_path
        assert bundle.hidden.normalized_import_path.replace("\\", "/").endswith(
            values["import_object_path"].split(">", 1)[1]
        )
        with pytest.raises(FixtureContractError, match="absolute Wwise path"):
            normalize_typed_import_object_path("relative\\<Sound>bad")
        with pytest.raises(FixtureContractError, match="invalid typed"):
            normalize_typed_import_object_path(r"\Root\<Sound>")
    finally:
        bundle.cleanup()


def test_direct_baselines_and_all_applied_oracle_transitions(
    fake_runtime: tuple[FakeTrustedWwise, dict[str, Any]],
) -> None:
    fake, kwargs = fake_runtime
    bundle = create_shared_fixture_bundle(**kwargs)
    try:
        query = bundle.baseline("Q1")
        assert isinstance(query.payload, PathOracleSnapshot)
        assert query.payload.object.id == bundle.hidden.query_notes_id
        children = bundle.baseline("Q2")
        assert isinstance(children.payload, ObjectRowsOracleSnapshot)
        assert [item.id for item in children.payload.objects] == [bundle.hidden.direct_child_id]
        search = bundle.baseline("Q3")
        assert isinstance(search.payload, ObjectRowsOracleSnapshot)
        assert [item.id for item in search.payload.objects] == [bundle.hidden.query_notes_id]
        editor = bundle.baseline("Q4")
        assert isinstance(editor.payload, ObjectRowsOracleSnapshot)
        assert editor.payload.objects
        assert all(item.type == "Sound" for item in editor.payload.objects)
        missing = bundle.baseline("Q5")
        assert isinstance(missing.payload, MissingPathOracleSnapshot)
        assert missing.payload.path == bundle.hidden.missing_query_path
        for case_id in ("Q1", "Q2", "Q3", "Q4", "Q5"):
            baseline = bundle.baseline(case_id)
            current = bundle.snapshot(case_id)
            assert bundle.compare(case_id, baseline, current, expectation="unchanged").passed
        audio_before = bundle.baseline("I1")
        assert isinstance(audio_before.payload, AudioOracleSnapshot)
        assert audio_before.payload.object is None
        soundbank_before = bundle.baseline("S1")
        assert isinstance(soundbank_before.payload, SoundBankOracleSnapshot)
        assert soundbank_before.payload.inclusions == ()
        switch_before = bundle.baseline("W1")
        assert isinstance(switch_before.payload, SwitchOracleSnapshot)
        assert switch_before.payload.assignments == ()
        assert switch_before.payload.reference_id == bundle.hidden.switch_group_id
        assert switch_before.payload.direct_child.parent_id == bundle.hidden.switch_container_id
        assert switch_before.payload.state_or_switch.parent_id == bundle.hidden.switch_group_id
        assert isinstance(bundle.baseline("M3").payload, ObjectPresenceOracleSnapshot)
        assert isinstance(bundle.baseline("M4").payload, ObjectPresenceOracleSnapshot)
        assert isinstance(bundle.baseline("M5").payload, RenameOracleSnapshot)
        assert isinstance(bundle.baseline("M6").payload, FieldOracleSnapshot)
        assert isinstance(bundle.baseline("M7").payload, ReferenceOracleSnapshot)
        remove_baseline = bundle.baseline("W2")
        assert isinstance(remove_baseline.payload, SwitchOracleSnapshot)
        assert len(remove_baseline.payload.assignments) == 1

        notes_before = bundle.snapshot("M1")
        fake.objects[bundle.hidden.notes_target_id]["notes"] = bundle.prompt_values("M1")["notes_value"]
        notes_after = bundle.snapshot("M1")
        assert bundle.compare("M1", notes_before, notes_after, expectation="applied").passed

        create_before = bundle.snapshot("M3")
        fake._execute(
            {
                "operation": "object.create",
                "arguments": {
                    "parent": {"kind": "path", "value": bundle.hidden.create_parent_path},
                    "type": "ActorMixer",
                    "name": bundle.hidden.create_name,
                    "notes": bundle.hidden.create_notes,
                },
            }
        )
        create_after = bundle.snapshot("M3")
        assert bundle.compare("M3", create_before, create_after, expectation="applied").passed

        delete_before = bundle.snapshot("M4")
        fake.objects.pop(bundle.hidden.delete_target_id)
        delete_after = bundle.snapshot("M4")
        assert bundle.compare("M4", delete_before, delete_after, expectation="applied").passed

        rename_before = bundle.snapshot("M5")
        fake._execute(
            {
                "operation": "object.setName",
                "arguments": {
                    "object": {"value": bundle.hidden.rename_target_id},
                    "value": bundle.hidden.rename_value,
                },
            }
        )
        rename_after = bundle.snapshot("M5")
        assert bundle.compare("M5", rename_before, rename_after, expectation="applied").passed

        property_before = bundle.snapshot("M6")
        fake.objects[bundle.hidden.property_target_id]["Volume"] = -3.0
        property_after = bundle.snapshot("M6")
        assert bundle.compare("M6", property_before, property_after, expectation="applied").passed

        reference_before = bundle.snapshot("M7")
        fake.references[bundle.hidden.reference_source_id] = bundle.hidden.reference_target_id
        reference_after = bundle.snapshot("M7")
        assert bundle.compare("M7", reference_before, reference_after, expectation="applied").passed

        remove_before = bundle.snapshot("W2")
        fake._execute(
            {
                "operation": "switchContainer.removeAssignment",
                "arguments": {
                    "switch_container": {"value": bundle.hidden.remove_switch_container_id},
                    "child": {"value": bundle.hidden.remove_direct_child_id},
                    "state_or_switch": {"value": bundle.hidden.state_or_switch_id},
                },
            }
        )
        remove_after = bundle.snapshot("W2")
        assert bundle.compare("W2", remove_before, remove_after, expectation="applied").passed

        audio_before = bundle.snapshot("I1")
        fake.add_imported_audio(
            path=bundle.hidden.normalized_import_path,
            notes=bundle.prompt_values("I1")["import_notes"],
        )
        audio_after = bundle.snapshot("I1")
        assert bundle.compare("I1", audio_before, audio_after, expectation="applied").passed

        soundbank_before = bundle.snapshot("S1")
        fake.inclusions = [
            {
                "object": {"id": bundle.hidden.included_object_id},
                "filter": ["structures", "media", "media"],
            }
        ]
        soundbank_after = bundle.snapshot("S1")
        assert bundle.compare("S1", soundbank_before, soundbank_after, expectation="applied").passed

        switch_before = bundle.snapshot("W1")
        fake.assignments = [
            {
                "child": {"id": bundle.hidden.direct_child_id},
                "stateOrSwitch": bundle.hidden.state_or_switch_id,
            }
        ]
        switch_after = bundle.snapshot("W1")
        comparison = bundle.compare("W1", switch_before, switch_after, expectation="applied")
        assert comparison.passed, comparison.failures

        unchanged = bundle.snapshot("M2")
        assert bundle.compare("M2", unchanged, unchanged, expectation="unchanged").passed
    finally:
        bundle.cleanup()


def test_applied_oracle_fails_on_wav_change_and_wrong_complete_state(
    fake_runtime: tuple[FakeTrustedWwise, dict[str, Any]],
) -> None:
    fake, kwargs = fake_runtime
    bundle = create_shared_fixture_bundle(**kwargs)
    try:
        before = bundle.snapshot("I1")
        fake.add_imported_audio(
            path=bundle.hidden.normalized_import_path,
            notes=bundle.prompt_values("I1")["import_notes"],
        )
        bundle.hidden.audio_file.write_bytes(bundle.hidden.audio_file.read_bytes() + b"changed")
        after = bundle.snapshot("I1")
        comparison = bundle.compare("I1", before, after, expectation="applied")
        assert not comparison.passed
        assert "fixture WAV changed during import" in comparison.failures

        before_bank = bundle.snapshot("S1")
        fake.inclusions = [
            {"object": bundle.hidden.included_object_id, "filters": ["media"]},
        ]
        after_bank = bundle.snapshot("S1")
        assert not bundle.compare("S1", before_bank, after_bank, expectation="applied").passed
    finally:
        bundle.cleanup()


def test_cleanup_removes_assignment_then_objects_leaf_to_root_and_only_owned_ids(
    fake_runtime: tuple[FakeTrustedWwise, dict[str, Any]],
) -> None:
    fake, kwargs = fake_runtime
    bundle = create_shared_fixture_bundle(**kwargs)
    imported_id = fake.add_imported_audio(
        path=bundle.hidden.normalized_import_path,
        notes=bundle.prompt_values("I1")["import_notes"],
    )
    fake.assignments = [
        {
            "child": bundle.hidden.direct_child_id,
            "stateOrSwitch": {"id": bundle.hidden.state_or_switch_id},
        }
    ]
    expected = [
        imported_id,
        bundle.hidden.remove_direct_child_id,
        bundle.hidden.remove_switch_container_id,
        bundle.hidden.reference_source_id,
        bundle.hidden.reference_target_id,
        bundle.hidden.property_target_id,
        bundle.hidden.rename_target_id,
        bundle.hidden.delete_target_id,
        bundle.hidden.direct_child_id,
        bundle.hidden.switch_container_id,
        bundle.hidden.state_or_switch_id,
        bundle.hidden.switch_group_id,
        bundle.hidden.soundbank_id,
        bundle.hidden.included_object_id,
        bundle.hidden.adversarial_target_id,
        bundle.hidden.notes_target_id,
        bundle.hidden.query_notes_id,
    ]

    bundle.cleanup()

    assert fake.delete_order == expected
    assert fake.objects == {}
    assert fake.assignments == []
    cleanup_operations = [
        record.operation for record in bundle.transactions if record.lane == "cleanup"
    ]
    assert cleanup_operations[0] == "object.delete"  # imported audio leaf
    assert cleanup_operations[1] == "switchContainer.removeAssignment"
    assert cleanup_operations[2:] == ["object.delete"] * 16
    assert set(fake.delete_order) == {imported_id, *bundle.hidden.setup_created_ids}


def test_unknown_case_adapter_expectation_and_malformed_read_fail_closed(
    fake_runtime: tuple[FakeTrustedWwise, dict[str, Any]],
) -> None:
    fake, kwargs = fake_runtime
    bundle = create_shared_fixture_bundle(**kwargs)
    try:
        with pytest.raises(FixtureContractError, match="unknown semantic fixture case"):
            bundle.prompt_values("X1")
        with pytest.raises(FixtureContractError, match="requires fixture adapter"):
            bundle.prompt_values("Q1", adapter="invented_adapter")
        with pytest.raises(FixtureContractError, match="offline catalog"):
            bundle.snapshot("C1")
        q1 = bundle.snapshot("Q1")
        with pytest.raises(FixtureContractError, match="unknown oracle expectation"):
            bundle.compare("Q1", q1, q1, expectation="invented")  # type: ignore[arg-type]

        original = bundle._oracle.read_call  # focused corruption of the injected boundary
        bundle._oracle.read_call = lambda _uri, _args, _options: {"return": "not-an-array"}
        with pytest.raises(FixtureContractError, match="mapping array"):
            bundle.snapshot("Q1")
        bundle._oracle.read_call = original
    finally:
        bundle.cleanup()


@pytest.mark.parametrize(
    "bad_payload",
    [
        [],
        {"contract": "wrong", "ok": True, "command": "preview"},
        {"contract": GATEWAY_CONTRACT, "ok": False, "command": "preview"},
        {"contract": GATEWAY_CONTRACT, "ok": True, "command": "execute"},
    ],
)
def test_trusted_gateway_errors_fail_closed_before_returning_a_bundle(
    tmp_path: Path,
    bad_payload: Any,
) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    def bad_gateway(_argv: Sequence[str], _env: Mapping[str, str]) -> Any:
        return bad_payload

    def query_aware_read(
        _uri: str,
        args: Mapping[str, Any],
        _options: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if args.get("waql") == 'from type Query where name = "Sound = SFX" take 2':
            return {
                "return": [
                    {
                        "id": FACTORY_QUERY_ID,
                        "name": "Sound = SFX",
                        "type": "Query",
                        "path": FACTORY_QUERY_PATH,
                    }
                ]
            }
        return {"return": []}

    with pytest.raises(FixtureContractError, match="trusted gateway"):
        create_shared_fixture_bundle(
            version="2022.1",
            host="localhost",
            port=8080,
            sandbox_path=sandbox,
            private_root=tmp_path / "private",
            runner_env={"PATH": "/usr/bin"},
            trusted_gateway=bad_gateway,
            read_call=query_aware_read,
            fixture_token="bad-gateway",
        )


def test_setup_failure_rolls_back_only_verified_partial_fixture_ids(tmp_path: Path) -> None:
    fake = FakeTrustedWwise()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    preview_count = 0

    def fail_once(argv: Sequence[str], env: Mapping[str, str]) -> Mapping[str, Any]:
        nonlocal preview_count
        parsed = _parse_gateway_argv(argv)
        if parsed["command"] == "preview":
            preview_count += 1
            if preview_count == 4:
                return {
                    "contract": GATEWAY_CONTRACT,
                    "ok": False,
                    "command": "preview",
                    "message": "injected setup failure",
                }
        return fake.gateway(argv, env)

    with pytest.raises(FixtureContractError, match="trusted gateway preview failed"):
        create_shared_fixture_bundle(
            version="2022.1",
            host="localhost",
            port=8080,
            sandbox_path=sandbox,
            private_root=tmp_path / "private",
            runner_env={"PATH": "/usr/bin"},
            trusted_gateway=fail_once,
            read_call=fake.read,
            fixture_token="partial-failure",
        )

    # Three verified creates preceded the injected failure; partial teardown
    # removes precisely those three GUIDs, in leaf/reference-safe reverse order.
    assert fake.objects == {}
    assert fake.delete_order == ["{fixture-0003}", "{fixture-0002}", "{fixture-0001}"]


def test_post_execute_result_parse_failure_recovers_unique_path_and_rolls_back(
    tmp_path: Path,
) -> None:
    fake = FakeTrustedWwise()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    corrupted = False

    def corrupt_first_create_result(
        argv: Sequence[str], env: Mapping[str, str]
    ) -> Mapping[str, Any]:
        nonlocal corrupted
        result = dict(fake.gateway(argv, env))
        parsed = _parse_gateway_argv(argv)
        if parsed["command"] == "execute" and not corrupted:
            transaction_id = parsed["command_args"][0]
            if fake.transactions[transaction_id]["request"]["operation"] == "object.create":
                corrupted = True
                # The fake has already created the object, but the trusted
                # result no longer exposes its GUID to setup_ids.
                result["dispatch_result"] = {"result": {}}
        return result

    with pytest.raises(FixtureContractError, match="object.create result"):
        create_shared_fixture_bundle(
            version="2022.1",
            host="localhost",
            port=8080,
            sandbox_path=sandbox,
            private_root=tmp_path / "private",
            runner_env={
                "PATH": "/usr/bin",
                "WAAPI_CODEX_GATEWAY_REQUIRED": "1",
            },
            trusted_gateway=corrupt_first_create_result,
            read_call=fake.read,
            fixture_token="parse-failure",
        )

    assert corrupted
    assert fake.objects == {}
    assert fake.delete_order == ["{fixture-0001}"]
    assert all(
        "WAAPI_CODEX_GATEWAY_REQUIRED" not in request["env"] for request in fake.requests
    )


def test_post_execute_verify_failure_uses_execute_proof_for_rollback(tmp_path: Path) -> None:
    fake = FakeTrustedWwise()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    failed = False

    def fail_first_create_verify(
        argv: Sequence[str], env: Mapping[str, str]
    ) -> Mapping[str, Any]:
        nonlocal failed
        result = dict(fake.gateway(argv, env))
        parsed = _parse_gateway_argv(argv)
        if parsed["command"] == "verify" and not failed:
            transaction_id = parsed["command_args"][0]
            if fake.transactions[transaction_id]["request"]["operation"] == "object.create":
                failed = True
                result["ok"] = False
        return result

    with pytest.raises(FixtureContractError, match="trusted gateway verify failed"):
        create_shared_fixture_bundle(
            version="2022.1",
            host="localhost",
            port=8080,
            sandbox_path=sandbox,
            private_root=tmp_path / "private",
            runner_env={"PATH": "/usr/bin"},
            trusted_gateway=fail_first_create_verify,
            read_call=fake.read,
            fixture_token="verify-failure",
        )

    assert failed
    assert fake.objects == {}
    assert fake.delete_order == ["{fixture-0001}"]


def test_partial_recovery_ambiguity_fails_closed_without_deleting_candidate(
    tmp_path: Path,
) -> None:
    fake = FakeTrustedWwise()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    corrupted = False

    def corrupt_first_create_result(
        argv: Sequence[str], env: Mapping[str, str]
    ) -> Mapping[str, Any]:
        nonlocal corrupted
        result = dict(fake.gateway(argv, env))
        parsed = _parse_gateway_argv(argv)
        if parsed["command"] == "execute" and not corrupted:
            transaction_id = parsed["command_args"][0]
            if fake.transactions[transaction_id]["request"]["operation"] == "object.create":
                corrupted = True
                result["dispatch_result"] = {"result": {}}
        return result

    def ambiguous_recovery_read(
        uri: str, args: Mapping[str, Any], options: Mapping[str, Any]
    ) -> Any:
        result = fake.read(uri, args, options)
        source = args.get("from")
        if (
            corrupted
            and isinstance(source, Mapping)
            and "path" in source
            and isinstance(result, Mapping)
            and len(result.get("return", [])) == 1
        ):
            return {"return": [result["return"][0], copy.deepcopy(result["return"][0])]}
        return result

    with pytest.raises(FixtureContractError, match="object.create result") as caught:
        create_shared_fixture_bundle(
            version="2022.1",
            host="localhost",
            port=8080,
            sandbox_path=sandbox,
            private_root=tmp_path / "private",
            runner_env={"PATH": "/usr/bin"},
            trusted_gateway=corrupt_first_create_result,
            read_call=ambiguous_recovery_read,
            fixture_token="ambiguous-recovery",
        )

    assert fake.delete_order == []
    assert tuple(fake.objects) == ("{fixture-0001}",)
    assert any(
        "query-recovery" in note and "resolved 2 objects" in note
        for note in getattr(caught.value, "__notes__", ())
    )


def _parse_gateway_argv(argv: Sequence[str]) -> dict[str, Any]:
    values = tuple(argv)
    index = 0
    globals_: dict[str, str] = {}
    while index < len(values) and values[index].startswith("--"):
        key = values[index]
        assert key in {
            "--host",
            "--port",
            "--version",
            "--timeout",
            "--state-dir",
            "--evidence-dir",
        }
        globals_[key] = values[index + 1]
        index += 2
    command = values[index]
    return {
        "globals": globals_,
        "command": command,
        "command_args": values[index + 1 :],
    }


def _identity(value: Any) -> str:
    if isinstance(value, str):
        return value
    assert isinstance(value, Mapping)
    result = value["id"]
    assert isinstance(result, str)
    return result

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.transactions import TransactionStore
from wwise_waapi.project_setting_business_contracts import (
    GAME_PARAMETER_SET_RANGE_URI,
    SOUND_SET_ACTIVE_SOURCE_URI,
    project_setting_business_operations,
    project_setting_business_versions,
)
from wwise_waapi.source_control_business_contracts import (
    SOURCE_CONTROL_COMMIT_URI,
    SOURCE_CONTROL_GET_SOURCE_FILES_URI,
    SOURCE_CONTROL_SET_PROVIDER_URI,
    source_control_business_operations,
    source_control_business_versions,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_remaining_core_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path, *, version: str = "2025.1") -> dict[str, str]:
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
        "WWISE_WAAPI_PORT": "31337",
    }


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation in sorted(project_setting_business_operations())
        for version in project_setting_business_versions(operation)
    ],
)
def test_project_setting_rows_expose_one_business_draft_and_no_typed_fields(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert exit_code == 0, payload
    assert payload["contract"] == "waapi-skill.core-business-route/v1"
    assert payload["business_adapter"]["contract"] == (
        "waapi-skill.project-setting-business/v1"
    )
    assert payload["continuation"] == {
        "subcommand": "draft-start",
        "gateway_argv": ["draft-start", operation],
        "copy_exactly": True,
        "append_arguments": "forbidden",
    }
    encoded = json.dumps(payload, sort_keys=True)
    assert "typed-call" not in encoded
    assert "schema_digest" not in encoded
    assert "native request" not in encoded.casefold()


@pytest.mark.parametrize("operation", sorted(project_setting_business_operations()))
def test_project_setting_rows_block_typed_call_before_connection(
    tmp_path: Path,
    operation: str,
) -> None:
    called = False

    def reject_connection(url: str) -> None:
        nonlocal called
        called = True
        raise AssertionError(f"typed bypass connected to {url}")

    exit_code, payload = gateway.execute_gateway(
        ["typed-call", operation, "--schema-digest", "0" * 64],
        env=_env(tmp_path),
        client_factory=reject_connection,
    )

    assert exit_code == 2
    assert "closed Core business" in payload["message"]
    assert called is False


def test_project_setting_draft_start_returns_one_exact_first_role(
    tmp_path: Path,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-start",
            SOUND_SET_ACTIVE_SOURCE_URI,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )

    assert exit_code == 0, payload
    next_action = payload["draft"]["next_action_binding"]
    assert next_action["required_next_phase"] == (
        "bind_next_project_setting_role"
    )
    assert next_action["object_binding"]["next_role"] == "sound"
    prefix = next_action["object_binding"]["by_id"]["fixed_argv_prefix"]
    assert prefix[-2:] == ["--role", "sound"]
    assert "declaration" not in next_action


def test_game_parameter_draft_exposes_one_copy_ready_exact_name_binding(
    tmp_path: Path,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-start",
            GAME_PARAMETER_SET_RANGE_URI,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )

    assert exit_code == 0, payload
    binding = payload["draft"]["next_action_binding"]["object_binding"]
    assert binding["next_role"] == "game_parameter"
    assert binding["direct_query_before_binding"] == "forbidden"
    exact_name = binding["by_exact_name"]
    assert exact_name["fixed_argv_prefix"][-4:] == [
        "--role",
        "game_parameter",
        "--exact-type-name",
        "GameParameter",
    ]
    assert exact_name["append"] == ["<exact-game-parameter-name>"]
    assert "query" not in binding["selection_rule"]


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation in sorted(source_control_business_operations())
        for version in source_control_business_versions(operation)
        if operation != SOURCE_CONTROL_SET_PROVIDER_URI
    ],
)
def test_source_control_rows_expose_only_the_closed_business_contract(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert exit_code == 0, payload
    assert payload["business_adapter"]["contract"] == (
        "waapi-skill.source-control-business/v1"
    )
    assert "typed-call" not in json.dumps(payload, sort_keys=True)


@pytest.mark.parametrize(
    "operation",
    sorted(source_control_business_operations() - {SOURCE_CONTROL_SET_PROVIDER_URI}),
)
def test_source_control_rows_block_typed_call_before_connection(
    tmp_path: Path,
    operation: str,
) -> None:
    called = False

    def reject_connection(url: str) -> None:
        nonlocal called
        called = True
        raise AssertionError(f"typed source-control bypass connected to {url}")

    exit_code, payload = gateway.execute_gateway(
        ["typed-call", operation, "--schema-digest", "0" * 64],
        env=_env(tmp_path),
        client_factory=reject_connection,
    )

    assert exit_code == 2
    assert "closed Core business" in payload["message"]
    assert called is False


@pytest.mark.parametrize(
    "operation",
    (SOURCE_CONTROL_COMMIT_URI, SOURCE_CONTROL_GET_SOURCE_FILES_URI),
)
def test_source_control_draft_start_returns_one_complete_declaration(
    tmp_path: Path,
    operation: str,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), "draft-start", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )

    assert exit_code == 0, payload
    next_action = payload["draft"]["next_action_binding"]
    assert next_action["required_next_phase"] == (
        "declare_complete_source_control_plan"
    )
    declaration = next_action["declaration"]
    assert "draft-declare-source-control-plan" in declaration["fixed_argv_prefix"]
    assert declaration["native_request_input"] == "forbidden"
    assert "--project-file" in declaration["file_locator_flags"]["project-relative"]


class _SourceControlDraftClient:
    def __init__(self, tmp_path: Path) -> None:
        self.project_root = tmp_path / "SampleProject"
        self.originals = self.project_root / "Originals"
        self.originals.mkdir(parents=True)
        self.project_file = self.project_root / "SampleProject.wproj"
        self.project_file.write_text("fixture", encoding="utf-8")

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        if uri == "ak.wwise.core.getInfo":
            return {
                "displayName": "Wwise",
                "isCommandLine": True,
                "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "processId": 4242,
                "processPath": "/Applications/Wwise/WwiseConsole",
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
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "name": "SampleProject",
                "path": str(self.project_file),
                "directories": {
                    "root": str(self.project_root),
                    "originals": str(self.originals),
                },
            }
        raise AssertionError(f"unexpected WAAPI call {uri}: {args!r} {options!r}")

    def disconnect(self) -> None:
        return None


class _ProjectSettingDraftClient(_SourceControlDraftClient):
    sound_id = "{11111111-1111-1111-1111-111111111111}"
    source_id = "{22222222-2222-2222-2222-222222222222}"
    game_parameter_id = "{33333333-3333-3333-3333-333333333333}"

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        if uri == "ak.wwise.core.object.get":
            assert isinstance(args, dict)
            if args.get("waql") == (
                'from type GameParameter where name = "WeatherIntensity" take 2'
            ):
                return {
                    "return": [
                        {
                            "id": self.game_parameter_id,
                            "name": "WeatherIntensity",
                            "type": "GameParameter",
                            "path": (
                                r"\Game Parameters\Default Work Unit"
                                r"\WeatherIntensity"
                            ),
                        }
                    ]
                }
            requested = args.get("from", {}).get("id", [])
            rows = []
            for object_id in requested:
                if str(object_id).upper() == self.sound_id:
                    rows.append(
                        {
                            "id": self.sound_id,
                            "name": "Weather_Loop",
                            "type": "Sound",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather_Loop",
                        }
                    )
                elif str(object_id).upper() == self.source_id:
                    rows.append(
                        {
                            "id": self.source_id,
                            "name": "Weather_Loop_Alt",
                            "type": "AudioFileSource",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit"
                                r"\Weather_Loop\Weather_Loop_Alt"
                            ),
                        }
                    )
                elif str(object_id).upper() == self.game_parameter_id:
                    rows.append(
                        {
                            "id": self.game_parameter_id,
                            "name": "WeatherIntensity",
                            "type": "GameParameter",
                            "path": (
                                r"\Game Parameters\Default Work Unit"
                                r"\WeatherIntensity"
                            ),
                        }
                    )
                else:
                    raise AssertionError(f"unexpected object id {object_id}")
            return {"return": rows}
        return super().call(uri, args, options)


def _bind_project_setting_role(
    tmp_path: Path,
    *,
    state_dir: Path,
    client: _ProjectSettingDraftClient,
    draft_id: str,
    authority: str,
    revision: int,
    role: str,
    object_id: str,
) -> dict[str, object]:
    code, payload = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--role",
            role,
            "--object-id",
            object_id,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, payload
    return payload


def test_game_parameter_exact_name_binding_resolves_inside_the_draft(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = _ProjectSettingDraftClient(tmp_path)
    code, started = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-start",
            GAME_PARAMETER_SET_RANGE_URI,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started

    code, bound = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-bind-object",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--role",
            "game_parameter",
            "--exact-type-name",
            "GameParameter",
            "WeatherIntensity",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, bound
    assert {
        key: bound["bound_object"][key]
        for key in ("role", "name", "type")
    } == {
        "role": "game_parameter",
        "name": "WeatherIntensity",
        "type": "GameParameter",
    }
    assert "id" not in bound["bound_object"]
    assert "path" not in bound["bound_object"]
    assert bound["draft"]["next_action_binding"]["required_next_phase"] == (
        "declare_complete_project_setting_plan"
    )
    assert bound["draft"]["next_action_binding"]["declaration"]["append"] == [
        "--game-parameter-handle <bound-game-parameter-handle>",
        "--minimum <finite-number>",
        "--maximum <finite-number>",
        "--curve-update-outcome stretch|preserve-x",
    ]

    code, declared = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-project-setting-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(bound["draft"]["revision"]),
            "--game-parameter-handle",
            bound["bound_object"]["handle"],
            "--minimum",
            "-10",
            "--maximum",
            "100",
            "--curve-update-outcome",
            "stretch",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_project_setting_plan"
    )


def test_project_setting_gateway_binds_exact_roles_then_seals_readback_preview(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = _ProjectSettingDraftClient(tmp_path)
    code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", SOUND_SET_ACTIVE_SOURCE_URI],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    sound = _bind_project_setting_role(
        tmp_path,
        state_dir=state_dir,
        client=client,
        draft_id=draft_id,
        authority=authority,
        revision=started["draft"]["revision"],
        role="sound",
        object_id=client.sound_id,
    )
    assert sound["draft"]["next_action_binding"]["object_binding"]["next_role"] == (
        "source"
    )
    source = _bind_project_setting_role(
        tmp_path,
        state_dir=state_dir,
        client=client,
        draft_id=draft_id,
        authority=authority,
        revision=sound["draft"]["revision"],
        role="source",
        object_id=client.source_id,
    )
    sound_handle = sound["bound_object"]["handle"]
    source_handle = source["bound_object"]["handle"]
    code, declared = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-project-setting-plan",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(source["draft"]["revision"]),
            "--sound-handle",
            sound_handle,
            "--source-handle",
            source_handle,
            "--platform-name",
            "Windows",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_project_setting_plan"
    )
    code, checked = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    code, previewed = gateway.execute_gateway(
        [
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
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    assert artifact["request"]["arguments"]["args"] == {
        "sound": client.sound_id,
        "source": client.source_id,
        "platform": "Windows",
    }
    assert artifact["prepared_operation"]["verification_plan"]["kind"] == (
        "project-setting-state"
    )


def test_source_control_commit_declaration_seals_live_roots_and_exact_message(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    client = _SourceControlDraftClient(tmp_path)
    work_unit = client.project_root / "Events" / "Default Work Unit.wwu"
    work_unit.parent.mkdir()
    work_unit.write_text("fixture", encoding="utf-8")
    code, started = gateway.execute_gateway(
        ["--state-dir", str(state_dir), "draft-start", SOURCE_CONTROL_COMMIT_URI],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started

    code, declared = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-declare-source-control-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(started["draft"]["revision"]),
            "--project-file",
            "Events/Default Work Unit.wwu",
            "--commit-message",
            'Keep "Weather" exact; no shell reconstruction',
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_source_control_plan"
    )
    record = OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    session = BusinessDeclarationSession.from_dict(
        record.composition["business_session"]
    )
    assert session.settings["source_control_roots"] == {
        "project": str(client.project_root),
        "originals": str(client.originals),
    }
    assert session.settings["source_control_plan"]["commit_message"] == (
        'Keep "Weather" exact; no shell reconstruction'
    )

    code, checked = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "draft-check",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(declared["draft"]["revision"]),
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, checked
    code, previewed = gateway.execute_gateway(
        [
            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(checked["draft"]["revision"]),
            "--apply",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert code == 0, previewed
    artifact = TransactionStore(state_dir).load_preview(
        previewed["transaction_id"]
    ).artifact
    assert artifact["request"]["arguments"] == {
        "api": SOURCE_CONTROL_COMMIT_URI,
        "args": {
            "files": [str(work_unit)],
            "message": 'Keep "Weather" exact; no shell reconstruction',
        },
        "options": {},
        "io_root": str(client.project_root),
    }


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_source_control_provider_configuration_is_an_explicit_boundary(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", SOURCE_CONTROL_SET_PROVIDER_URI],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"provider boundary connected to {url}"),
    )

    assert exit_code == 2
    assert "provider" in payload["message"].casefold()
    assert "credential" in payload["message"].casefold()


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize(
    "operation",
    ("ak.wwise.core.undo.cancelGroup", "ak.wwise.core.undo.endGroup"),
)
def test_undo_members_are_compound_only_and_never_expose_typed_construction(
    tmp_path: Path,
    version: str,
    operation: str,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"Undo boundary connected to {url}"),
    )

    assert exit_code == 2
    assert "compound Undo" in payload["message"]
    assert "waapi.undoGroup" in payload["message"]


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_source_file_usage_outputs_are_disclosed_and_sealed_through_public_draft(tmp_path, version):
    from tests.unit.test_object_graph_business_gateway import _info

    state_dir = tmp_path / "state"
    usage = {"id": "{11111111-1111-1111-1111-111111111111}", "name": "Rain", "type": "Sound",
             "path": "\\Actor-Mixer Hierarchy\\Rain", "shortId": 1, "parent": None}
    calls = []
    class Client(_SourceControlDraftClient):
        def call(self, uri, args=None, options=None):
            if uri == SOURCE_CONTROL_GET_SOURCE_FILES_URI:
                calls.append((args, options))
                return {"return": [{"file": "SFX/Rain.wav", "isMissing": False, "usage": [usage]}]}
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            return super().call(uri, args, options)

    client = Client(tmp_path)
    env = _env(tmp_path, version=version)
    code, schema = gateway.execute_gateway(["--version", version, "request-schema", SOURCE_CONTROL_GET_SOURCE_FILES_URI], env=env)
    assert code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    assert "usage_outputs" in declaration["optional_fields"]
    choices = declaration["usage_output_choices"]
    assert choices["short-id"]["result_field"] == "shortId"
    assert choices["parent"]["result_field"] == "parent"

    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state_dir), *argv], env=env, client_factory=lambda _url: client)
    code, phase = run("draft-start", SOURCE_CONTROL_GET_SOURCE_FILES_URI)
    assert code == 0, phase
    draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
    disclosed = phase["draft"]["next_action_binding"]["declaration"]["stable_scalar_flags"]
    assert disclosed["usage_outputs"] == "--usage-output <disclosed-business-output> (repeatable)"
    code, phase = run("draft-declare-source-control-plan", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]),
        "--usage-output", "short-id", "--usage-output", "parent")
    assert code == 0, phase
    code, phase = run("draft-check", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]))
    assert code == 0, phase
    code, previewed = run("preview-from-draft", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), "--apply")
    assert code == 0, previewed
    artifact = TransactionStore(state_dir).load_preview(previewed["transaction_id"]).artifact
    assert artifact["request"]["arguments"]["options"] == {
        "return": ["file", "folder", "isUsed", "isMissing", "usage"],
        "objectReturn": ["id", "name", "type", "path", "shortId", "parent"],
    }

    assert calls == []  # Preparation did not perform the sealed external read.
    code, shown = run("transaction-show", previewed["transaction_id"], "--summary-only")
    assert code == 0, shown
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    code, executed = run("execute", previewed["transaction_id"])
    assert code == 0, executed
    assert calls == [({"filter": "all", "recursive": True}, {
        "return": ["file", "folder", "isUsed", "isMissing", "usage"],
        "objectReturn": ["id", "name", "type", "path", "shortId", "parent"],
    })]
    code, verified = run("verify", previewed["transaction_id"])
    assert code == 0, json.dumps(verified, ensure_ascii=False)
    assert verified["agent_result"]["result"]["items"][0]["usage"] == [usage]
    assert verified["agent_result"]["verified"] is False  # Read result validation is not provider-effect proof.
    code, repeated = run("execute", previewed["transaction_id"])
    assert code != 0 and len(calls) == 1


@pytest.mark.parametrize("flags,operation,expected", (
    (("--usage-output", "short-id", "--no-usage-objects"), SOURCE_CONTROL_GET_SOURCE_FILES_URI, "SOURCE_CONTROL_USAGE_OUTPUT_CONFLICT"),
    (("--usage-output", "parent", "--usage-output", "parent"), SOURCE_CONTROL_GET_SOURCE_FILES_URI, "SOURCE_CONTROL_USAGE_OUTPUT_INVALID"),
    (("--usage-output", "custom-states"), SOURCE_CONTROL_GET_SOURCE_FILES_URI, "SOURCE_CONTROL_USAGE_OUTPUT_INVALID"),
    (("--usage-output", "parent", "--project-file", "SampleProject.wproj", "--commit-message", "message"), SOURCE_CONTROL_COMMIT_URI, "File actions do not accept source-file search fields"),
))
def test_source_control_usage_output_repair_preserves_the_original_draft(tmp_path, flags, operation, expected):
    from tests.unit.test_object_graph_business_gateway import _info
    class Client(_SourceControlDraftClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info("2023.1")
            return super().call(uri, args, options)
    client = Client(tmp_path)
    env, state_dir = _env(tmp_path, version="2023.1"), tmp_path / "state"
    code, started = gateway.execute_gateway(["--state-dir", str(state_dir), "draft-start", operation], env=env)
    assert code == 0, started
    draft, authority = started["draft"]["draft_id"], started["task_authority"]
    before = OperationDraftStore(state_dir).inspect(draft, task_authority=authority)
    code, rejected = gateway.execute_gateway(["--state-dir", str(state_dir), "draft-declare-source-control-plan",
        draft, "--task-authority", authority, "--expected-revision", str(before.revision), *flags],
        env=env, client_factory=lambda _url: client)
    assert code == 2, rejected
    assert expected in json.dumps(rejected, ensure_ascii=False)
    after = OperationDraftStore(state_dir).inspect(draft, task_authority=authority)
    assert (before.state, before.revision, before.composition, before.audit, before.check, before.seal) == (
        after.state, after.revision, after.composition, after.audit, after.check, after.seal)


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_source_file_usage_outputs_do_not_advertise_unpinned_source_control_route(tmp_path, version):
    code, payload = gateway.execute_gateway(["--version", version, "request-schema", SOURCE_CONTROL_GET_SOURCE_FILES_URI],
        env=_env(tmp_path, version=version), client_factory=lambda _url: pytest.fail("offline schema connected"))
    assert code == 2 and payload["ok"] is False
    assert "usage_output_choices" not in json.dumps(payload)


def _source_control_object_file_case(tmp_path, *, version="2025.1", choice="--object-file", operation="ak.wwise.core.sourceControl.checkOut", live_type=None, declaration_error=None, object_count=1, external_containing=False, approve_external=False, before_check=None, check_error=None):
    from tests.unit.test_object_graph_business_gateway import _info
    state_dir = tmp_path / "state"
    object_id = "{11111111-1111-1111-1111-111111111111}"
    class Client(_SourceControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.containing = ((tmp_path / "approved" / "External.wwu") if external_containing else
                               self.project_root / "Actor-Mixer Hierarchy" / "Default Work Unit.wwu")
            self.containing.parent.mkdir()
            self.containing.write_text("fixture", encoding="utf-8")
            self.media = self.originals / "Rain.wav"
            self.media.write_bytes(b"fixture")
            self.row = {"id": object_id, "name": "Rain", "type": live_type or ("AudioFileSource" if choice == "--original-media-object" else "Sound"), "path": "\\Actor-Mixer Hierarchy\\Rain",
                        "parent": None, "filePath": str(self.containing), "originalFilePath": str(self.media)}
            self.rows = {object_id: self.row}
            if object_count == 2:
                second_id = "{22222222-2222-2222-2222-222222222222}"
                self.rows[second_id] = {**self.row, "id": second_id, "name": "RainTwo", "path": "\\Actor-Mixer Hierarchy\\RainTwo"}
            self.calls = []
        def call(self, uri, args=None, options=None):
            self.calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.object.get":
                return {"return": [dict(self.rows[selected]) for selected in args["from"]["id"] if selected in self.rows]}
            if uri == operation:
                return ({"log": [], "result": [{"owner": "fixture-owner", "status": "fixture-status"}]}
                        if operation.endswith("getStatus") else {"log": []})
            return super().call(uri, args, options)
    client = Client()
    env = _env(tmp_path, version=version)
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state_dir), *argv], env=env, client_factory=lambda _url: client)
    code, phase = run("draft-start", operation)
    assert code == 0, phase
    draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
    selections = []
    for selected in client.rows:
        code, phase = run("draft-bind-object", draft, "--task-authority", authority,
            "--expected-revision", str(phase["draft"]["revision"]), "--object-id", selected)
        assert code == 0, phase
        selections.extend((choice, phase["bound_object"]["handle"]))
    code, phase = run("draft-declare-source-control-plan", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), *selections,
        *(("--commit-message", "Exact object-file changes") if operation.endswith("commit") else ()),
        *(("--io-root", str(client.containing.parent)) if approve_external else ()))
    if declaration_error:
        assert code == 2 and declaration_error in json.dumps(phase), phase
        return client, state_dir, phase, run
    assert code == 0, phase
    if before_check is not None:
        before_check(client)
    code, phase = run("draft-check", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]))
    if check_error:
        assert code == 2 and check_error in json.dumps(phase), phase
        return client, state_dir, phase, run
    assert code == 0, phase
    if operation.endswith("getStatus"):
        return client, state_dir, phase, run
    code, preview = run("preview-from-draft", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), "--apply")
    assert code == 0, preview
    code, shown = run("transaction-show", preview["transaction_id"], "--summary-only")
    assert code == 0, shown
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    return client, state_dir, preview, run


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_source_control_containing_file_scope_is_derived_from_exact_bound_object(tmp_path, version):
    client, state_dir, preview, run = _source_control_object_file_case(tmp_path, version=version)
    artifact = TransactionStore(state_dir).load_preview(preview["transaction_id"]).artifact
    assert artifact["request"]["arguments"]["args"] == {"files": [str(client.containing)]}
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0 and executed["executed"] is True, executed
    writes = [row for row in client.calls if row[0] == "ak.wwise.core.sourceControl.checkOut"]
    assert [row[1:] for row in writes] == [({"files": [str(client.containing)]}, {})]
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["agent_result"]["verified"] is False, verified
    assert verified["agent_result"]["result"] == {"log": []}


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("choice", ("--object-file", "--original-media-object"))
def test_source_control_object_file_accessor_drift_stops_before_provider_write(tmp_path, version, choice):
    client, state_dir, preview, run = _source_control_object_file_case(tmp_path, version=version, choice=choice)
    accessor = "filePath" if choice == "--object-file" else "originalFilePath"
    other = client.project_root / "Another.wwu"
    other.write_text("fixture", encoding="utf-8")
    client.row[accessor] = str(other)
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2 and rejected["status"] == "repreview_required", rejected
    assert rejected["executed"] is False
    assert not any(row[0].startswith("ak.wwise.core.sourceControl.") for row in client.calls)


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_source_control_exact_audio_source_original_file_executes_once_without_claiming_provider_effect(tmp_path, version):
    client, state_dir, preview, run = _source_control_object_file_case(tmp_path, version=version, choice="--original-media-object")
    artifact = TransactionStore(state_dir).load_preview(preview["transaction_id"]).artifact
    assert artifact["request"]["arguments"]["args"] == {"files": [str(client.media)]}
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0 and executed["executed"] is True, executed
    writes = [row for row in client.calls if row[0] == "ak.wwise.core.sourceControl.checkOut"]
    assert len(writes) == 1 and writes[0][1] == {"files": [str(client.media)]}
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["agent_result"]["verified"] is False, verified
    code, replay = run("execute", preview["transaction_id"])
    assert code == 2 and len([row for row in client.calls if row[0].endswith("checkOut")]) == 1, replay


def test_source_control_sound_original_file_needs_exact_source_and_language_choice(tmp_path):
    client, state_dir, rejected, _run = _source_control_object_file_case(tmp_path,
        choice="--original-media-object", live_type="Sound", declaration_error="exact AudioFileSource")
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.sourceControl.") for row in client.calls)


@pytest.mark.parametrize("change", ("missing", "replaced", "symlink"))
def test_source_control_object_file_binding_drift_cannot_reach_provider(tmp_path, change):
    client, _state_dir, preview, run = _source_control_object_file_case(tmp_path)
    client.containing.unlink()
    if change == "replaced":
        client.containing.write_text("changed payload after immutable Preview", encoding="utf-8")
    elif change == "symlink":
        target = client.project_root / "different.wwu"
        target.write_text("unapproved file", encoding="utf-8")
        client.containing.symlink_to(target)
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2 and rejected["ok"] is False, rejected
    assert not any(row[0].startswith("ak.wwise.core.sourceControl.") for row in client.calls)


@pytest.mark.parametrize("changed,value", (("name", "Different"), ("type", "Event"), ("path", "\\Actor-Mixer Hierarchy\\Moved"),
                                           ("id", "{33333333-3333-3333-3333-333333333333}"), ("filePath", None)))
def test_source_control_object_identity_and_missing_accessor_drift_fail_closed(tmp_path, changed, value):
    client, _state_dir, preview, run = _source_control_object_file_case(tmp_path)
    client.row[changed] = value
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2 and rejected["ok"] is False, rejected
    assert not any(row[0].startswith("ak.wwise.core.sourceControl.") for row in client.calls)


def test_source_control_two_objects_in_one_containing_file_are_one_native_file_scope(tmp_path):
    client, state_dir, preview, run = _source_control_object_file_case(tmp_path, object_count=2)
    artifact = TransactionStore(state_dir).load_preview(preview["transaction_id"]).artifact
    assert artifact["request"]["arguments"]["args"] == {"files": [str(client.containing)]}
    assert len(artifact["request"]["arguments"]["source_control_binding"]["objects"]) == 2
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0 and executed["executed"] is True, executed
    assert [row[1] for row in client.calls if row[0].endswith("checkOut")] == [{"files": [str(client.containing)]}]


@pytest.mark.parametrize("action", ("add", "commit", "delete", "revert", "getStatus"))
def test_source_control_file_actions_share_the_exact_object_scope_without_status_identity_inference(tmp_path, action):
    operation = "ak.wwise.core.sourceControl." + action
    client, state_dir, preview, run = _source_control_object_file_case(tmp_path, operation=operation)
    if action == "getStatus":
        assert preview["agent_result"] == {"log": [], "result": [{"owner": "fixture-owner", "status": "fixture-status"}]}
        assert "transaction_id" not in preview
    else:
        code, executed = run("execute", preview["transaction_id"])
        assert code == 0 and executed["executed"] is True, executed
    calls = [row for row in client.calls if row[0] == operation]
    expected = {"files": [str(client.containing)]}
    if action == "commit":
        expected["message"] = "Exact object-file changes"
    assert len(calls) == 1 and calls[0][1] == expected
    if action != "getStatus":
        code, verified = run("verify", preview["transaction_id"])
        assert code == 0 and verified["agent_result"]["verified"] is False, verified
        assert verified["agent_result"]["result"] == {"log": []}


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_source_control_object_file_discovery_is_versioned_and_keeps_explicit_file_alternatives(tmp_path, version):
    code, schema = gateway.execute_gateway(["--version", version, "request-schema", "ak.wwise.core.sourceControl.checkOut"],
        env=_env(tmp_path, version=version), client_factory=lambda url: pytest.fail(f"offline discovery connected to {url}"))
    if version in {"2021.1", "2022.1"}:
        assert code == 2 and "object_file_scopes" not in json.dumps(schema), schema
        return
    assert code == 0, schema
    declaration = schema["business_adapter"]["declaration"]
    assert set(declaration["optional_fields"]) >= {"files", "object_files", "io_root"}
    assert "files" not in declaration["required_fields"]
    choices = declaration["object_file_scopes"]
    assert choices["maximum_scopes"] == 64
    assert choices["containing-file"]["cli"] == "--object-file <Object Handle>"
    assert choices["original-media"]["cli"] == "--original-media-object <AudioFileSource Handle>"
    assert choices["file_input"] == "one_or_more_file_locators_or_object_file_scopes"
    code, phase = gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), "draft-start", "ak.wwise.core.sourceControl.checkOut"],
        env=_env(tmp_path, version=version), client_factory=lambda url: pytest.fail(f"offline start connected to {url}"))
    assert code == 0, phase
    binding = phase["draft"]["next_action_binding"]["declaration"]["optional_object_file_binding"]
    assert "draft-bind-object" in binding["fixed_argv_prefix"]
    assert binding["append"] == ["--object-id <chosen-exact-GUID>"]


def test_source_control_observed_external_file_still_requires_explicit_io_authority(tmp_path):
    client, state_dir, rejected, _run = _source_control_object_file_case(tmp_path,
        external_containing=True, declaration_error="SOURCE_CONTROL_PATH_OUTSIDE_ROOT")
    assert not (state_dir / "transactions").exists()
    assert not any(row[0].startswith("ak.wwise.core.sourceControl.") for row in client.calls)


def test_source_control_observed_external_file_can_use_an_exact_approved_io_root(tmp_path):
    client, state_dir, preview, run = _source_control_object_file_case(tmp_path, external_containing=True, approve_external=True)
    artifact = TransactionStore(state_dir).load_preview(preview["transaction_id"]).artifact
    assert artifact["request"]["arguments"]["io_root"] == str(client.containing.parent)
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0 and executed["executed"] is True, executed
    assert [row[1] for row in client.calls if row[0].endswith("checkOut")] == [{"files": [str(client.containing)]}]


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_source_control_per_file_status_read_preserves_native_responses_under_read_only_policy(tmp_path, version):
    from tests.unit.test_object_graph_business_gateway import _info
    operation = "ak.wwise.core.sourceControl.getStatus"
    class Client(_SourceControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.calls = []
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == operation:
                self.calls.append((args, options))
                return {"result": [{"owner": "native-owner", "status": "native-status", "nativeID": "{11111111-1111-1111-1111-111111111111}"}], "log": []}
            return super().call(uri, args, options)
    client = Client()
    env = _env(tmp_path, version=version)
    config_path = Path(env["WAAPI_SKILL_CONFIG_PATH"])
    config = json.loads(config_path.read_text())
    config["project_modification_policy"] = "read_only"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    code, schema = gateway.execute_gateway(["--version", version, "request-schema", operation], env=env,
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"))
    assert code == 0 and schema["business_adapter"]["read_alternative"]["subcommand"] == "core-call", schema
    code, result = gateway.execute_gateway(["core-call", operation, "--project-file", "Events/A.wwu", "--originals-file", "雨.wav"],
        env=env, client_factory=lambda _url: client)
    assert code == 0 and result["complete"] is True, json.dumps(result, ensure_ascii=False)
    paths = [str(client.project_root / "Events" / "A.wwu"), str(client.originals / "雨.wav")]
    assert client.calls == [({"files": [path]}, {}) for path in paths]
    observed = result["agent_result"]
    assert [{"file": row["file"], "result": row["result"]} for row in observed["files"]] == [
        {"file": path, "result": {"result": [{"owner": "native-owner", "status": "native-status",
         "nativeID": "{11111111-1111-1111-1111-111111111111}"}], "log": []}} for path in paths]
    assert all(row["call"]["ok"] is True and row["schema_validation"]["request"]["unresolved_refs"] == []
               for row in observed["files"])
    assert observed["provider_identity_verified"] is False
    assert observed["provider_effects_verified"] is False
    assert list(result)[-1] == "agent_result"


def _source_status_read(tmp_path, responses, *, version="2025.1", flags=None, after_read=None, timeout=None):
    from tests.unit.test_object_graph_business_gateway import _info
    operation = "ak.wwise.core.sourceControl.getStatus"
    class Client(_SourceControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.calls = []
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == operation:
                self.calls.append((args, options))
                response = responses[len(self.calls) - 1]
                if after_read is not None:
                    after_read()
                if isinstance(response, Exception):
                    raise response
                return response
            return super().call(uri, args, options)
    client = Client()
    env = _env(tmp_path, version=version)
    config_path = Path(env["WAAPI_SKILL_CONFIG_PATH"])
    config = json.loads(config_path.read_text())
    config["project_modification_policy"] = "read_only"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    argv = [*(["--timeout", str(timeout)] if timeout is not None else []), "core-call", operation, *(flags if flags is not None else
            ["--project-file", "A.wwu", "--project-file", "B.wwu", "--project-file", "C.wwu"])]
    code, result = gateway.execute_gateway(argv, env=env, client_factory=lambda _url: client)
    return client, code, result


def test_source_control_status_second_file_failure_keeps_first_exact_response_without_retry(tmp_path):
    first = {"result": [{"owner": "native owner", "status": "checked out"}], "log": [{"message": "native log"}]}
    client, code, result = _source_status_read(tmp_path, [first, RuntimeError("provider unavailable")])
    assert code != 0 and result["complete"] is False, result
    report = result["agent_result"]
    assert report["incomplete_reason"] == "native_call_failed"
    assert report["files"][0]["result"] == first
    assert report["files"][1]["file"] == str(client.project_root / "B.wwu")
    assert "provider unavailable" in json.dumps(report["files"][1]["failure"])
    assert report["remaining_files"] == [str(client.project_root / "C.wwu")]
    assert len(client.calls) == 2 and report["automatic_retry"] is False
    assert report["provider_identity_verified"] is False and report["provider_effects_verified"] is False
    assert list(result)[-1] == "agent_result"


@pytest.mark.parametrize(("native", "reason"), [
    ({"result": [{"owner": "preserved-owner"}], "log": []}, "status_not_observed"),
    ({"result": [], "log": [{"message": "no status supplied"}]}, "status_not_observed"),
    ({"result": [{"owner": True, "status": "checked out"}], "log": []}, "status_result_shape_invalid"),
    ({"result": [{"owner": "native", "status": True}], "log": []}, "status_result_shape_invalid"),
])
def test_source_control_status_missing_or_wrong_typed_field_is_partial_with_exact_native_data(tmp_path, native, reason):
    client, code, result = _source_status_read(tmp_path, [native])
    assert code != 0 and result["complete"] is False, result
    report = result["agent_result"]
    assert report["incomplete_reason"] == reason
    assert report["files"][0]["result"] == native
    assert len(client.calls) == 1
    assert report["remaining_files"] == [str(client.project_root / name) for name in ("B.wwu", "C.wwu")]


def test_source_control_status_native_byte_overflow_is_bounded_failure_not_complete(tmp_path):
    client, code, result = _source_status_read(tmp_path, [{"result": [{"status": "x" * (17 * 1024)}], "log": []}])
    assert code != 0 and result["complete"] is False, result
    report = result["agent_result"]
    assert report["incomplete_reason"] == "native_call_failed"
    failure = report["files"][0]["failure"]
    assert failure["error_code"] == "RESULT_TOO_LARGE" and failure["details"]["limit_bytes"] == 16384
    assert "x" * 1024 not in json.dumps(result)
    assert len(client.calls) == 1 and len(report["remaining_files"]) == 2


def test_source_control_status_cumulative_rows_overflow_retains_all_bounded_responses(tmp_path):
    # Each result fits 16 KiB independently; together these legal anonymous rows exceed 4096.
    native = {"result": [{"status": "ok"}], "log": [{} for _ in range(1050)]}
    client, code, result = _source_status_read(tmp_path, [native] * 4, flags=[
        flag for name in ("A", "B", "C", "D", "E") for flag in ("--project-file", f"{name}.wwu")])
    assert code != 0 and result["complete"] is False, result
    report = result["agent_result"]
    assert report["incomplete_reason"] == "status_row_budget_exceeded", json.dumps(report)
    assert report["observed_row_count"] == 4204
    assert [row["result"] for row in report["files"]] == [native] * 4
    assert len(client.calls) == 4 and report["remaining_files"] == [str(client.project_root / "E.wwu")]


@pytest.mark.parametrize(("version", "flags"), [
    ("2021.1", ["--project-file", "A.wwu"]),
    ("2022.1", ["--project-file", "A.wwu"]),
    ("2025.1", []),
    ("2025.1", [flag for index in range(33) for flag in ("--project-file", f"{index}.wwu")]),
    ("2025.1", ["--project-file", "A.wwu", "--object-id", "{11111111-1111-1111-1111-111111111111}"]),
])
def test_source_control_status_invalid_selection_stops_before_connection(tmp_path, version, flags):
    code, result = gateway.execute_gateway(["core-call", "ak.wwise.core.sourceControl.getStatus", *flags],
        env=_env(tmp_path, version=version), client_factory=lambda url: pytest.fail(f"invalid read connected to {url}"))
    assert code == 2 and result["ok"] is False


@pytest.mark.parametrize("flags", [
    ["--project-file", "../outside.wwu"],
    ["--exact-file", "/outside/A.wwu"],
])
def test_source_control_status_file_scope_cannot_escape_existing_io_policy(tmp_path, flags):
    client, code, result = _source_status_read(tmp_path, [], flags=flags)
    assert code != 0 and result["ok"] is False, result
    assert client.calls == []


def test_source_control_status_deadline_keeps_completed_file_before_next_call(tmp_path):
    import time
    count = [0]
    def delay_second():
        count[0] += 1
        if count[0] == 2:
            time.sleep(0.3)
    first = {"result": [{"status": "native-status"}], "log": []}
    client, code, result = _source_status_read(tmp_path, [first, first], after_read=delay_second, timeout=0.15)
    assert code != 0 and result["complete"] is False, result
    report = result["agent_result"]
    assert report["files"][0]["result"] == first
    assert report["files"][1]["failure"]["error_code"] == "TIMEOUT"
    assert len(client.calls) == 2 and report["automatic_retry"] is False
    assert report["remaining_files"] == [str(client.project_root / "C.wwu")]


@pytest.mark.parametrize("action", ("delete", "commit"))
def test_source_control_status_read_classification_keeps_write_transactions_policy_blocked(tmp_path, action):
    operation = "ak.wwise.core.sourceControl." + action
    client, state_dir, preview, run = _source_control_object_file_case(tmp_path, operation=operation)
    config_path = tmp_path / "config.json"
    config = json.loads(config_path.read_text())
    config["project_modification_policy"] = "read_only"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    code, result = run("execute", preview["transaction_id"])
    assert code != 0 and "read_only" in json.dumps(result), result
    assert not any(call[0] == operation for call in client.calls)


def test_source_control_status_draft_rechecks_exact_object_file_before_terminal_read(tmp_path):
    client, _state, result, _run = _source_control_object_file_case(tmp_path,
        operation="ak.wwise.core.sourceControl.getStatus",
        before_check=lambda client: client.row.__setitem__("filePath", str(client.project_root / "different.wwu")),
        check_error="SOURCE_CONTROL_OBJECT_FILE_BINDING_CHANGED")
    assert result["ok"] is False
    assert not any(row[0].endswith("sourceControl.getStatus") for row in client.calls)

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
    sorted(source_control_business_operations()),
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
def test_source_control_provider_configuration_requires_the_closed_profile_contract(
    tmp_path: Path,
    version: str,
) -> None:
    exit_code, payload = gateway.execute_gateway(
        ["--version", version, "request-schema", SOURCE_CONTROL_SET_PROVIDER_URI],
        env=_env(tmp_path, version=version),
        client_factory=lambda url: pytest.fail(f"provider boundary connected to {url}"),
    )

    assert exit_code == 0, payload
    assert payload["business_adapter"]["declaration"]["provider_profile"]["cli"] == "--provider-profile configured"


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


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_source_control_provider_profile_is_configured_offline_and_disclosed_without_secrets(tmp_path, version):
    profile = tmp_path / "private-profile.json"
    code, result = gateway.execute_gateway(["config-set", "--source-control-profile", str(profile)],
        env=_env(tmp_path, version=version), client_factory=lambda url: pytest.fail(f"config connected {url}"))
    assert code == 0 and result["effective"]["source_control_profile"] == str(profile), result
    code, schema = gateway.execute_gateway(["--version", version, "request-schema", SOURCE_CONTROL_SET_PROVIDER_URI],
        env={"WAAPI_SKILL_CONFIG_PATH": str(tmp_path / "config.json")},
        client_factory=lambda url: pytest.fail(f"schema connected {url}"))
    assert code == 0, schema
    adapter = schema["business_adapter"]
    assert adapter["declaration"]["provider_profile"]["cli"] == "--provider-profile configured"
    assert adapter["protected_result"]["native_text"] == "never_persisted_or_disclosed"
    assert adapter["start"]["subcommand"] == "draft-start"


def _provider_profile_case(tmp_path, *, version="2025.1", selection="provider", native=None, before_preview=None, document_update=None, setup_change=None, declaration_error=False, policy="ask_before_changes"):
    from tests.unit.test_object_graph_business_gateway import _info
    secret = 'fake-password-雪-"\\-needle'
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    credential = private / "credential.txt"
    credential.write_text(secret, encoding="utf-8")
    credential.chmod(0o600)
    profile = private / "profile.json"
    document = {"contract": "waapi-skill.source-control-profile/v1", "label": "Team test profile", "selection": selection}
    if selection == "provider":
        document.update(provider="Perforce", connection={"host": "fake-host", "port": "1666", "server": "fake-server", "username": "fake-user", "workspace": "fake-workspace"}, password_file="credential.txt")
    if document_update is not None:
        document_update(document)
    profile.write_text(json.dumps(document), encoding="utf-8")
    profile.chmod(0o600)
    if setup_change is not None:
        setup_change(profile, credential)
    class Client(_SourceControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.calls = []
            self.fail_cleanup = False
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == SOURCE_CONTROL_SET_PROVIDER_URI:
                self.calls.append((args, options))
                if callable(native):
                    return native()
                if isinstance(native, Exception):
                    raise native
                return native if native is not None else {"log": [{"severity": "Message", "time": 0, "messageId": secret, "message": secret, "parameters": [secret.encode().hex()]}]}
            return super().call(uri, args, options)
        def disconnect(self):
            if self.fail_cleanup:
                raise RuntimeError(secret)
    client = Client()
    env = _env(tmp_path, version=version)
    state = tmp_path / "state"
    evidence = tmp_path / "evidence"
    code, configured = gateway.execute_gateway(["config-set", "--source-control-profile", str(profile), "--project-modification-policy", policy], env=env)
    assert code == 0, configured
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state), "--evidence-dir", str(evidence), *argv], env=env, client_factory=lambda url: client)
    code, phase = run("draft-start", SOURCE_CONTROL_SET_PROVIDER_URI)
    assert code == 0, phase
    declaration = phase["draft"]["next_action_binding"]["declaration"]
    assert declaration["append"] == ["--provider-profile", "configured"]
    assert "--commit-message" not in json.dumps(declaration) and "--exact-file" not in json.dumps(declaration)
    draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
    code, phase = run("draft-declare-source-control-plan", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), "--provider-profile", "configured")
    if declaration_error:
        assert code == 2, phase
        return client, run, phase, state, evidence, profile, credential, secret
    assert code == 0, phase
    code, phase = run("draft-check", draft, "--task-authority", authority, "--expected-revision", str(phase["draft"]["revision"]))
    assert code == 0, phase
    if before_preview is not None:
        before_preview(profile, credential)
    code, preview = run("preview-from-draft", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), "--apply")
    assert code == 0, preview
    return client, run, preview, state, evidence, profile, credential, secret


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_source_control_provider_profile_preview_and_execution_never_persist_credentials_or_native_echo(tmp_path, version):
    client, run, preview, state, evidence, profile, credential, secret = _provider_profile_case(tmp_path, version=version)
    assert client.calls == []
    artifact = TransactionStore(state).load_preview(preview["transaction_id"]).artifact
    rendered = json.dumps(artifact, ensure_ascii=False)
    assert "Team test profile" in rendered and "Perforce" in rendered and str(profile) in rendered
    assert secret not in rendered and "fake-user" not in rendered
    code, shown = run("transaction-show", preview["transaction_id"], "--summary-only")
    assert code == 0, shown
    for payload in (preview, shown):
        public = json.dumps(payload)
        assert "Team test profile" in public and "Perforce" in public and str(profile) in public, public
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0 and executed["executed"] is True, executed
    assert client.calls == [({"provider": "Perforce", "host": "fake-host", "port": "1666", "server": "fake-server", "username": "fake-user", "workspace": "fake-workspace", "password": secret}, {})]
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["agent_result"]["verified"] is False, verified
    observation = verified["agent_result"]["result"]
    assert observation["protected_native_result"] is True and observation["native_log_count"] == 1
    assert observation["provider_effects_verified"] is False
    for root in (state, evidence):
        for file in root.rglob("*"):
            if file.is_file() and file.suffix != ".key":
                content = file.read_bytes()
                assert b"fake-password" not in content and secret.encode().hex().encode() not in content, file
                assert b"fake-user" not in content, file
    assert secret not in json.dumps([preview, shown, executed, verified], ensure_ascii=False)
    code, replay = run("execute", preview["transaction_id"])
    assert code != 0 and len(client.calls) == 1, replay


def _authorize_provider_preview(run, preview):
    code, shown = run("transaction-show", preview["transaction_id"], "--summary-only")
    assert code == 0, shown
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    return confirmed


def _assert_no_provider_secret_artifacts(state, evidence, secret, *payloads):
    for root in (state, evidence):
        for file in root.rglob("*"):
            if file.is_file() and file.suffix != ".key":
                content = file.read_bytes()
                assert b"fake-password" not in content and secret.encode().hex().encode() not in content, file
    assert "fake-password" not in json.dumps(payloads, ensure_ascii=False)


@pytest.mark.parametrize("native", [
    pytest.param(lambda: None, id="missing-response"),
    RuntimeError('provider echoed fake-password-雪-"\\-needle'),
    {"log": [{"severity": "Message", "time": 0, "messageId": "id", "message": "fake-password-雪-\"\\-needle", "fake-password-雪-\"\\-needle": "echo"}]},
    {"log": [{"severity": "Message", "time": 0, "messageId": "id", "message": "x" * 12000}]},
])
def test_source_control_provider_native_exception_malformed_or_large_echo_is_protected_before_evidence(tmp_path, native):
    client, run, preview, state, evidence, _profile, _credential, secret = _provider_profile_case(tmp_path, native=native)
    _authorize_provider_preview(run, preview)
    code, result = run("execute", preview["transaction_id"])
    assert code != 0 and len(client.calls) == 1, result
    assert result["automatic_retry"] is False
    if callable(native):
        assert result["state"] == "indeterminate"
        assert result["dispatch_result"]["error_code"] == "PROTECTED_PROVIDER_RESULT_INVALID"
    _assert_no_provider_secret_artifacts(state, evidence, secret, result)
    code, replay = run("execute", preview["transaction_id"])
    assert code != 0 and len(client.calls) == 1, replay


@pytest.mark.parametrize("change", ("credential", "profile", "config", "permissions", "key", "key-permissions", "credential-link"))
def test_source_control_provider_file_or_configuration_drift_cannot_reach_native_provider(tmp_path, change):
    client, run, preview, state, evidence, profile, credential, secret = _provider_profile_case(tmp_path)
    _authorize_provider_preview(run, preview)
    if change == "credential":
        credential.write_text("changed fake credential", encoding="utf-8")
    elif change == "profile":
        document = json.loads(profile.read_text())
        document["label"] = "Changed profile"
        profile.write_text(json.dumps(document))
    elif change == "config":
        config = tmp_path / "config.json"
        document = json.loads(config.read_text())
        document["source_control_profile"] = str(profile.parent / "different.json")
        config.write_text(json.dumps(document))
    elif change == "permissions":
        credential.chmod(0o644)
    elif change == "key":
        (state / "provider-profiles" / "content.key").write_bytes(b"x" * 32)
    elif change == "key-permissions":
        (state / "provider-profiles" / "content.key").chmod(0o644)
    else:
        archived = credential.with_suffix(".preserved")
        credential.rename(archived)
        credential.symlink_to(archived)
    code, result = run("execute", preview["transaction_id"])
    assert code != 0 and client.calls == [], result
    _assert_no_provider_secret_artifacts(state, evidence, secret, result)


def test_source_control_provider_disabled_intent_is_reviewable_and_has_no_connection_arguments(tmp_path):
    client, run, preview, state, evidence, profile, _credential, secret = _provider_profile_case(tmp_path, selection="disabled", native={"log": []})
    rendered = json.dumps(TransactionStore(state).load_preview(preview["transaction_id"]).artifact)
    assert "disabled" in rendered and "Team test profile" in rendered and str(profile) in rendered
    _authorize_provider_preview(run, preview)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0 and client.calls == [({"provider": ""}, {})], result
    code, result = run("verify", preview["transaction_id"])
    assert code == 0 and result["agent_result"]["verified"] is False, result
    _assert_no_provider_secret_artifacts(state, evidence, secret, result)


def test_source_control_provider_cleanup_exception_is_protected_before_gateway_error_projection(tmp_path):
    client, run, preview, state, evidence, _profile, _credential, secret = _provider_profile_case(tmp_path)
    _authorize_provider_preview(run, preview)
    client.fail_cleanup = True
    code, result = run("execute", preview["transaction_id"])
    assert code != 0 and len(client.calls) == 1, result
    _assert_no_provider_secret_artifacts(state, evidence, secret, result)
    assert "withheld" in result["details"]["cleanup_failure"]["message"], result


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_source_control_provider_profile_route_does_not_claim_unpinned_old_version_support(tmp_path, version):
    code, result = gateway.execute_gateway(["--version", version, "request-schema", SOURCE_CONTROL_SET_PROVIDER_URI],
        env=_env(tmp_path, version=version), client_factory=lambda url: pytest.fail(f"old route connected {url}"))
    assert code == 2 and result["ok"] is False


@pytest.mark.parametrize("change", ("malformed", "extra-field", "profile-permissions", "directory-permissions", "credential-outside", "missing-credential"))
def test_source_control_provider_invalid_private_setup_never_echoes_file_contents_or_contacts_provider(tmp_path, change):
    def update(document):
        if change == "extra-field":
            document["args"] = {"password": "fake-password"}
        if change == "credential-outside":
            document["password_file"] = "../credential.txt"
        if change == "missing-credential":
            document["password_file"] = "missing.txt"
    def setup(profile, _credential):
        if change == "malformed":
            profile.write_text('{"fake-password": broken')
        elif change == "profile-permissions":
            profile.chmod(0o644)
        elif change == "directory-permissions":
            profile.parent.chmod(0o755)
    client, _run, failure, state, evidence, _profile, _credential, secret = _provider_profile_case(
        tmp_path, document_update=update, setup_change=setup, declaration_error=True)
    assert client.calls == [] and "profile" in failure["message"].lower(), failure
    _assert_no_provider_secret_artifacts(state, evidence, secret, failure)


def test_source_control_custom_provider_omits_all_optional_native_fields_without_inventing_availability(tmp_path):
    def custom(document):
        document["provider"] = "User declared provider"
        del document["connection"]
        del document["password_file"]
    client, run, preview, state, evidence, _profile, _credential, secret = _provider_profile_case(
        tmp_path, document_update=custom, native={"log": []})
    _authorize_provider_preview(run, preview)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0 and client.calls == [({"provider": "User declared provider"}, {})], result
    code, result = run("verify", preview["transaction_id"])
    assert code == 0 and result["agent_result"]["verified"] is False, result
    _assert_no_provider_secret_artifacts(state, evidence, secret, result)


def test_source_control_provider_read_only_policy_blocks_even_an_authorized_preview(tmp_path):
    client, run, preview, state, evidence, _profile, _credential, secret = _provider_profile_case(tmp_path)
    _authorize_provider_preview(run, preview)
    config = tmp_path / "config.json"
    document = json.loads(config.read_text())
    document["project_modification_policy"] = "read_only"
    config.write_text(json.dumps(document))
    code, result = run("execute", preview["transaction_id"])
    assert code != 0 and client.calls == [] and "read_only" in json.dumps(result), result
    _assert_no_provider_secret_artifacts(state, evidence, secret, result)


def test_source_control_provider_timeout_and_late_native_exception_remain_confidential(tmp_path):
    import threading
    import time
    finished = threading.Event()
    def delayed():
        try:
            time.sleep(0.2)
            raise RuntimeError('fake-password-雪-"\\-needle')
        finally:
            finished.set()
    client, run, preview, state, evidence, _profile, _credential, secret = _provider_profile_case(tmp_path, native=delayed)
    _authorize_provider_preview(run, preview)
    code, result = run("--timeout", "0.1", "execute", preview["transaction_id"])
    assert code != 0 and len(client.calls) == 1, result
    assert "TIMEOUT" in json.dumps(result)
    assert finished.wait(1)
    _assert_no_provider_secret_artifacts(state, evidence, secret, result)


def test_source_control_provider_cannot_bypass_failed_file_privacy_proof(tmp_path, monkeypatch):
    import wwise_waapi.source_control_profiles as profiles
    original = profiles._private
    def missing_proof(path, metadata, *, directory):
        if path.name == "private":
            raise profiles.ProviderProfileError("Fixed Windows owner/DACL proof unavailable")
        return original(path, metadata, directory=directory)
    monkeypatch.setattr(profiles, "_private", missing_proof)
    client, _run, result, state, evidence, _profile, _credential, secret = _provider_profile_case(tmp_path, declaration_error=True)
    assert client.calls == []
    _assert_no_provider_secret_artifacts(state, evidence, secret, result)


def test_source_control_provider_allow_changes_records_policy_authority_before_dispatch(tmp_path):
    client, run, preview, state, evidence, _profile, _credential, secret = _provider_profile_case(tmp_path, policy="allow_changes", native={"log": []})
    assert client.calls == [] and preview["state"] == "policy_authorized", preview
    code, shown = run("transaction-show", preview["transaction_id"], "--summary-only")
    assert code == 0 and "policy_authorization" in json.dumps(shown), shown
    code, result = run("execute", preview["transaction_id"])
    assert code == 0 and len(client.calls) == 1, result
    _assert_no_provider_secret_artifacts(state, evidence, secret, preview, shown, result)


def test_source_control_provider_ask_before_changes_does_not_dispatch_without_confirmation(tmp_path):
    client, run, preview, state, evidence, _profile, _credential, secret = _provider_profile_case(tmp_path)
    code, refused = run("execute", preview["transaction_id"])
    assert code != 0 and client.calls == [], refused
    _assert_no_provider_secret_artifacts(state, evidence, secret, refused)


def _sound_source_file_case(tmp_path, *, version="2025.1", mode="active", language="French", declaration_error=False, include_direct=False, prepare=None, move=False, plan_flags=None):
    from tests.unit.test_object_graph_business_gateway import _info
    sound_id = "{11111111-1111-1111-1111-111111111111}"
    source_id = "{22222222-2222-2222-2222-222222222222}"
    other_id = "{33333333-3333-3333-3333-333333333333}"
    french_id = "{44444444-4444-4444-4444-444444444444}"
    sfx_id = "{55555555-5555-5555-5555-555555555555}"
    operation = "ak.wwise.core.sourceControl." + ("move" if move else "checkOut")
    class Client(_SourceControlDraftClient):
        def __init__(self):
            super().__init__(tmp_path)
            self.media = self.originals / "French" / "雨.wav"
            self.media.parent.mkdir()
            self.media.write_bytes(b"French fixture")
            self.other_media = self.originals / "SFX" / "different.wav"
            self.other_media.parent.mkdir()
            self.other_media.write_bytes(b"SFX fixture")
            self.sound = {"id": sound_id, "name": "Rain", "type": "Sound", "path": "\\Actor-Mixer Hierarchy\\Rain",
                "activeSource": {"id": source_id, "name": "Localized recording"}, "originalFilePath": str(self.media)}
            self.source = {"id": source_id, "name": "Localized recording", "type": "AudioFileSource", "path": self.sound["path"] + "\\Localized recording",
                "parent": {"id": sound_id, "name": "Rain"}, "audioSource:language": {"id": french_id, "name": "French"}, "originalFilePath": str(self.media)}
            self.other = {"id": other_id, "name": "Other recording", "type": "AudioFileSource", "path": self.sound["path"] + "\\Other recording",
                "parent": {"id": sound_id, "name": "Rain"}, "audioSource:language": {"id": sfx_id, "name": "SFX"}, "originalFilePath": str(self.other_media)}
            self.rows = {sound_id: self.sound, source_id: self.source, other_id: self.other}
            self.rows[french_id] = {"id": french_id, "name": "French", "type": "Language", "path": "\\Languages\\French"}
            self.rows[sfx_id] = {"id": sfx_id, "name": "SFX", "type": "Language", "path": "\\Languages\\SFX"}
            self.children = [self.source, self.other]
            self.language_matches = [self.rows[french_id]]
            self.calls = []
        def call(self, uri, args=None, options=None):
            self.calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.object.get":
                if "waql" in args:
                    if args["waql"].startswith("from type Language"):
                        assert args["waql"] == 'from type Language where name = "French" take 2'
                        return {"return": [dict(row) for row in self.language_matches]}
                    assert args["waql"] == f'from object "{sound_id}" select children take 65'
                    return {"return": [dict(row) for row in self.children]}
                return {"return": [dict(self.rows[selected]) for selected in args["from"]["id"] if selected in self.rows]}
            if uri == operation:
                return {"log": []}
            return super().call(uri, args, options)
    client = Client()
    if prepare is not None:
        prepare(client)
    env = _env(tmp_path, version=version)
    state = tmp_path / "state"
    def run(*argv):
        return gateway.execute_gateway(["--state-dir", str(state), *argv], env=env, client_factory=lambda url: client)
    code, phase = run("draft-start", operation)
    assert code == 0, phase
    draft, authority = phase["draft"]["draft_id"], phase["task_authority"]
    handles = {}
    for object_id in ([sound_id, source_id, other_id] if move else [sound_id, source_id] if mode == "source" or include_direct else [sound_id]):
        code, phase = run("draft-bind-object", draft, "--task-authority", authority,
            "--expected-revision", str(phase["draft"]["revision"]), "--object-id", object_id)
        assert code == 0, phase
        handles[object_id] = phase["bound_object"]["handle"]
    selected = ([handles[sound_id], handles[source_id], language] if mode == "source" else [handles[sound_id], language])
    flags = [f"--sound-{mode}-media", *selected]
    if include_direct:
        flags.extend(("--original-media-object", handles[source_id]))
    if move:
        flags = ["--move-source-sound-active", "rain", handles[sound_id], language,
                 "--move-destination-object", "rain", handles[other_id], "original-media", "moved-雨.wav"]
    if plan_flags is not None:
        flags = plan_flags(client, handles)
    code, phase = run("draft-declare-source-control-plan", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), *flags)
    if declaration_error:
        assert code == 2, phase
        return client, state, phase, run
    assert code == 0, phase
    code, phase = run("draft-check", draft, "--task-authority", authority, "--expected-revision", str(phase["draft"]["revision"]))
    assert code == 0, json.dumps(phase, ensure_ascii=False)
    code, preview = run("preview-from-draft", draft, "--task-authority", authority,
        "--expected-revision", str(phase["draft"]["revision"]), "--apply")
    assert code == 0, preview
    code, shown = run("transaction-show", preview["transaction_id"], "--summary-only")
    assert code == 0, shown
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    return client, state, preview, run


def test_sound_active_source_media_scope_binds_explicit_language_and_exact_source_file(tmp_path):
    client, state, preview, run = _sound_source_file_case(tmp_path)
    artifact = TransactionStore(state).load_preview(preview["transaction_id"]).artifact
    row = artifact["request"]["arguments"]["source_control_binding"]["objects"][0]
    assert row["type"] == "Sound" and row["source"]["id"] == client.source["id"]
    assert row["media_selection"] == {"mode": "active", "language": "French"}
    assert row["source"]["language"] == client.source["audioSource:language"]
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    calls = [call for call in client.calls if call[0].endswith("sourceControl.checkOut")]
    assert calls == [("ak.wwise.core.sourceControl.checkOut", {"files": [str(client.media)]}, {})]
    assert any(call[0].endswith("object.get") and call[2].get("language") == "French" for call in client.calls)
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["agent_result"]["verified"] is False, verified


def test_sound_unique_language_media_scope_selects_source_independently_of_active_source(tmp_path):
    client, _state, preview, run = _sound_source_file_case(tmp_path, mode="language", language="SFX")
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    calls = [call for call in client.calls if call[0].endswith("sourceControl.checkOut")]
    assert calls == [("ak.wwise.core.sourceControl.checkOut", {"files": [str(client.other_media)]}, {})]


def test_sound_explicit_source_media_scope_preserves_parent_language_and_exact_file(tmp_path):
    client, _state, preview, run = _sound_source_file_case(tmp_path, mode="source", include_direct=True)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    calls = [call for call in client.calls if call[0].endswith("sourceControl.checkOut")]
    assert calls == [("ak.wwise.core.sourceControl.checkOut", {"files": [str(client.media)]}, {})]


@pytest.mark.parametrize("change", ["active-reference-name", "parent-name"])
def test_sound_source_media_rejects_inconsistent_reference_names(tmp_path, change):
    def prepare(client):
        reference = client.sound["activeSource"] if change == "active-reference-name" else client.source["parent"]
        reference["name"] = "Unrelated object"
    client, _state, _error, _run = _sound_source_file_case(tmp_path, prepare=prepare, declaration_error=True)
    assert not any(call[0].endswith("sourceControl.checkOut") for call in client.calls)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_sound_source_media_disclosure_is_versioned_and_separates_three_selections(tmp_path, version):
    code, result = gateway.execute_gateway(["--version", version, "request-schema", "ak.wwise.core.sourceControl.checkOut"],
        env=_env(tmp_path, version=version), client_factory=lambda url: pytest.fail("offline disclosure connected"))
    if version in {"2021.1", "2022.1"}:
        assert code == 2 and "sound-original-media" not in json.dumps(result), result
        return
    assert code == 0, result
    choices = result["business_adapter"]["declaration"]["object_file_scopes"]["sound-original-media"]
    assert choices["language"] == "explicit_exact_Language_name_or_GUID; checked_against_selected_source"
    assert choices["selections"] == {
        "active": "--sound-active-media <Sound Handle> <language>",
        "language": "--sound-language-media <Sound Handle> <language>",
        "source": "--sound-source-media <Sound Handle> <AudioFileSource Handle> <language>",
    }
    assert choices["maximum_children"] == 64


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("mode", ["active", "language", "source"])
def test_sound_media_selections_dispatch_exact_file_in_each_pinned_source_control_version(tmp_path, version, mode):
    client, _state, preview, run = _sound_source_file_case(tmp_path, version=version, mode=mode)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.checkOut")] == [{"files": [str(client.media)]}]


@pytest.mark.parametrize("change", ["active-source", "sound-name", "source-name", "source-parent", "source-language", "source-file", "file-stat"])
def test_sound_media_scope_drift_stops_before_provider_dispatch(tmp_path, change):
    client, _state, preview, run = _sound_source_file_case(tmp_path)
    if change == "active-source":
        client.sound["activeSource"] = {"id": client.other["id"], "name": client.other["name"]}
        client.sound["originalFilePath"] = str(client.other_media)
    elif change == "sound-name":
        client.sound["name"] = "Renamed Sound"
    elif change == "source-name":
        client.source["name"] = "Renamed source"
    elif change == "source-parent":
        client.source["parent"] = {"id": client.other["id"]}
    elif change == "source-language":
        client.source["audioSource:language"] = client.other["audioSource:language"]
    elif change == "source-file":
        client.source["originalFilePath"] = str(client.other_media)
    else:
        client.media.write_bytes(b"changed fixture after Preview")
    code, result = run("execute", preview["transaction_id"])
    assert code != 0, result
    assert not any(call[0].endswith("sourceControl.checkOut") for call in client.calls)


@pytest.mark.parametrize("change", ["missing-source", "missing-file", "missing-language", "wrong-language", "wrong-parent", "inconsistent-active-file", "malformed-active", "missing-match", "multiple-matches", "duplicate-child", "overflow"])
def test_sound_media_incomplete_or_ambiguous_selection_never_dispatches(tmp_path, change):
    mode = "language" if change in {"missing-match", "multiple-matches", "duplicate-child", "overflow"} else "active"
    def prepare(client):
        if change == "missing-source":
            del client.rows[client.source["id"]]
        elif change == "missing-file":
            del client.source["originalFilePath"]
        elif change == "missing-language":
            del client.source["audioSource:language"]
        elif change == "wrong-language":
            client.source["audioSource:language"] = client.other["audioSource:language"]
        elif change == "wrong-parent":
            client.source["parent"] = {"id": client.other["id"]}
        elif change == "inconsistent-active-file":
            client.sound["originalFilePath"] = str(client.other_media)
        elif change == "malformed-active":
            client.sound["activeSource"] = {"id": "broken"}
        elif change == "missing-match":
            client.children = [client.other]
        elif change == "multiple-matches":
            client.other["audioSource:language"] = client.source["audioSource:language"]
        elif change == "duplicate-child":
            client.children.append(dict(client.source))
        else:
            client.children = [dict(client.source)] * 65
    client, _state, _error, _run = _sound_source_file_case(tmp_path, mode=mode, prepare=prepare, declaration_error=True)
    assert not any(call[0].endswith("sourceControl.checkOut") for call in client.calls)


@pytest.mark.parametrize("mode", ["active", "language", "source"])
def test_sound_source_language_guid_accepts_matching_id_only_native_reference(tmp_path, mode):
    def prepare(client):
        client.source["audioSource:language"].pop("name")
    client, _state, preview, run = _sound_source_file_case(tmp_path, mode=mode,
        language="{44444444-4444-4444-4444-444444444444}", prepare=prepare)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.checkOut")] == [{"files": [str(client.media)]}]


def test_sound_explicit_source_can_be_inactive_but_must_still_belong_to_sound_and_language(tmp_path):
    def prepare(client):
        client.sound["activeSource"] = {"id": client.other["id"], "name": client.other["name"]}
        client.sound["originalFilePath"] = str(client.other_media)
    client, _state, preview, run = _sound_source_file_case(tmp_path, mode="source", prepare=prepare)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.checkOut")] == [{"files": [str(client.media)]}]


def test_source_control_move_binds_sound_media_to_observed_destination_object_directory(tmp_path):
    client, state, preview, run = _sound_source_file_case(tmp_path, move=True)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.move")] == [{
        "files": [str(client.media)], "newFiles": [str(client.other_media.parent / "moved-雨.wav")]}]
    artifact = TransactionStore(state).load_preview(preview["transaction_id"]).artifact
    assert artifact["request"]["arguments"]["source_control_binding"]["moves"][0]["row_id"] == "rain"
    code, verified = run("verify", preview["transaction_id"])
    assert code == 0 and verified["agent_result"]["verified"] is False, verified


@pytest.mark.parametrize("conflict", ["duplicate-source", "duplicate-destination", "crossed-source-destination"])
def test_source_control_move_rejects_cross_row_file_conflicts_before_provider(tmp_path, conflict):
    def flags(client, handles):
        source = handles[client.source["id"]]
        other = handles[client.other["id"]]
        result = ["--move-source-object", "a", source, "original-media",
                  "--move-destination-object", "a", other, "original-media", "first.wav"]
        second_source = source if conflict == "duplicate-source" else other
        second_name = "first.wav" if conflict == "duplicate-destination" else "second.wav"
        if conflict == "crossed-source-destination":
            # An existing literal row contributes a source equal to the first derived destination.
            # Give the literal source an exact new path during declaration; the conflict must be
            # rejected regardless of which per-file existence check runs first.
            result.extend(("--move-source-file", "b", "originals", "SFX/first.wav",
                           "--move-destination-file", "b", "originals", "SFX/second.wav"))
            (client.other_media.parent / "first.wav").write_bytes(b"already a source")
        else:
            result.extend(("--move-source-object", "b", second_source, "original-media",
                           "--move-destination-object", "b", other, "original-media", second_name))
        return result
    client, _state, _error, _run = _sound_source_file_case(tmp_path, move=True, plan_flags=flags, declaration_error=True)
    assert not any(call[0].endswith("sourceControl.move") for call in client.calls)


@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
def test_source_control_move_preserves_multiple_bound_rows_and_literal_pairs(tmp_path, version):
    def flags(client, handles):
        extra = client.originals / "literal.txt"
        extra.write_text("literal source", encoding="utf-8")
        return ["--move", "originals", "literal.txt", "originals", "renamed.txt",
            "--move-source-sound-active", "a", handles[client.sound["id"]], "French",
            "--move-destination-object", "a", handles[client.other["id"]], "original-media", "rain-new.wav",
            "--move-source-object", "b", handles[client.other["id"]], "original-media",
            "--move-destination-object", "b", handles[client.source["id"]], "original-media", "sfx-new.wav"]
    client, state, preview, run = _sound_source_file_case(tmp_path, move=True, version=version, plan_flags=flags)
    artifact = TransactionStore(state).load_preview(preview["transaction_id"]).artifact
    binding = artifact["request"]["arguments"]["source_control_binding"]
    assert [row["row_id"] for row in binding["moves"]] == [None, "a", "b"]
    assert len(binding["objects"]) == 3
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.move")] == [{
        "files": [str(client.originals / "literal.txt"), str(client.media), str(client.other_media)],
        "newFiles": [str(client.originals / "renamed.txt"), str(client.other_media.parent / "rain-new.wav"), str(client.media.parent / "sfx-new.wav")]}]


@pytest.mark.parametrize("change", ["destination-anchor-name", "destination-anchor-path", "destination-anchor-file", "destination-anchor-stat", "destination-appeared", "destination-link", "source-language", "source-stat"])
def test_source_control_move_rechecks_each_endpoint_and_destination_absence(tmp_path, change):
    client, _state, preview, run = _sound_source_file_case(tmp_path, move=True)
    destination = client.other_media.parent / "moved-雨.wav"
    if change == "destination-anchor-name":
        client.other["name"] = "Different source identity"
    elif change == "destination-anchor-path":
        client.other["path"] += "Renamed"
    elif change == "destination-anchor-file":
        client.other["originalFilePath"] = str(client.media)
    elif change == "destination-anchor-stat":
        client.other_media.write_bytes(b"changed anchor file")
    elif change == "destination-appeared":
        destination.write_bytes(b"do not overwrite me")
    elif change == "destination-link":
        destination.symlink_to(client.media)
    elif change == "source-language":
        client.source["audioSource:language"] = client.other["audioSource:language"]
    else:
        client.media.write_bytes(b"changed source file")
    code, result = run("execute", preview["transaction_id"])
    assert code != 0, result
    assert not any(call[0].endswith("sourceControl.move") for call in client.calls)


@pytest.mark.parametrize("selection", ["sound-language", "sound-source", "exact-source", "literal-source", "containing-file"])
def test_source_control_move_reuses_closed_source_choices_and_literal_destination(tmp_path, selection):
    def prepare(client):
        client.containing = client.project_root / "source.wwu"
        client.containing.write_text("containing work unit", encoding="utf-8")
        client.sound["filePath"] = str(client.containing)
    def flags(client, handles):
        if selection == "sound-language":
            source = ["--move-source-sound-language", "row", handles[client.sound["id"]], "French"]
        elif selection == "sound-source":
            source = ["--move-source-sound-source", "row", handles[client.sound["id"]], handles[client.source["id"]], "French"]
        elif selection == "exact-source":
            source = ["--move-source-object", "row", handles[client.source["id"]], "original-media"]
        elif selection == "containing-file":
            source = ["--move-source-object", "row", handles[client.sound["id"]], "containing-file"]
        else:
            source = ["--move-source-file", "row", "originals", "French/雨.wav"]
        return [*source, "--move-destination-file", "row", "originals", "new.wav"]
    client, _state, preview, run = _sound_source_file_case(tmp_path, move=True, prepare=prepare, plan_flags=flags)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    expected_source = client.containing if selection == "containing-file" else client.media
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.move")] == [{
        "files": [str(expected_source)], "newFiles": [str(client.originals / "new.wav")]}]


@pytest.mark.parametrize("invalid", ["missing-destination", "duplicate-source-choice", "bad-label", "traversing-basename", "existing-destination", "wrong-object-scope"])
def test_source_control_move_invalid_closed_rows_never_dispatch(tmp_path, invalid):
    def flags(client, handles):
        label = "bad label" if invalid == "bad-label" else "row"
        source = ["--move-source-object", label, handles[client.source["id"]], "original-media"]
        if invalid == "missing-destination":
            return source
        if invalid == "duplicate-source-choice":
            source += source
        basename = "../escape.wav" if invalid == "traversing-basename" else "different.wav" if invalid == "existing-destination" else "new.wav"
        scope = "guessed" if invalid == "wrong-object-scope" else "original-media"
        return [*source, "--move-destination-object", label, handles[client.other["id"]], scope, basename]
    client, _state, _error, _run = _sound_source_file_case(tmp_path, move=True, plan_flags=flags, declaration_error=True)
    assert not any(call[0].endswith("sourceControl.move") for call in client.calls)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_source_control_move_discloses_repeated_closed_row_choices_and_object_binding(tmp_path, version):
    code, result = gateway.execute_gateway(["--version", version, "request-schema", "ak.wwise.core.sourceControl.move"],
        env=_env(tmp_path, version=version), client_factory=lambda url: pytest.fail("offline disclosure connected"))
    if version in {"2021.1", "2022.1"}:
        assert code == 2 and "object_move_rows" not in json.dumps(result), result
        return
    assert code == 0, result
    declaration = result["business_adapter"]["declaration"]
    assert "object_moves" in declaration["optional_fields"] and "moves" not in declaration["required_fields"]
    choices = declaration["object_move_rows"]
    assert choices["maximum_rows"] == 256 and choices["maximum_object_scopes"] == 64
    assert choices["source_choices"] == {
        "file": "--move-source-file <row> <project|originals|exact> <path>",
        "object": "--move-source-object <row> <Object Handle> <containing-file|original-media>",
        "sound-active": "--move-source-sound-active <row> <Sound Handle> <language>",
        "sound-language": "--move-source-sound-language <row> <Sound Handle> <language>",
        "sound-source": "--move-source-sound-source <row> <Sound Handle> <AudioFileSource Handle> <language>",
    }
    assert choices["destination_choices"]["object-directory"] == "--move-destination-object <row> <Object Handle> <containing-file|original-media> <new-basename>"
    code, started = gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), "draft-start", "ak.wwise.core.sourceControl.move"],
        env=_env(tmp_path, version=version), client_factory=lambda url: pytest.fail("offline start connected"))
    assert code == 0, started
    assert "draft-bind-object" in started["draft"]["next_action_binding"]["declaration"]["optional_object_file_binding"]["fixed_argv_prefix"]


@pytest.mark.parametrize("approved", [False, True])
def test_source_control_move_object_directory_still_requires_existing_io_authority(tmp_path, approved):
    def prepare(client):
        client.external = tmp_path / "outside-project.wav"
        client.external.write_bytes(b"external destination anchor")
        client.other["originalFilePath"] = str(client.external)
    def flags(client, handles):
        return ["--move-source-object", "row", handles[client.source["id"]], "original-media",
            "--move-destination-object", "row", handles[client.other["id"]], "original-media", "new.wav",
            *(["--io-root", str(tmp_path)] if approved else [])]
    client, _state, result, run = _sound_source_file_case(tmp_path, move=True, prepare=prepare, plan_flags=flags, declaration_error=not approved)
    if approved:
        code, result = run("execute", result["transaction_id"])
        assert code == 0, result
        assert [call[1] for call in client.calls if call[0].endswith("sourceControl.move")] == [{
            "files": [str(client.media)], "newFiles": [str(tmp_path / "new.wav")]}]
    else:
        assert not any(call[0].endswith("sourceControl.move") for call in client.calls)


def test_source_control_move_literal_source_can_use_bound_destination_directory(tmp_path):
    def flags(client, handles):
        return ["--move-source-file", "literal", "originals", "French/雨.wav",
            "--move-destination-object", "literal", handles[client.other["id"]], "original-media", "literal-new.wav"]
    client, _state, preview, run = _sound_source_file_case(tmp_path, move=True, plan_flags=flags)
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.move")] == [{
        "files": [str(client.media)], "newFiles": [str(client.other_media.parent / "literal-new.wav")]}]


@pytest.mark.parametrize("literal_form", ["labelled", "legacy", "mixed"])
def test_source_control_move_literal_rows_also_seal_destination_absence(tmp_path, literal_form):
    def flags(client, handles):
        if literal_form == "labelled":
            return ["--move-source-file", "row", "originals", "French/雨.wav",
                    "--move-destination-file", "row", "originals", "literal-new.wav"]
        result = ["--move", "originals", "French/雨.wav", "originals", "literal-new.wav"]
        if literal_form == "mixed":
            result.extend(("--move-source-object", "bound", handles[client.other["id"]], "original-media",
                "--move-destination-object", "bound", handles[client.source["id"]], "original-media", "another-new.wav"))
        return result
    client, _state, preview, run = _sound_source_file_case(tmp_path, move=True, plan_flags=flags)
    (client.originals / "literal-new.wav").write_bytes(b"arrived after Preview; preserve me")
    code, result = run("execute", preview["transaction_id"])
    assert code != 0, result
    assert not any(call[0].endswith("sourceControl.move") for call in client.calls)


def test_sound_unique_language_selection_is_rechecked_when_a_second_source_appears(tmp_path):
    client, _state, preview, run = _sound_source_file_case(tmp_path, mode="language")
    client.other["audioSource:language"] = dict(client.source["audioSource:language"])
    code, result = run("execute", preview["transaction_id"])
    assert code != 0, result
    assert not any(call[0].endswith("sourceControl.checkOut") for call in client.calls)


@pytest.mark.parametrize("change", ["parent", "language"])
def test_sound_explicit_source_relationship_is_rechecked_before_provider_dispatch(tmp_path, change):
    client, _state, preview, run = _sound_source_file_case(tmp_path, mode="source")
    if change == "parent":
        client.source["parent"] = {"id": client.other["id"]}
    else:
        client.source["audioSource:language"] = dict(client.other["audioSource:language"])
    code, result = run("execute", preview["transaction_id"])
    assert code != 0, result
    assert not any(call[0].endswith("sourceControl.checkOut") for call in client.calls)


def test_sound_active_media_accepts_name_only_reference_only_after_unique_scoped_source_readback(tmp_path):
    def prepare(client):
        client.sound["activeSource"].pop("id")
    client, state, preview, run = _sound_source_file_case(tmp_path, prepare=prepare)
    artifact = TransactionStore(state).load_preview(preview["transaction_id"]).artifact
    row = artifact["request"]["arguments"]["source_control_binding"]["objects"][0]
    assert row["active_source"] == {"name": "Localized recording"}
    assert row["source"]["id"] == client.source["id"]
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.checkOut")] == [{"files": [str(client.media)]}]


@pytest.mark.parametrize("invalid", ["present-malformed-id", "missing-name-match", "ambiguous-name"])
def test_sound_active_name_reference_never_hides_invalid_or_ambiguous_identity(tmp_path, invalid):
    def prepare(client):
        client.sound["activeSource"] = {"name": client.source["name"]}
        if invalid == "present-malformed-id":
            client.sound["activeSource"]["id"] = "broken"
        elif invalid == "missing-name-match":
            client.sound["activeSource"]["name"] = "No such source"
        else:
            client.other["name"] = client.source["name"]
            client.other["audioSource:language"] = dict(client.source["audioSource:language"])
    client, _state, _error, _run = _sound_source_file_case(tmp_path, prepare=prepare, declaration_error=True)
    assert not any(call[0].endswith("sourceControl.checkOut") for call in client.calls)



@pytest.mark.parametrize("version", ["2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("mode", ["active", "language", "source"])
def test_sound_source_name_only_language_is_certified_against_requested_guid(tmp_path, mode, version):
    def prepare(client):
        client.source["audioSource:language"] = {"name": "French"}
    client, state, preview, run = _sound_source_file_case(tmp_path, mode=mode, version=version,
        language="{44444444-4444-4444-4444-444444444444}", prepare=prepare)
    row = TransactionStore(state).load_preview(preview["transaction_id"]).artifact["request"]["arguments"]["source_control_binding"]["objects"][0]
    assert row["source"]["language"] == {"name": "French"}
    assert row["source"]["language_identity"] == {"id": "{44444444-4444-4444-4444-444444444444}",
        "name": "French", "type": "Language", "path": "\\Languages\\French"}
    code, result = run("execute", preview["transaction_id"])
    assert code == 0, result
    assert [call[1] for call in client.calls if call[0].endswith("sourceControl.checkOut")] == [{"files": [str(client.media)]}]



@pytest.mark.parametrize("invalid", ["missing", "ambiguous", "wrong-type", "wrong-name", "wrong-guid", "exact-read-drift", "malformed-present-id"])
def test_sound_source_name_only_language_rejects_unproved_identity_before_dispatch(tmp_path, invalid):
    def prepare(client):
        client.source["audioSource:language"] = {"name": "French"}
        candidate = dict(client.language_matches[0])
        client.language_matches = [candidate]
        if invalid == "missing":
            client.language_matches = []
        elif invalid == "ambiguous":
            client.language_matches.append({**candidate, "id": "{55555555-5555-5555-5555-555555555555}"})
        elif invalid == "wrong-type":
            candidate["type"] = "Sound"
        elif invalid == "wrong-name":
            candidate["name"] = "SFX"
        elif invalid == "wrong-guid":
            candidate["id"] = "{55555555-5555-5555-5555-555555555555}"
            client.rows[candidate["id"]] = dict(candidate)
        elif invalid == "exact-read-drift":
            client.rows[candidate["id"]]["path"] = "\\Languages\\Moved"
        else:
            client.source["audioSource:language"]["id"] = "broken"
    client, _state, _error, _run = _sound_source_file_case(tmp_path,
        language="{44444444-4444-4444-4444-444444444444}", prepare=prepare, declaration_error=True)
    assert not any(call[0].endswith("sourceControl.checkOut") for call in client.calls)


@pytest.mark.parametrize("change", ["identity", "ambiguity"])
def test_sound_source_resolved_language_is_rechecked_before_provider_dispatch(tmp_path, change):
    def prepare(client):
        client.source["audioSource:language"] = {"name": "French"}
    client, _state, preview, run = _sound_source_file_case(tmp_path,
        language="{44444444-4444-4444-4444-444444444444}", prepare=prepare)
    if change == "identity":
        client.rows["{44444444-4444-4444-4444-444444444444}"]["path"] = "\\Languages\\Moved"
    else:
        client.language_matches.append({**client.language_matches[0], "id": "{55555555-5555-5555-5555-555555555555}"})
    code, result = run("execute", preview["transaction_id"])
    assert code != 0, result
    assert not any(call[0].endswith("sourceControl.checkOut") for call in client.calls)


@pytest.mark.parametrize("drift", (False, True))
def test_bound_move_rechecks_resolved_name_only_language_guid_proof(tmp_path, drift):
    language = "{44444444-4444-4444-4444-444444444444}"
    def prepare(client):
        client.source["audioSource:language"] = {"name": "French"}
    client, state, preview, run = _sound_source_file_case(
        tmp_path, move=True, language=language, prepare=prepare)
    binding = TransactionStore(state).load_preview(preview["transaction_id"]).artifact[
        "request"]["arguments"]["source_control_binding"]
    assert binding["objects"][0]["source"]["language"] == {"name": "French"}
    assert binding["objects"][0]["source"]["language_identity"]["id"] == language
    assert binding["moves"][0]["source_path"] == str(client.media)
    if drift:
        client.rows[language]["path"] = r"\Languages\Moved"
    code, payload = run("execute", preview["transaction_id"])
    writes = [call[1] for call in client.calls if call[0].endswith("sourceControl.move")]
    if drift:
        assert code != 0 and writes == [], payload
    else:
        assert code == 0, payload
        assert writes == [{"files": [str(client.media)],
                           "newFiles": [str(client.other_media.parent / "moved-雨.wav")]}]
        code, verified = run("verify", preview["transaction_id"])
        assert code == 0 and verified["agent_result"]["verified"] is False, verified

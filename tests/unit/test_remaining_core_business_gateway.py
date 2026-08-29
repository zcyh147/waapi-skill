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
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
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
            "--role",
            "sound_handle",
            sound_handle,
            "--role",
            "source_handle",
            source_handle,
            "--value",
            "platform_name",
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

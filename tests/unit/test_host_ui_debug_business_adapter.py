from __future__ import annotations

from tests.support.gateway_config import set_gateway_config

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import BusinessContext, BusinessDeclarationError
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.host_ui_debug_business import (
    materialize_host_ui_debug_business_request,
    materialize_waapi_schema_read_args,
)
from wwise_waapi.host_ui_debug_business_contracts import (
    HOST_UI_DEBUG_BUSINESS_OPERATIONS,
    host_ui_debug_business_contract_data,
)
from wwise_waapi.operation_registry import BUSINESS_DECLARATION_INPUT_MODE, operation_input_mode
from wwise_waapi.operation_drafts import OperationDraftStore


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_host_ui_debug_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


LANES = {
    "ak.wwise.waapi.getSchema": (
        "2021.1",
        "2022.1",
        "2023.1",
        "2024.1",
        "2025.1",
    ),
    "ak.wwise.debug.generateToneWAV": ("2023.1", "2024.1", "2025.1"),
    "ak.wwise.ui.project.open": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.ui.project.close": ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"),
    "ak.wwise.ui.project.create": ("2023.1", "2024.1", "2025.1"),
}


def _session(version: str, plan: dict[str, object]) -> BusinessDeclarationSession:
    return BusinessDeclarationSession.create(
        BusinessContext.create(
            task_authority="da1-" + "1" * 40,
            project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            project_path="/fixtures/SampleProject.wproj",
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        )
    ).with_settings({"host_ui_debug_plan": plan})


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / f"config-{version}.json"
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
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_VERSION": version}


class _HostClient:
    def __init__(
        self,
        tmp_path: Path,
        version: str = "2025.1",
        *,
        is_command_line: bool = False,
    ) -> None:
        self.version = version
        self.is_command_line = is_command_line
        project_root = tmp_path / "project"
        project_root.mkdir(exist_ok=True)
        self.project_file = project_root / "Sample Project.wproj"
        self.project_file.write_text("fixture", encoding="utf-8")
        self.calls: list[tuple[str, object, object]] = []

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return {
                "displayName": "WwiseConsole" if self.is_command_line else "Wwise",
                "isCommandLine": self.is_command_line,
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {
                    "year": int(self.version.split(".", 1)[0]),
                    "major": 1,
                    "minor": 0,
                    "build": 1,
                    "displayName": f"v{self.version}.0.1",
                },
            }
        if uri == "ak.wwise.core.getProjectInfo":
            return {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "name": "Sample Project",
                "path": str(self.project_file),
            }
        if uri == "ak.wwise.core.object.get":
            return {
                "return": [
                    {
                        "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                        "name": "Sample Project",
                        "type": "Project",
                        "path": str(self.project_file),
                        "filePath": str(self.project_file),
                    }
                ]
            }
        if uri == "ak.wwise.waapi.getSchema":
            return {}
        raise AssertionError(f"unexpected call {uri} {args} {options}")


def test_host_ui_debug_inventory_retains_issue_90_and_adds_six_authoring_rows() -> None:
    rows = sorted(
        f"{version}|function|{operation}"
        for operation, versions in LANES.items()
        for version in versions
    )

    assert set(HOST_UI_DEBUG_BUSINESS_OPERATIONS) == set(LANES)
    assert len(rows) == 21
    historical = [row for row in rows if not (
        row.startswith(("2024.1|", "2025.1|")) and "|ak.wwise.ui.project." in row
    )]
    assert len(historical) == 15
    assert canonical_sha256(historical) == (
        "8d701d66442416c74f627e468842139fa8971b441b9b813be95cd9e7d3712ee0"
    )


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in LANES.items()
        for version in versions
    ],
)
def test_every_host_ui_debug_lane_has_one_closed_business_entry(
    operation: str,
    version: str,
) -> None:
    contract = host_ui_debug_business_contract_data(operation, version)

    if operation == "ak.wwise.waapi.getSchema":
        assert contract["input_mode"] == "bounded_business_read"
        assert contract["declaration"]["subcommand"] == "waapi-schema"
    else:
        assert operation_input_mode(operation, version) == BUSINESS_DECLARATION_INPUT_MODE
        assert contract["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
        assert contract["declaration"]["subcommand"] == "draft-declare-host-plan"
        assert contract["declaration"]["settings_field"] == "host_ui_debug_plan"
        assert business_adapter(operation).family == "host-ui-debug-business"
        assert business_adapter(operation).accepts_update_command(
            "draft-declare-host-plan"
        )
    assert contract["legacy_typed_call_public"] is False

    encoded = repr(contract)
    for native_leak in (
        "waveformChannelMask",
        "autoCheckOutToSourceControl",
        "onMigrationRequired",
        "bypassSave",
        "includeExamples",
        "args",
        "options",
    ):
        assert native_leak not in encoded


def test_schema_lookup_maps_one_exact_target_and_versioned_examples() -> None:
    old = materialize_waapi_schema_read_args(
        "2023.1",
        target_uri="ak.wwise.core.object.get",
        include_examples=None,
    )
    assert old == {"uri": "ak.wwise.core.object.get"}

    current = materialize_waapi_schema_read_args(
        "2025.1",
        target_uri="ak.wwise.core.object.get",
        include_examples=True,
    )
    assert current == {
        "uri": "ak.wwise.core.object.get",
        "includeExamples": True,
    }

    with pytest.raises(ValueError, match="unavailable before Wwise 2024.1"):
        materialize_waapi_schema_read_args(
            "2023.1",
            target_uri="ak.wwise.core.object.get",
            include_examples=True,
        )


def test_tone_plan_compiles_business_units_and_channel_indexes(tmp_path: Path) -> None:
    output = (tmp_path / "测试 tone.wav").resolve()
    request = materialize_host_ui_debug_business_request(
        "ak.wwise.debug.generateToneWAV",
        _session(
            "2025.1",
            {
                "output_file": str(output),
                "waveform": "white_noise",
                "frequency_hz": 880,
                "channel_layout": "3.0",
                "bit_depth": "float32",
                "sample_rate_hz": 96000,
                "attack_seconds": 0.1,
                "sustain_seconds": 1.5,
                "release_seconds": 0.2,
                "sustain_db": -6,
                "anonymous_channels": True,
                "waveform_channels": [0, 2],
                "markers": [
                    {"position_seconds": 0.5, "label": "Verse A"},
                    {"position_seconds": 1.0},
                ],
            },
        ),
    )

    assert request["arguments"] == {
        "api": "ak.wwise.debug.generateToneWAV",
        "args": {
            "path": str(output),
            "waveform": "whiteNoise",
            "frequency": 880,
            "channelConfig": "3.0",
            "bitDepth": "float32",
            "sampleRate": 96000,
            "attackTime": 0.1,
            "sustainTime": 1.5,
            "releaseTime": 0.2,
            "sustainLevel": -6,
            "setAnonymous": True,
            "waveformChannelMask": 5,
            "markers": [
                {"position": 0.5, "label": "Verse A"},
                {"position": 1.0},
            ],
        },
        "options": {},
        "io_root": str(output.parent),
    }


def test_tone_schema_owns_version_deltas_and_closed_choices() -> None:
    v23 = host_ui_debug_business_contract_data(
        "ak.wwise.debug.generateToneWAV", "2023.1"
    )["declaration"]
    v24 = host_ui_debug_business_contract_data(
        "ak.wwise.debug.generateToneWAV", "2024.1"
    )["declaration"]
    v25 = host_ui_debug_business_contract_data(
        "ak.wwise.debug.generateToneWAV", "2025.1"
    )["declaration"]

    assert "anonymous_channels" not in v23["public_fields"]
    assert "waveform_channels" not in v23["public_fields"]
    assert "markers" not in v23["public_fields"]
    assert {"anonymous_channels", "waveform_channels"} <= set(v24["public_fields"])
    assert "markers" not in v24["public_fields"]
    assert "markers" in v25["public_fields"]
    assert v25["input_forms"]["waveform"]["choices"] == [
        "silence",
        "sine",
        "triangle",
        "square",
        "white_noise",
    ]


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("action", ("open", "close"))
@pytest.mark.parametrize("discard", (None, False, True))
def test_project_switch_preserves_save_prompt_unless_discard_is_explicit(
    tmp_path: Path, version: str, action: str, discard: bool | None,
) -> None:
    plan: dict[str, object] = {}
    if action == "open":
        plan["project_file"] = str((tmp_path / "Target.wproj").resolve())
    if discard is not None:
        field = (
            "discard_unsaved_current_project" if action == "open"
            else "discard_unsaved_changes"
        )
        plan[field] = discard
    request = materialize_host_ui_debug_business_request(
        f"ak.wwise.ui.project.{action}", _session(version, plan),
    )
    assert request["arguments"]["args"]["bypassSave"] is (discard is True)


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_authoring_project_plans_compile_without_native_field_authorship(
    tmp_path: Path, version: str,
) -> None:
    project = (tmp_path / "New Project.wproj").resolve()
    old_open = materialize_host_ui_debug_business_request(
        "ak.wwise.ui.project.open",
        _session(
            "2021.1",
            {
                "project_file": str(project),
                "discard_unsaved_current_project": True,
                "upgrade_policy": "fail",
            },
        ),
    )
    assert old_open["arguments"]["args"] == {
        "path": str(project),
        "bypassSave": True,
        "onUpgrade": "fail",
    }

    current_open = materialize_host_ui_debug_business_request(
        "ak.wwise.ui.project.open",
        _session(
            version,
            {
                "project_file": str(project),
                "discard_unsaved_current_project": False,
                "upgrade_policy": "migrate",
                "migration_policy": "fail",
                "auto_checkout": False,
            },
        ),
    )
    assert current_open["arguments"]["args"] == {
        "path": str(project),
        "bypassSave": False,
        "onUpgrade": "migrate",
        "onMigrationRequired": "fail",
        "autoCheckOutToSourceControl": False,
    }

    closed = materialize_host_ui_debug_business_request(
        "ak.wwise.ui.project.close",
        _session(version, {"discard_unsaved_changes": True}),
    )
    assert closed["arguments"]["args"] == {"bypassSave": True}

    created = materialize_host_ui_debug_business_request(
        "ak.wwise.ui.project.create",
        _session(
            version,
            {
                "project_file": str(project),
                "languages": ["English(US)", "Japanese"],
                "platforms": [["Windows", "Windows_Studio"], ["Mac", "Mac"]],
            },
        ),
    )
    assert created["arguments"]["args"] == {
        "path": str(project),
        "languages": ["English(US)", "Japanese"],
        "platforms": [
            {"basePlatform": "Windows", "name": "Windows_Studio"},
            {"basePlatform": "Mac", "name": "Mac"},
        ],
    }


def test_invalid_version_field_and_native_name_fail_closed(tmp_path: Path) -> None:
    output = str((tmp_path / "tone.wav").resolve())

    with pytest.raises(BusinessDeclarationError) as version_error:
        materialize_host_ui_debug_business_request(
            "ak.wwise.debug.generateToneWAV",
            _session("2023.1", {"output_file": output, "markers": []}),
        )
    assert version_error.value.error_code == "INVALID_ARGUMENT"

    with pytest.raises(BusinessDeclarationError) as native_error:
        materialize_host_ui_debug_business_request(
            "ak.wwise.debug.generateToneWAV",
            _session(
                "2025.1",
                {"output_file": output, "waveformChannelMask": 5},
            ),
        )
    assert native_error.value.error_code == "INVALID_ARGUMENT"


def test_tone_channel_layout_constraints_fail_closed(tmp_path: Path) -> None:
    output = str((tmp_path / "tone.wav").resolve())

    with pytest.raises(BusinessDeclarationError) as channel_error:
        materialize_host_ui_debug_business_request(
            "ak.wwise.debug.generateToneWAV",
            _session(
                "2025.1",
                {
                    "output_file": output,
                    "channel_layout": "2.0",
                    "waveform_channels": [2],
                },
            ),
        )
    assert channel_error.value.error_code == "INVALID_ARGUMENT"
    assert channel_error.value.repair["field"] == "waveform_channels"

    with pytest.raises(BusinessDeclarationError) as ambisonics_error:
        materialize_host_ui_debug_business_request(
            "ak.wwise.debug.generateToneWAV",
            _session(
                "2025.1",
                {
                    "output_file": output,
                    "channel_layout": "Ambisonics 1st order",
                    "waveform": "sine",
                },
            ),
        )
    assert ambisonics_error.value.error_code == "INVALID_ARGUMENT"
    assert ambisonics_error.value.repair["field"] == "waveform"


@pytest.mark.parametrize(
    ("version", "operation"),
    [
        (version, operation)
        for operation, versions in LANES.items()
        for version in versions
    ],
)
def test_request_schema_exposes_only_the_closed_host_route(
    tmp_path: Path,
    version: str,
    operation: str,
) -> None:
    code, schema = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, schema
    assert schema["input_shape"] == "business_declaration"
    assert schema["native_request_fields_disclosed"] is False
    assert schema["business_adapter"]["contract"] == (
        "waapi-skill.host-ui-debug-business/v1"
    )
    assert schema["continuation"]["subcommand"] == (
        "waapi-schema"
        if operation == "ak.wwise.waapi.getSchema"
        else "draft-start"
    )
    assert "fields" not in schema
    assert "typed_request_contract" not in schema


def test_waapi_schema_is_one_bounded_direct_business_read(tmp_path: Path) -> None:
    client = _HostClient(tmp_path, "2025.1")
    code, payload = gateway.execute_gateway(
        [
            "waapi-schema",
            "ak.wwise.core.object.get",
            "--include-examples",
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 0, payload
    assert payload["status"] == "ok"
    assert payload["agent_result"] == {}
    assert client.calls[-1] == (
        "ak.wwise.waapi.getSchema",
        {
            "uri": "ak.wwise.core.object.get",
            "includeExamples": True,
        },
        {},
    )


def test_host_plan_draft_records_only_business_fields(tmp_path: Path) -> None:
    operation = "ak.wwise.debug.generateToneWAV"
    state_dir = tmp_path / "state"
    env = _env(tmp_path, "2025.1")
    client = _HostClient(tmp_path, "2025.1", is_command_line=True)
    output = (tmp_path / "tone.wav").resolve()
    code, started = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=set_gateway_config(env, wwise_version="2025.1"),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    assert started["draft"]["next_action_binding"]["required_next_phase"] == (
        "declare_complete_host_plan"
    )

    code, declared = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-declare-host-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--value",
            "output_file",
            str(output),
            "--value",
            "waveform",
            "sine",
            "--value",
            "frequency_hz",
            "440",
            "--value",
            "channel_layout",
            "3.0",
            "--item",
            "waveform_channels",
            "0",
            "--item",
            "waveform_channels",
            "2",
            "--marker",
            "0.5",
            "Intro",
        ],
        env=set_gateway_config(env, wwise_version="2025.1"),
        client_factory=lambda _url: client,
    )

    assert code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_host_plan"
    )
    record = OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    session = BusinessDeclarationSession.from_dict(
        record.composition["business_session"]
    )
    assert session.settings["host_ui_debug_plan"] == {
        "output_file": str(output),
        "waveform": "sine",
        "frequency_hz": 440,
        "channel_layout": "3.0",
        "waveform_channels": [0, 2],
        "markers": [{"position_seconds": 0.5, "label": "Intro"}],
    }
    encoded = json.dumps(declared)
    assert "waveformChannelMask" not in encoded

    check_client = _HostClient(tmp_path, "2025.1", is_command_line=True)
    check_code, checked = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-check",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "2",
        ],
        env=set_gateway_config(env, wwise_version="2025.1"),
        client_factory=lambda _url: check_client,
    )
    assert check_code == 0, json.dumps(checked, indent=2)
    assert checked["next_command"]["gateway_argv"][0] == "preview-from-draft"

    preview_client = _HostClient(tmp_path, "2025.1", is_command_line=True)
    preview_code, previewed = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "preview-from-draft",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            str(checked["draft"]["revision"]),
        ],
        env=set_gateway_config(env, wwise_version="2025.1"),
        client_factory=lambda _url: preview_client,
    )
    assert preview_code == 0, previewed
    assert previewed["state"] == "awaiting_confirmation"
    request = previewed["agent_result"]["request"]
    assert request["arguments"]["api"] == "ak.wwise.debug.generateToneWAV"
    assert request["arguments"]["args"]["waveformChannelMask"] == 5
    assert request["arguments"]["args"]["markers"] == [
        {"position": 0.5, "label": "Intro"}
    ]


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_authoring_project_plan_rejects_console_before_project_probe(
    tmp_path: Path, version: str,
) -> None:
    operation = "ak.wwise.ui.project.open"
    state_dir = tmp_path / "state"
    env = _env(tmp_path, version)
    code, started = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=set_gateway_config(env, wwise_version=version),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    client = _HostClient(tmp_path, version, is_command_line=True)

    code, rejected = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-declare-host-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--value",
            "project_file",
            str(client.project_file),
        ],
        env=set_gateway_config(env, wwise_version=version),
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert rejected["status"] == "authoring_host_required", json.dumps(rejected)
    assert [call[0] for call in client.calls] == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize("version", ("2023.1", "2024.1", "2025.1"))
def test_authoring_project_draft_rejects_console_during_check(tmp_path: Path, version: str) -> None:
    operation = "ak.wwise.ui.project.open"
    state_dir = tmp_path / "state"
    env = _env(tmp_path, version)
    authoring = _HostClient(tmp_path, version, is_command_line=False)
    code, started = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-start",
            operation,
        ],
        env=set_gateway_config(env, wwise_version=version),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    code, declared = gateway.execute_gateway(
        [

            "--state-dir",
            str(state_dir),
            "draft-declare-host-plan",
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--value",
            "project_file",
            str(authoring.project_file),
        ],
        env=set_gateway_config(env, wwise_version=version),
        client_factory=lambda _url: authoring,
    )
    assert code == 0, declared

    console = _HostClient(tmp_path, version, is_command_line=True)
    code, rejected = gateway.execute_gateway(
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
        env=set_gateway_config(env, wwise_version=version),
        client_factory=lambda _url: console,
    )

    assert code == 2
    assert rejected["status"] == "authoring_host_required", json.dumps(rejected)
    assert [call[0] for call in console.calls] == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize(
    "argv",
    (
        [

            "typed-call",
            "ak.wwise.debug.generateToneWAV",
            "--schema-digest",
            "stale",
        ],
        [

            "typed-call",
            "ak.wwise.waapi.getSchema",
            "--schema-digest",
            "stale",
        ],
    ),
)
def test_host_ui_debug_legacy_typed_ingress_is_blocked_before_connection(
    tmp_path: Path,
    argv: list[str],
) -> None:
    code, rejected = gateway.execute_gateway(
        argv,
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"legacy ingress connected to {url}"),
    )

    assert code == 2
    assert "business" in rejected["message"].casefold()


class _ToneFileClient(_HostClient):
    """Owned fake side effect; its file is not a Gateway effect verifier."""
    def __init__(self, *args, write_output=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.write_output = write_output

    def call(self, uri, args=None, options=None):
        if uri == 'ak.wwise.debug.generateToneWAV':
            self.calls.append((uri, args, options))
            if self.write_output:
                import wave
                with wave.open(args['path'], 'wb') as output:
                    output.setnchannels(2)
                    output.setsampwidth(2)
                    output.setframerate(8000)
                    output.writeframes(b'\x00' * 16)
            return {}
        return super().call(uri, args, options)


def _tone_collection_preview(tmp_path, version, fields, *, policy='ask_before_changes',
                             is_command_line=True, write_output=True, reject_declaration=False):
    state = ['--state-dir', str(tmp_path / 'state')]
    env = set_gateway_config(_env(tmp_path, version), project_modification_policy=policy)
    output = tmp_path / 'io' / 'tone.wav'
    output.parent.mkdir(exist_ok=True)
    client = _ToneFileClient(tmp_path, version, is_command_line=is_command_line, write_output=write_output)
    code, schema = gateway.execute_gateway(['request-schema', 'ak.wwise.debug.generateToneWAV'],
        env=env, client_factory=lambda _: pytest.fail('schema is offline'))
    assert code == 0, schema
    code, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']],
        env=env, client_factory=lambda _: pytest.fail('start is offline'))
    assert code == 0, started
    declaration = started['draft']['next_action_binding']['declaration']
    code, declared = gateway.execute_gateway([*state, 'draft-declare-host-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
        '--value', 'output_file', str(output), '--value', 'waveform', 'white_noise',
        '--value', 'channel_layout', '2.0', '--value', 'sample_rate_hz', '8000',
        '--value', 'bit_depth', 'int16', '--value', 'attack_seconds', '0',
        '--value', 'sustain_seconds', '0.0005', '--value', 'release_seconds', '0',
        *fields], env=env, client_factory=lambda _: client)
    if reject_declaration:
        assert code != 0, declared
        assert not output.exists()
        assert 'ak.wwise.debug.generateToneWAV' not in [call[0] for call in client.calls]
        return declared
    assert code == 0, declared
    code, checked = gateway.execute_gateway([*state, 'draft-check', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(declared['draft']['revision'])],
        env=env, client_factory=lambda _: client)
    assert code == 0, checked
    code, preview = gateway.execute_gateway([*state, 'preview-from-draft', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(checked['draft']['revision'])],
        env=env, client_factory=lambda _: client)
    if policy == 'read_only':
        assert code != 0, preview
        assert not output.exists()
    else:
        assert code == 0, preview
    return env, state, client, output, schema, declaration, preview


def _finish_tone_collection(env, state, client, preview):
    tx = preview['transaction_id']
    if preview['state'] == 'awaiting_confirmation':
        _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
        code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
            '--confirmation-token', shown['confirmation']['token']], env=env)
        assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    code, verified = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    assert code == 0, verified
    assert verified['state'] == 'result_schema_checked'
    assert verified['verified'] is False
    assert verified['agent_result']['verified'] is False
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 1
    return verified


def test_tone_explicit_empty_choices_survive_public_draft_preview_execute_verify(tmp_path):
    env, state, client, output, schema, declaration, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'], is_command_line=False)
    for field in ('waveform_channels', 'markers'):
        expected = {'flag': '--empty', 'arguments': [field], 'repeatable': False}
        assert schema['business_adapter']['declaration']['input_forms'][field]['empty_form'] == expected
        assert declaration['input_forms'][field]['empty_form'] == expected
    request = preview['agent_result']['request']
    assert request['arguments']['args'] == {'path': str(output), 'waveform': 'whiteNoise',
        'channelConfig': '2.0', 'sampleRate': 8000, 'bitDepth': 'int16',
        'attackTime': 0, 'sustainTime': 0.0005, 'releaseTime': 0, 'waveformChannelMask': 0, 'markers': []}
    assert not output.exists()
    verified = _finish_tone_collection(env, state, client, preview)
    assert verified['agent_result']['request'] == request
    import wave
    with wave.open(str(output), 'rb') as artifact:
        assert (artifact.getnchannels(), artifact.getsampwidth(), artifact.getframerate(), artifact.getnframes()) == (2, 2, 8000, 4)
        assert artifact.readframes(4) == b'\x00' * 16
    # This independent fake file observation does not close the product's
    # missing artifact/effect oracle; the Gateway truthfully remains weak.
    assert verified['verification']['business_state_verified'] is False


@pytest.mark.parametrize('is_command_line', [False, True], ids=['authoring', 'console'])
@pytest.mark.parametrize('version,fields,expected', [
    ('2023.1', [], {}),
    ('2024.1', ['--empty', 'waveform_channels'], {'waveformChannelMask': 0}),
    ('2025.1', [], {}),
    ('2025.1', ['--empty', 'waveform_channels', '--empty', 'markers'], {'waveformChannelMask': 0, 'markers': []}),
    ('2025.1', ['--item', 'waveform_channels', '0', '--item', 'waveform_channels', '1', '--marker', '0.25', '入口\\cue'],
        {'waveformChannelMask': 3, 'markers': [{'position': 0.25, 'label': '入口\\cue'}]}),
])
def test_tone_collection_omission_empty_and_populated_states_stay_distinct(tmp_path, version, fields, expected, is_command_line):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, version, fields,
        is_command_line=is_command_line)
    native = preview['agent_result']['request']['arguments']['args']
    assert native == {'path': str(output), 'waveform': 'whiteNoise', 'channelConfig': '2.0',
        'sampleRate': 8000, 'bitDepth': 'int16', 'attackTime': 0, 'sustainTime': 0.0005, 'releaseTime': 0, **expected}
    verified = _finish_tone_collection(env, state, client, preview)
    dispatched = [call[1] for call in client.calls if call[0] == 'ak.wwise.debug.generateToneWAV']
    assert dispatched == [native]
    assert verified['agent_result']['request'] == preview['agent_result']['request']
    assert output.is_file()


@pytest.mark.parametrize('version,fields', [
    ('2023.1', ['--empty', 'waveform_channels']),
    ('2023.1', ['--empty', 'markers']),
    ('2024.1', ['--empty', 'markers']),
    ('2025.1', ['--empty', 'waveform_channels', '--item', 'waveform_channels', '0']),
    ('2025.1', ['--item', 'waveform_channels', '0', '--empty', 'waveform_channels']),
    ('2025.1', ['--empty', 'markers', '--marker', '0.5']),
    ('2025.1', ['--marker', '0.5', '--empty', 'markers']),
    ('2025.1', ['--empty', 'markers', '--empty', 'markers']),
    ('2025.1', ['--empty', 'waveform_channels', '--empty', 'waveform_channels']),
    ('2025.1', ['--item', 'waveform_channels', '0', '--item', 'waveform_channels', '0']),
    ('2025.1', ['--empty', 'waveform']),
    ('2025.1', ['--value', 'waveformChannelMask', '0']),
    ('2025.1', ['--value', 'markers', '[]']),
    ('2025.1', ['--empty', 'languages']),
])
def test_tone_empty_choices_reject_conflicts_duplicates_native_fields_and_wrong_versions_before_mutation(tmp_path, version, fields):
    rejected = _tone_collection_preview(tmp_path, version, fields, reject_declaration=True)
    assert rejected['ok'] is False


@pytest.mark.parametrize('policy', ['read_only', 'ask_before_changes', 'allow_changes'])
def test_tone_empty_choices_keep_all_three_modification_policies(tmp_path, policy):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'], policy=policy)
    if policy == 'read_only':
        assert not output.exists()
        assert 'ak.wwise.debug.generateToneWAV' not in [call[0] for call in client.calls]
        assert 'read_only' in preview['message']
        return
    assert (preview['state'] == 'awaiting_confirmation') is (policy == 'ask_before_changes')
    _finish_tone_collection(env, state, client, preview)
    code, repeated = gateway.execute_gateway([*state, 'execute', preview['transaction_id']],
        env=env, client_factory=lambda _: client)
    assert code != 0, repeated
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 1


def test_tone_current_verifier_discloses_missing_artifact_effect_gap(tmp_path):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'], write_output=False)
    verified = _finish_tone_collection(env, state, client, preview)
    assert not output.exists()
    assert verified['verification']['business_state_verified'] is False
    assert verified['verification_strength'] == 'complete_reflected_schema'
    # Pending #193 artifact verifier must replace this weak boundary with a
    # meaningful missing-effect failure. This control grants no effect credit.

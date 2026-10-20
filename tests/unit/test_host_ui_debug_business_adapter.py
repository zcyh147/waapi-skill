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
    """Synthetic owned effect for the public oracle; no native Wwise evidence."""
    def __init__(self, *args, write_output=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.write_output = write_output
        self.artifact_bytes = None
        self.after_write = None
        self.session_label = None

    def call(self, uri, args=None, options=None):
        if uri == 'ak.wwise.debug.generateToneWAV':
            self.calls.append((uri, args, options))
            if self.write_output and self.artifact_bytes is not None:
                Path(args['path']).write_bytes(self.artifact_bytes)
            elif self.write_output:
                import wave
                with wave.open(args['path'], 'wb') as output:
                    output.setnchannels(2)
                    output.setsampwidth(2)
                    output.setframerate(8000)
                    output.writeframes(b'\x00' * 16)
            if self.after_write is not None:
                self.after_write(Path(args['path']))
            return {}
        observed = super().call(uri, args, options)
        if uri == 'ak.wwise.core.getInfo' and self.session_label is not None:
            observed['sessionId'] = self.session_label
        return observed


def _tone_collection_preview(tmp_path, version, fields, *, policy='ask_before_changes',
                             is_command_line=True, write_output=True, reject_declaration=False, values=None, existing_bytes=None, declaration_only=False, reject_preparation=False, client_setup=None):
    state = ['--state-dir', str(tmp_path / 'state')]
    env = set_gateway_config(_env(tmp_path, version), project_modification_policy=policy)
    output = tmp_path / 'io' / 'tone.wav'
    output.parent.mkdir(exist_ok=True)
    if existing_bytes is not None:
        output.write_bytes(existing_bytes)
    business_values = {'waveform': 'white_noise', 'channel_layout': '2.0', 'sample_rate_hz': '8000',
        'bit_depth': 'int16', 'attack_seconds': '0', 'sustain_seconds': '0.0005', 'release_seconds': '0'}
    business_values.update(values or {})
    value_argv = [token for field, value in business_values.items() if value is not None for token in (('--toggle', field, 'enable' if value == 'true' else 'disable') if field == 'anonymous_channels' else ('--value', field, value))]
    client = _ToneFileClient(tmp_path, version, is_command_line=is_command_line, write_output=write_output)
    if client_setup is not None:
        client_setup(client)
    code, schema = gateway.execute_gateway(['request-schema', 'ak.wwise.debug.generateToneWAV'],
        env=env, client_factory=lambda _: pytest.fail('schema is offline'))
    assert code == 0, schema
    code, started = gateway.execute_gateway([*state, *schema['continuation']['gateway_argv']],
        env=env, client_factory=lambda _: pytest.fail('start is offline'))
    assert code == 0, started
    declaration = started['draft']['next_action_binding']['declaration']
    code, declared = gateway.execute_gateway([*state, 'draft-declare-host-plan', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(started['draft']['revision']),
        '--value', 'output_file', str(output), *value_argv,
        *fields], env=env, client_factory=lambda _: client)
    if declaration_only:
        return code, declared, client
    if reject_declaration:
        assert code != 0, declared
        assert not output.exists()
        assert 'ak.wwise.debug.generateToneWAV' not in [call[0] for call in client.calls]
        return declared
    assert code == 0, declared
    code, checked = gateway.execute_gateway([*state, 'draft-check', started['draft']['draft_id'],
        '--task-authority', started['task_authority'], '--expected-revision', str(declared['draft']['revision'])],
        env=env, client_factory=lambda _: client)
    if reject_preparation:
        assert code != 0, checked
        return checked, client
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


def _finish_tone_collection(env, state, client, preview, *, expect_failure=False, expected_state='result_schema_checked', return_verify_outcome=False):
    tx = preview['transaction_id']
    if preview['state'] == 'awaiting_confirmation':
        _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
        code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
            '--confirmation-token', shown['confirmation']['token']], env=env)
        assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    code, verified = gateway.execute_gateway([*state, 'verify', tx], env=env, client_factory=lambda _: client)
    if return_verify_outcome:
        return code, verified
    if expect_failure:
        assert code != 0, verified
        assert verified['state'] == 'verification_failed'
        assert verified['verified'] is False
        return verified
    assert code == 0, verified
    assert verified['state'] == expected_state
    assert verified['verified'] is (expected_state == 'verified')
    assert verified['agent_result']['verified'] is (expected_state == 'verified')
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
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['agent_result']['request'] == request
    import wave
    with wave.open(str(output), 'rb') as artifact:
        assert (artifact.getnchannels(), artifact.getsampwidth(), artifact.getframerate(), artifact.getnframes()) == (2, 2, 8000, 4)
        assert artifact.readframes(4) == b'\x00' * 16
    # Synthetic output checks the public artifact oracle, not native Wwise behavior.
    assert verified['verification']['business_state_verified'] is True


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
    if expected.get('markers'):
        client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks([(7, 2000, '入口\\cue'.encode('utf-8'))]))
    verified = _finish_tone_collection(env, state, client, preview,
        expected_state='verified' if expected.get('waveformChannelMask') == 0 else 'result_schema_checked')
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
    _finish_tone_collection(env, state, client, preview, expected_state='verified')
    code, repeated = gateway.execute_gateway([*state, 'execute', preview['transaction_id']],
        env=env, client_factory=lambda _: client)
    assert code != 0, repeated
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 1


def test_tone_verifier_rejects_missing_artifact_after_one_native_dispatch(tmp_path):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'], write_output=False)
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=True)
    assert not output.exists()
    assert verified['verification']['business_state_verified'] is False
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 1
    assert 'artifact' in str(verified['verification']).lower()


def test_tone_verifier_rejects_malformed_artifact_despite_success_reply(tmp_path):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'])
    client.artifact_bytes = b'not a wave artifact'
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=True)
    assert output.read_bytes() == b'not a wave artifact'
    assert verified['verification']['business_state_verified'] is False



def _tone_wav_bytes(*, floating=False, samples=None, rate=8000, channels=2, extra=b'', fmt_override=None):
    import struct
    # Four known audio frames. This fixture is independent of the Gateway compiler.
    if samples is None:
        samples = [0.0 if floating else 0] * 8
    audio = struct.pack('<' + ('f' if floating else 'h') * len(samples), *samples)
    width = 4 if floating else 2
    fmt = fmt_override if fmt_override is not None else struct.pack('<HHIIHH',
        3 if floating else 1, channels, rate, rate * channels * width, channels * width, width * 8)
    body = b'WAVEfmt ' + struct.pack('<I', len(fmt)) + fmt + (b'\0' if len(fmt) % 2 else b'')
    body += b'data' + struct.pack('<I', len(audio)) + audio + extra
    return b'RIFF' + struct.pack('<I', len(body)) + body


@pytest.mark.parametrize('floating', [False, True], ids=['pcm16', 'float32'])
def test_tone_verifier_checks_all_silent_samples_and_exact_format(tmp_path, floating):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'],
        values={'bit_depth': 'float32' if floating else 'int16'})
    client.artifact_bytes = _tone_wav_bytes(floating=floating)
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['verification']['business_state_verified'] is True
    assert verified['stdout_projection']['stdout_budget_bytes'] == 24576
    assert verified['agent_result']['request'] == preview['agent_result']['request']


@pytest.mark.parametrize('defect', ['rate', 'frames', 'last_off_channel', 'format'])
def test_tone_verifier_rejects_wrong_requested_artifact_state(tmp_path, defect):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'])
    kwargs = {'rate': 16000} if defect == 'rate' else {'samples': [0] * 10} if defect == 'frames' else (
        {'samples': [0] * 7 + [1]} if defect == 'last_off_channel' else {'floating': True})
    client.artifact_bytes = _tone_wav_bytes(**kwargs)
    _finish_tone_collection(env, state, client, preview, expect_failure=True)



def _riff_chunk(kind, payload):
    import struct
    return kind + struct.pack('<I', len(payload)) + payload + (b'\0' if len(payload) % 2 else b'')


@pytest.mark.parametrize('metadata', ['cue', 'orphan-label'])
def test_tone_explicit_empty_markers_rejects_unrequested_cues_and_labels(tmp_path, metadata):
    import struct
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'])
    if metadata == 'cue':
        extra = _riff_chunk(b'cue ', struct.pack('<I', 1) + struct.pack('<II4sIII', 7, 0, b'data', 0, 0, 0))
    else:
        extra = _riff_chunk(b'LIST', b'adtl' + _riff_chunk(b'labl', struct.pack('<I', 7) + b'unrequested\0'))
    client.artifact_bytes = _tone_wav_bytes(extra=extra)
    _finish_tone_collection(env, state, client, preview, expect_failure=True)



def test_tone_prewrite_rejects_replaced_isolated_root_before_dispatch(tmp_path):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'])
    output.parent.rename(tmp_path / 'old-io')
    output.parent.mkdir()
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, stopped = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, stopped
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 0



@pytest.mark.parametrize('overwrite', [False, True], ids=['unchanged-valid', 'rewritten-identical'])
def test_tone_existing_valid_output_verifies_state_without_claiming_content_change(tmp_path, overwrite):
    expected_bytes = _tone_wav_bytes()
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'], existing_bytes=expected_bytes,
        write_output=overwrite)
    client.artifact_bytes = expected_bytes
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    readback = verified['verification']['readbacks'][0]
    assert readback['created'] is False
    assert readback['changed'] is False
    assert output.read_bytes() == expected_bytes


@pytest.mark.parametrize('change', ['appeared', 'replaced', 'symlink'])
def test_tone_prewrite_rejects_changed_output_before_mutation(tmp_path, change):
    existing = _tone_wav_bytes() if change == 'replaced' else None
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'], existing_bytes=existing)
    if change == 'symlink':
        target = tmp_path / 'outside.wav'
        target.write_bytes(_tone_wav_bytes())
        output.symlink_to(target)
    else:
        output.write_bytes(b'changed output')
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    _, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env)
    assert confirmed['ok'] is True
    code, stopped = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code != 0, stopped
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 0


@pytest.mark.parametrize('effect', ['directory', 'symlink', 'unchanged-wrong'])
def test_tone_artifact_verification_rejects_wrong_existing_or_nonregular_effect(tmp_path, effect):
    existing = b'old malformed artifact' if effect == 'unchanged-wrong' else None
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'], existing_bytes=existing, write_output=False)
    if effect == 'directory':
        client.after_write = lambda path: path.mkdir()
    elif effect == 'symlink':
        target = tmp_path / 'unowned.wav'
        target.write_bytes(_tone_wav_bytes())
        client.after_write = lambda path: path.symlink_to(target)
    _finish_tone_collection(env, state, client, preview, expect_failure=True)


@pytest.mark.parametrize('sample', [float('nan'), float('inf'), -float('inf')])
def test_tone_float_verification_rejects_nonfinite_samples_anywhere(tmp_path, sample):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'], values={'bit_depth': 'float32'})
    client.artifact_bytes = _tone_wav_bytes(floating=True, samples=[0.0] * 7 + [sample])
    _finish_tone_collection(env, state, client, preview, expect_failure=True)


@pytest.mark.parametrize('defect', ['truncated', 'chunk-extent', 'duplicate-data', 'byte-rate', 'block-align', 'unknown-subtype', 'wrong-speakers', 'short-list'])
def test_tone_parser_rejects_bounded_malformed_or_wrong_format_artifacts(tmp_path, defect):
    import struct
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'])
    if defect == 'truncated':
        blob = _tone_wav_bytes()[:-1]
    elif defect == 'chunk-extent':
        blob = bytearray(_tone_wav_bytes())
        blob[40:44] = struct.pack('<I', 0xffffffff)
    elif defect == 'duplicate-data':
        blob = _tone_wav_bytes(extra=_riff_chunk(b'data', b''))
    elif defect == 'short-list':
        blob = _tone_wav_bytes(extra=_riff_chunk(b'LIST', b'x'))
    elif defect in {'byte-rate', 'block-align'}:
        fmt = struct.pack('<HHIIHH', 1, 2, 8000, 42 if defect == 'byte-rate' else 32000,
            2 if defect == 'block-align' else 4, 16)
        blob = _tone_wav_bytes(fmt_override=fmt)
    else:
        subtype = bytes.fromhex('0100000000001000800000aa00389b71') if defect == 'wrong-speakers' else b'\0' * 16
        fmt = struct.pack('<HHIIHHHHI', 65534, 2, 8000, 32000, 4, 16, 22, 16, 4) + subtype
        blob = _tone_wav_bytes(fmt_override=fmt)
    client.artifact_bytes = bytes(blob)
    _finish_tone_collection(env, state, client, preview, expect_failure=True)


@pytest.mark.parametrize('floating', [False, True])
def test_tone_extensible_exact_pcm_float_subtype_and_empty_cue_are_verified(tmp_path, floating):
    import struct
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--empty', 'markers'],
        values={'bit_depth': 'float32' if floating else 'int16'})
    subtype = bytes.fromhex(('03000000' if floating else '01000000') + '00001000800000aa00389b71')
    bits, align = (32, 8) if floating else (16, 4)
    fmt = struct.pack('<HHIIHHHHI', 65534, 2, 8000, 8000 * align, align, bits, 22, bits, 3) + subtype
    extra = _riff_chunk(b'cue ', struct.pack('<I', 0)) + _riff_chunk(b'JUNK', b'abc')
    client.artifact_bytes = _tone_wav_bytes(floating=floating, fmt_override=fmt, extra=extra)
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['verification']['readbacks'][0]['wav']['markers']['cue_count'] == 0



def test_tone_output_estimate_rejects_resource_overflow_before_dispatch(tmp_path):
    rejected, client = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'sustain_seconds': '1000000'}, reject_preparation=True)
    assert '512 MiB' in str(rejected)
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 0


def test_tone_large_marker_request_survives_exact_terminal_delivery(tmp_path, monkeypatch, capsys):
    fields = [token for number in range(4) for token in ('--marker', str(number), 'x' * 8192)]
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', fields)
    client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks([(index, index * 8000, b'x' * 8192) for index in range(4)]))
    verified = _finish_tone_collection(env, state, client, preview)
    rendered = gateway.gateway_stdout_json_encoder(verified).encode(gateway.gateway_stdout_payload(verified)) + '\n'
    with monkeypatch.context() as emitting:
        emitting.setattr(gateway, 'execute_gateway', lambda argv: (0, verified))
        assert gateway.main(['verify', preview['transaction_id']]) == 0
    assert capsys.readouterr().out == rendered
    decoded = json.loads(rendered)
    assert decoded['agent_result'] == verified['agent_result']
    assert decoded['agent_result']['request'] == preview['agent_result']['request']
    assert list(decoded)[-1] == 'agent_result'
    assert 32768 < len(rendered.encode('utf-8')) <= 286720
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 1




@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
def test_tone_pinned_omitted_defaults_bind_to_independently_generated_audio(tmp_path, version):
    values = {field: None for field in ('waveform', 'channel_layout', 'sample_rate_hz', 'bit_depth',
        'attack_seconds', 'sustain_seconds', 'release_seconds')}
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, version, [], values=values)
    assert preview['agent_result']['request']['arguments']['args'] == {'path': str(output)}
    client.artifact_bytes = _tone_wav_bytes(channels=1, rate=48000, samples=[0] * 48000)
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['verification']['readbacks'][0]['wav']['frames'] == 48000


@pytest.mark.parametrize('layout,channels,mask', [('0.1', 1, 8), ('1.0', 1, 4), ('2.1', 3, 11), ('3.0', 3, 7)])
def test_tone_layout_verification_uses_exact_speaker_positions_not_just_channel_count(tmp_path, layout, channels, mask):
    import struct
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'], values={'channel_layout': layout})
    fmt = struct.pack('<HHIIHHHHI', 65534, channels, 8000, 16000 * channels, channels * 2, 16, 22, 16, mask)
    fmt += bytes.fromhex('0100000000001000800000aa00389b71')
    client.artifact_bytes = _tone_wav_bytes(channels=channels, samples=[0] * channels * 4, fmt_override=fmt)
    _finish_tone_collection(env, state, client, preview, expected_state='verified')


@pytest.mark.parametrize('negative', [False, True])
def test_tone_partial_mask_scans_silent_channel_while_active_waveform_stays_unproven(tmp_path, negative):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--item', 'waveform_channels', '0'])
    client.artifact_bytes = _tone_wav_bytes(samples=[1, 0, -1, 0, 1, 0, -1, 1 if negative else 0])
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=negative)
    if not negative:
        assert verified['verification_strength'] == 'partial_tone_artifact'
        assert 'active waveform' in str(verified['verification']['readbacks'][0]['unresolved'])


@pytest.mark.parametrize('branch', ['fractional-rate', 'fractional-segment', 'anonymous', 'ambisonic'])
def test_tone_unresolved_native_interpretations_remain_explicit_without_fabricated_success(tmp_path, branch):
    values, wav = {}, {}
    if branch == 'fractional-rate':
        values['sample_rate_hz'] = '8000.5'
    elif branch == 'fractional-segment':
        values['sustain_seconds'] = '0.00051'
    elif branch == 'anonymous':
        values['anonymous_channels'] = 'true'
    else:
        values.update(channel_layout='Ambisonics 1st order', waveform='silence')
        wav = {'channels': 4, 'samples': [0] * 16}
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'], values=values)
    client.artifact_bytes = _tone_wav_bytes(**wav)
    verified = _finish_tone_collection(env, state, client, preview)
    assert verified['verification_strength'] == 'partial_tone_artifact'
    assert verified['verification']['readbacks'][0]['unresolved']


def test_tone_zero_duration_is_a_valid_empty_audio_state(tmp_path):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'], values={'sustain_seconds': '0'})
    client.artifact_bytes = _tone_wav_bytes(samples=[])
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['verification']['readbacks'][0]['wav']['frames'] == 0



def test_tone_verification_digest_comes_from_one_confined_opened_artifact(tmp_path, monkeypatch):
    import hashlib
    import os
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'])
    literal = _tone_wav_bytes()
    client.artifact_bytes = literal
    real_open, target_opens = os.open, []
    def recording_open(path, *args, **kwargs):
        if Path(path) == output:
            target_opens.append(str(path))
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(os, 'open', recording_open)
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert target_opens == [str(output)]
    observed = verified['verification']['readbacks'][0]
    assert observed['artifact']['file']['sha256'] == hashlib.sha256(literal).hexdigest()
    assert observed['wav']['nonzero_samples_by_channel'] == [0, 0]


def test_tone_verification_rejects_owned_root_replacement_during_native_effect(tmp_path):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'])
    def replace_root(path):
        path.parent.rename(tmp_path / 'executed-old-root')
        path.parent.mkdir()
        path.write_bytes(_tone_wav_bytes())
    client.after_write = replace_root
    _finish_tone_collection(env, state, client, preview, expect_failure=True)



def test_tone_removed_output_root_is_a_recorded_verification_failure(tmp_path):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'])
    client.after_write = lambda path: path.parent.rename(tmp_path / 'removed-owned-root')
    _finish_tone_collection(env, state, client, preview, expect_failure=True)



def test_tone_preparation_normalizes_post_hash_output_disappearance(tmp_path, monkeypatch):
    import os
    output = tmp_path / 'io' / 'tone.wav'
    real_fstat = os.fstat
    injected = []
    def unlink_after_hash(descriptor):
        observed = real_fstat(descriptor)
        try:
            at_end = os.lseek(descriptor, 0, os.SEEK_CUR) == observed.st_size
        except OSError:
            at_end = False
        if not injected and at_end and observed.st_size > 0 and output.exists() and output.stat().st_ino == observed.st_ino:
            output.unlink()
            injected.append(True)
        return observed
    monkeypatch.setattr(os, 'fstat', unlink_after_hash)
    rejected, client = _tone_collection_preview(tmp_path, '2025.1', ['--empty', 'waveform_channels'],
        existing_bytes=_tone_wav_bytes(), reject_preparation=True)
    assert injected
    assert rejected['error_code'] == 'FILE_CHANGED', rejected
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 0



def test_tone_verification_normalizes_root_disappearance_between_stat_and_resolve(tmp_path, monkeypatch):
    env, state, client, output, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels'])
    original_resolve, injected = Path.resolve, []
    def disappearing_resolve(path, *args, **kwargs):
        if path == output.parent and kwargs.get('strict') is True and not injected:
            path.rename(tmp_path / 'lost-root-during-resolve')
            injected.append(True)
        return original_resolve(path, *args, **kwargs)
    client.after_write = lambda _: monkeypatch.setattr(Path, 'resolve', disappearing_resolve)
    _finish_tone_collection(env, state, client, preview, expect_failure=True)
    assert injected



def _maximum_marker_fields(tmp_path, unit):
    plan = {'output_file': str(tmp_path / 'io' / 'tone.wav'), 'waveform': 'white_noise',
        'channel_layout': '2.0', 'sample_rate_hz': 8000, 'bit_depth': 'int16',
        'attack_seconds': 0, 'sustain_seconds': 0.0005, 'release_seconds': 0,
        'waveform_channels': [], 'markers': [{'position_seconds': 0, 'label': ''} for _ in range(128)]}
    def size():
        return len(json.dumps(plan, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    low, high = 0, 8192 // len(unit.encode('utf-8'))
    while low < high:
        middle = (low + high + 1) // 2
        for marker in plan['markers']:
            marker['label'] = unit * middle
        if size() <= 131072:
            low = middle
        else:
            high = middle - 1
    for marker in plan['markers']:
        marker['label'] = unit * low
    plan['markers'][-1]['label'] += 'x' * (131072 - size())
    assert size() == 131072
    assert max(len(marker['label'].encode('utf-8')) for marker in plan['markers']) <= 8192
    return [token for marker in plan['markers'] for token in ('--marker', '0', marker['label'])], plan['markers']


@pytest.mark.parametrize('unit', ['x', '界', '"\\\n'], ids=['ascii', 'utf8', 'escaping'])
def test_maximum_tone_marker_plan_and_count_survive_artifact_and_actual_stdout(tmp_path, unit, monkeypatch, capsys):
    import struct
    fields, markers = _maximum_marker_fields(tmp_path, unit)
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', *fields],
        client_setup=lambda fake: setattr(fake, 'session_label', '界"\\' * 500))
    cue = struct.pack('<I', 128) + b''.join(struct.pack('<II4sIII', index, 0, b'data', 0, 0, 0) for index in range(128))
    adtl = b'adtl' + b''.join(_riff_chunk(b'labl', struct.pack('<I', index) + marker['label'].encode('utf-8') + b'\0')
        for index, marker in enumerate(markers))
    assert len(adtl) < 131072
    client.artifact_bytes = _tone_wav_bytes(extra=_riff_chunk(b'cue ', cue) + _riff_chunk(b'LIST', adtl))
    verified = _finish_tone_collection(env, state, client, preview,
        expected_state='verified' if unit.isascii() else 'result_schema_checked')
    rendered = gateway.gateway_stdout_json_encoder(verified).encode(gateway.gateway_stdout_payload(verified)) + '\n'
    with monkeypatch.context() as emitting:
        emitting.setattr(gateway, 'execute_gateway', lambda argv: (0, verified))
        assert gateway.main(['verify', preview['transaction_id']]) == 0
    assert capsys.readouterr().out == rendered
    decoded = json.loads(rendered)
    assert decoded['agent_result'] == verified['agent_result']
    assert decoded['agent_result']['request'] == preview['agent_result']['request']
    assert list(decoded)[-1] == 'agent_result'
    assert len(rendered.encode('utf-8')) <= 286720
    assert 'session_context' in decoded
    assert decoded['stdout_projection']['stdout_budget_bytes'] == 286720
    from wwise_waapi.transactions import TransactionStore
    store = TransactionStore(Path(state[1]))
    assert store.load_preview(preview['transaction_id']).artifact['request'] == decoded['agent_result']['request']
    events = store.read_events(preview['transaction_id'])
    journal = next(event['details']['verification'] for event in events if event['event_type'] == 'verification_recorded')
    assert decoded['stdout_projection']['verification_canonical_sha256'] == canonical_sha256(journal)
    (tmp_path / 'terminal.stdout.json').write_text(rendered, encoding='utf-8')



@pytest.mark.parametrize('branch', ['marker-metadata', 'extensible-header'])
def test_tone_prewrite_artifact_budget_accounts_for_metadata_and_format_header(tmp_path, monkeypatch, branch):
    from wwise_waapi import operation_tone
    # Scale the fixed artifact resource bound, never a native capability or
    # caller-controlled option; expose omitted overhead without a 512 MiB file.
    monkeypatch.setattr(operation_tone, 'MAX_TREE_FILE_BYTES', 256 if branch == 'marker-metadata' else 64)
    fields = ['--empty', 'waveform_channels']
    values = {}
    if branch == 'marker-metadata':
        fields += ['--marker', '0', 'x' * 256]
    else:
        values['channel_layout'] = '0.1'
    rejected, client = _tone_collection_preview(tmp_path, '2025.1', fields,
        values=values, reject_preparation=True)
    assert rejected['error_code'] == 'LIMIT_EXCEEDED', rejected
    assert [call[0] for call in client.calls].count('ak.wwise.debug.generateToneWAV') == 0



def test_tone_one_byte_over_business_plan_budget_is_rejected_before_mutation(tmp_path):
    fields, _ = _maximum_marker_fields(tmp_path, 'x')
    fields[-1] += 'x'
    rejected = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', *fields], reject_declaration=True)
    assert rejected['error_code'] == 'INVALID_ARGUMENT'
    assert '131072' in str(rejected)


@pytest.mark.parametrize('defect', ['other-api', 'unsupported-version', 'unknown-field', 'label-limit', 'marker-count', 'options', 'missing-root', 'unbound-aggregate', 'wrong-root', 'unbound-mask'])
def test_unowned_tone_shapes_cannot_gain_extra_terminal_capacity(tmp_path, defect):
    from copy import deepcopy
    fields = [token for number in range(4) for token in ('--marker', str(number), 'x' * 8192)]
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', fields)
    client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks([(index, index * 8000, b'x' * 8192) for index in range(4)]))
    verified = _finish_tone_collection(env, state, client, preview)
    payload = deepcopy(verified)
    from wwise_waapi.transactions import TransactionStore
    events = TransactionStore(Path(state[1])).read_events(preview['transaction_id'])
    payload['verification'] = deepcopy(next(event['details']['verification'] for event in events
        if event['event_type'] == 'verification_recorded'))
    request = payload['agent_result']['request']
    arguments = request['arguments']
    if defect == 'other-api':
        arguments['api'] = 'ak.wwise.ui.commands.getCommands'
    elif defect == 'unsupported-version':
        request['version'] = '2022.1'
    elif defect == 'unknown-field':
        arguments['args']['padding'] = True
    elif defect == 'label-limit':
        arguments['args']['markers'][0]['label'] += 'x'
    elif defect == 'marker-count':
        arguments['args']['markers'] += [{'position': 0}] * 125
    elif defect == 'options':
        arguments['options'] = {'extra': True}
    elif defect == 'missing-root':
        arguments.pop('io_root')
    elif defect == 'wrong-root':
        arguments['io_root'] = str(tmp_path / 'unbound-root')
    elif defect == 'unbound-mask':
        arguments['args']['waveformChannelMask'] = -1
    else:
        arguments['args']['markers'] *= 5
    with pytest.raises(gateway.GatewayResultShapeError) as caught:
        gateway.project_successful_transaction_verify_payload(payload)
    assert caught.value.error_code == 'VERIFY_SUCCESS_SUMMARY_BUDGET_EXCEEDED'


def _tone_marker_chunks(rows):
    import struct
    # Known RIFF fixture: cue IDs deliberately differ from positions/order.
    cue = struct.pack('<I', len(rows)) + b''.join(struct.pack('<II4sIII', identity, 0, b'data', 0, 0, frame)
        for identity, frame, _ in rows)
    labels = b'adtl' + b''.join(_riff_chunk(b'labl', struct.pack('<I', identity) + label)
        for identity, _, label in rows if label is not None)
    return _riff_chunk(b'cue ', cue) + _riff_chunk(b'LIST', labels)


def test_tone_populated_ascii_markers_verify_exact_pairs_and_duplicate_positions(tmp_path):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--marker', '0', 'B', '--marker', '0.00025', 'C', '--marker', '0', 'A'])
    client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks([(91, 0, b'A\0'), (13, 2, b'C'), (42, 0, b'B\0')]))
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    from wwise_waapi.transactions import TransactionStore
    journal = next(event['details']['verification'] for event in TransactionStore(Path(state[1])).read_events(preview['transaction_id'])
                   if event['event_type'] == 'verification_recorded')
    observed = journal['readbacks'][0]['wav']['markers']
    assert observed['cue_count'] == 3
    assert observed['label_count'] == 3
    assert observed['requested_positions_checked'] is True
    assert observed['requested_labels_checked'] is True


@pytest.mark.parametrize('rows', [
    [(91, 0, b'A'), (13, 2, b'C')],
    [(91, 0, b'A'), (13, 3, b'C'), (42, 0, b'B')],
    [(91, 2, b'A'), (13, 0, b'C'), (42, 0, b'B')],
    [(91, 0, b'A'), (13, 2, b'wrong'), (42, 0, b'B')],
    [(91, 0, b'A'), (13, 2, b'C'), (42, 2, b'B')],
    [(91, 0, b'A'), (13, 2, None), (42, 0, b'B')],
    [(91, 0, b'A'), (13, 2, b'C'), (91, 0, b'B')],
], ids=['missing', 'wrong-position', 'swapped-associations', 'wrong-label', 'lost-duplicate-position', 'missing-label', 'duplicate-cue-id'])
def test_tone_populated_markers_reject_wrong_observable_effect_after_one_dispatch(tmp_path, rows):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--marker', '0', 'B', '--marker', '0.00025', 'C', '--marker', '0', 'A'])
    client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks(rows))
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=True)
    assert 'marker' in str(verified).lower() or 'cue' in str(verified).lower()
    assert [row[0] for row in client.calls].count('ak.wwise.debug.generateToneWAV') == 1


@pytest.mark.parametrize('fields', [['--marker', '0'], ['--marker', '0', '']])
def test_tone_explicit_empty_marker_label_can_be_omitted_in_native_label_chunks(tmp_path, fields):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', *fields])
    client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks([(77, 0, None)]))
    _finish_tone_collection(env, state, client, preview, expected_state='verified')


@pytest.mark.parametrize('position,label', [('0.00013', 'A'), ('0', '界')])
def test_tone_marker_native_interpretation_gaps_retain_known_checks_and_do_not_claim_completion(tmp_path, position, label):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--marker', position, label])
    client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks([(77, 1 if position != '0' else 0, label.encode('utf-8'))]))
    verified = _finish_tone_collection(env, state, client, preview)
    assert verified['verified'] is False
    assert 'marker' in str(verified).lower()


@pytest.mark.parametrize('position,label,frame,actual_label', [('0', '界', 1, '界'.encode('utf-8')), ('0.00013', 'A', 1, b'wrong')])
def test_tone_partial_marker_interpretations_still_reject_known_wrong_postconditions(tmp_path, position, label, frame, actual_label):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--empty', 'waveform_channels', '--marker', position, label])
    client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks([(77, frame, actual_label)]))
    _finish_tone_collection(env, state, client, preview, expect_failure=True)


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('floating', [False, True], ids=['pcm16', 'float32'])
@pytest.mark.parametrize('layout,channels', [('5.1', 6), ('Ambisonics 1st order', 4)])
def test_tone_anonymous_extensible_header_proves_unassigned_requested_channel_count(tmp_path, version, floating, layout, channels):
    import struct
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, version, [],
        values={'anonymous_channels': 'true', 'channel_layout': layout, 'waveform': 'silence',
                'bit_depth': 'float32' if floating else 'int16'})
    width = 4 if floating else 2
    fmt = struct.pack('<HHIIHHHHI', 65534, channels, 8000, 8000 * channels * width,
        channels * width, width * 8, 22, width * 8, 0)
    fmt += bytes.fromhex('0300000000001000800000aa00389b71' if floating else '0100000000001000800000aa00389b71')
    client.artifact_bytes = _tone_wav_bytes(floating=floating, channels=channels, samples=[0] * channels * 4, fmt_override=fmt)
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['agent_result']['request']['arguments']['args']['setAnonymous'] is True


@pytest.mark.parametrize('defect', ['assigned-speakers', 'wrong-count', 'nonzero-last-sample'])
def test_tone_anonymous_header_proof_rejects_wrong_requested_effect(tmp_path, defect):
    import struct
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'anonymous_channels': 'true', 'channel_layout': '5.1', 'waveform': 'silence'})
    channels = 4 if defect == 'wrong-count' else 6
    mask = 3 if defect == 'assigned-speakers' else 0
    fmt = struct.pack('<HHIIHHHHI', 65534, channels, 8000, 16000 * channels,
        channels * 2, 16, 22, 16, mask) + bytes.fromhex('0100000000001000800000aa00389b71')
    samples = [0] * channels * 4
    if defect == 'nonzero-last-sample':
        samples[-1] = 1
    client.artifact_bytes = _tone_wav_bytes(channels=channels, samples=samples, fmt_override=fmt)
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=True)
    if defect == 'assigned-speakers':
        assert 'anonymous' in str(verified)
        assert 'malformed' not in str(verified)


def test_tone_2023_anonymous_field_rejected_before_mutation(tmp_path):
    rejected = _tone_collection_preview(tmp_path, '2023.1', [],
        values={'anonymous_channels': 'true', 'waveform': 'silence'}, reject_declaration=True)
    assert rejected['error_code'] == 'GatewayInputError'


def test_tone_legacy_anonymous_header_retains_unresolved_representation(tmp_path):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'anonymous_channels': 'true', 'waveform': 'silence'})
    client.artifact_bytes = _tone_wav_bytes()
    verified = _finish_tone_collection(env, state, client, preview)
    assert 'anonymous' in str(verified)


def test_tone_128_empty_label_markers_verify_through_actual_main_with_ordinary_output_budget(tmp_path, monkeypatch, capsys):
    fields = [token for _ in range(128) for token in ('--marker', '0')]
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', fields,
        values={'waveform': 'silence'})
    client.artifact_bytes = _tone_wav_bytes(extra=_tone_marker_chunks([(identity, 0, None) for identity in range(128)]))
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    actual_execute = gateway.execute_gateway
    observed_payloads = []
    def observe_actual_gateway(argv):
        result = actual_execute(argv)
        observed_payloads.append(result[1])
        return result
    with monkeypatch.context() as emitting:
        emitting.setenv('WAAPI_SKILL_CONFIG_PATH', env['WAAPI_SKILL_CONFIG_PATH'])
        emitting.setattr(gateway, 'default_client_factory', lambda _: client)
        # Observe the real public verify result, without replacing its verifier,
        # result or filesystem behavior; main emits that exact machine object.
        emitting.setattr(gateway, 'execute_gateway', observe_actual_gateway)
        assert gateway.main([*state, 'verify', tx]) == 0
    rendered = capsys.readouterr().out
    decoded = json.loads(rendered)
    assert decoded['verified'] is True
    assert decoded['stdout_projection']['stdout_budget_bytes'] == 24576
    assert len(rendered.encode('utf-8')) <= 24576
    assert decoded['agent_result'] == observed_payloads[0]['agent_result']
    assert decoded['agent_result']['request'] == preview['agent_result']['request']
    assert list(decoded)[-1] == 'agent_result'
    assert [row[0] for row in client.calls].count('ak.wwise.debug.generateToneWAV') == 1
    from wwise_waapi.transactions import TransactionStore
    journal = next(event['details']['verification'] for event in TransactionStore(Path(state[1])).read_events(tx)
        if event['event_type'] == 'verification_recorded')
    assert journal['readbacks'][0]['wav']['markers']['cue_count'] == 128
    assert journal['readbacks'][0]['wav']['markers']['label_count'] == 0
    assert decoded['stdout_projection']['verification_canonical_sha256'] == canonical_sha256(journal)
    (tmp_path / 'terminal.stdout.json').write_text(rendered, encoding='utf-8')


@pytest.mark.parametrize('name', ['int16-0db', 'int16-6db', 'float32-0db', 'float32-6db'])
@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
def test_tone_retained_native_stationary_sine_conforms_to_requested_signal_policy(tmp_path, name, version):
    import hashlib
    fixture_root = Path(__file__).resolve().parents[1] / 'fixtures' / 'tone' / 'console-2025.1.7.9143'
    manifest = json.loads((fixture_root / 'manifest.json').read_text())
    specimen = manifest['files'][name + '.wav']
    raw = (fixture_root / (name + '.wav')).read_bytes()
    assert len(raw) == specimen['size'] and hashlib.sha256(raw).hexdigest() == specimen['sha256']
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, version, [],
        values={'waveform': 'sine', 'channel_layout': '1.0', 'sample_rate_hz': '48000',
            'bit_depth': specimen['bit_depth'], 'attack_seconds': '0', 'sustain_seconds': '0.25',
            'release_seconds': '0', 'sustain_db': str(specimen['sustain_db'])})
    client.artifact_bytes = raw
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    from wwise_waapi.transactions import TransactionStore
    journal = next(event['details']['verification'] for event in TransactionStore(Path(state[1])).read_events(preview['transaction_id'])
        if event['event_type'] == 'verification_recorded')
    wav = journal['readbacks'][0]['wav']
    assert (wav['format_tag'], wav['sample_format'], wav['bits'], wav['valid_bits']) == (
        65534, specimen['bit_depth'], 16 if specimen['bit_depth'] == 'int16' else 32, 0)
    assert (wav['channels'], wav['speaker_mask'], wav['sample_rate'], wav['frames']) == (1, 4, 48000, 12000)
    assert verified['verification_strength'] == 'tone_wav_artifact'
    assert journal['business_state_verified'] is True
    signal = wav['stationary_sine']
    assert signal['policy'] == 'stationary-sine-numerical-conformance-v1'
    assert signal['gain_tolerance_db'] == 0.02
    assert signal['shape_tolerance_relative'] == 0.002
    assert signal['channels'][0]['max_sample_error'] <= signal['sample_error_limit']
    assert signal['channels'][0]['measured_gain'] > 0
    assert signal['observability_reason'] is None


@pytest.mark.parametrize('defect', ['contradictory-valid-bits', 'excess-valid-bits', 'unknown-subtype',
    'subtype-container-mismatch', 'extension-length', 'block-alignment'])
def test_tone_zero_union_field_never_bypasses_contradictory_format_checks(tmp_path, defect):
    import struct
    fixture_root = Path(__file__).resolve().parents[1] / 'fixtures' / 'tone' / 'console-2025.1.7.9143'
    raw = bytearray((fixture_root / 'int16-0db.wav').read_bytes())
    if defect in {'contradictory-valid-bits', 'excess-valid-bits'}:
        struct.pack_into('<H', raw, 38, 15 if defect == 'contradictory-valid-bits' else 17)
    elif defect == 'unknown-subtype':
        raw[44:60] = bytes(16)
    elif defect == 'subtype-container-mismatch':
        raw[44] = 3  # Explicit IEEE-float GUID with an unchanged16-bit container.
    elif defect == 'extension-length':
        struct.pack_into('<H', raw, 36, 21)
    else:
        struct.pack_into('<H', raw, 32, 3)
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'sine', 'channel_layout': '1.0', 'sample_rate_hz': '48000',
            'attack_seconds': '0', 'sustain_seconds': '0.25', 'release_seconds': '0'})
    client.artifact_bytes = bytes(raw)
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=True)
    failed = [row for row in verified['verification']['assertions'] if not row['passed']]
    assert len(failed) == 1 and failed[0]['evidence']['code'] == 'INVALID_TONE_WAV'
    assert [row[0] for row in client.calls].count('ak.wwise.debug.generateToneWAV') == 1


@pytest.mark.parametrize('version', ['2021.1', '2022.1'])
def test_tone_older_pinned_routes_remain_unavailable_without_native_calls(tmp_path, version):
    code, rejected = gateway.execute_gateway(['--version', version, 'request-schema',
        'ak.wwise.debug.generateToneWAV'], env=_env(tmp_path, version),
        client_factory=lambda _: pytest.fail('older route discovery must remain offline'))
    assert code != 0 and rejected['ok'] is False, rejected
    assert 'continuation' not in rejected


def test_stationary_square_does_not_certify_retained_wrong_requested_frequency_after_one_execution(tmp_path):
    import hashlib
    fixtures = Path(__file__).resolve().parents[1] / 'fixtures/tone/console-2025.1.7.9143/waveforms'
    manifest = json.loads((fixtures / 'manifest.json').read_text())
    specimen = manifest['files']['square-stationary.wav']
    raw = (fixtures / 'square-stationary.wav').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == specimen['sha256'] and len(raw) == specimen['size']
    assert manifest['native_business_acceptance'] is False
    values = {key: str(value) for key, value in specimen['request'].items()}
    values['frequency_hz'] = '880'
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [], values=values)
    client.artifact_bytes = raw
    verified = _finish_tone_collection(env, state, client, preview)
    writes = [call for call in client.calls if call[0] == 'ak.wwise.debug.generateToneWAV']
    assert len(writes) == 1 and writes[0][1] == preview['agent_result']['request']['arguments']['args']
    assert writes[0][1]['frequency'] == 880
    _, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
    journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
    signal = journal['readbacks'][0]['wav']['stationary_square']
    assert signal['channels'][0]['exact_cadence_conforms'] is False
    assert 'native phase arithmetic precision is unspecified' in signal['observability_reason']
    assert verified['verification_strength'] == 'partial_tone_artifact'


def test_stationary_sine_rejects_retained_wrong_requested_frequency_after_one_execution(tmp_path):
    fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'tone' / 'console-2025.1.7.9143' / 'float32-0db.wav'
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'sine', 'frequency_hz': '880', 'channel_layout': '1.0',
            'sample_rate_hz': '48000', 'bit_depth': 'float32', 'attack_seconds': '0',
            'sustain_seconds': '0.25', 'release_seconds': '0', 'sustain_db': '0'})
    client.artifact_bytes = fixture.read_bytes()
    frozen_request = preview['agent_result']['request']
    assert frozen_request['arguments']['args']['frequency'] == 880
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=True)
    writes = [call for call in client.calls if call[0] == 'ak.wwise.debug.generateToneWAV']
    assert len(writes) == 1 and writes[0][1] == frozen_request['arguments']['args']
    assert 'sine' in str(verified['verification']).lower()


def test_stationary_square_rejects_gain_even_when_every_sign_has_the_requested_cadence(tmp_path):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'square', 'frequency_hz': '800', 'sample_rate_hz': '8000',
            'bit_depth': 'float32', 'channel_layout': '1.0', 'sustain_seconds': '0.01', 'sustain_db': '-6'})
    # Worked ten-sample cycle with .13-cycle initial phase; independent of the
    # verifier's phase intersection and with the correct cadence at wrong gain.
    signs = [1, 1, 1, 1, -1, -1, -1, -1, -1, 1]
    client.artifact_bytes = _tone_wav_bytes(floating=True, channels=1, samples=[.7 * sign for sign in signs] * 8)
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=True)
    assert 'gain' in str(verified['verification']).lower()


def test_stationary_square_retained_native_bytes_verify_without_relabelling_original_collection(tmp_path):
    import hashlib
    fixtures = Path(__file__).resolve().parents[1] / 'fixtures/tone/console-2025.1.7.9143/waveforms'
    manifest = json.loads((fixtures / 'manifest.json').read_text())
    specimen = manifest['files']['square-stationary.wav']
    raw = (fixtures / 'square-stationary.wav').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == specimen['sha256'] and len(raw) == specimen['size']
    assert manifest['original_verification_strength'] == 'partial_tone_artifact'
    assert manifest['native_business_acceptance'] is False
    env, state, client, _, schema, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={key: str(value) for key, value in specimen['request'].items()})
    client.artifact_bytes = raw
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['agent_result']['request'] == preview['agent_result']['request']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
    journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
    signal = journal['readbacks'][0]['wav']['stationary_square']
    assert signal['observability_reason'] is None
    assert signal['channels'][0]['measured_gain'] == .5006684064865112
    assert signal['requested_gain'] == .5011872336272722
    assert signal['channels'][0]['max_sample_error'] > signal['representation_error']
    disclosure = schema['business_adapter']['safety']['tone_artifact_verification']['stationary_square_checks']
    assert (disclosure['gain_tolerance_db'], disclosure['shape_tolerance_relative'], disclosure['representation_units']) == (.02, .002, 2)
    assert disclosure['phase'] == 'one common unparameterized phase per active channel; exact rational cadence; either limiting sign at exact discontinuities only'


@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('floating', [True, False], ids=['float32', 'pcm16'])
@pytest.mark.parametrize('frequency,phase,db', [(800, .13, -6), (125.5, .27, 0), (1000, .5, -6)])
def test_stationary_square_phase_varied_analytic_signals_verify_through_versioned_gateway(tmp_path, version, floating, frequency, phase, db):
    import math
    channels = 1 if version == '2023.1' else 2
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, version,
        [] if channels == 1 else ['--item', 'waveform_channels', '0'],
        values={'waveform': 'square', 'channel_layout': '1.0' if channels == 1 else '2.0',
            'frequency_hz': str(frequency), 'sample_rate_hz': '8000', 'sustain_seconds': '0.1',
            'bit_depth': 'float32' if floating else 'int16', 'sustain_db': str(db)})
    gain = 1 if db == 0 else .5011872336272722
    samples = []
    for frame in range(800):
        # Independent mathematical reference, not the production interval solver.
        sample = gain if math.sin(math.tau * (frequency * frame / 8000 + phase)) >= 0 else -gain
        if not floating:
            sample = max(-32768, min(32767, round(sample * 32768)))
        samples.extend([sample] + [0] * (channels - 1))
    client.artifact_bytes = _tone_wav_bytes(floating=floating, channels=channels, samples=samples)
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['verification_strength'] == 'tone_wav_artifact'
    _, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
    journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
    signal = journal['readbacks'][0]['wav']['stationary_square']
    assert signal['frequency_hz'] == frequency and signal['observability_reason'] is None
    assert [row['channel'] for row in signal['channels']] == [0]
    assert len(signal['channels'][0]['phase_relative_intervals_units']) <= 2
    assert signal['channels'][0]['max_sample_error'] <= signal['sample_error_limit']


@pytest.mark.parametrize('defect', ['frequency', 'duty', 'sine', 'triangle', 'dc', 'ramp',
    'silence', 'late-magnitude', 'off-edge-sign', 'late-silent', 'mean-gain', 'mean-gain-with-cadence'])
def test_stationary_square_wrong_effects_never_verify_without_fitting_gain_frequency_or_edges(tmp_path, defect):
    import math
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--item', 'waveform_channels', '0'],
        values={'waveform': 'square', 'frequency_hz': '800', 'sample_rate_hz': '8000',
            'bit_depth': 'float32', 'sustain_seconds': '0.01', 'sustain_db': '-6'})
    gain = .5011872336272722
    signs = [1, 1, 1, 1, -1, -1, -1, -1, -1, 1]
    samples = []
    for frame in range(80):
        sample = gain * signs[frame % 10]
        if defect == 'frequency':
            sample = gain * signs[(2 * frame) % 10]
        elif defect == 'duty':
            sample = gain if frame % 10 < 7 else -gain
        elif defect in {'sine', 'triangle'}:
            phase = math.tau * (frame / 10 + .13)
            sample = gain * (math.sin(phase) if defect == 'sine' else 2 / math.pi * math.asin(math.sin(phase)))
        elif defect == 'dc':
            sample += .02
        elif defect == 'ramp':
            sample *= frame / 79
        elif defect == 'silence':
            sample = 0
        elif defect == 'late-magnitude' and frame == 79:
            sample += .02
        elif defect == 'off-edge-sign' and frame == 77:
            sample = -sample
        elif defect in {'mean-gain', 'mean-gain-with-cadence'}:
            # Inside the combined per-sample budget but outside .02 dB gain:
            # this needs the independent gain check, not only shape membership.
            sample *= 1.003
            if defect == 'mean-gain-with-cadence':
                sample = gain * 1.003 * signs[(2 * frame) % 10]
        samples.extend([sample, .1 if defect == 'late-silent' and frame == 79 else 0])
    client.artifact_bytes = _tone_wav_bytes(floating=True, samples=samples)
    cadence_only = defect in {'frequency', 'duty', 'off-edge-sign'}
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=not cadence_only)
    if cadence_only:
        assert verified['verification_strength'] == 'partial_tone_artifact'
        _, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
        journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
        assert journal['readbacks'][0]['wav']['stationary_square']['channels'][0]['exact_cadence_conforms'] is False
    else:
        assert 'square' in str(verified['verification']).lower() or 'silent channel' in str(verified['verification'])
    if defect in {'mean-gain', 'mean-gain-with-cadence'}:
        assert 'mean absolute gain' in str(verified['verification'])


@pytest.mark.parametrize('defect', [None, 'off-edge-sign', 'near-frequency'])
def test_stationary_square_exact_discontinuities_have_no_neighboring_transition_window(tmp_path, defect):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'square', 'frequency_hz': '2000.0000000000002' if defect == 'near-frequency' else '2000',
            'sample_rate_hz': '8000', 'channel_layout': '1.0', 'bit_depth': 'float32',
            'sustain_seconds': '0.01', 'sustain_db': '-6'})
    # At phase zero, frames 0 and 2 of each four-frame cycle are exact edges.
    # Their limiting signs may vary; frames 1 and 3 are strictly + and -.
    signs = ([1, 1, 1, -1] + [-1, 1, -1, -1]) * 10
    if defect == 'off-edge-sign':
        signs[-1] = 1
    client.artifact_bytes = _tone_wav_bytes(floating=True, channels=1,
        samples=[.5011872336272722 * sign for sign in signs])
    verified = _finish_tone_collection(env, state, client, preview,
        expected_state='verified' if defect is None else 'result_schema_checked')
    if defect is not None:
        assert verified['verification_strength'] == 'partial_tone_artifact'
        _, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
        journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
        signal = journal['readbacks'][0]['wav']['stationary_square']
        assert signal['channels'][0]['exact_cadence_conforms'] is False
        assert 'native phase arithmetic precision is unspecified' in signal['observability_reason']


@pytest.mark.parametrize('defect', [None, 'wrong-observable-channel'])
def test_stationary_square_partial_channel_does_not_hide_another_channel_effect(tmp_path, defect):
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'square', 'frequency_hz': '800', 'sample_rate_hz': '8000',
            'bit_depth': 'float32', 'sustain_seconds': '0.001', 'sustain_db': '-6'})
    first = [1, 1, 1, 1, 1, -1, -1, -1]  # No recurrence yet.
    second = [1, 1, -1, -1, -1, -1, -1, 1]
    if defect:
        second[5] = 1
    client.artifact_bytes = _tone_wav_bytes(floating=True,
        samples=[.5011872336272722 * sign for pair in zip(first, second) for sign in pair])
    verified = _finish_tone_collection(env, state, client, preview)
    _, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
    journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
    signal = journal['readbacks'][0]['wav']['stationary_square']
    assert 'recurrence' in signal['channels'][0]['observability_reason']
    if defect is None:
        assert signal['channels'][1]['observability_reason'] is None
    else:
        assert signal['channels'][1]['exact_cadence_conforms'] is False
        assert 'precision is unspecified' in signal['channels'][1]['observability_reason']
    assert verified['verification_strength'] == 'partial_tone_artifact'


@pytest.mark.parametrize('case', ['short', 'empty', 'quantized', 'aliased', 'fractional-frames', 'fractional-rate',
    'wrong-level-despite-alias', 'square-envelope', 'triangle', 'noise'])
def test_stationary_square_known_checks_and_unfinished_effects_remain_distinct(tmp_path, case):
    values = {'waveform': 'square', 'frequency_hz': '800', 'sample_rate_hz': '8000',
        'bit_depth': 'float32', 'channel_layout': '1.0', 'sustain_seconds': '0.01', 'sustain_db': '-6'}
    frames = 80
    if case == 'short':
        frames, values['sustain_seconds'] = 1, '0.000125'
    elif case == 'empty':
        frames, values['sustain_seconds'] = 0, '0'
    elif case == 'quantized':
        values.update(bit_depth='int16', sustain_db='-96')
    elif case in {'aliased', 'wrong-level-despite-alias'}:
        values['frequency_hz'] = '4000'
    elif case == 'fractional-frames':
        values['sustain_seconds'] = '0.01001'
    elif case == 'fractional-rate':
        values['sample_rate_hz'] = '8000.5'
    elif case == 'square-envelope':
        values.update(attack_seconds='0.002', sustain_seconds='0.008')
    elif case in {'triangle', 'noise'}:
        values['waveform'] = 'triangle' if case == 'triangle' else 'white_noise'
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [], values=values)
    signs = [1, 1, 1, 1, -1, -1, -1, -1, -1, 1]
    gain = .7 if case == 'wrong-level-despite-alias' else .5011872336272722
    samples = [0] * frames if case == 'quantized' else [gain * signs[frame % 10] for frame in range(frames)]
    client.artifact_bytes = _tone_wav_bytes(floating=case != 'quantized', channels=1, samples=samples)
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=case == 'wrong-level-despite-alias')
    if case == 'wrong-level-despite-alias':
        assert 'gain' in str(verified['verification'])
        return
    assert verified['verification_strength'] == 'partial_tone_artifact'
    _, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
    journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
    wav = journal['readbacks'][0]['wav']
    if case in {'square-envelope', 'triangle', 'noise'}:
        assert 'stationary_square' not in wav
        assert 'active waveform' in str(journal['readbacks'][0]['unresolved'])
    else:
        reason = wav['stationary_square']['observability_reason']
        expected = {'short': 'recurrence', 'empty': 'empty', 'quantized': 'quantization', 'aliased': 'Nyquist',
            'fractional-frames': 'fractional', 'fractional-rate': 'fractional'}[case]
        assert expected in reason


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
def test_stationary_square_36_anonymous_channels_preserve_exact_terminal_result(tmp_path, monkeypatch, capsys, version):
    import math
    import struct
    from wwise_waapi.transactions import TransactionStore
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, version, [],
        values={'waveform': 'square', 'channel_layout': 'Ambisonics 5th order', 'anonymous_channels': 'true',
            'frequency_hz': '800.0000000000001', 'sample_rate_hz': '8000', 'bit_depth': 'float32',
            'sustain_db': '-6', 'sustain_seconds': '0.01'})
    samples = [.5011872336272722 * (1 if math.sin(math.tau * (800.0000000000001 * frame / 8000 + .137 + channel / 997)) >= 0 else -1)
        for frame in range(80) for channel in range(36)]
    fmt = struct.pack('<HHIIHHHHI', 65534, 36, 8000, 1152000, 144, 32, 22, 32, 0)
    fmt += bytes.fromhex('0300000000001000800000aa00389b71')
    client.artifact_bytes = _tone_wav_bytes(floating=True, channels=36, samples=samples, fmt_override=fmt)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    actual_execute = gateway.execute_gateway
    observed_payloads = []
    def observe_actual_gateway(argv):
        result = actual_execute(argv)
        observed_payloads.append(result[1])
        return result
    with monkeypatch.context() as emitting:
        emitting.setenv('WAAPI_SKILL_CONFIG_PATH', env['WAAPI_SKILL_CONFIG_PATH'])
        emitting.setattr(gateway, 'default_client_factory', lambda _: client)
        emitting.setattr(gateway, 'execute_gateway', observe_actual_gateway)
        assert gateway.main([*state, 'verify', tx]) == 0
    rendered = capsys.readouterr().out
    decoded = json.loads(rendered)
    assert decoded['verified'] is True
    assert decoded['stdout_projection']['stdout_budget_bytes'] == 24576
    assert len(rendered.encode('utf-8')) <= 24576
    assert decoded['agent_result'] == observed_payloads[0]['agent_result']
    assert decoded['agent_result']['request'] == preview['agent_result']['request']
    assert list(decoded)[-1] == 'agent_result'
    journal = next(event['details']['verification'] for event in TransactionStore(Path(state[1])).read_events(tx)
        if event['event_type'] == 'verification_recorded')
    wav = journal['readbacks'][0]['wav']
    assert (wav['channels'], wav['speaker_mask']) == (36, 0)
    signal = wav['stationary_square']
    assert [row['channel'] for row in signal['channels']] == list(range(36))
    assert all(row['observability_reason'] is None for row in signal['channels'])
    assert decoded['stdout_projection']['verification_canonical_sha256'] == canonical_sha256(journal)
    assert [row[0] for row in client.calls].count('ak.wwise.debug.generateToneWAV') == 1
    (tmp_path / 'square-36-terminal.stdout.json').write_text(rendered, encoding='utf-8')


@pytest.mark.parametrize('defect', [None, 'frequency', 'waveform', 'gain', 'attack', 'release', 'silent-active', 'late-silent'])
def test_stationary_sine_full_signal_and_selected_channel_effects_are_request_bound(tmp_path, defect):
    import math
    # Independent analytic signal: -6 dB amplitude is a fixed worked reference;
    # no implementation helper, retained output or measured fit generates it.
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1',
        ['--item', 'waveform_channels', '0'],
        values={'waveform': 'sine', 'frequency_hz': '800', 'sample_rate_hz': '8000',
            'bit_depth': 'float32', 'sustain_seconds': '0.01', 'sustain_db': '-6'})
    samples = []
    for frame in range(80):
        phase = math.tau * (1600 if defect == 'frequency' else 800) * frame / 8000 + 0.37
        sample = (1 if defect == 'gain' else 0.5011872336272722) * math.sin(phase)
        if defect == 'waveform':
            # A harmonic-distorted wave has the correct fundamental gain;
            # rejecting it requires full shape proof, not only a level check.
            sample += 0.1 * 0.5011872336272722 * math.sin(3 * phase)
        elif defect == 'attack':
            sample *= frame / 79
        elif defect == 'release':
            sample *= 1 - frame / 79
        elif defect == 'silent-active':
            sample = 0
        samples.extend([sample, 0.1 if defect == 'late-silent' and frame == 79 else 0])
    client.artifact_bytes = _tone_wav_bytes(floating=True, samples=samples)
    verified = _finish_tone_collection(env, state, client, preview,
        expect_failure=defect is not None, expected_state='verified')
    writes = [row for row in client.calls if row[0] == 'ak.wwise.debug.generateToneWAV']
    assert len(writes) == 1
    assert writes[0][1]['frequency'] == 800 and writes[0][1]['sustainLevel'] == -6
    if defect is not None:
        assert 'sine' in str(verified['verification']).lower() or 'silent channel' in str(verified['verification'])
        if defect != 'late-silent':
            assert 'stationary-sine-numerical-conformance-v1' in str(verified['verification'])
    else:
        from wwise_waapi.transactions import TransactionStore
        journal = next(event['details']['verification'] for event in TransactionStore(Path(state[1])).read_events(preview['transaction_id'])
            if event['event_type'] == 'verification_recorded')
        observed = journal['readbacks'][0]['wav']
        assert observed['nonzero_samples_by_channel'] == [80, 0]
        assert observed['stationary_sine']['channels'][0]['phase_radians'] == pytest.approx(0.37, abs=1e-6)
        assert [row['channel'] for row in observed['stationary_sine']['channels']] == [0]


@pytest.mark.parametrize('case', ['short', 'aliased', 'quantized', 'fractional', 'other-waveform'])
def test_stationary_sine_inconclusive_and_unimplemented_effects_remain_distinct_and_partial(tmp_path, case):
    values = {'waveform': 'sine', 'frequency_hz': '800', 'sample_rate_hz': '8000',
        'bit_depth': 'float32', 'channel_layout': '1.0', 'sustain_seconds': '0.01'}
    frames = 80
    if case == 'short':
        frames, values['sustain_seconds'] = 1, '0.000125'
    elif case == 'aliased':
        values['frequency_hz'] = '4000'
    elif case == 'quantized':
        values.update(bit_depth='int16', sustain_db='-96')
    elif case == 'fractional':
        values['sustain_seconds'] = '0.01001'
    elif case == 'other-waveform':
        values['waveform'] = 'triangle'
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [], values=values)
    client.artifact_bytes = _tone_wav_bytes(floating=case != 'quantized', channels=1, samples=[0] * frames)
    verified = _finish_tone_collection(env, state, client, preview)
    assert verified['verification_strength'] == 'partial_tone_artifact'
    from wwise_waapi.transactions import TransactionStore
    journal = next(event['details']['verification'] for event in TransactionStore(Path(state[1])).read_events(preview['transaction_id'])
        if event['event_type'] == 'verification_recorded')
    observed = journal['readbacks'][0]
    assert observed['unresolved']
    if case == 'other-waveform':
        assert 'stationary_sine' not in observed['wav']
        assert 'active waveform' in str(observed['unresolved'])
    else:
        reason = observed['wav']['stationary_sine']['observability_reason']
        assert {'short': 'rank deficient', 'aliased': 'Nyquist', 'quantized': 'quantization',
            'fractional': 'fractional'}[case] in reason


def test_stationary_sine_short_but_resolvable_record_proves_digital_conformance(tmp_path):
    import math
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'sine', 'frequency_hz': '800', 'sample_rate_hz': '8000',
            'bit_depth': 'float32', 'channel_layout': '1.0', 'sustain_seconds': '0.0005'})
    client.artifact_bytes = _tone_wav_bytes(floating=True, channels=1,
        samples=[math.sin(math.tau * frame / 10 + 0.37) for frame in range(4)])
    _finish_tone_collection(env, state, client, preview, expected_state='verified')


@pytest.mark.parametrize('version', ['2023.1', '2024.1', '2025.1'])
@pytest.mark.parametrize('floating', [True, False])
def test_sine_envelope_verifies_requested_linear_segments_with_independent_unparameterized_phases(tmp_path, version, floating):
    import math
    env, state, client, _, schema, _, preview = _tone_collection_preview(tmp_path, version,
        ['--item', 'waveform_channels', '0'] if version != '2023.1' else [],
        values={'waveform': 'sine', 'frequency_hz': '800', 'sample_rate_hz': '8000',
            'channel_layout': '2.0' if version != '2023.1' else '1.0',
            'bit_depth': 'float32' if floating else 'int16', 'sustain_db': '-6', 'attack_seconds': '0.0025',
            'sustain_seconds': '0.005', 'release_seconds': '0.00375'})
    samples = []
    for frame in range(90):
        if frame < 20:
            amplitude, phase = frame / 20, .37
        elif frame < 60:
            amplitude, phase = 1, -.52
        else:
            amplitude, phase = (90 - frame) / 30, 1.12
        sample = .5011872336272722 * amplitude * math.sin(math.tau * frame / 10 + phase)
        samples.append(sample if floating else round(sample * 32768))
        if version != '2023.1':
            samples.append(0)
    client.artifact_bytes = _tone_wav_bytes(floating=floating, samples=samples, channels=1 if version == '2023.1' else 2)
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['verification_strength'] == 'tone_wav_artifact'
    code, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
    assert code == 0
    journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
    signal = journal['readbacks'][0]['wav']['sine_envelope']
    assert signal['policy'] == 'sine-envelope-numerical-conformance-v1'
    assert signal['phase_relationship_checked'] is False
    assert [row['name'] for row in signal['segments']] == ['attack', 'sustain', 'release']
    assert [row['frames'] for row in signal['segments']] == [20, 40, 30]
    assert [row['channels'][0]['phase_radians'] for row in signal['segments']] == pytest.approx([.37, -.52, 1.12], abs=1e-6 if floating else 1e-4)
    assert signal['observability_reason'] is None
    disclosure = schema['business_adapter']['safety']['tone_artifact_verification']['sine_envelope_checks']
    assert disclosure['phase_relationship_checked'] is False


@pytest.mark.parametrize('name', ['sine-attack-only', 'sine-release-only', 'sine-attack-release'])
def test_sine_envelope_retained_2025_native_bytes_verify_without_relabelling_original_characterization(tmp_path, name):
    import hashlib
    fixtures = Path(__file__).resolve().parents[1] / 'fixtures/tone/console-2025.1.7.9143/envelopes'
    manifest = json.loads((fixtures / 'manifest.json').read_text())
    specimen = manifest['files'][name + '.wav']
    raw = (fixtures / (name + '.wav')).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == specimen['sha256'] and len(raw) == specimen['size']
    assert manifest['native_business_acceptance'] is False
    assert manifest['original_verification_strength'] == 'partial_tone_artifact'
    values = {key: str(value) for key, value in {**manifest['common_request'], **specimen['request']}.items()}
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [], values=values)
    client.artifact_bytes = raw
    verified = _finish_tone_collection(env, state, client, preview, expected_state='verified')
    assert verified['verification_strength'] == 'tone_wav_artifact'
    assert verified['agent_result']['request'] == preview['agent_result']['request']
    code, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
    assert code == 0
    journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
    signal = journal['readbacks'][0]['wav']['sine_envelope']
    assert signal['observability_reason'] is None and signal['phase_relationship_checked'] is False
    assert (signal['gain_tolerance_db'], signal['shape_tolerance_relative']) == (.02, .002)
    assert journal['business_state_verified'] is True


@pytest.mark.parametrize('defect', ['curve', 'swapped-segments', 'gain', 'frequency', 'silence', 'missing-envelope', 'late-sample'])
def test_sine_envelope_rejects_wrong_requested_signal_after_exactly_one_execution(tmp_path, defect):
    import math
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'sine', 'channel_layout': '1.0', 'frequency_hz': '800',
            'sample_rate_hz': '8000', 'bit_depth': 'float32', 'sustain_db': '-6',
            'attack_seconds': '0.0025', 'sustain_seconds': '0.005', 'release_seconds': '0.00375'})
    samples = []
    for frame in range(90):
        attack, sustain_end, release = (30, 70, 20) if defect == 'swapped-segments' else (20, 60, 30)
        amplitude = frame / attack if frame < attack else (90 - frame) / release if frame >= sustain_end else 1
        if defect == 'curve':
            amplitude *= amplitude
        elif defect == 'missing-envelope':
            amplitude = 1
        frequency = 1600 if defect == 'frequency' else 800
        gain = .7 if defect == 'gain' else .5011872336272722
        sample = gain * amplitude * math.sin(math.tau * frequency * frame / 8000 + .37)
        if defect == 'silence':
            sample = 0
        if defect == 'late-sample' and frame == 89:
            sample += .02
        samples.append(sample)
    client.artifact_bytes = _tone_wav_bytes(floating=True, channels=1, samples=samples)
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=True)
    assert 'sine-envelope-numerical-conformance-v1' in str(verified['verification'])
    writes = [call for call in client.calls if call[0] == 'ak.wwise.debug.generateToneWAV']
    assert len(writes) == 1 and writes[0][1] == preview['agent_result']['request']['arguments']['args']


@pytest.mark.parametrize('case', ['rank-deficient', 'quantized', 'fractional', 'aliased', 'wrong-observable-segment'])
def test_sine_envelope_inconclusive_segments_remain_partial_and_keep_other_segment_checks(tmp_path, case):
    import math
    values = {'waveform': 'sine', 'channel_layout': '1.0', 'frequency_hz': '800',
        'sample_rate_hz': '8000', 'bit_depth': 'float32', 'sustain_db': '-6',
        'attack_seconds': '0.000125', 'sustain_seconds': '0.005', 'release_seconds': '0.0025'}
    if case == 'quantized':
        values.update(bit_depth='int16', sustain_db='-96')
    elif case == 'fractional':
        values['attack_seconds'] = '0.000126'
    elif case == 'aliased':
        values['frequency_hz'] = '4000'
    samples = []
    for frame in range(61):
        envelope = 0 if frame == 0 else (61 - frame) / 20 if frame >= 41 else 1
        gain = .7 if case == 'wrong-observable-segment' else .5011872336272722
        samples.append(0 if case in {'quantized', 'aliased'} else gain * envelope * math.sin(math.tau * frame / 10 + .37))
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [], values=values)
    client.artifact_bytes = _tone_wav_bytes(floating=case != 'quantized', channels=1, samples=samples)
    verified = _finish_tone_collection(env, state, client, preview, expect_failure=case == 'wrong-observable-segment')
    if case == 'wrong-observable-segment':
        assert 'gain differs' in str(verified['verification'])
    else:
        assert verified['verification_strength'] == 'partial_tone_artifact'
        code, shown = gateway.execute_gateway([*state, 'transaction-show', preview['transaction_id']], env=env)
        assert code == 0
        journal = next(row['details']['verification'] for row in shown['events'] if row['event_type'] == 'verification_recorded')
        signal = journal['readbacks'][0]['wav']['sine_envelope']
        reason = signal['segments'][1]['observability_reason'] if case == 'quantized' else signal['observability_reason']
        assert {'rank-deficient': 'rank deficient', 'quantized': 'quantization',
            'fractional': 'fractional', 'aliased': 'Nyquist'}[case] in reason
        if case == 'rank-deficient':
            assert signal['segments'][0]['observability_reason']
            assert signal['segments'][1]['channels'] and signal['segments'][2]['channels']


def test_sine_envelope_rejects_nonzero_zero_weight_frame_even_when_segment_phase_is_unobservable(tmp_path):
    import math
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'sine', 'channel_layout': '1.0', 'frequency_hz': '800',
            'sample_rate_hz': '8000', 'bit_depth': 'float32', 'sustain_db': '-6',
            'attack_seconds': '0.000125', 'sustain_seconds': '0.005', 'release_seconds': '0.0025'})
    samples = [.1] + [.5011872336272722 * (1 if frame < 41 else (61 - frame) / 20)
        * math.sin(math.tau * frame / 10 + .37) for frame in range(1, 61)]
    client.artifact_bytes = _tone_wav_bytes(floating=True, channels=1, samples=samples)
    _finish_tone_collection(env, state, client, preview, expect_failure=True)


def test_sine_envelope_all_supported_standard_channels_preserve_exact_terminal_agent_result(tmp_path, monkeypatch, capsys):
    import math
    import struct
    env, state, client, _, _, _, preview = _tone_collection_preview(tmp_path, '2025.1', [],
        values={'waveform': 'sine', 'channel_layout': '7.1.4', 'frequency_hz': '800',
            'sample_rate_hz': '8000', 'bit_depth': 'float32', 'sustain_db': '-6',
            'attack_seconds': '0.0025', 'sustain_seconds': '0.005', 'release_seconds': '0.00375'})
    samples = []
    for frame in range(90):
        amplitude = frame / 20 if frame < 20 else (90 - frame) / 30 if frame >= 60 else 1
        samples.extend(.5011872336272722 * amplitude * math.sin(math.tau * frame / 10 + channel / 10)
            for channel in range(12))
    # Exact 7.1.4 speaker positions from the matching SDK AkSpeakerConfig.h.
    fmt = struct.pack('<HHIIHHHHI', 65534, 12, 8000, 384000, 48, 32, 22, 32, 185919)
    fmt += bytes.fromhex('0300000000001000800000aa00389b71')
    client.artifact_bytes = _tone_wav_bytes(floating=True, channels=12, samples=samples, fmt_override=fmt)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    actual_execute = gateway.execute_gateway
    observed_payloads = []
    def observe_actual_gateway(argv):
        result = actual_execute(argv)
        observed_payloads.append(result[1])
        return result
    with monkeypatch.context() as emitting:
        emitting.setenv('WAAPI_SKILL_CONFIG_PATH', env['WAAPI_SKILL_CONFIG_PATH'])
        emitting.setattr(gateway, 'default_client_factory', lambda _: client)
        emitting.setattr(gateway, 'execute_gateway', observe_actual_gateway)
        assert gateway.main([*state, 'verify', tx]) == 0
    rendered = capsys.readouterr().out
    decoded = json.loads(rendered)
    assert decoded['verified'] is True
    assert len(rendered.encode('utf-8')) <= 24576
    assert decoded['agent_result'] == observed_payloads[0]['agent_result']
    assert decoded['agent_result']['request'] == preview['agent_result']['request']
    assert list(decoded)[-1] == 'agent_result'
    assert [row[0] for row in client.calls].count('ak.wwise.debug.generateToneWAV') == 1


@pytest.mark.parametrize('version,large_markers', [('2024.1', False), ('2025.1', False), ('2025.1', True)],
    ids=['2024', '2025', '2025-large-markers'])
def test_tone_anonymous_override_uses_fifth_order_count_with_full_36_channel_proof_and_exact_terminal_result(tmp_path, monkeypatch, capsys, version, large_markers):
    import math
    import struct
    from wwise_waapi.canonical import canonical_sha256
    from wwise_waapi.transactions import TransactionStore
    markers = [token for _ in range(4) for token in ('--marker', '0', 'x' * 8192)] if large_markers else []
    env, state, client, _, schema, _, preview = _tone_collection_preview(tmp_path, version, markers,
        values={'waveform': 'sine', 'channel_layout': 'Ambisonics 5th order', 'anonymous_channels': 'true',
            'frequency_hz': '800', 'sample_rate_hz': '8000', 'bit_depth': 'float32', 'sustain_db': '-6',
            'attack_seconds': '0.0025', 'sustain_seconds': '0.005', 'release_seconds': '0.00375'})
    frozen_args = preview['agent_result']['request']['arguments']['args']
    assert frozen_args['channelConfig'] == 'Ambisonics 5th order' and frozen_args['setAnonymous'] is True
    assert 'anonymous_layout_override' in schema['business_adapter']['safety']['tone_artifact_verification']
    samples = []
    for frame in range(90):
        amplitude = frame / 20 if frame < 20 else (90 - frame) / 30 if frame >= 60 else 1
        samples.extend(.5011872336272722 * amplitude * math.sin(math.tau * frame / 10 + channel / 10)
            for channel in range(36))
    fmt = struct.pack('<HHIIHHHHI', 65534, 36, 8000, 1152000, 144, 32, 22, 32, 0)
    fmt += bytes.fromhex('0300000000001000800000aa00389b71')
    extra = _tone_marker_chunks([(identity, 0, b'x' * 8192) for identity in range(4)]) if large_markers else b''
    client.artifact_bytes = _tone_wav_bytes(floating=True, channels=36, samples=samples, fmt_override=fmt, extra=extra)
    tx = preview['transaction_id']
    _, shown = gateway.execute_gateway([*state, 'transaction-show', tx], env=env)
    code, confirmed = gateway.execute_gateway([*state, 'confirm', tx,
        '--confirmation-token', shown['confirmation']['token']], env=env)
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway([*state, 'execute', tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    actual_execute = gateway.execute_gateway
    observed_payloads = []
    def observe_actual_gateway(argv):
        result = actual_execute(argv)
        observed_payloads.append(result[1])
        return result
    with monkeypatch.context() as emitting:
        emitting.setenv('WAAPI_SKILL_CONFIG_PATH', env['WAAPI_SKILL_CONFIG_PATH'])
        emitting.setattr(gateway, 'default_client_factory', lambda _: client)
        emitting.setattr(gateway, 'execute_gateway', observe_actual_gateway)
        assert gateway.main([*state, 'verify', tx]) == 0
    rendered = capsys.readouterr().out
    decoded = json.loads(rendered)
    assert decoded['verified'] is True
    budget = 286720 if large_markers else 24576
    assert decoded['stdout_projection']['stdout_budget_bytes'] == budget
    assert len(rendered.encode('utf-8')) <= budget
    assert decoded['agent_result'] == observed_payloads[0]['agent_result']
    assert decoded['agent_result']['request'] == preview['agent_result']['request']
    assert list(decoded)[-1] == 'agent_result'
    journal = next(event['details']['verification'] for event in TransactionStore(Path(state[1])).read_events(tx)
        if event['event_type'] == 'verification_recorded')
    wav = journal['readbacks'][0]['wav']
    assert (wav['channels'], wav['speaker_mask']) == (36, 0)
    assert all([row['channel'] for row in segment['channels']] == list(range(36)) for segment in wav['sine_envelope']['segments'])
    assert decoded['stdout_projection']['verification_canonical_sha256'] == canonical_sha256(journal)
    assert [row[0] for row in client.calls].count('ak.wwise.debug.generateToneWAV') == 1
    (tmp_path / 'anonymous-36-terminal.stdout.json').write_text(rendered)


@pytest.mark.parametrize('version', ['2024.1', '2025.1'])
@pytest.mark.parametrize('anonymous', [None, 'false'])
def test_tone_genuine_ambisonics_still_rejects_nonsilence_before_native_dispatch(tmp_path, version, anonymous):
    values = {'waveform': 'sine', 'channel_layout': 'Ambisonics 5th order'}
    if anonymous is not None:
        values['anonymous_channels'] = anonymous
    rejected = _tone_collection_preview(tmp_path, version, [], values=values, reject_declaration=True)
    assert rejected['error_code'] == 'INVALID_ARGUMENT'
    assert rejected['details']['repair']['field'] == 'waveform'


def test_tone_2023_cannot_request_an_unavailable_anonymous_override_for_ambisonics(tmp_path):
    rejected = _tone_collection_preview(tmp_path, '2023.1', [], reject_declaration=True,
        values={'waveform': 'sine', 'channel_layout': 'Ambisonics 5th order', 'anonymous_channels': 'true'})
    assert rejected['error_code'] == 'GatewayInputError'

from __future__ import annotations

import importlib.util
import argparse
import json
import sys
from pathlib import Path

import pytest

from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
)
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.cli_console_business import (
    MAX_CLI_CONSOLE_COLLECTION_ITEMS,
    materialize_cli_console_business_request,
)
from wwise_waapi.cli_console_business_contracts import (
    CLI_CONSOLE_BUSINESS_OPERATIONS,
    cli_console_business_contract_data,
    cli_console_native_field_ownership,
)
from wwise_waapi.cli_console_business_cli import cli_console_plan_from_namespace
from wwise_waapi.manifest import ManifestStore
from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    operation_input_mode,
    parse_operation_request,
)
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.platform_commands import (
    decode_windows_model_argv,
    encode_windows_model_argv,
)


ALL = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
V22 = ("2022.1", "2023.1", "2024.1", "2025.1")
V23 = ("2023.1", "2024.1", "2025.1")
LANES = {
    "ak.wwise.cli.addNewPlatform": ALL,
    "ak.wwise.cli.convertExternalSource": ALL,
    "ak.wwise.cli.createNewProject": ALL,
    "ak.wwise.cli.dumpObjects": ALL,
    "ak.wwise.cli.generateSoundbank": ALL,
    "ak.wwise.cli.migrate": ALL,
    "ak.wwise.cli.moveMediaIdsToSingleFile": ALL,
    "ak.wwise.cli.moveMediaIdsToWorkUnits": ALL,
    "ak.wwise.cli.tabDelimitedImport": ALL,
    "ak.wwise.cli.updateMediaIdsInSingleFile": ALL,
    "ak.wwise.cli.verify": V22,
    "ak.wwise.cli.waapiServer": ALL,
    "ak.wwise.console.project.create": V23,
    "ak.wwise.console.project.open": V23,
}

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_cli_console_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


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


def _session(version: str, plan: dict[str, object]) -> BusinessDeclarationSession:
    return BusinessDeclarationSession.create(
        BusinessContext.create(
            task_authority="da1-" + "1" * 40,
            project_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
            project_path="/fixtures/SampleProject.wproj",
            wwise_version=version,
            wwise_build=f"{version}.fixture",
        )
    ).with_settings({"cli_console_plan": plan})


def test_cli_console_inventory_is_the_exact_65_row_issue_89_family() -> None:
    rows = sorted(
        f"{version}|function|{operation}"
        for operation, versions in LANES.items()
        for version in versions
    )

    assert set(CLI_CONSOLE_BUSINESS_OPERATIONS) == set(LANES)
    assert len(rows) == 65
    assert canonical_sha256(rows) == (
        "3f5b7464510f32b6f06dc4c6c3e0a7da700159ad07b8aff69b4b759bed41b9e1"
    )


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in LANES.items()
        for version in versions
    ],
)
def test_every_cli_console_lane_has_one_deep_business_entry(
    operation: str,
    version: str,
) -> None:
    contract = cli_console_business_contract_data(operation, version)

    assert operation_input_mode(operation, version) == BUSINESS_DECLARATION_INPUT_MODE
    assert contract["input_mode"] == BUSINESS_DECLARATION_INPUT_MODE
    assert contract["declaration"]["subcommand"] == (
        "draft-declare-cli-console-plan"
    )
    assert contract["declaration"]["settings_field"] == "cli_console_plan"
    assert contract["legacy_typed_call_public"] is False
    assert contract["legacy_native_option_assembly_public"] is False
    assert business_adapter(operation).family == "cli-console-business"
    assert business_adapter(operation).accepts_update_command(
        "draft-declare-cli-console-plan"
    )

    encoded = repr(contract)
    for native_leak in (
        "custom-global-opening-cmd",
        "custom-global-closing-cmd",
        "custom-pre-gen-cmd",
        "custom-post-gen-cmd",
        "no-source-control",
        "no-wwise-dat",
        "no-decode",
        "args",
        "options",
    ):
        assert native_leak not in encoded


def test_cli_console_schema_discloses_every_closed_scalar_choice() -> None:
    expected = {
        "soundbank_scope": ["all", "selected"],
        "verbosity": ["normal", "quiet", "verbose"],
        "source_control": ["disabled", "enabled"],
        "wwise_dat": ["omit", "write"],
        "decoded_media": ["omit", "write"],
        "tabular_import_mode": ["create", "replace", "reuse"],
        "content": ["names", "property_sets"],
        "migration_policy": ["fail", "migrate"],
    }

    disclosed: dict[str, list[str]] = {}
    for operation, versions in LANES.items():
        for version in versions:
            forms = cli_console_business_contract_data(operation, version)[
                "declaration"
            ]["input_forms"]
            for field, choices in expected.items():
                if field in forms:
                    assert forms[field]["choices"] == choices
                    disclosed[field] = choices

    assert disclosed == expected


def test_generate_soundbank_scope_is_explicit_and_gateway_owned() -> None:
    contract = cli_console_business_contract_data(
        "ak.wwise.cli.generateSoundbank",
        "2025.1",
    )["declaration"]

    assert "soundbank_scope" in contract["required_fields"]
    assert contract["input_forms"]["soundbank_scope"] == {
        "flag": "--value",
        "arguments": ["soundbank_scope", "<value>"],
        "repeatable": False,
        "choices": ["all", "selected"],
    }


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in LANES.items()
        for version in versions
    ],
)
def test_every_cli_console_lane_materializes_one_schema_valid_request(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    project = tmp_path / f"项目 {version}.wproj"
    plan: dict[str, object] = {}
    if not (
        operation == "ak.wwise.cli.waapiServer"
        and version in {"2023.1", "2024.1", "2025.1"}
    ):
        plan["project_file"] = str(project)
    if operation == "ak.wwise.cli.addNewPlatform":
        plan.update(base_platform="Windows", platform_name="Windows_Test")
    elif operation == "ak.wwise.cli.generateSoundbank":
        plan["soundbank_scope"] = "all"
    elif operation == "ak.wwise.cli.dumpObjects":
        plan["output_file"] = str(tmp_path / "对象.txt")
    elif operation == "ak.wwise.cli.tabDelimitedImport":
        plan["table_file"] = str(tmp_path / "Import.tsv")

    request = materialize_cli_console_business_request(
        operation,
        _session(version, plan),
    )

    assert request["arguments"]["api"] == operation
    parse_operation_request(request, expected_version=version)


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in LANES.items()
        for version in versions
    ],
)
def test_every_reflected_native_field_is_business_owned_or_prohibited(
    operation: str,
    version: str,
) -> None:
    manifest_root = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "waapi-skill"
        / "resources"
        / "manifest"
    )
    schemas = ManifestStore(root=manifest_root).load(version)["schemas"]
    row = next(item for item in schemas if item["uri"] == operation)
    reflected = set(row["schema"]["argsSchema"]["properties"])
    coverage = cli_console_native_field_ownership(operation, version)
    owned = {
        native
        for native_fields in coverage["owned"].values()
        for native in native_fields
    }

    assert owned | set(coverage["prohibited"]) == reflected
    assert owned.isdisjoint(coverage["prohibited"])


@pytest.mark.parametrize(
    ("operation", "version"),
    [
        (operation, version)
        for operation, versions in LANES.items()
        for version in versions
    ],
)
def test_every_cli_console_request_schema_hides_native_typed_construction(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    code, schema = gateway.execute_gateway(
        ["--version", version, "request-schema", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"offline schema connected to {url}"),
    )

    assert code == 0, schema
    assert schema["input_shape"] == "business_declaration"
    assert schema["native_request_fields_disclosed"] is False
    assert schema["continuation"] == {
        "subcommand": "draft-start",
        "gateway_argv": ["draft-start", operation],
        "copy_exactly": True,
        "append_arguments": "forbidden",
    }
    encoded = json.dumps(schema)
    assert '"fields"' not in encoded
    assert "request-map-container" not in encoded
    assert "request-array-item" not in encoded


def test_cli_console_draft_exposes_one_complete_plan_continuation(
    tmp_path: Path,
) -> None:
    operation = "ak.wwise.cli.generateSoundbank"
    code, started = gateway.execute_gateway(
        [
            "--version",
            "2025.1",
            "--state-dir",
            str(tmp_path / "state"),
            "draft-start",
            operation,
        ],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )

    assert code == 0, started
    continuation = started["draft"]["next_action_binding"]
    assert continuation["required_next_phase"] == (
        "declare_complete_cli_console_plan"
    )
    assert "draft-declare-cli-console-plan" in continuation["declaration"][
        "fixed_argv_prefix"
    ]
    assert continuation["declaration"]["submit_once"] is True
    assert continuation["declaration"]["native_request_input"] == "forbidden"


class _CliConsoleDraftClient:
    def __init__(
        self,
        tmp_path: Path,
        version: str = "2025.1",
        *,
        is_command_line: bool = True,
    ) -> None:
        self.version = version
        self.is_command_line = is_command_line
        self.project_file = tmp_path / "Sample Project.wproj"
        self.project_file.write_text("fixture", encoding="utf-8")

    def call(self, uri: str, args: object = None, options: object = None) -> object:
        if uri == "ak.wwise.core.getInfo":
            return {
                "displayName": "WwiseConsole",
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
        raise AssertionError(f"unexpected call {uri} {args} {options}")


def test_cli_console_plan_command_records_only_high_level_business_fields(
    tmp_path: Path,
) -> None:
    operation = "ak.wwise.cli.generateSoundbank"
    state_dir = tmp_path / "state"
    env = _env(tmp_path, "2025.1")
    client = _CliConsoleDraftClient(tmp_path)
    code, started = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-start", operation,
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started

    code, declared = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-declare-cli-console-plan",
            started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "1",
            "--value", "project_file", str(client.project_file),
            "--value", "soundbank_scope", "selected",
            "--item", "soundbanks", "Weather",
            "--item", "platforms", "Windows",
            "--value", "verbosity", "quiet",
            "--toggle", "generate_header", "enable",
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert code == 0, declared
    draft = declared["draft"]
    assert draft["next_action_binding"]["required_next_phase"] == (
        "check_complete_cli_console_plan"
    )
    record = OperationDraftStore(state_dir).inspect(
        draft["draft_id"],
        task_authority=started["task_authority"],
    )
    session = BusinessDeclarationSession.from_dict(
        record.composition["business_session"]
    )
    assert session.settings["cli_console_plan"] == {
        "project_file": str(client.project_file),
        "soundbank_scope": "selected",
        "soundbanks": ["Weather"],
        "platforms": ["Windows"],
        "verbosity": "quiet",
        "generate_header": True,
    }
    encoded = json.dumps(declared)
    assert "no-source-control" not in encoded
    assert "custom-post-gen-cmd" not in encoded


def test_cli_console_plan_rejects_authoring_host_before_project_probe(
    tmp_path: Path,
) -> None:
    operation = "ak.wwise.cli.generateSoundbank"
    state_dir = tmp_path / "state"
    env = _env(tmp_path, "2025.1")
    code, started = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-start", operation,
        ],
        env=env,
        client_factory=lambda url: pytest.fail(f"offline start connected to {url}"),
    )
    assert code == 0, started
    client = _CliConsoleDraftClient(
        tmp_path,
        is_command_line=False,
    )

    code, rejected = gateway.execute_gateway(
        [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-declare-cli-console-plan", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", "1",
            "--value", "project_file", str(client.project_file),
        ],
        env=env,
        client_factory=lambda _url: client,
    )

    assert code == 2
    assert rejected["status"] == "command_line_host_required"
    assert rejected["details"]["required_host"] == "wwise-console"
    assert OperationDraftStore(state_dir).inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    ).revision == 1


def test_cli_console_plan_rejects_collection_above_fixed_ceiling(
    tmp_path: Path,
) -> None:
    with pytest.raises(BusinessDeclarationError) as caught:
        materialize_cli_console_business_request(
            "ak.wwise.cli.generateSoundbank",
            _session(
                "2025.1",
                    {
                        "project_file": str(tmp_path / "Project.wproj"),
                        "soundbank_scope": "selected",
                        "soundbanks": [
                        f"Bank_{index}"
                        for index in range(MAX_CLI_CONSOLE_COLLECTION_ITEMS + 1)
                    ],
                },
            ),
        )

    assert caught.value.details["field"] == "soundbanks"


@pytest.mark.parametrize(
    "argv",
    (
        [
            "--version", "2025.1", "typed-call",
            "ak.wwise.cli.generateSoundbank", "--schema-digest", "stale",
        ],
        [
            "--version", "2025.1", "request-map-container",
            "ak.wwise.cli.generateSoundbank", "--map-handle", "legacy",
            "--key", "args", "--shape", "object",
        ],
    ),
)
def test_cli_console_legacy_typed_ingress_is_blocked_before_connection(
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


def test_cli_console_hostile_windows_business_values_round_trip_as_argv_data() -> None:
    project = r"C:\Wwise Projects\天气 & 100%!\Project 'A'.wproj"
    output = r"C:\Builds\$env:TEMP & whoami | out<file>^!%\Banks"
    namespace = argparse.Namespace(
        value=[
            ["project_file", project],
            ["soundbank_scope", "selected"],
            ["external_source_output_directory", output],
            ["verbosity", "quiet"],
        ],
        item=[["soundbanks", "Weather ' Main"]],
        mapping=[],
        toggle=[["generate_header", "enable"]],
    )

    plan = cli_console_plan_from_namespace(
        namespace,
        operation="ak.wwise.cli.generateSoundbank",
        version="2025.1",
    )
    argv = (
        "python",
        r"C:\WAAPI Skill\scripts\run.py",
        "gateway.py",
        "draft-declare-cli-console-plan",
        "od1-0123456789abcdef0123456789abcdef",
        "--value", "project_file", project,
        "--value", "external_source_output_directory", output,
        "--item", "soundbanks", "Weather ' Main",
    )

    assert plan["project_file"] == project
    assert plan["external_source_output_directory"] == output
    assert decode_windows_model_argv(encode_windows_model_argv(argv)) == argv


def test_operations_catalog_routes_cli_console_intent_to_request_schema(
    tmp_path: Path,
) -> None:
    code, payload = gateway.execute_gateway(
        ["operations", "--detail"],
        env=_env(tmp_path, "2025.1"),
        client_factory=lambda url: pytest.fail(f"offline catalog connected to {url}"),
    )

    assert code == 0, payload
    rows = {
        row["api"]: row
        for row in payload["request_schema_routes"]
        if row["api"] in CLI_CONSOLE_BUSINESS_OPERATIONS
    }
    assert set(rows) == set(CLI_CONSOLE_BUSINESS_OPERATIONS)
    assert rows["ak.wwise.cli.verify"]["supported_versions"] == list(V22)
    assert "generate SoundBanks" in rows[
        "ak.wwise.cli.generateSoundbank"
    ]["intent"]
    payload_keys = list(payload)
    assert payload_keys.index("routing_precedence") < payload_keys.index("operations")
    assert payload["routing_precedence"] == {
        "primary_media_import": {
            "match_terms": [
                "import media",
                "reimport media",
                "replace existing media",
                "replace media source",
                "导入媒体",
                "重新导入",
                "替换媒体",
            ],
            "choose": ["operation-schema", "audio.import"],
            "takes_precedence_over": [
                "operation-schema",
                "object.set",
            ],
            "rule": (
                "a primary media import, reimport, or media replacement uses "
                "audio.import even when it also updates properties, "
                "references, Events, or Switch assignments"
            ),
        },
        "explicit_cli_soundbank_generation": {
            "match_terms": ["WwiseConsole", "CLI", "command-line", "命令行"],
            "choose": [
                "request-schema",
                "ak.wwise.cli.generateSoundbank",
            ],
            "takes_precedence_over": [
                "operation-schema",
                "soundbank.generate",
            ],
            "rule": (
                "explicit command-line SoundBank generation uses the exact "
                "reflected CLI URI"
            ),
        },
        "exact_authoring_ui_command_id": {
            "match_example": "SaveProject",
            "choose": ["operation-schema", "ui.commands.execute"],
            "takes_precedence_over": [
                "request-schema",
                "ak.wwise.core.project.save",
            ],
            "rule": (
                "an exact CamelCase Wwise Authoring command ID named by the "
                "user is not a generic connected-project action"
            ),
        },
        "single_existing_object_edit": {
            "choose_by_outcome": {
                "rename": ["operation-schema", "object.setName"],
                "notes": ["operation-schema", "object.setNotes"],
                "scalar_property": [
                    "operation-schema",
                    "object.setProperty",
                ],
                "reference": [
                    "operation-schema",
                    "object.setReference",
                ],
            },
            "takes_precedence_over": ["operation-schema", "object.set"],
            "rule": (
                "one existing object's one requested edit uses its dedicated "
                "route; object.set is only for a larger atomic outcome"
            ),
        },
    }
    assert payload["selection_guidance"] == {
        "connected_project_save": {
            "choose": ["request-schema", "ak.wwise.core.project.save"],
            "use_when": "the user asks to save the connected project without naming a UI command ID",
            "never_substitute": ["operation-schema", "ui.commands.execute"],
        },
        "game_parameter_range": {
            "choose": ["request-schema", "ak.wwise.core.gameParameter.setRange"],
            "use_when": "the user asks to set one Game Parameter minimum and maximum",
            "never_substitute": [
                "operation-schema",
                "object.setProperty",
                "object.set",
            ],
        },
        "profiler_data_capture": {
            "choose": [
                "request-schema",
                "ak.wwise.core.profiler.enableProfilerData",
            ],
            "use_when": "the user asks to enable or disable named Profiler capture data",
            "never_guess_uri": True,
        },
        "runtime_event_action": {
            "choose": ["request-schema", "ak.soundengine.executeActionOnEvent"],
            "use_when": "the user asks to stop, pause, resume, or break one runtime Event",
            "never_substitute": ["operation-schema", "object.set"],
        },
    }


def test_add_platform_business_plan_derives_native_names(tmp_path) -> None:
    project = tmp_path / "项目 with spaces.wproj"
    request = materialize_cli_console_business_request(
        "ak.wwise.cli.addNewPlatform",
        _session(
            "2025.1",
            {
                "project_file": str(project),
                "base_platform": "Windows",
                "platform_name": "Windows_Studio",
                "copy_settings_from_platform": "Windows_Old",
            },
        ),
    )

    assert request["operation"] == "waapi.call"
    assert request["arguments"]["api"] == "ak.wwise.cli.addNewPlatform"
    assert request["arguments"]["args"] == {
        "project": str(project),
        "new-platform-base": "Windows",
        "new-platform-name": "Windows_Studio",
        "copy-from-platform": "Windows_Old",
    }
    assert request["arguments"]["io_root"] == str(tmp_path)
    parse_operation_request(request, expected_version="2025.1")


def test_generate_soundbank_plan_derives_flags_mappings_and_modes(tmp_path) -> None:
    project = tmp_path / "Project.wproj"
    table = tmp_path / "导入.tsv"
    definition = tmp_path / "Banks.txt"
    output = tmp_path / "Generated Banks"
    request = materialize_cli_console_business_request(
        "ak.wwise.cli.generateSoundbank",
        _session(
            "2025.1",
                {
                    "project_file": str(project),
                    "soundbank_scope": "selected",
                    "soundbanks": ["Weather", "Music"],
                "platforms": ["Windows", "Mac"],
                "languages": ["English(US)"],
                "definition_files": [str(definition)],
                "tabular_import_files": [str(table)],
                "tabular_import_mode": "reuse",
                "output_directories_by_platform": [
                    ["Windows", str(output / "Win")],
                    ["Mac", str(output / "Mac")],
                ],
                "soundbank_directories_by_platform": [
                    ["Windows", str(output / "Win" / "Banks")],
                ],
                "verbosity": "quiet",
                "source_control": "disabled",
                "decoded_media": "omit",
                "generate_header": True,
                "save_project": False,
            },
        ),
    )

    args = request["arguments"]["args"]
    assert args["project"] == str(project)
    assert args["bank"] == ["Weather", "Music"]
    assert args["platform"] == ["Windows", "Mac"]
    assert args["language"] == ["English(US)"]
    assert args["import-definition-file"] == [str(definition)]
    assert args["tab-delimited-import-file"] == [str(table)]
    assert args["tab-delimited-operation"] == "useExisting"
    assert args["output"] == [
        ["Windows", str(output / "Win")],
        ["Mac", str(output / "Mac")],
    ]
    assert args["soundbank-path"] == [
        "Windows",
        str(output / "Win" / "Banks"),
    ]
    assert args["quiet"] is True
    assert args["no-source-control"] is True
    assert args["no-decode"] is True
    assert args["header-file"] is True
    assert args["save"] is False
    assert "verbose" not in args
    assert str(output) in request["arguments"]["io_root"]
    parse_operation_request(request, expected_version="2025.1")


def test_generate_soundbank_keeps_relative_native_output_below_gateway_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "Project.wproj"
    request = materialize_cli_console_business_request(
        "ak.wwise.cli.generateSoundbank",
        _session(
            "2025.1",
                {
                    "project_file": str(project),
                    "soundbank_scope": "all",
                    "soundbank_directories_by_platform": [
                    ["Windows", "GeneratedSoundBanks/Windows"],
                ],
            },
        ),
    )

    assert request["arguments"]["args"]["soundbank-path"] == [
        "Windows",
        "GeneratedSoundBanks/Windows",
    ]
    assert request["arguments"]["io_root"] == str(tmp_path)
    parse_operation_request(request, expected_version="2025.1")


def test_generate_soundbank_all_scope_omits_native_bank_selector(tmp_path: Path) -> None:
    request = materialize_cli_console_business_request(
        "ak.wwise.cli.generateSoundbank",
        _session(
            "2025.1",
            {
                "project_file": str(tmp_path / "Project.wproj"),
                "soundbank_scope": "all",
            },
        ),
    )

    assert "bank" not in request["arguments"]["args"]


@pytest.mark.parametrize(
    "plan",
    (
        {"soundbank_scope": "all", "soundbanks": ["Weather"]},
        {"soundbank_scope": "selected"},
    ),
)
def test_generate_soundbank_scope_rejects_ambiguous_selection(
    tmp_path: Path,
    plan: dict[str, object],
) -> None:
    with pytest.raises(BusinessDeclarationError) as caught:
        materialize_cli_console_business_request(
            "ak.wwise.cli.generateSoundbank",
            _session(
                "2025.1",
                {"project_file": str(tmp_path / "Project.wproj"), **plan},
            ),
        )

    assert caught.value.details["field"] == "soundbanks"


def test_waapi_server_plan_joins_closed_allow_lists_and_derives_controls(
    tmp_path,
) -> None:
    project = tmp_path / "Server.wproj"
    request = materialize_cli_console_business_request(
        "ak.wwise.cli.waapiServer",
        _session(
            "2025.1",
            {
                "project_file": str(project),
                "allowed_addresses": ["127.0.0.1", "::1"],
                "allowed_origins": ["https://studio.example"],
                "wamp_port": 18080,
                "http_port": 18090,
                "wamp_max_clients": 4,
                "http_max_clients": 3,
                "allow_project_migration": False,
                "source_control": "disabled",
                "watchdog_seconds": 30,
            },
        ),
    )

    assert request["arguments"]["args"] == {
        "project": str(project),
        "allowed-addr": "127.0.0.1,::1",
        "allowed-origin": "https://studio.example",
        "wamp-port": 18080,
        "http-port": 18090,
        "wamp-max-clients": 4,
        "http-max-clients": 3,
        "allow-migration": False,
        "no-source-control": True,
        "watchdog-timeout": 30,
    }
    parse_operation_request(request, expected_version="2025.1")


def test_console_project_plans_derive_native_nested_platforms_and_policy(
    tmp_path,
) -> None:
    create_path = tmp_path / "新 Project.wproj"
    create = materialize_cli_console_business_request(
        "ak.wwise.console.project.create",
        _session(
            "2025.1",
            {
                "project_file": str(create_path),
                "languages": ["English(US)", "Japanese"],
                "platforms": [
                    ["Windows", "Windows_Studio"],
                    ["Mac", "Mac"],
                ],
            },
        ),
    )
    assert create["arguments"]["args"] == {
        "path": str(create_path),
        "languages": ["English(US)", "Japanese"],
        "platforms": [
            {"basePlatform": "Windows", "name": "Windows_Studio"},
            {"basePlatform": "Mac", "name": "Mac"},
        ],
    }
    parse_operation_request(create, expected_version="2025.1")

    opened = materialize_cli_console_business_request(
        "ak.wwise.console.project.open",
        _session(
            "2025.1",
            {
                "project_file": str(create_path),
                "auto_checkout": False,
                "migration_policy": "fail",
            },
        ),
    )
    assert opened["arguments"]["args"] == {
        "path": str(create_path),
        "autoCheckOutToSourceControl": False,
        "onMigrationRequired": "fail",
    }
    parse_operation_request(opened, expected_version="2025.1")


@pytest.mark.parametrize(
    ("version", "plan", "field"),
    [
        (
            "2021.1",
            {"project_file": "/tmp/P.wproj", "source_control": "disabled"},
            "source_control",
        ),
        (
            "2024.1",
            {"project_file": "/tmp/P.wproj", "wwise_dat": "omit"},
            "wwise_dat",
        ),
        (
            "2023.1",
            {"project_file": "/tmp/P.wproj", "watchdog_seconds": 1},
            "watchdog_seconds",
        ),
    ],
)
def test_version_specific_business_fields_fail_closed(
    version: str,
    plan: dict[str, object],
    field: str,
) -> None:
    operation = (
        "ak.wwise.cli.generateSoundbank"
        if field == "wwise_dat"
        else "ak.wwise.cli.waapiServer"
        if field == "watchdog_seconds"
        else "ak.wwise.cli.migrate"
    )
    with pytest.raises(BusinessDeclarationError) as caught:
        materialize_cli_console_business_request(
            operation,
            _session(version, plan),
        )
    assert caught.value.details["field"] == field

from __future__ import annotations

import json
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.execution_contracts import ExecutionContractRegistry
from wwise_waapi.io_policy import IOPolicyError, validate_isolated_io
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


VERSION = "2025.1"
SOURCE_CONTROL_VERSIONS = ("2023.1", "2024.1", "2025.1")
GENERATE_SOUNDBANK_RELATIVE_WRITE_CASES = tuple(
    (
        version,
        field,
        value,
        json_path,
        relative_target,
    )
    for version in SUPPORTED_WWISE_VERSION_KEYS
    for field, value, json_path, relative_target in (
        ("cache", "cache", "$.args.cache", "cache"),
        (
            "header-file-path",
            "generated/headers",
            "$.args.header-file-path",
            "generated/headers",
        ),
        (
            "root-output-path",
            "generated/root",
            "$.args.root-output-path",
            "generated/root",
        ),
        (
            "soundbank-path",
            ["Mac", "generated/Mac"],
            "$.args.soundbank-path[1]",
            "generated/Mac",
        ),
    )
    if field != "root-output-path" or version != "2021.1"
)


def _assert_error(error_code: str, **request):
    with pytest.raises(IOPolicyError) as caught:
        validate_isolated_io(**request)
    assert caught.value.error_code == error_code
    return caught.value


def test_every_versioned_isolated_function_has_one_successful_packaged_schema():
    registry = ExecutionContractRegistry()

    for version in SUPPORTED_WWISE_VERSION_KEYS:
        isolated = {
            entry.uri
            for entry in registry.entries(version)
            if entry.item_type == "function" and entry.route == "isolated_transaction"
        }
        schema_rows = registry.manifest_store.load(version)["schemas"]
        successful = {
            row["uri"]
            for row in schema_rows
            if row.get("status") == "ok" and isinstance(row.get("schema"), dict)
        }
        assert isolated
        assert isolated <= successful


def test_non_isolated_function_is_rejected_before_path_scanning():
    error = _assert_error(
        "NOT_ISOLATED_TRANSACTION",
        version=VERSION,
        uri="ak.wwise.core.ping",
        args={"path": "relative/path"},
    )
    assert error.details["route"] == "bounded_call"


def test_unknown_uri_has_structured_execution_contract_error():
    error = _assert_error(
        "EXECUTION_CONTRACT_ERROR",
        version=VERSION,
        uri="ak.wwise.does.notExist",
    )
    payload = error.as_dict()
    assert payload["ok"] is False
    assert payload["details"]["version"] == VERSION
    json.dumps(payload)


def test_read_only_project_path_is_absolute_and_audited_without_root(tmp_path: Path):
    project = tmp_path / "Project" / "Example.wproj"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.cli.verify",
        args={"project": str(project)},
    )

    assert audit.requires_io_root is False
    assert audit.io_root is None
    assert len(audit.read_paths) == 1
    assert audit.read_paths[0].json_path == "$.args.project"
    assert audit.read_paths[0].resolved_path == str(project.resolve())
    assert audit.read_paths[0].within_io_root is None
    assert audit.read_paths[0].manifest_declared is True


def test_relative_read_path_is_rejected(tmp_path: Path):
    _assert_error(
        "RELATIVE_IO_PATH",
        version=VERSION,
        uri="ak.wwise.core.sourceControl.getStatus",
        args={"files": ["Project/file.wwu", str(tmp_path / "absolute.wwu")]},
    )


def test_nested_nul_path_is_rejected_before_missing_root():
    error = _assert_error(
        "NUL_IN_IO_PATH",
        version=VERSION,
        uri="ak.wwise.core.soundbank.convertExternalSources",
        args={"sources": [{"input": "/tmp/source\x00.wsources", "platform": "Mac"}]},
    )
    assert error.details["json_path"] == "$.args.sources[0].input"


def test_write_path_requires_an_explicit_io_root(tmp_path: Path):
    _assert_error(
        "IO_ROOT_REQUIRED",
        version=VERSION,
        uri="ak.wwise.debug.generateToneWAV",
        args={"path": str(tmp_path / "tone.wav")},
    )


def test_write_path_inside_root_is_audited(tmp_path: Path):
    root = tmp_path / "sandbox"
    target = root / "generated" / "tone.wav"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.debug.generateToneWAV",
        args={"path": str(target)},
        io_root=root,
    )

    assert audit.requires_io_root is True
    assert audit.io_root == str(root.resolve())
    assert len(audit.write_paths) == 1
    assert audit.write_paths[0].resolved_path == str(target.resolve())
    assert audit.write_paths[0].within_io_root is True
    assert audit.explicit_write_confinement_proven is True
    assert audit.implicit_write_confinement_proven is None


def test_write_path_outside_root_is_rejected(tmp_path: Path):
    root = tmp_path / "sandbox"
    target = tmp_path / "outside" / "tone.wav"

    error = _assert_error(
        "IO_PATH_OUTSIDE_ROOT",
        version=VERSION,
        uri="ak.wwise.debug.generateToneWAV",
        args={"path": str(target)},
        io_root=root,
    )
    assert error.details["resolved_path"] == str(target.resolve())


def test_existing_symlink_cannot_escape_write_root(tmp_path: Path):
    root = tmp_path / "sandbox"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    error = _assert_error(
        "IO_PATH_OUTSIDE_ROOT",
        version=VERSION,
        uri="ak.wwise.debug.generateToneWAV",
        args={"path": str(root / "escape" / "tone.wav")},
        io_root=root,
    )
    assert error.details["resolved_path"] == str((outside / "tone.wav").resolve())


def test_io_root_must_be_absolute(tmp_path: Path):
    _assert_error(
        "RELATIVE_IO_PATH",
        version=VERSION,
        uri="ak.wwise.debug.generateToneWAV",
        args={"path": str(tmp_path / "tone.wav")},
        io_root="relative-sandbox",
    )


def test_filesystem_root_is_not_a_write_boundary(tmp_path: Path):
    _assert_error(
        "IO_ROOT_TOO_BROAD",
        version=VERSION,
        uri="ak.wwise.debug.generateToneWAV",
        args={"path": str(tmp_path / "tone.wav")},
        io_root=Path("/"),
    )


def test_read_input_may_be_outside_root_but_remains_in_audit(tmp_path: Path):
    root = tmp_path / "sandbox"
    source = tmp_path / "source" / "external.wsources"
    output = root / "converted"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.core.soundbank.convertExternalSources",
        args={
            "sources": [
                {"input": str(source), "output": str(output), "platform": "Mac"}
            ]
        },
        io_root=root,
    )

    assert [(item.field, item.role, item.within_io_root) for item in audit.paths] == [
        ("input", "read", False),
        ("output", "write", True),
    ]
    assert audit.implicit_writes


def test_wwise_managed_paths_are_not_misclassified_as_absolute_os_paths(tmp_path: Path):
    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.core.audio.import",
        args={
            "imports": [
                {
                    "objectPath": r"\\Actor-Mixer Hierarchy\\Default Work Unit\\<Sound>Bird",
                    "importLocation": r"\\Actor-Mixer Hierarchy\\Default Work Unit",
                    "originalsSubFolder": r"Birds\\Ambient",
                }
            ]
        },
        io_root=tmp_path / "sandbox",
    )

    assert audit.paths == ()
    assert audit.requires_io_root is True
    assert audit.implicit_writes
    assert audit.explicit_write_confinement_proven is None
    assert audit.implicit_write_confinement_proven is False


def test_platform_path_array_audits_only_path_positions(tmp_path: Path):
    root = tmp_path / "sandbox"
    project = tmp_path / "Project.wproj"
    windows_output = root / "Windows"
    mac_output = root / "Mac"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.cli.convertExternalSource",
        args={
            "project": str(project),
            "output": ["Windows", str(windows_output), "Mac", str(mac_output)],
        },
        io_root=root,
    )

    assert [item.raw_path for item in audit.paths] == [
        str(project),
        str(windows_output),
        str(mac_output),
    ]
    assert [item.role for item in audit.paths] == ["read", "write", "write"]


def test_nested_platform_pair_arrays_audit_only_pair_path_positions(tmp_path: Path):
    root = tmp_path / "sandbox"
    project = tmp_path / "Project.wproj"
    windows_source = tmp_path / "inputs" / "windows.wsources"
    mac_source = tmp_path / "inputs" / "mac.wsources"
    windows_output = root / "Windows"
    mac_output = root / "Mac"

    audit = validate_isolated_io(
        version="2022.1",
        uri="ak.wwise.cli.convertExternalSource",
        args={
            "project": str(project),
            "source-by-platform": [
                ["Windows", str(windows_source)],
                ["Mac", str(mac_source)],
            ],
            "output": [
                ["Windows", str(windows_output)],
                ["Mac", str(mac_output)],
            ],
        },
        io_root=root,
    )

    assert [(item.json_path, item.raw_path, item.role) for item in audit.paths] == [
        ("$.args.project", str(project), "read"),
        ("$.args.source-by-platform[0][1]", str(windows_source), "read"),
        ("$.args.source-by-platform[1][1]", str(mac_source), "read"),
        ("$.args.output[0][1]", str(windows_output), "write"),
        ("$.args.output[1][1]", str(mac_output), "write"),
    ]
    assert audit.explicit_write_confinement_proven is True


def test_generate_soundbank_nested_platform_pairs_share_the_same_closed_audit_shape(
    tmp_path: Path,
):
    root = tmp_path / "sandbox"
    project = tmp_path / "Project.wproj"

    audit = validate_isolated_io(
        version="2022.1",
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(project),
            "soundbank-path": [
                ["Windows", str(root / "Windows")],
                ["Mac", str(root / "Mac")],
            ],
            "cache": str(root / "cache"),
            "root-output-path": str(root),
        },
        io_root=root,
    )

    assert [(item.json_path, item.role) for item in audit.paths] == [
        ("$.args.project", "read"),
        ("$.args.soundbank-path[0][1]", "write"),
        ("$.args.soundbank-path[1][1]", "write"),
        ("$.args.cache", "write"),
        ("$.args.root-output-path", "write"),
    ]


@pytest.mark.parametrize(
    "value",
    (
        [["Windows"]],
        [["Windows", "/tmp/windows"], ["Mac", 7]],
        [["Windows", "/tmp/windows"], "Mac", "/tmp/mac"],
    ),
)
def test_malformed_or_mixed_nested_platform_pairs_fail_closed(
    tmp_path: Path,
    value: list[object],
):
    error = _assert_error(
        "AMBIGUOUS_PLATFORM_PATH_MAPPING",
        version="2022.1",
        uri="ak.wwise.cli.convertExternalSource",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "output": value,
        },
        io_root=tmp_path,
    )
    assert error.details["json_path"] == "$.args.output"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_generate_soundbank_bank_file_selector_is_audited_without_treating_names_as_paths(
    tmp_path: Path,
    version: str,
):
    root = tmp_path / "sandbox"
    project = tmp_path / "Project.wproj"
    bank_list = tmp_path / "inputs" / "banks.txt"

    audit = validate_isolated_io(
        version=version,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(project),
            "bank": ["Main", str(bank_list)],
        },
        io_root=root,
    )

    assert [(item.json_path, item.role) for item in audit.paths] == [
        ("$.args.project", "read"),
        ("$.args.bank[1]", "read"),
    ]
    assert audit.paths[1].manifest_declared is True
    assert audit.paths[1].schema_ref is not None


def test_generate_soundbank_relative_bank_file_selector_fails_closed(tmp_path: Path):
    error = _assert_error(
        "RELATIVE_IO_PATH",
        version=VERSION,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "bank": ["Main", "inputs/banks.txt"],
        },
        io_root=tmp_path / "sandbox",
    )
    assert error.details["json_path"] == "$.args.bank[1]"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_generate_soundbank_import_without_save_keeps_project_read_only(
    tmp_path: Path,
    version: str,
):
    root = tmp_path / "sandbox"
    project = tmp_path / "Project.wproj"
    definition = tmp_path / "inputs" / "banks.tsv"

    audit = validate_isolated_io(
        version=version,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(project),
            "import-definition-file": [str(definition)],
            "save": False,
        },
        io_root=root,
    )

    assert [(item.field, item.role) for item in audit.paths] == [
        ("project", "read"),
        ("import-definition-file", "read"),
    ]
    assert all(item.manifest_declared for item in audit.paths)


def test_generate_soundbank_save_confines_the_project_path(tmp_path: Path):
    root = tmp_path / "sandbox"
    project = root / "Project.wproj"
    definition = tmp_path / "inputs" / "banks.tsv"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(project),
            "import-definition-file": str(definition),
            "save": True,
        },
        io_root=root,
    )

    assert [(item.field, item.role, item.within_io_root) for item in audit.paths] == [
        ("project", "write", True),
        ("import-definition-file", "read", False),
    ]


@pytest.mark.parametrize(
    "version,field,value,json_path,relative_target",
    GENERATE_SOUNDBANK_RELATIVE_WRITE_CASES,
)
def test_generate_soundbank_manifest_relative_write_paths_resolve_under_io_root(
    tmp_path: Path,
    version: str,
    field: str,
    value: str | list[str],
    json_path: str,
    relative_target: str,
):
    root = tmp_path / "sandbox"
    project = tmp_path / "Project.wproj"

    audit = validate_isolated_io(
        version=version,
        uri="ak.wwise.cli.generateSoundbank",
        args={"project": str(project), field: value},
        io_root=root,
    )

    assert len(audit.write_paths) == 1
    write = audit.write_paths[0]
    assert write.json_path == json_path
    assert write.raw_path == relative_target
    assert write.resolved_path == str((root / relative_target).resolve())
    assert write.within_io_root is True
    assert write.manifest_declared is True
    assert audit.explicit_write_confinement_proven is True


def test_generate_soundbank_relative_write_still_requires_io_root(tmp_path: Path):
    _assert_error(
        "IO_ROOT_REQUIRED",
        version=VERSION,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "cache": "cache",
        },
    )


def test_generate_soundbank_relative_read_path_is_still_rejected(tmp_path: Path):
    error = _assert_error(
        "RELATIVE_IO_PATH",
        version=VERSION,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "source-file": "inputs/external.wsources",
        },
        io_root=tmp_path / "sandbox",
    )
    assert error.details["json_path"] == "$.args.source-file"


def test_generate_soundbank_unlisted_relative_output_is_rejected(tmp_path: Path):
    error = _assert_error(
        "RELATIVE_IO_PATH",
        version=VERSION,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "output": "generated/external-sources",
        },
        io_root=tmp_path / "sandbox",
    )
    assert error.details["json_path"] == "$.args.output"


def test_generate_soundbank_undeclared_version_field_cannot_gain_relative_access(
    tmp_path: Path,
):
    error = _assert_error(
        "RELATIVE_IO_PATH",
        version="2021.1",
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "root-output-path": "generated/root",
        },
        io_root=tmp_path / "sandbox",
    )
    assert error.details["json_path"] == "$.args.root-output-path"


def test_generate_soundbank_relative_parent_traversal_is_rejected(tmp_path: Path):
    root = tmp_path / "sandbox"
    error = _assert_error(
        "IO_PATH_OUTSIDE_ROOT",
        version=VERSION,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "root-output-path": "../outside",
        },
        io_root=root,
    )
    assert error.details["resolved_path"] == str((tmp_path / "outside").resolve())


def test_generate_soundbank_relative_symlink_cannot_escape_io_root(tmp_path: Path):
    root = tmp_path / "sandbox"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    error = _assert_error(
        "IO_PATH_OUTSIDE_ROOT",
        version=VERSION,
        uri="ak.wwise.cli.generateSoundbank",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "cache": "escape/cache",
        },
        io_root=root,
    )
    assert error.details["resolved_path"] == str((outside / "cache").resolve())


def test_odd_platform_path_array_fails_closed(tmp_path: Path):
    _assert_error(
        "AMBIGUOUS_PLATFORM_PATH_MAPPING",
        version=VERSION,
        uri="ak.wwise.cli.convertExternalSource",
        args={
            "project": str(tmp_path / "Project.wproj"),
            "output": ["Windows", str(tmp_path / "Windows"), "Mac"],
        },
        io_root=tmp_path / "sandbox",
    )


def test_implicit_write_requires_root_without_an_explicit_output_path(tmp_path: Path):
    _assert_error(
        "IO_ROOT_REQUIRED",
        version=VERSION,
        uri="ak.wwise.core.audio.convert",
        args={},
    )

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.core.audio.convert",
        args={},
        io_root=tmp_path / "sandbox",
    )
    assert audit.paths == ()
    assert audit.requires_io_root is True
    assert audit.implicit_writes
    assert audit.implicit_write_confinement_proven is False


def test_boolean_header_file_switch_is_not_misclassified_as_a_path(tmp_path: Path):
    project = tmp_path / "Project.wproj"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.cli.generateSoundbank",
        args={"project": str(project), "header-file": True},
        io_root=tmp_path / "sandbox",
    )

    assert [(item.field, item.role) for item in audit.paths] == [("project", "read")]
    assert audit.implicit_write_confinement_proven is False


def test_soundbank_disk_write_flag_dynamically_requires_root(tmp_path: Path):
    memory_only = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.core.soundbank.generate",
        args={"writeToDisk": False},
    )
    assert memory_only.requires_io_root is False

    _assert_error(
        "IO_ROOT_REQUIRED",
        version=VERSION,
        uri="ak.wwise.core.soundbank.generate",
        args={"writeToDisk": True},
    )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_isolated_screen_capture_has_no_filesystem_requirement(version: str):
    audit = validate_isolated_io(
        version=version,
        uri="ak.wwise.ui.captureScreen",
        args={"viewName": "Designer"},
    )

    assert audit.paths == ()
    assert audit.requires_io_root is False
    assert audit.io_root is None


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_cli_output_is_confined_while_project_is_a_read_input(
    tmp_path: Path,
    version: str,
):
    root = tmp_path / "sandbox"
    project = tmp_path / "Project.wproj"
    output = root / "objects.json"

    audit = validate_isolated_io(
        version=version,
        uri="ak.wwise.cli.dumpObjects",
        args={"project": str(project), "output": str(output)},
        io_root=root,
    )

    assert [(item.field, item.role, item.within_io_root) for item in audit.paths] == [
        ("project", "read", False),
        ("output", "write", True),
    ]


@pytest.mark.parametrize("version", SOURCE_CONTROL_VERSIONS)
def test_source_control_originals_folder_is_a_wwise_relative_selector(
    version: str,
):
    audit = validate_isolated_io(
        version=version,
        uri="ak.wwise.core.sourceControl.getSourceFiles",
        args={"folder": r"Voices\\English(US)", "recursive": True},
    )

    assert audit.paths == ()
    assert audit.requires_io_root is False
    assert audit.io_root is None


@pytest.mark.parametrize("version", SOURCE_CONTROL_VERSIONS)
def test_reflected_source_control_file_array_remains_manifest_declared(
    tmp_path: Path,
    version: str,
):
    source = tmp_path / "Project" / "file.wwu"
    audit = validate_isolated_io(
        version=version,
        uri="ak.wwise.core.sourceControl.getStatus",
        args={"files": [str(source)]},
    )

    assert len(audit.read_paths) == 1
    assert audit.read_paths[0].manifest_declared is True
    assert audit.read_paths[0].schema_ref is not None


def test_project_mutating_cli_confines_the_project_path(tmp_path: Path):
    root = tmp_path / "sandbox"
    project = root / "Project.wproj"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.cli.migrate",
        args={"project": str(project)},
        io_root=root,
    )

    assert len(audit.write_paths) == 1
    assert audit.write_paths[0].field == "project"
    assert audit.write_paths[0].within_io_root is True


def test_console_project_open_is_treated_as_a_write_capable_path(tmp_path: Path):
    root = tmp_path / "sandbox"
    project = root / "Project.wproj"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.console.project.open",
        args={"path": str(project)},
        io_root=root,
    )

    assert len(audit.write_paths) == 1
    assert audit.write_paths[0].json_path == "$.args.path"


@pytest.mark.parametrize(
    ("version", "uri"),
    (
        ("2021.1", "ak.wwise.ui.project.open"),
        ("2022.1", "ak.wwise.ui.project.open"),
        ("2023.1", "ak.wwise.ui.project.open"),
        ("2023.1", "ak.wwise.ui.project.create"),
    ),
)
def test_ui_project_transitions_confine_the_target_project_path(
    tmp_path: Path,
    version: str,
    uri: str,
):
    root = tmp_path / "sandbox"
    project = root / "Project" / "Project.wproj"

    audit = validate_isolated_io(
        version=version,
        uri=uri,
        args={"path": str(project)},
        io_root=root,
    )

    assert len(audit.write_paths) == 1
    assert audit.write_paths[0].json_path == "$.args.path"
    assert audit.write_paths[0].within_io_root is True


def test_unknown_nested_options_path_fails_conservatively_into_write_audit(tmp_path: Path):
    root = tmp_path / "sandbox"
    target = root / "request.log"

    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.ui.captureScreen",
        options={"diagnostics": {"outputFile": str(target)}},
        io_root=root,
    )

    assert len(audit.write_paths) == 1
    assert audit.write_paths[0].json_path == "$.options.diagnostics.outputFile"
    assert audit.write_paths[0].manifest_declared is False


def test_non_object_args_are_rejected_with_json_safe_details():
    error = _assert_error(
        "INVALID_IO_REQUEST",
        version=VERSION,
        uri="ak.wwise.ui.captureScreen",
        args=[],  # type: ignore[arg-type]
    )
    assert error.details == {"section": "args", "actual_type": "list"}
    json.dumps(error.as_dict())


def test_successful_audit_serializes_as_stable_structured_data(tmp_path: Path):
    project = tmp_path / "Project.wproj"
    audit = validate_isolated_io(
        version=VERSION,
        uri="ak.wwise.cli.verify",
        args={"project": str(project)},
    )

    payload = audit.as_dict()
    assert payload["contract"] == "waapi-skill.isolated-io-audit/v1"
    assert payload["ok"] is True
    assert payload["path_count"] == 1
    assert payload["read_path_count"] == 1
    assert payload["write_path_count"] == 0
    assert payload["confinement_scope"] == "explicit_write_paths_only"
    assert payload["implicit_write_confinement_proven"] is None
    json.dumps(payload)

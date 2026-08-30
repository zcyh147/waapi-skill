from __future__ import annotations

import os
from pathlib import Path
from pathlib import PureWindowsPath

import pytest

from wwise_waapi.io_policy import validate_isolated_io  # pyright: ignore[reportMissingImports]
from wwise_waapi.platform_paths import (  # pyright: ignore[reportMissingImports]
    WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE,
    WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT,
    WwiseWirePathError,
    adapt_cli_dispatch_paths,
    build_wwise_console_command,
    requires_wwise_wire_path_adaptation,
    resolve_windows_wwise_console_from_env,
    windows_wwise_console_path,
)


def test_windows_wwiseroot_template_uses_required_backslash_strategy() -> None:
    assert WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE == r"%WWISEROOT%\Authoring\x64\Release\bin\WwiseConsole.exe"
    assert str(windows_wwise_console_path("%WWISEROOT%")) == WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE


def test_windows_wwiseroot_resolution_preserves_spaces_and_backslashes() -> None:
    resolved = resolve_windows_wwise_console_from_env(
        {"WWISEROOT": r"C:\Program Files\Audiokinetic\Wwise 2022.1"}
    )

    assert resolved == PureWindowsPath(r"C:\Program Files\Audiokinetic\Wwise 2022.1\Authoring\x64\Release\bin\WwiseConsole.exe")
    assert str(resolved) == r"C:\Program Files\Audiokinetic\Wwise 2022.1\Authoring\x64\Release\bin\WwiseConsole.exe"


def test_windows_wwiseroot_resolution_returns_none_without_env() -> None:
    assert resolve_windows_wwise_console_from_env({}) is None


def test_wwise_console_command_is_shell_safe_argument_list_with_spaces() -> None:
    console_path = PureWindowsPath(r"C:\Program Files\Audiokinetic\Wwise 2022.1\Authoring\x64\Release\bin\WwiseConsole.exe")
    project_path = PureWindowsPath(r"D:\Fixture Projects\Wwise Sample\Sample Project.wproj")

    command = build_wwise_console_command(console_path, 26443, project_path=project_path, extra_args=["--verbose"])

    assert command == [
        str(console_path),
        "waapi-server",
        str(project_path),
        "--wamp-port",
        "26443",
        "--http-port",
        "0",
        "--verbose",
    ]
    assert isinstance(command, list)
    assert "Program Files" in command[0]
    assert "Fixture Projects" in command[2]


def _wine_project_guard(home: Path, project: Path, *, host: str = "127.0.0.1") -> dict[str, object]:
    relative = project.relative_to(home)
    return {
        "fingerprint": "guard-sha256",
        "endpoint": {"host": host, "port": 8080},
        "wwise": {
            "platform": "x64",
            "processPath": r"c:\Program Files\Audiokinetic\Wwise\WwiseConsole.exe",
        },
        "project": {
            "state": "open",
            "path": "\\",
            "filePath": "Y:\\" + "\\".join(relative.parts),
        },
    }


def _io_audit(uri: str, paths: list[tuple[str, str, str, str]]) -> dict[str, object]:
    return {
        "uri": uri,
        "paths": [
            {
                "section": section,
                "json_path": json_path,
                "raw_path": raw_path,
                "resolved_path": resolved_path,
            }
            for section, json_path, raw_path, resolved_path in paths
        ],
    }


def _wine_no_project_transition_guard(
    target_project: Path,
    *,
    canonical_path: str | None = None,
) -> dict[str, object]:
    return {
        "fingerprint": "no-project-transition-sha256",
        "endpoint": {"host": "127.0.0.1", "port": 8080},
        "wwise": {
            "platform": "x64",
            "processPath": r"c:\Program Files\Audiokinetic\Wwise\Wwise.exe",
        },
        "project_guard_mode": "transition_to_path",
        "project": {"state": "none"},
        "postcondition": {
            "state": "open",
            "canonical_path": canonical_path or f"posix:{target_project.resolve()}",
        },
    }


def test_local_wine_cli_dispatch_translates_only_exact_audited_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "case" / "business-host" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project/>", encoding="utf-8")
    target = home / "case" / "project" / "SampleProject.wproj"
    manifest = home / "case" / "assets" / "delivery.wsources"
    output = home / "case" / "output"
    args = {
        "project": str(target),
        "platform": ["Windows"],
        "source-file": str(manifest),
        "output": ["Windows", str(output)],
        "note": str(manifest),
    }
    audit = _io_audit(
        "ak.wwise.cli.convertExternalSource",
        [
            ("args", "$.args.project", str(target), str(target.resolve())),
            ("args", "$.args.source-file", str(manifest), str(manifest.resolve())),
            ("args", "$.args.output[1]", str(output), str(output.resolve())),
        ],
    )

    adapted = adapt_cli_dispatch_paths(
        uri="ak.wwise.cli.convertExternalSource",
        args=args,
        options={},
        io_audit=audit,
        project_guard=_wine_project_guard(home, project),
        host_os_name="posix",
        account_home=home,
    )

    assert adapted.args == {
        "project": r"Y:\case\project\SampleProject.wproj",
        "platform": ["Windows"],
        "source-file": r"Y:\case\assets\delivery.wsources",
        "output": ["Windows", r"Y:\case\output"],
        "note": str(manifest),
    }
    assert args["project"] == str(target)
    assert adapted.proof["applied"] is True
    assert adapted.proof["translated_path_count"] == 3
    assert adapted.proof["project_guard_fingerprint"] == "guard-sha256"
    assert all(row["round_trip_verified"] is True for row in adapted.proof["path_bindings"])
    assert adapted.proof["mapping"]["anchor_drive"] == "Y"
    assert adapted.proof["host_dispatch_sha256"] != adapted.proof["wire_dispatch_sha256"]


@pytest.mark.parametrize(
    "uri",
    (
        "ak.wwise.console.project.create",
        "ak.wwise.console.project.open",
    ),
)
def test_local_wine_console_project_dispatch_translates_the_audited_path(
    tmp_path: Path,
    uri: str,
) -> None:
    home = tmp_path / "home"
    active_project = home / "case" / "active" / "SampleProject.wproj"
    target_project = home / "case" / "target" / "TargetProject.wproj"
    active_project.parent.mkdir(parents=True)
    active_project.write_text("<Project/>", encoding="utf-8")
    target_project.parent.mkdir(parents=True)
    target_project.write_text("<Project/>", encoding="utf-8")
    args = {"path": str(target_project)}

    adapted = adapt_cli_dispatch_paths(
        uri=uri,
        args=args,
        options={},
        io_audit=_io_audit(
            uri,
            [("args", "$.args.path", str(target_project), str(target_project.resolve()))],
        ),
        project_guard=_wine_project_guard(home, active_project),
        host_os_name="posix",
        account_home=home,
    )

    assert requires_wwise_wire_path_adaptation(uri) is True
    assert adapted.args == {"path": r"Y:\case\target\TargetProject.wproj"}
    assert adapted.proof["mode"] == "local_posix_wine"
    assert adapted.proof["translated_path_count"] == 1


@pytest.mark.parametrize(
    ("uri", "target_exists"),
    (
        ("ak.wwise.ui.project.open", True),
        ("ak.wwise.ui.project.create", False),
    ),
)
@pytest.mark.skipif(
    os.name == "nt",
    reason="This test simulates local POSIX Wine drive translation",
)
def test_local_wine_authoring_project_transition_without_current_project_uses_target_anchor(
    tmp_path: Path,
    uri: str,
    target_exists: bool,
) -> None:
    home = tmp_path / "home"
    target_project = home / "case" / "target" / "TargetProject.wproj"
    target_project.parent.mkdir(parents=True)
    if target_exists:
        target_project.write_text("<Project/>", encoding="utf-8")
    guard = _wine_no_project_transition_guard(target_project)

    adapted = adapt_cli_dispatch_paths(
        uri=uri,
        args={"path": str(target_project)},
        options={},
        io_audit=_io_audit(
            uri,
            [
                (
                    "args",
                    "$.args.path",
                    str(target_project),
                    str(target_project.resolve()),
                )
            ],
        ),
        project_guard=guard,
        current_project_guard=guard,
        host_os_name="posix",
        account_home=home,
    )

    assert requires_wwise_wire_path_adaptation(uri) is True
    assert adapted.args == {"path": r"Y:\case\target\TargetProject.wproj"}
    assert adapted.proof["mode"] == "local_posix_wine"
    assert adapted.proof["mapping"]["anchor_source"] == "transition_target"
    assert adapted.proof["translated_path_count"] == 1


@pytest.mark.skipif(
    os.name == "nt",
    reason="This test simulates local POSIX Wine drive translation",
)
def test_local_wine_authoring_transition_target_preserves_complex_posix_spelling(
    tmp_path: Path,
) -> None:
    home = tmp_path / "HomeCase"
    target_project = (
        home / "Space Ω $&;'() [Case]" / "TargetProject.WPROJ"
    )
    target_project.parent.mkdir(parents=True)
    target_project.write_text("<Project/>", encoding="utf-8")
    uri = "ak.wwise.ui.project.open"
    guard = _wine_no_project_transition_guard(target_project)

    adapted = adapt_cli_dispatch_paths(
        uri=uri,
        args={"path": str(target_project)},
        options={},
        io_audit=_io_audit(
            uri,
            [
                (
                    "args",
                    "$.args.path",
                    str(target_project),
                    str(target_project.resolve()),
                )
            ],
        ),
        project_guard=guard,
        current_project_guard=guard,
        host_os_name="posix",
        account_home=home,
    )

    assert adapted.args == {
        "path": "Y:\\Space Ω $&;'() [Case]\\TargetProject.WPROJ"
    }


@pytest.mark.parametrize(
    "canonical_path",
    (
        r"windows:c:\projects\TargetProject.wproj",
        r"windows:\\server\share\TargetProject.wproj",
        "posix:/tmp/case/../TargetProject.wproj",
    ),
)
def test_local_wine_authoring_transition_target_rejects_non_posix_or_traversal_flavors(
    tmp_path: Path,
    canonical_path: str,
) -> None:
    home = tmp_path / "home"
    target_project = home / "case" / "TargetProject.wproj"
    target_project.parent.mkdir(parents=True)
    target_project.write_text("<Project/>", encoding="utf-8")
    uri = "ak.wwise.ui.project.open"
    guard = _wine_no_project_transition_guard(
        target_project,
        canonical_path=canonical_path,
    )

    with pytest.raises(WwiseWirePathError) as rejected:
        adapt_cli_dispatch_paths(
            uri=uri,
            args={"path": str(target_project)},
            options={},
            io_audit=_io_audit(
                uri,
                [
                    (
                        "args",
                        "$.args.path",
                        str(target_project),
                        str(target_project.resolve()),
                    )
                ],
            ),
            project_guard=guard,
            current_project_guard=guard,
            host_os_name="posix",
            account_home=home,
        )

    assert rejected.value.error_code == "WIRE_PATH_CONTEXT_UNAVAILABLE"


@pytest.mark.skipif(
    os.name == "nt",
    reason="A backslash is a native separator on Windows",
)
def test_local_wine_authoring_transition_target_rejects_mixed_separator_component(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    target_project = home / "case\\mixed" / "TargetProject.wproj"
    target_project.parent.mkdir(parents=True)
    target_project.write_text("<Project/>", encoding="utf-8")
    uri = "ak.wwise.ui.project.open"
    guard = _wine_no_project_transition_guard(target_project)

    with pytest.raises(WwiseWirePathError) as rejected:
        adapt_cli_dispatch_paths(
            uri=uri,
            args={"path": str(target_project)},
            options={},
            io_audit=_io_audit(
                uri,
                [
                    (
                        "args",
                        "$.args.path",
                        str(target_project),
                        str(target_project.resolve()),
                    )
                ],
            ),
            project_guard=guard,
            current_project_guard=guard,
            host_os_name="posix",
            account_home=home,
        )

    assert rejected.value.error_code == "WIRE_PATH_COMPONENT_UNSAFE"


@pytest.mark.skipif(
    os.name == "nt",
    reason="This test simulates local POSIX Wine drive translation",
)
def test_local_wine_authoring_transition_target_rejects_audit_path_drift(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    target_project = home / "case" / "TargetProject.wproj"
    other_project = home / "other" / "OtherProject.wproj"
    for path in (target_project, other_project):
        path.parent.mkdir(parents=True)
        path.write_text("<Project/>", encoding="utf-8")
    uri = "ak.wwise.ui.project.open"
    guard = _wine_no_project_transition_guard(target_project)

    with pytest.raises(WwiseWirePathError) as rejected:
        adapt_cli_dispatch_paths(
            uri=uri,
            args={"path": str(other_project)},
            options={},
            io_audit=_io_audit(
                uri,
                [
                    (
                        "args",
                        "$.args.path",
                        str(other_project),
                        str(other_project.resolve()),
                    )
                ],
            ),
            project_guard=guard,
            current_project_guard=guard,
            host_os_name="posix",
            account_home=home,
        )

    assert rejected.value.error_code == "WIRE_PATH_AUDIT_MISMATCH"


def test_nested_platform_pairs_flow_from_io_audit_to_transient_wine_dispatch(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    business_project = home / "case" / "business-host" / "SampleProject.wproj"
    target_project = home / "case" / "project" / "SampleProject.wproj"
    windows_source = home / "case" / "assets" / "windows.wsources"
    mac_source = home / "case" / "assets" / "mac.wsources"
    windows_output = home / "case" / "cli-io" / "Windows"
    mac_output = home / "case" / "cli-io" / "Mac"
    for path in (business_project, target_project, windows_source, mac_source):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    args = {
        "project": str(target_project),
        "platform": ["Windows", "Mac"],
        "source-by-platform": [
            ["Windows", str(windows_source)],
            ["Mac", str(mac_source)],
        ],
        "output": [
            ["Windows", str(windows_output)],
            ["Mac", str(mac_output)],
        ],
    }
    audit = validate_isolated_io(
        version="2022.1",
        uri="ak.wwise.cli.convertExternalSource",
        args=args,
        io_root=windows_output.parent,
    )

    adapted = adapt_cli_dispatch_paths(
        uri="ak.wwise.cli.convertExternalSource",
        args=args,
        options={},
        io_audit=audit.as_dict(),
        project_guard=_wine_project_guard(home, business_project),
        host_os_name="posix",
        account_home=home,
    )

    assert adapted.args == {
        "project": r"Y:\case\project\SampleProject.wproj",
        "platform": ["Windows", "Mac"],
        "source-by-platform": [
            ["Windows", r"Y:\case\assets\windows.wsources"],
            ["Mac", r"Y:\case\assets\mac.wsources"],
        ],
        "output": [
            ["Windows", r"Y:\case\cli-io\Windows"],
            ["Mac", r"Y:\case\cli-io\Mac"],
        ],
    }
    assert adapted.proof["translated_path_count"] == 5
    assert [row["json_path"] for row in adapted.proof["path_bindings"]] == [
        "$.args.project",
        "$.args.source-by-platform[0][1]",
        "$.args.source-by-platform[1][1]",
        "$.args.output[0][1]",
        "$.args.output[1][1]",
    ]


def test_local_wine_2022_soundbank_waapi_translates_only_reflected_path_fields(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = home / "case" / "project" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project/>", encoding="utf-8")
    source_list = home / "case" / "assets" / "delivery.wsources"
    output = home / "case" / "output"
    args = {
        "sources": [
            {
                "input": str(source_list),
                "platform": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "output": str(output),
            }
        ]
    }
    uri = "ak.wwise.core.soundbank.convertExternalSources"
    audit = _io_audit(
        uri,
        [
            (
                "args",
                "$.args.sources[0].input",
                str(source_list),
                str(source_list.resolve()),
            ),
            (
                "args",
                "$.args.sources[0].output",
                str(output),
                str(output.resolve()),
            ),
        ],
    )

    adapted = adapt_cli_dispatch_paths(
        uri=uri,
        args=args,
        options={},
        io_audit=audit,
        project_guard=_wine_project_guard(home, project),
        host_os_name="posix",
        account_home=home,
    )

    assert adapted.args == {
        "sources": [
            {
                "input": r"Y:\case\assets\delivery.wsources",
                "platform": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "output": r"Y:\case\output",
            }
        ]
    }
    assert adapted.proof["uri"] == uri
    assert adapted.proof["translated_path_count"] == 2
    assert [row["json_path"] for row in adapted.proof["path_bindings"]] == [
        "$.args.sources[0].input",
        "$.args.sources[0].output",
    ]


def test_local_wine_tab_import_translates_only_the_audited_import_file(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = home / "case" / "project" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project/>", encoding="utf-8")
    long_root = home.joinpath(*(f"segment-{index}-" + "x" * 42 for index in range(5)))
    long_root.mkdir(parents=True)
    import_file = long_root / "compound-import.tsv"
    import_file.write_text(
        "Object Path\tObject Type\n<Random Container>Batch\tRandom Container\n",
        encoding="utf-8",
    )
    assert len(str(import_file)) >= 260
    uri = "ak.wwise.core.audio.importTabDelimited"
    args = {
        "importFile": str(import_file),
        "importLocation": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
        "importLanguage": "SFX",
        "importOperation": "createNew",
        "autoAddToSourceControl": False,
    }
    options = {"return": ["id", "name"]}
    audit = {
        "contract": WWISE_WIRE_PATH_INPUT_AUDIT_CONTRACT,
        "uri": uri,
        "scope": "transient_dispatch_read_paths_only",
        "paths": [
            {
                "section": "args",
                "json_path": "$.args.importFile",
                "field": "importFile",
                "role": "read",
                "raw_path": str(import_file),
                "resolved_path": str(import_file.resolve()),
            }
        ],
    }

    adapted = adapt_cli_dispatch_paths(
        uri=uri,
        args=args,
        options=options,
        io_audit=audit,
        project_guard=_wine_project_guard(home, project),
        host_os_name="posix",
        account_home=home,
    )

    assert requires_wwise_wire_path_adaptation(uri) is True
    assert adapted.args == {
        **args,
        "importFile": "Y:\\" + "\\".join(import_file.relative_to(home).parts),
    }
    assert adapted.options == options
    assert args["importFile"] == str(import_file)
    assert adapted.proof["translated_path_count"] == 1
    assert adapted.proof["path_bindings"][0]["json_path"] == "$.args.importFile"


def test_local_wine_2022_process_definition_files_translates_only_sealed_files(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = home / "case" / "project" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project/>", encoding="utf-8")
    definition = home / "case" / "assets" / "banks.tsv"
    uri = "ak.wwise.core.soundbank.processDefinitionFiles"
    args = {"files": [str(definition)]}
    audit = _io_audit(
        uri,
        [
            (
                "args",
                "$.args.files[0]",
                str(definition),
                str(definition.resolve()),
            )
        ],
    )

    adapted = adapt_cli_dispatch_paths(
        uri=uri,
        args=args,
        options={},
        io_audit=audit,
        project_guard=_wine_project_guard(home, project),
        host_os_name="posix",
        account_home=home,
    )

    assert adapted.args == {"files": [r"Y:\case\assets\banks.tsv"]}
    assert adapted.proof["translated_path_count"] == 1

    tampered = {"files": [str(home / "case" / "assets" / "other.tsv")]}
    with pytest.raises(WwiseWirePathError) as drift:
        adapt_cli_dispatch_paths(
            uri=uri,
            args=tampered,
            options={},
            io_audit=audit,
            project_guard=_wine_project_guard(home, project),
            host_os_name="posix",
            account_home=home,
        )
    assert drift.value.error_code == "WIRE_PATH_AUDIT_MISMATCH"


def test_local_wine_cli_dispatch_resolves_audited_relative_write(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "case" / "business-host" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project/>", encoding="utf-8")
    args = {"project": str(home / "case" / "target.wproj"), "cache": "cache"}
    audit = _io_audit(
        "ak.wwise.cli.generateSoundbank",
        [
            ("args", "$.args.project", args["project"], str(Path(args["project"]).resolve())),
            ("args", "$.args.cache", "cache", str((home / "case" / "cache").resolve())),
        ],
    )

    adapted = adapt_cli_dispatch_paths(
        uri="ak.wwise.cli.generateSoundbank",
        args=args,
        options={},
        io_audit=audit,
        project_guard=_wine_project_guard(home, project),
        host_os_name="posix",
        account_home=home,
    )

    assert adapted.args["project"] == r"Y:\case\target.wproj"
    assert adapted.args["cache"] == r"Y:\case\cache"
    assert [row["mode"] for row in adapted.proof["path_bindings"]] == [
        "translated",
        "relative_resolved_then_translated",
    ]


def test_local_wine_cli_dispatch_uses_z_for_paths_outside_account_home(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = home / "case" / "business-host" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project/>", encoding="utf-8")
    target = home / "case" / "target.wproj"
    external_output = tmp_path / "external-volume" / "output"
    args = {"project": str(target), "output": str(external_output)}
    audit = _io_audit(
        "ak.wwise.cli.convertExternalSource",
        [
            ("args", "$.args.project", str(target), str(target.resolve())),
            (
                "args",
                "$.args.output",
                str(external_output),
                str(external_output.resolve()),
            ),
        ],
    )

    adapted = adapt_cli_dispatch_paths(
        uri="ak.wwise.cli.convertExternalSource",
        args=args,
        options={},
        io_audit=audit,
        project_guard=_wine_project_guard(home, project),
        host_os_name="posix",
        account_home=home,
    )

    expected_z = "Z:\\" + "\\".join(external_output.resolve().parts[1:])
    assert adapted.args["project"] == r"Y:\case\target.wproj"
    assert adapted.args["output"] == expected_z
    assert [row["drive"] for row in adapted.proof["path_bindings"]] == ["Y", "Z"]
    assert adapted.proof["mapping"]["anchor_drive"] == "Y"


def test_local_wine_cli_dispatch_rejects_audit_drift_and_remote_windows(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "case" / "business-host" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<Project/>", encoding="utf-8")
    path = home / "case" / "target.wproj"
    args = {"project": str(path)}
    audit = _io_audit(
        "ak.wwise.cli.migrate",
        [("args", "$.args.project", str(home / "other.wproj"), str(path.resolve()))],
    )

    with pytest.raises(WwiseWirePathError, match="no longer matches") as drift:
        adapt_cli_dispatch_paths(
            uri="ak.wwise.cli.migrate",
            args=args,
            options={},
            io_audit=audit,
            project_guard=_wine_project_guard(home, project),
            host_os_name="posix",
            account_home=home,
        )
    assert drift.value.error_code == "WIRE_PATH_AUDIT_MISMATCH"

    with pytest.raises(WwiseWirePathError, match="remote Windows") as remote:
        adapt_cli_dispatch_paths(
            uri="ak.wwise.cli.migrate",
            args=args,
            options={},
            io_audit=_io_audit(
                "ak.wwise.cli.migrate",
                [("args", "$.args.project", str(path), str(path.resolve()))],
            ),
            project_guard=_wine_project_guard(home, project, host="192.0.2.10"),
            host_os_name="posix",
            account_home=home,
        )
    assert remote.value.error_code == "REMOTE_WWISE_PATH_MAPPING_UNAVAILABLE"


def test_native_windows_cli_dispatch_is_identity_without_wine_mapping() -> None:
    args = {"project": r"D:\Projects\SampleProject.wproj"}
    adapted = adapt_cli_dispatch_paths(
        uri="ak.wwise.cli.migrate",
        args=args,
        options={},
        io_audit={"uri": "ak.wwise.cli.migrate", "paths": []},
        project_guard={"fingerprint": "native"},
        host_os_name="nt",
    )

    assert adapted.args == args
    assert adapted.proof["mode"] == "native_windows_identity"
    assert adapted.proof["applied"] is False
    assert adapted.proof["host_dispatch_sha256"] == adapted.proof["wire_dispatch_sha256"]
    assert len(adapted.proof["host_dispatch_sha256"]) == 64


def test_native_posix_cli_dispatch_is_identity_without_wine_mapping(
    tmp_path: Path,
) -> None:
    target = tmp_path / "SampleProject.wproj"
    args = {"project": str(target)}
    guard = {
        "fingerprint": "native-posix",
        "endpoint": {"host": "127.0.0.1", "port": 8080},
        "wwise": {"processPath": "/Applications/Wwise.app/Contents/MacOS/Wwise"},
        "project": {"state": "open", "path": str(target)},
    }
    adapted = adapt_cli_dispatch_paths(
        uri="ak.wwise.cli.migrate",
        args=args,
        options={},
        io_audit=_io_audit(
            "ak.wwise.cli.migrate",
            [("args", "$.args.project", str(target), str(target.resolve()))],
        ),
        project_guard=guard,
        current_project_guard=guard,
        host_os_name="posix",
    )

    assert adapted.args == args
    assert adapted.proof["mode"] == "native_posix_identity"
    assert adapted.proof["applied"] is False
    assert adapted.proof["host_dispatch_sha256"] == adapted.proof["wire_dispatch_sha256"]

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Mapping, Sequence

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.support.platform_process import run_windows_powershell_model_command
from wwise_waapi.platform_commands import (
    encode_windows_model_argv,
    encode_windows_powershell_argv,
)
from .support import codex_harness as codex_harness_module
from .support.codex_harness import (  # pyright: ignore[reportMissingImports]
    CodexCliHarness,
    CodexCliTask,
    CodexCommandRecord,
    CodexGatewayErrorExpectation,
    CodexHarnessError,
    CodexHarnessConfig,
    WindowsPowerShellCoreHost,
    audit_prompt_input_payload,
    audit_session_events,
    build_exec_command,
    build_prompt_audit_command,
    build_task_exec_command,
    build_task_resume_command,
    classify_commands,
    classify_task_commands,
    classify_codex_infrastructure_failure,
    completed_command_records,
    count_invalid_jsonl_lines,
    discover_windows_powershell_core,
    discover_windows_user_skill_paths,
    final_agent_message,
    gateway_continuation_binding_errors,
    gateway_runtime_apis,
    inspect_isolated_environment,
    is_link_or_junction,
    isolated_codex_environment,
    kill_process_group,
    parse_command_argv,
    powershell_core_host_fingerprint,
    probe_windows_powershell_core,
    parse_jsonl_events,
    run_process,
    subprocess_process_group_options,
    prepare_workspace_skill_install,
    recoverable_preprocess_attempt_indexes,
    snapshot_tree_hash,
    snapshot_workspace,
    turn_usage,
    validate_powershell_core_probe_output,
    workspace_changes,
    validated_skill_read,
    verify_workspace_skill_install,
    workspace_skill_install_path,
)
from .support.codex_gateway_broker import (  # pyright: ignore[reportMissingImports]
    BASH_ENV_NAME,
    BROKER_ENDPOINT_ENV,
    BROKER_TOKEN_ENV,
    BROKER_TRANSPORT_ENV,
    CodexGatewayBroker,
    ExpectedGatewayStep,
    GATEWAY_REQUIRED_ENV,
    SemanticJsonArgument,
    SHIM_TRUSTED_PYTHON_ENV,
)
from .support.codex_gateway_contracts import (
    TASK_LOCAL_RUNNER_POSIX,
    TASK_LOCAL_RUNNER_WINDOWS,
    TYPED_REQUEST_SCHEMA_CONTRACT,
)


_FAKE_KILL_RETURN_CODE = -9
_WINDOWS_POWERSHELL_CORE = r"C:\Program Files\PowerShell\7\pwsh.exe"
_WINDOWS_POWERSHELL_CORE_HOST = WindowsPowerShellCoreHost(
    executable=_WINDOWS_POWERSHELL_CORE,
    version="7.6.4",
    native_argument_passing="Windows",
    sha256="a" * 64,
)


def _closed_next_command(
    full_argv: Sequence[str],
    *,
    platform_name: str,
    select_model_command: bool = True,
) -> dict[str, object]:
    gateway_argv = list(full_argv[3:])
    next_command: dict[str, object] = {
        "contract": "waapi-skill.gateway-next-command/v2",
        "command": gateway_argv[0],
        "gateway_argv": gateway_argv,
        "full_argv": list(full_argv),
        "copy_exactly": True,
        "shell_tool_timeout_ms": 30_000,
        "shell_family": (
            "windows-powershell-encoded" if platform_name == "nt" else "posix-sh"
        ),
    }
    model_command: str | None = None
    if platform_name == "nt":
        shell_command = encode_windows_powershell_argv(full_argv)
        if select_model_command:
            model_command = encode_windows_model_argv(full_argv)
            next_command["shell_command"] = shell_command
            next_command["model_shell_family"] = "windows-pwsh-literal-v1"
    else:
        shell_command = shlex.join(full_argv)
    next_command["copy_instruction"] = {
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
        next_command["model_command"] = model_command
    else:
        next_command["shell_command"] = shell_command
    return next_command


def windows_powershell_recording(script: str, *, executable: str = _WINDOWS_POWERSHELL_CORE) -> str:
    return shlex.join((executable, "-NoProfile", "-Command", script))


def test_windows_powershell_recording_preserves_json_backslash_escapes() -> None:
    request = {
        "parent": {
            "kind": "path",
            "value": r"\Actor-Mixer Hierarchy\Default Work Unit",
        }
    }
    request_json = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    expected = (
        "python",
        r"C:\Agent Workspace\waapi-skill\scripts\run.py",
        "gateway.py",
        "preview",
        "--request-json",
        request_json,
    )
    script = encode_windows_model_argv(expected)
    command = windows_powershell_recording(script)

    assert tuple(shlex.split(command, posix=True)) == (
        _WINDOWS_POWERSHELL_CORE,
        "-NoProfile",
        "-Command",
        script,
    )
    assert parse_command_argv(
        command,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    ) == (expected, False, "")
    assert json.loads(expected[-1]) == request


def portable_windows_outer_split(
    command: str,
    *,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    assert platform_name == "nt"
    return tuple(shlex.split(command, posix=True))


def completed_windows_record(
    command: str,
    output: Mapping[str, object] | str | None = None,
    *,
    exit_code: int = 0,
    status: str = "completed",
) -> CodexCommandRecord:
    argv, has_operators, parse_error, parser_kind = codex_harness_module._parse_command_argv(
        command,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )
    return CodexCommandRecord(
        command=command,
        exit_code=exit_code,
        status=status,
        aggregated_output=(
            output
            if isinstance(output, str)
            else json.dumps(output, ensure_ascii=False)
            if output is not None
            else ""
        ),
        argv=argv,
        has_shell_operators=has_operators,
        parse_error=parse_error,
        parser_kind=parser_kind,
    )


def completed_record(
    command: str,
    output: Mapping[str, object] | str | None = None,
    *,
    exit_code: int = 0,
    status: str = "completed",
) -> CodexCommandRecord:
    argv, has_operators, parse_error, parser_kind = (
        codex_harness_module._parse_command_argv(
            command,
            platform_name="posix",
        )
    )
    return CodexCommandRecord(
        command=command,
        exit_code=exit_code,
        status=status,
        aggregated_output=(
            output
            if isinstance(output, str)
            else json.dumps(output, ensure_ascii=False)
            if output is not None
            else ""
        ),
        argv=argv,
        has_shell_operators=has_operators,
        parse_error=parse_error,
        parser_kind=parser_kind,
    )


def test_response_derived_posix_continuation_binds_exact_inner_script() -> None:
    full_argv = (
        "python",
        "/tmp/Skill Path/scripts/run.py",
        "gateway.py",
        "confirm",
        "tx-1",
    )
    next_command = _closed_next_command(full_argv, platform_name="posix")
    payload = {"next_command": next_command}
    selected = str(next_command["shell_command"])
    prior = completed_record("python initial.py", payload)
    current_command = shlex.join(("/bin/bash", "-lc", selected))
    current = CodexCommandRecord(
        command=current_command,
        exit_code=0,
        status="completed",
        aggregated_output="{}",
        argv=tuple(shlex.split(selected)),
        has_shell_operators=False,
        parser_kind="posix-shell",
    )

    errors = gateway_continuation_binding_errors(
        (prior, current),
        (SimpleNamespace(payload=payload), SimpleNamespace(payload={})),
        platform_name="posix",
    )

    assert errors == ()


def test_response_derived_windows_model_command_binds_exact_inner_script() -> None:
    full_argv = (
        "python",
        r"C:\Agent Workspace\.agents\skills\waapi-skill\scripts\run.py",
        "gateway.py",
        "confirm",
        "tx-1",
    )
    next_command = _closed_next_command(full_argv, platform_name="nt")
    payload = {"next_command": next_command}
    selected = str(next_command["model_command"])
    prior = completed_windows_record(
        windows_powershell_recording("python initial.py"),
        payload,
    )
    current = completed_windows_record(
        shlex.join(
            (
                _WINDOWS_POWERSHELL_CORE_HOST.executable,
                "-NoProfile",
                "-Command",
                selected,
            )
        ),
        {},
    )

    errors = gateway_continuation_binding_errors(
        (prior, current),
        (SimpleNamespace(payload=payload), SimpleNamespace(payload={})),
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert errors == ()


def test_response_derived_windows_fallback_binds_exact_encoded_script() -> None:
    full_argv = (
        "python",
        r"C:\Agent Workspace\.agents\skills\waapi-skill\scripts\run.py",
        "gateway.py",
        "confirm",
        "x" * 1100,
    )
    next_command = _closed_next_command(
        full_argv,
        platform_name="nt",
        select_model_command=False,
    )
    payload = {"next_command": next_command}
    selected = str(next_command["shell_command"])
    prior = completed_windows_record(
        windows_powershell_recording("python initial.py"),
        payload,
    )
    current = completed_windows_record(
        shlex.join(
            (
                _WINDOWS_POWERSHELL_CORE_HOST.executable,
                "-NoProfile",
                "-Command",
                selected,
            )
        ),
        {},
    )

    errors = gateway_continuation_binding_errors(
        (prior, current),
        (SimpleNamespace(payload=payload), SimpleNamespace(payload={})),
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert errors == ()


@pytest.mark.parametrize(
    "tamper",
    (
        "legacy_field",
        "equivalent_requote",
        "missing_copy_instruction",
        "missing_selected_field",
        "invalid_source_field",
        "prior_output_mismatch",
        "wrong_outer_wrapper",
    ),
)
def test_response_derived_windows_continuation_fails_closed(
    tamper: str,
) -> None:
    confirmation_token = "ct1-0123456789abcdefghjkmnpq"
    full_argv = (
        "python",
        r"C:\Agent Workspace\.agents\skills\waapi-skill\scripts\run.py",
        "gateway.py",
        "confirm",
        "tx-1",
        "--confirmation-token",
        confirmation_token,
    )
    next_command = _closed_next_command(full_argv, platform_name="nt")
    payload = {"next_command": next_command}
    observed = str(next_command["model_command"])
    prior_payload: Mapping[str, object] = payload
    if tamper == "legacy_field":
        observed = str(next_command["shell_command"])
    elif tamper == "equivalent_requote":
        observed = (
            "python 'C:\\Agent Workspace\\.agents\\skills\\waapi-skill\\scripts\\run.py' "
            "gateway.py confirm tx-1 --confirmation-token "
            f"{confirmation_token}"
        )
    elif tamper == "missing_copy_instruction":
        del next_command["copy_instruction"]
    elif tamper == "missing_selected_field":
        del next_command["model_command"]
    elif tamper == "invalid_source_field":
        instruction = next_command["copy_instruction"]
        assert isinstance(instruction, dict)
        instruction["source_field"] = "shell_command"
    elif tamper == "prior_output_mismatch":
        prior_payload = {"next_command": {**next_command, "command": "execute"}}
    prior = completed_windows_record(
        windows_powershell_recording("python initial.py"),
        prior_payload,
    )
    current = completed_windows_record(
        (
            observed
            if tamper == "wrong_outer_wrapper"
            else shlex.join(
                (
                    _WINDOWS_POWERSHELL_CORE_HOST.executable,
                    "-NoProfile",
                    "-Command",
                    observed,
                )
            )
        ),
        {},
    )

    errors = gateway_continuation_binding_errors(
        (prior, current),
        (SimpleNamespace(payload=payload), SimpleNamespace(payload={})),
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert len(errors) == 1
    assert errors[0].startswith("command 2: ")
    assert "tx-1" not in errors[0]
    assert confirmation_token not in errors[0]


def test_model_authored_command_without_prior_continuation_is_unchanged() -> None:
    record = completed_record("python initial.py", {})

    assert gateway_continuation_binding_errors(
        (record,),
        (SimpleNamespace(payload={}),),
        platform_name="posix",
    ) == ()


def passing_prompt_audit() -> codex_harness_module.CodexPromptAudit:
    return codex_harness_module.CodexPromptAudit(
        item_count=1,
        prompt_sha256="a" * 64,
        has_memory=False,
        has_target_skill=True,
        has_user_agent_skills=False,
        has_codex_system_skills=False,
        skill_inventory=(("waapi-skill", "/isolated/waapi-skill/SKILL.md"),),
        target_skill_count=1,
        target_skill_locator_matches=True,
    )


def executable_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("codex test executable\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def windows_standalone_binary(
    root: Path,
    *,
    binary_in_bin: bool = True,
) -> Path:
    """Create the closed official-standalone shape expected on Windows."""

    package_marker = root / "codex-package.json"
    package_marker.parent.mkdir(parents=True, exist_ok=True)
    package_marker.write_text('{"version":"1.2.3"}\n', encoding="utf-8")
    binary = executable_file(
        root / "bin" / "codex.exe" if binary_in_bin else root / "codex.exe"
    )
    executable_file(root / "bin" / "codex-code-mode-host.exe")
    executable_file(root / "codex-path" / "rg.exe")
    executable_file(root / "codex-resources" / "codex-command-runner.exe")
    executable_file(root / "codex-resources" / "codex-windows-sandbox-setup.exe")
    return binary


def test_codex_binary_discovery_uses_host_native_path_lookup(tmp_path: Path) -> None:
    linux_binary = executable_file(tmp_path / "codex")
    windows_binary = windows_standalone_binary(tmp_path / "windows-standalone")
    linux_calls: list[str] = []
    windows_calls: list[str] = []

    def linux_which(name: str) -> str | None:
        linux_calls.append(name)
        return str(linux_binary) if name == "codex" else None

    def windows_which(name: str) -> str | None:
        windows_calls.append(name)
        return str(windows_binary) if name == "codex.exe" else None

    assert codex_harness_module.discover_codex_binary(
        platform_name="linux", which=linux_which
    ) == linux_binary.resolve(strict=True)
    assert linux_calls == ["codex"]
    assert codex_harness_module.discover_codex_binary(
        platform_name="win32",
        which=windows_which,
        probe=lambda _path: "codex-cli 1.2.3",
    ) == windows_binary.resolve(strict=True)
    assert windows_calls == ["codex.exe"]

    windows_alias_calls: list[str] = []

    def windows_alias_which(name: str) -> str | None:
        windows_alias_calls.append(name)
        return str(linux_binary) if name == "codex" else None

    with pytest.raises(CodexHarnessError, match="host-native .exe"):
        codex_harness_module.discover_codex_binary(
            platform_name="win32",
            which=windows_alias_which,
            probe=lambda _path: "codex-cli 1.2.3",
        )
    assert windows_alias_calls == ["codex.exe", "codex"]


def test_codex_binary_discovery_skips_outer_sandbox_proxy(
    tmp_path: Path,
) -> None:
    proxy = executable_file(tmp_path / ".codex" / ".sandbox-bin" / "codex.exe")
    host = windows_standalone_binary(tmp_path / "host-standalone")
    environment = {
        "PATH": os.pathsep.join((str(proxy.parent), str(host.parent))),
    }

    assert codex_harness_module.discover_codex_binary(
        platform_name="win32",
        environment=environment,
        probe=lambda _path: "codex-cli 1.2.3",
    ) == (
        host.resolve(strict=True)
    )

    environment = {"PATH": str(proxy.parent)}
    with pytest.raises(
        CodexHarnessError,
        match=r"outer sandbox proxy.*--codex-binary",
    ):
        codex_harness_module.discover_codex_binary(
            platform_name="win32",
            environment=environment,
            probe=lambda _path: "codex-cli 1.2.3",
        )
    with pytest.raises(CodexHarnessError, match=r"outer sandbox proxy.*--codex-binary"):
        codex_harness_module._strict_codex_binary(
            proxy,
            source="explicit",
            platform_name="win32",
        )


def test_windows_codex_discovery_skips_unlaunchable_windowsapps_candidate(
    tmp_path: Path,
) -> None:
    packaged = executable_file(
        tmp_path
        / "Program Files"
        / "WindowsApps"
        / "OpenAI.Codex_1.0_arm64__test"
        / "app"
        / "resources"
        / "codex.exe"
    )
    host = windows_standalone_binary(tmp_path / "Host CLI & 工具")
    environment = {
        "PATH": os.pathsep.join((str(packaged.parent), str(host.parent))),
    }
    probed: list[Path] = []

    def probe(candidate: Path) -> str:
        probed.append(candidate)
        if candidate == packaged.resolve(strict=True):
            denied = PermissionError(13, "Access denied")
            denied.winerror = 5  # type: ignore[attr-defined]
            raise denied
        return "codex-cli 1.2.3"

    assert codex_harness_module.discover_codex_binary(
        platform_name="win32",
        environment=environment,
        probe=probe,
    ) == host.resolve(strict=True)
    assert probed == [host.resolve(strict=True)]


def test_windows_codex_discovery_prefers_official_standalone_current(
    tmp_path: Path,
) -> None:
    current = windows_standalone_binary(
        tmp_path
        / "profile"
        / ".codex"
        / "packages"
        / "standalone"
        / "current"
    )
    ambient = executable_file(tmp_path / "ambient" / "codex.exe")
    environment = {
        "USERPROFILE": str(tmp_path / "profile"),
        "PATH": str(ambient.parent),
    }
    probed: list[Path] = []

    assert codex_harness_module.discover_codex_binary(
        platform_name="win32",
        environment=environment,
        probe=lambda path: probed.append(path) or "codex-cli 1.2.3",
    ) == current.resolve(strict=True)
    assert probed == [current.resolve(strict=True)]


def test_windows_codex_discovery_reports_all_unusable_candidates(
    tmp_path: Path,
) -> None:
    packaged = executable_file(
        tmp_path / "Program Files" / "WindowsApps" / "codex.exe"
    )

    with pytest.raises(
        CodexHarnessError,
        match=r"no usable host-native Codex CLI.*protected Microsoft Store.*standalone",
    ):
        codex_harness_module.discover_codex_binary(
            platform_name="win32",
            environment={"PATH": str(packaged.parent)},
            probe=lambda _path: "codex-cli 1.2.3",
        )


def test_windows_codex_discovery_rejects_alias_resolving_into_windowsapps(
    tmp_path: Path,
) -> None:
    packaged = windows_standalone_binary(
        tmp_path / "Program Files" / "WindowsApps" / "OpenAI.Codex_test"
    )
    alias = tmp_path / "ordinary-bin" / "codex.exe"
    alias.parent.mkdir()
    create_symlink_or_skip(alias, packaged)
    probed: list[Path] = []

    with pytest.raises(CodexHarnessError, match="protected Microsoft Store"):
        codex_harness_module.discover_codex_binary(
            platform_name="win32",
            environment={"PATH": str(alias.parent)},
            probe=lambda path: probed.append(path) or "codex-cli 1.2.3",
        )

    assert probed == []


def test_windows_codex_discovery_rejects_executable_without_standalone_package(
    tmp_path: Path,
) -> None:
    unbound = executable_file(tmp_path / "plain" / "bin" / "codex.exe")
    probed: list[Path] = []

    with pytest.raises(CodexHarnessError, match=r"package marker is missing"):
        codex_harness_module.discover_codex_binary(
            platform_name="win32",
            environment={"PATH": str(unbound.parent)},
            probe=lambda path: probed.append(path) or "codex-cli 1.2.3",
        )

    assert probed == []


def test_windows_codex_discovery_continues_after_invalid_version_output(
    tmp_path: Path,
) -> None:
    invalid = windows_standalone_binary(tmp_path / "invalid")
    valid = windows_standalone_binary(tmp_path / "valid")
    probed: list[Path] = []

    def probe(path: Path) -> str:
        probed.append(path)
        return "not Codex" if path == invalid.resolve(strict=True) else "codex-cli 1.2.3"

    assert codex_harness_module.discover_codex_binary(
        platform_name="win32",
        environment={
            "PATH": os.pathsep.join((str(invalid.parent), str(valid.parent))),
        },
        probe=probe,
    ) == valid.resolve(strict=True)
    assert probed == [invalid.resolve(strict=True), valid.resolve(strict=True)]


@pytest.mark.parametrize("mode", ("Standard", "Windows"))
def test_powershell_core_probe_contract_accepts_73_or_newer_safe_native_modes(
    mode: str,
) -> None:
    host = validate_powershell_core_probe_output(
        f"Core|7.6.4|{mode}\r\n",
        executable=_WINDOWS_POWERSHELL_CORE,
        sha256="b" * 64,
    )

    assert host.version == "7.6.4"
    assert host.native_argument_passing == mode
    assert powershell_core_host_fingerprint(host) == {
        "path": _WINDOWS_POWERSHELL_CORE,
        "version": "7.6.4",
        "native_argument_passing": mode,
        "sha256": "b" * 64,
    }
    assert json.loads(json.dumps(powershell_core_host_fingerprint(host))) == (
        powershell_core_host_fingerprint(host)
    )


@pytest.mark.parametrize(
    "output",
    (
        "Desktop|7.6.4|Windows",
        "Core|7.2.99|Windows",
        "Core|7.6.4|Legacy",
        "Core|7.6|Windows",
        "Core|7.6.4|Windows\nextra",
        "Core|7.6.4|Windows\n\n",
    ),
)
def test_powershell_core_probe_contract_rejects_unsupported_host(output: str) -> None:
    with pytest.raises(CodexHarnessError, match="PowerShell Core"):
        validate_powershell_core_probe_output(
            output,
            executable=_WINDOWS_POWERSHELL_CORE,
            sha256="b" * 64,
        )


def test_windows_powershell_core_discovery_binds_exact_selected_path() -> None:
    probed: list[str] = []

    host = discover_windows_powershell_core(
        platform_name="win32",
        environment={"Path": r"C:\Program Files\PowerShell\7;C:\Windows\System32"},
        which=lambda name, *, path: (
            _WINDOWS_POWERSHELL_CORE
            if name == "pwsh.exe" and "PowerShell" in str(path)
            else None
        ),
        probe=lambda path: probed.append(str(path)) or _WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert host is _WINDOWS_POWERSHELL_CORE_HOST
    assert probed == [_WINDOWS_POWERSHELL_CORE]


def test_powershell_core_probe_rejects_original_reparse_before_launch(
    tmp_path: Path,
) -> None:
    target = tmp_path / "real-pwsh.exe"
    target.write_bytes(b"target")
    alias = tmp_path / "pwsh.exe"
    create_symlink_or_skip(alias, target)
    launched: list[object] = []

    with pytest.raises(CodexHarnessError, match="non-reparse pwsh.exe"):
        probe_windows_powershell_core(
            alias,
            runner=lambda *args, **kwargs: launched.append((args, kwargs)),  # type: ignore[arg-type,return-value]
        )

    assert launched == []


def test_powershell_core_probe_allows_a_cold_interactive_windows_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "pwsh.exe"
    executable.write_bytes(b"reviewed-powershell-core")
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="Core|7.6.4|Windows",
            stderr="",
        )

    monkeypatch.setattr(
        codex_harness_module,
        "validate_powershell_core_probe_output",
        lambda *_args, **_kwargs: _WINDOWS_POWERSHELL_CORE_HOST,
    )
    host = probe_windows_powershell_core(executable, runner=runner)

    assert host is _WINDOWS_POWERSHELL_CORE_HOST
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 30.0


def test_windows_codex_runtime_path_keeps_broker_shim_first(
    tmp_path: Path,
) -> None:
    release = tmp_path / "standalone" / "releases" / "1.2.3-arm64"
    binary = windows_standalone_binary(release)
    resources = release / "codex-resources"
    codex_path = release / "codex-path"
    shim = tmp_path / "broker shims"
    inherited = tmp_path / "ambient"
    environment = {
        "WAAPI_CODEX_GATEWAY_REQUIRED": "1",
        "Path": f"{shim};{inherited}",
    }

    result = codex_harness_module.codex_process_environment(
        binary,
        environment,
        platform_name="win32",
        powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert result["Path"].split(";") == [
        str(shim),
        r"C:\Program Files\PowerShell\7",
        str(binary.parent.resolve(strict=True)),
        str(resources.resolve(strict=True)),
        str(codex_path.resolve(strict=True)),
        str(inherited),
    ]


def test_non_windows_codex_environment_is_unchanged_by_powershell_contract(
    tmp_path: Path,
) -> None:
    environment = {"PATH": "/custom/bin:/usr/bin", "MARKER": "unchanged"}

    result = codex_harness_module.codex_process_environment(
        tmp_path / "codex",
        environment,
        platform_name="darwin",
        powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert result == environment


def test_windows_codex_runtime_rejects_root_level_binary(
    tmp_path: Path,
) -> None:
    release = tmp_path / "standalone" / "releases" / "1.2.3-arm64"
    binary = windows_standalone_binary(release, binary_in_bin=False)

    with pytest.raises(CodexHarnessError, match=r"<release>\\bin\\codex.exe"):
        codex_harness_module.codex_process_environment(
            binary,
            {"Path": str(tmp_path / "ambient")},
            platform_name="win32",
        )


@pytest.mark.parametrize(
    "missing_relative",
    (
        Path("codex-package.json"),
        Path("bin") / "codex-code-mode-host.exe",
        Path("codex-path") / "rg.exe",
        Path("codex-resources") / "codex-command-runner.exe",
        Path("codex-resources") / "codex-windows-sandbox-setup.exe",
    ),
)
def test_windows_standalone_runtime_files_are_complete_and_fixed(
    tmp_path: Path,
    missing_relative: Path,
) -> None:
    release = tmp_path / "standalone" / "releases" / "1.2.3-arm64"
    binary = windows_standalone_binary(release)
    expected = [
        release / "codex-package.json",
        release / "bin" / "codex-code-mode-host.exe",
        release / "codex-path" / "rg.exe",
        release / "codex-resources" / "codex-command-runner.exe",
        release / "codex-resources" / "codex-windows-sandbox-setup.exe",
    ]

    assert codex_harness_module.codex_runtime_files(
        binary,
        platform_name="win32",
    ) == tuple(path.resolve(strict=True) for path in expected)

    (release / missing_relative).unlink()
    with pytest.raises(
        CodexHarnessError,
        match="package marker is missing|expected a real regular file",
    ):
        codex_harness_module.codex_runtime_files(
            binary,
            platform_name="win32",
        )


def test_windows_codex_version_probe_rejects_non_codex_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = windows_standalone_binary(tmp_path / "standalone")
    monkeypatch.setattr(
        codex_harness_module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [str(binary), "--version"],
            0,
            "something else 1.2.3\n",
            "",
        ),
    )

    with pytest.raises(CodexHarnessError, match="version output is invalid"):
        codex_harness_module._probe_codex_binary(
            binary,
            platform_name="win32",
            environment={"PATH": ""},
        )


@pytest.mark.parametrize(
    "value",
    (
        "codex-cli 0.146.0",
        "codex 1.2.3\n",
        "codex-cli 0.146.0-alpha.1+arm64\r\n",
    ),
)
def test_codex_version_output_accepts_one_bounded_semver_line(value: str) -> None:
    assert codex_harness_module.validate_codex_version_output(
        value,
        binary=Path("codex.exe"),
    ) == value.rstrip("\r\n")


@pytest.mark.parametrize(
    "value",
    (
        "",
        "something 1.2.3",
        " codex-cli 1.2.3",
        "codex-cli 1.2.3 ",
        "codex-cli 1.2.3\nsecond line",
        "codex-cli 1.2.3\0",
        "codex-cli 1.2.3+" + "a" * 256,
    ),
)
def test_codex_version_output_rejects_unbounded_or_ambiguous_text(value: str) -> None:
    with pytest.raises(CodexHarnessError, match="version output is invalid"):
        codex_harness_module.validate_codex_version_output(
            value,
            binary=Path("codex.exe"),
        )


def test_codex_binary_discovery_uses_app_fallback_only_on_macos(tmp_path: Path) -> None:
    fallback = executable_file(tmp_path / "Codex.app" / "Contents" / "Resources" / "codex")

    assert codex_harness_module.discover_codex_binary(
        platform_name="darwin",
        which=lambda _name: None,
        macos_app_fallback=fallback,
    ) == fallback.resolve(strict=True)
    with pytest.raises(CodexHarnessError, match="not found on PATH"):
        codex_harness_module.discover_codex_binary(
            platform_name="linux",
            which=lambda _name: None,
            macos_app_fallback=fallback,
        )


def test_explicit_codex_binary_has_priority_and_resolves_strictly(tmp_path: Path) -> None:
    explicit = executable_file(tmp_path / "explicit-codex.exe")

    assert codex_harness_module.resolve_codex_binary(explicit) == explicit.resolve(strict=True)
    with pytest.raises(CodexHarnessError, match="explicit Codex binary is unavailable"):
        codex_harness_module.resolve_codex_binary(tmp_path / "missing-codex.exe")

    non_native = executable_file(tmp_path / "codex.cmd")
    with pytest.raises(CodexHarnessError, match="host-native .exe"):
        codex_harness_module._strict_codex_binary(
            non_native,
            source="explicit",
            platform_name="win32",
        )


class InterruptingFakeProcess:
    """Popen test double that requires TERM, wait, KILL, then reap."""

    pid = 4242

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.communicate_calls: list[float | None] = []
        self.windows_signals: list[str] = []

    def poll(self) -> int | None:
        return self.returncode

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.communicate_calls.append(timeout)
        if len(self.communicate_calls) == 1:
            raise KeyboardInterrupt
        if len(self.communicate_calls) == 2:
            raise subprocess.TimeoutExpired(cmd=["fake-codex"], timeout=timeout or 0.0)
        self.returncode = _FAKE_KILL_RETURN_CODE
        return "reaped stdout", "reaped stderr"

    def terminate(self) -> None:
        self.windows_signals.append("terminate")

    def kill(self) -> None:
        self.windows_signals.append("kill")


def gateway_command(skill: Path, arguments: str) -> str:
    return recorded_argv_command(
        "python",
        str(skill / "scripts" / "run.py"),
        "gateway.py",
        *shlex.split(arguments, posix=True),
    )


def recorded_argv_command(*argv: str) -> str:
    """Render synthetic Codex argv with its platform-neutral JSONL grammar."""

    return shlex.join(argv)


def test_recorded_argv_command_round_trips_windows_paths_as_codex_evidence() -> None:
    runner = r"C:\Program Files\waapi-skill\scripts\run.py"
    command = recorded_argv_command(
        "python",
        runner,
        "gateway.py",
        "preview",
        "--request-json",
        '{"path":"C:\\\\Audio\\\\rifle.wav"}',
    )

    argv, has_operators, parse_error, parser_kind = (
        codex_harness_module._parse_command_argv(
            command,
            platform_name="nt",
        )
    )

    assert argv == (
        "python",
        runner,
        "gateway.py",
        "preview",
        "--request-json",
        '{"path":"C:\\\\Audio\\\\rifle.wav"}',
    )
    assert has_operators is False
    assert parse_error == ""
    assert parser_kind == "windows-native"

    raw_native_spelling = f"python {runner} gateway.py preview --request-json '{{}}'"
    raw_argv, raw_operators, raw_error, raw_parser_kind = (
        codex_harness_module._parse_command_argv(
            raw_native_spelling,
            platform_name="nt",
        )
    )
    raw_record = CodexCommandRecord(
        command=raw_native_spelling,
        exit_code=0,
        status="completed",
        aggregated_output=json.dumps(
            {
                "contract": "waapi-skill.gateway-result/v1",
                "command": "preview",
                "ok": True,
            }
        ),
        argv=raw_argv,
        has_shell_operators=raw_operators,
        parse_error=raw_error,
        parser_kind=raw_parser_kind,
    )
    raw_facts = classify_commands(
        (raw_record,),
        skill_source=Path(r"C:\Program Files\waapi-skill"),
        expected_gateway_subcommands=("preview",),
    )

    assert raw_argv != argv
    assert raw_facts.gateway_commands == ()
    assert raw_facts.unexpected_commands == (raw_native_spelling,)


def test_prompt_audit_rejects_memory_and_unexpected_personal_skills(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: waapi-skill\n---\n", encoding="utf-8")
    payload = [
        {
            "role": "system",
            "content": (
                "### Available skills\n"
                f"- waapi-skill: target (file: {skill}/SKILL.md)\n"
                "- demo: extra (file: /Users/xiye/.agents/skills/demo/SKILL.md)\n"
                "MEMORY_SUMMARY"
            ),
        },
    ]

    audit = audit_prompt_input_payload(payload, target_skill_source=skill)

    assert audit.has_target_skill is True
    assert audit.has_memory is True
    assert audit.has_user_agent_skills is True
    assert audit.passed is False


def test_skill_locator_classification_uses_local_path_parts(tmp_path: Path) -> None:
    personal = tmp_path / ".agents" / "skills" / "demo" / "SKILL.md"
    system = (
        tmp_path
        / ".codex"
        / "skills"
        / ".system"
        / "skill-creator"
        / "SKILL.md"
    )
    lookalike = tmp_path / ".agents" / "skills-archive" / "demo" / "SKILL.md"

    assert codex_harness_module.local_locator_contains_parts(
        str(personal),
        (".agents", "skills"),
    )
    assert codex_harness_module.is_codex_system_skill(str(system))
    assert not codex_harness_module.local_locator_contains_parts(
        str(lookalike),
        (".agents", "skills"),
    )
    assert not codex_harness_module.is_codex_system_skill(
        str(tmp_path / ".codex" / "skills" / ".system-archive" / "SKILL.md")
    )


def test_prompt_audit_accepts_exact_target_and_codex_system_skills(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: waapi-skill\n---\n", encoding="utf-8")
    payload = [
        {
            "role": "developer",
            "content": (
                "### Available skills\n"
                "- skill-creator: built in (file: /Users/test/.codex/skills/.system/skill-creator/SKILL.md)\n"
                f"- waapi-skill: target (file: {skill}/SKILL.md)"
            ),
        }
    ]
    audit = audit_prompt_input_payload(payload, target_skill_source=skill)

    assert audit.has_target_skill is True
    assert audit.has_memory is False
    assert audit.has_user_agent_skills is False
    assert audit.has_codex_system_skills is True
    assert audit.target_skill_count == 1
    assert audit.target_skill_locator_matches is True
    assert audit.unexpected_skills == ()
    assert audit.passed is True


def test_prompt_audit_binds_system_skills_to_exact_disposable_codex_home(tmp_path: Path) -> None:
    target = tmp_path / "waapi-skill"
    target.mkdir()
    (target / "SKILL.md").write_text("skill\n", encoding="utf-8")
    system_root = tmp_path / "codex-home" / "skills" / ".system"
    builtin = system_root / "skill-creator" / "SKILL.md"
    builtin.parent.mkdir(parents=True)
    builtin.write_text("system skill\n", encoding="utf-8")
    impostor = tmp_path / "workspace" / "skills" / ".system" / "impostor" / "SKILL.md"
    impostor.parent.mkdir(parents=True)
    impostor.write_text("not system\n", encoding="utf-8")

    accepted = audit_prompt_input_payload(
        [{"role": "developer", "content": f"- skill-creator: builtin (file: {builtin})\n- waapi-skill: target (file: {target / 'SKILL.md'})"}],
        target_skill_source=target,
        system_skill_root=system_root,
    )
    rejected = audit_prompt_input_payload(
        [{"role": "developer", "content": f"- impostor: fake (file: {impostor})\n- waapi-skill: target (file: {target / 'SKILL.md'})"}],
        target_skill_source=target,
        system_skill_root=system_root,
    )

    assert accepted.passed is True
    assert accepted.system_skills == (("skill-creator", str(builtin)),)
    assert rejected.passed is False
    assert rejected.unexpected_skills == (("impostor", str(impostor)),)


def test_prompt_audit_rejects_wrong_target_locator_and_user_prompt_name_spoof(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    wrong = tmp_path / "wrong-skill"
    skill.mkdir()
    wrong.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    (wrong / "SKILL.md").write_text("wrong\n", encoding="utf-8")

    wrong_locator = audit_prompt_input_payload(
        [{"role": "system", "content": f"- waapi-skill: wrong (file: {wrong}/SKILL.md)"}],
        target_skill_source=skill,
    )
    user_spoof = audit_prompt_input_payload(
        [
            {"role": "system", "content": "No skills are available."},
            {"role": "user", "content": "Please use waapi-skill."},
        ],
        target_skill_source=skill,
    )

    assert wrong_locator.passed is False
    assert wrong_locator.has_target_skill is False
    assert wrong_locator.unexpected_skills == (("waapi-skill", f"{wrong}/SKILL.md"),)
    assert user_spoof.has_target_skill is False
    assert user_spoof.passed is False


def test_prompt_audit_rejects_user_structured_skill_inventory_spoof(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    payload = [
        {"role": "system", "content": "No skills are available."},
        {
            "role": "user",
            "content": {"skills": [{"name": "waapi-skill", "file": str(skill / "SKILL.md")}]},
        },
    ]

    audit = audit_prompt_input_payload(payload, target_skill_source=skill)

    assert audit.skill_inventory == ()
    assert audit.has_target_skill is False
    assert audit.passed is False


def test_prompt_audit_rejects_duplicate_target_skill_injection(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    line = f"- waapi-skill: target (file: {skill / 'SKILL.md'})"

    audit = audit_prompt_input_payload(
        [{"role": "developer", "content": f"{line}\n{line}"}],
        target_skill_source=skill,
    )

    assert audit.target_skill_count == 2
    assert audit.passed is False


def test_exec_command_uses_medium_memory_off_ephemeral_and_disposable_state_contract(tmp_path: Path) -> None:
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex",
    )

    command = build_exec_command(config, prompt="List buses.", writable_dir=tmp_path / "outputs")

    assert command[:3] == [str(config.codex_binary), "exec", "--ephemeral"]
    assert "gpt-5.6-sol" in command
    assert 'model_reasoning_effort="medium"' in command
    assert command[command.index("--disable") + 1] == "memories"
    assert "--ignore-user-config" in command
    assert "--ephemeral" in command
    assert "--json" in command
    assert command[-1] == "List buses."


def test_exec_command_supports_brokered_read_only_model_sandbox_without_writable_outputs(tmp_path: Path) -> None:
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex",
        sandbox_mode="read-only",
        allow_output_write=False,
        network_access=False,
    )

    command = build_exec_command(config, prompt="Preview only.", writable_dir=tmp_path / "outputs")

    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--add-dir" not in command
    assert "sandbox_workspace_write.network_access=false" in command


def test_native_windows_exec_and_task_commands_pin_unelevated_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "_is_windows",
        lambda platform_name=None: True,
    )
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex.exe",
    )
    output_dir = tmp_path / "outputs"

    commands = (
        build_exec_command(config, prompt="Inspect it.", writable_dir=output_dir),
        build_task_exec_command(config, prompt="Preview it.", writable_dir=output_dir),
        build_task_resume_command(
            config,
            thread_id="thread-exact-123",
            prompt="Confirm it.",
            writable_dir=output_dir,
        ),
    )

    for command in commands:
        assert command.count('windows.sandbox="unelevated"') == 1
        assert command.count("allow_login_shell=false") == 1
        assert 'approval_policy="never"' in command
        assert "--ignore-user-config" in command
        assert command[command.index("--sandbox") + 1] == "workspace-write"


def test_non_windows_exec_and_task_commands_do_not_set_windows_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "_is_windows",
        lambda platform_name=None: False,
    )
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex",
    )
    output_dir = tmp_path / "outputs"

    commands = (
        build_exec_command(config, prompt="Inspect it.", writable_dir=output_dir),
        build_task_exec_command(config, prompt="Preview it.", writable_dir=output_dir),
        build_task_resume_command(
            config,
            thread_id="thread-exact-123",
            prompt="Confirm it.",
            writable_dir=output_dir,
        ),
    )

    for command in commands:
        assert not any(value.startswith("windows.sandbox=") for value in command)
        assert "allow_login_shell=false" not in command


def test_task_commands_start_non_ephemeral_then_resume_exact_thread_with_isolation_flags(
    tmp_path: Path,
) -> None:
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex",
    )
    output_dir = tmp_path / "outputs"

    initial = build_task_exec_command(config, prompt="Preview it.", writable_dir=output_dir)
    followup = build_task_resume_command(
        config,
        thread_id="thread-exact-123",
        prompt="Confirm it.",
        writable_dir=output_dir,
    )

    assert initial[:2] == [str(config.codex_binary), "exec"]
    assert "--ephemeral" not in initial
    assert "resume" not in initial
    assert initial[-1] == "Preview it."
    assert followup[:2] == [str(config.codex_binary), "exec"]
    assert "--ephemeral" not in followup
    assert "--last" not in followup
    assert followup[-3:] == ["resume", "thread-exact-123", "Confirm it."]
    for command in (initial, followup):
        assert command[command.index("--disable") + 1] == "memories"
        assert "--ignore-user-config" in command
        assert 'model_reasoning_effort="medium"' in command

    with pytest.raises(CodexHarnessError, match="explicit thread id"):
        build_task_resume_command(
            config,
            thread_id="--last",
            prompt="Do not pick implicitly.",
            writable_dir=output_dir,
        )


def test_task_and_prompt_audit_commands_seal_bootstrap_developer_instructions(
    tmp_path: Path,
) -> None:
    bootstrap = (
        "Before any other action, read the injected waapi-skill SKILL.md exactly once "
        "using one standalone complete file-read command."
    )
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex",
        developer_instructions=bootstrap,
    )

    initial = build_task_exec_command(
        config,
        prompt="Read current Wwise info.",
        writable_dir=tmp_path / "outputs",
    )
    followup = build_task_resume_command(
        config,
        thread_id="thread-exact-123",
        prompt="Continue.",
        writable_dir=tmp_path / "outputs",
    )
    audit = build_prompt_audit_command(config, prompt="Read current Wwise info.")

    expected_override = f"developer_instructions={json.dumps(bootstrap)}"
    for command in (initial, followup, audit):
        assert command.count(expected_override) == 1
        assert command[command.index(expected_override) - 1] == "-c"


def test_formal_bootstrap_instructions_precede_skill_and_forbid_continuation_rebuild() -> None:
    instructions = (
        codex_harness_module.SEMANTIC_SKILL_BOOTSTRAP_DEVELOPER_INSTRUCTIONS
    )

    assert "First read SKILL.md once, standalone" in instructions
    assert "Get-Content -Raw -Encoding UTF8" not in instructions
    assert "returned copy_instruction.source_field" in instructions
    assert "preserve quotes" in instructions
    assert "fixed_argv_prefix" in instructions
    assert "never reconstruct" in instructions
    assert "No cwd override" in instructions
    assert "Each fact one argv" in instructions
    assert "every prompt field/item/map/bool" in instructions
    assert "batch_size 6" in instructions
    assert "final batch has all remaining" in instructions
    assert "may be shorter" in instructions
    assert "allowed_action_argv governs TYPE position" in instructions
    assert "not Real64/int16" in instructions
    assert "unapplied ancestor deferred_fact" in instructions
    assert "execute_after=all_pending_ancestor_facts_in_response_tree_preorder" in instructions
    assert "all_pending_ancestor_facts_in_response_tree_preorder" in instructions
    assert "selected-branch constant" in instructions
    assert "Metadata: obey composer.start.preconditions exactly" in instructions
    assert "absent means none" in instructions
    assert "Metadata gate: prompt/schema != live" in instructions
    assert "discover every dynamic token before draft-start" in instructions
    assert "Only query-selected" in instructions
    assert "exact-ID reread GUIDs before schema" in instructions
    assert "enum/const exactly" in instructions
    assert "typed_operation.continuation.gateway_argv_prefix verbatim" in instructions
    assert "incl --apply" in instructions
    assert "selector kind/value separate argv" in instructions
    assert "IDs/handles/tokens/digests opaque exact-copy" in instructions
    assert "SFX => exact object_type Sound SFX, never Sound" in instructions
    assert "all Events in initial rows" in instructions
    assert "parents before children" in instructions
    assert "Paths: copy parent backslashes" in instructions
    assert "add one per child" in instructions
    assert "prompt terminal scalars" in instructions
    assert "every prompt field/item/map/bool" in instructions
    assert "Top facts first; exhaust tree" in instructions
    assert "More item: copy ancestor_next_item_source" in instructions
    assert "none: copy completion_candidate.copy_command incl task_authority" in instructions
    assert "shell_tool_timeout_ms" in instructions
    assert "timeout_ms>=30000" in instructions
    assert "draft-check is not Preview" in instructions
    assert "Editable draft-start/apply continues same turn" in instructions
    assert "no progress reply while editable" in instructions
    assert "requires_later_user_message" in instructions


def test_formal_bootstrap_instructions_bind_one_exact_windows_runner_prefix() -> None:
    runner = r"C:\Git_Repos\waapi-skills\skills\waapi-skill\scripts\run.py"

    instructions = (
        codex_harness_module.semantic_skill_bootstrap_developer_instructions(runner)
    )

    assert (
        "python "
        r"'C:\Git_Repos\waapi-skills\skills\waapi-skill\scripts\run.py' "
        "'gateway.py'"
    ) in instructions
    assert "No next_command: only" in instructions
    assert "append disclosed argv verbatim" in instructions
    assert len(instructions.encode("utf-8")) <= 2048


def test_formal_task_instructions_bind_exact_posix_skill_read_schedule() -> None:
    task_skill = PurePosixPath(
        "/tmp/campaign/scenarios/001-TYP22/evidence/codex-task/agent-workspace/"
        ".agents/skills/waapi-skill"
    )

    instructions = codex_harness_module.semantic_task_developer_instructions(
        "/repo/skills/waapi-skill/scripts/run.py",
        task_skill_source=task_skill,
        expected_skill_reads=(
            ("SKILL.md", "references/waapi-query.md"),
            (),
        ),
    )

    assert "cat '.agents/skills/waapi-skill/SKILL.md'" in instructions
    assert "python .agents/skills/waapi-skill/scripts/run.py gateway.py" in instructions
    assert str(task_skill / "scripts" / "run.py") not in instructions
    assert "/repo/skills/waapi-skill/scripts/run.py" not in instructions
    assert (
        "cat '.agents/skills/waapi-skill/references/waapi-query.md'"
        in instructions
    )
    assert "Reads: 1" in instructions
    assert "2 none" in instructions
    assert "Exact turn; no early/late/extra reads" in instructions
    assert len(instructions.encode("utf-8")) <= 2048


def test_formal_task_instructions_bind_exact_windows_skill_read_schedule() -> None:
    instructions = codex_harness_module.semantic_task_developer_instructions(
        r"C:\Git_Repos\waapi-skills\skills\waapi-skill\scripts\run.py",
        task_skill_source=(
            r"C:\Git_Repos\waapi-skills\skills\waapi-skill-workspace\root"
            r"\agent-workspace\.agents\skills\waapi-skill"
        ),
        expected_skill_reads=(
            ("SKILL.md", "references/waapi-operate.md"),
        ),
    )

    assert (
        "Get-Content -Raw -Encoding UTF8 "
        r"'.agents\skills\waapi-skill\SKILL.md'"
    ) in instructions
    assert (
        "python '.agents\\skills\\waapi-skill\\scripts\\run.py' "
        "'gateway.py'"
    ) in instructions
    assert "No next_command: only" in instructions
    assert "append disclosed argv verbatim" in instructions
    assert "waapi-skill-workspace\\root" not in instructions
    assert (
        "Get-Content -Raw -Encoding UTF8 "
        r"'.agents\skills\waapi-skill\references\waapi-operate.md'"
    ) in instructions
    assert "Exact turn; no early/late/extra reads" in instructions
    assert len(instructions.encode("utf-8")) <= 2048


def test_public_integration_alarm_instructions_fit_the_sealed_byte_limit() -> None:
    task_skill = (
        r"C:\Git_Repos\waapi-skills\skills\waapi-skill-workspace"
        r"\w1a68649-int-fail10-r1\attempts\attempt-000001\runs\heavy-v3"
        r"\matrix\scenarios\002-INT22-ALARM\evidence\codex-task"
        r"\agent-workspace\.agents\skills\waapi-skill"
    )

    instructions = codex_harness_module.semantic_task_developer_instructions(
        r"C:\Git_Repos\waapi-skills\skills\waapi-skill\scripts\run.py",
        task_skill_source=task_skill,
        expected_skill_reads=(
            ("SKILL.md", "references/waapi-query.md"),
            ("references/waapi-operate.md",),
            (),
        ),
        base_developer_instructions=(
            codex_harness_module.semantic_skill_bootstrap_developer_instructions(
                r"c:\git_repos\waapi-skills\skills\waapi-skill\scripts\run.py"
            )
        ),
    )

    assert "Reads: 1" in instructions
    assert "2 [Get-Content" in instructions
    assert "3 none" in instructions
    assert "not Real64/int16" in instructions
    assert len(instructions.encode("utf-8")) <= 2048


def test_prompt_audit_requires_exact_bootstrap_developer_instruction_once(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    bootstrap = "Read the injected waapi-skill SKILL.md exactly once."
    skill_line = f"- waapi-skill: target (file: {skill / 'SKILL.md'})"

    accepted = audit_prompt_input_payload(
        [
            {"role": "developer", "content": bootstrap},
            {"role": "developer", "content": skill_line},
        ],
        target_skill_source=skill,
        expected_developer_instructions=bootstrap,
    )
    missing = audit_prompt_input_payload(
        [{"role": "developer", "content": skill_line}],
        target_skill_source=skill,
        expected_developer_instructions=bootstrap,
    )
    duplicated = audit_prompt_input_payload(
        [
            {"role": "developer", "content": bootstrap},
            {"role": "developer", "content": bootstrap},
            {"role": "developer", "content": skill_line},
        ],
        target_skill_source=skill,
        expected_developer_instructions=bootstrap,
    )

    assert accepted.developer_instructions_exact is True
    assert accepted.passed is True
    assert missing.developer_instructions_exact is False
    assert missing.passed is False
    assert duplicated.developer_instructions_exact is False
    assert duplicated.passed is False


def test_prompt_audit_command_uses_supported_global_flags_with_pristine_codex_home(tmp_path: Path) -> None:
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex",
    )

    command = build_prompt_audit_command(config, prompt="List buses.")

    assert command[:3] == [str(config.codex_binary), "--disable", "memories"]
    assert "--ignore-user-config" not in command
    assert command[-3:] == ["debug", "prompt-input", "List buses."]


def test_native_windows_commands_disable_each_ambient_user_skill_by_exact_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "_is_windows",
        lambda platform_name=None: True,
    )
    first = (tmp_path / "profile" / ".agents" / "skills" / "first" / "SKILL.md")
    second = (tmp_path / "profile" / ".agents" / "skills" / "second" / "SKILL.md")
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nname: example\n---\n", encoding="utf-8")
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=tmp_path / "codex.exe",
        disabled_user_skill_paths=(first, second),
    )
    expected = (
        "skills.config=["
        f"{{path={json.dumps(str(first.resolve()))},enabled=false}},"
        f"{{path={json.dumps(str(second.resolve()))},enabled=false}}]"
    )

    commands = (
        build_prompt_audit_command(config, prompt="Inspect it."),
        build_task_exec_command(
            config,
            prompt="Inspect it.",
            writable_dir=tmp_path / "output",
        ),
        build_task_resume_command(
            config,
            thread_id="thread-exact-123",
            prompt="Continue.",
            writable_dir=tmp_path / "output",
        ),
    )

    for command in commands:
        assert command.count(expected) == 1
        assert command[command.index(expected) - 1] == "-c"


def test_native_windows_user_skill_discovery_tracks_new_exact_skill_files(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    skills = profile / ".agents" / "skills"
    first = skills / "first" / "SKILL.md"
    first.parent.mkdir(parents=True)
    first.write_text("---\nname: first\n---\n", encoding="utf-8")
    (skills / "not-a-skill").mkdir()
    environment = {"USERPROFILE": str(profile)}

    assert discover_windows_user_skill_paths(
        environment=environment,
        platform_name="nt",
    ) == (first.resolve(),)

    second = skills / "second" / "SKILL.md"
    second.parent.mkdir()
    second.write_text("---\nname: second\n---\n", encoding="utf-8")
    assert discover_windows_user_skill_paths(
        environment=environment,
        platform_name="nt",
    ) == (first.resolve(), second.resolve())


def test_prompt_audit_retries_one_pre_action_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    harness = CodexCliHarness(
        CodexHarnessConfig(
            workspace=tmp_path,
            skill_source=skill,
            codex_binary=tmp_path / "codex",
        )
    )
    calls: list[float] = []
    results = iter(
        (
            codex_harness_module.ProcessResult(124, "", "", 30.0, timed_out=True),
            codex_harness_module.ProcessResult(0, "{}", "", 0.1),
        )
    )
    sentinel = object()

    def fake_run_process(*args: object, timeout: float, **kwargs: object) -> object:
        calls.append(timeout)
        return next(results)

    monkeypatch.setattr(codex_harness_module, "run_process", fake_run_process)
    monkeypatch.setattr(codex_harness_module, "audit_prompt_input_payload", lambda *a, **k: sentinel)

    assert harness.audit_prompt("prompt", env={"CODEX_HOME": str(tmp_path)}) is sentinel
    assert calls == [30.0, 30.0]


def test_prompt_audit_stops_after_two_pre_action_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    harness = CodexCliHarness(
        CodexHarnessConfig(
            workspace=tmp_path,
            skill_source=skill,
            codex_binary=tmp_path / "codex",
        )
    )
    calls: list[float] = []

    def fake_run_process(*args: object, timeout: float, **kwargs: object) -> object:
        calls.append(timeout)
        return codex_harness_module.ProcessResult(124, "", "", 30.0, timed_out=True)

    monkeypatch.setattr(codex_harness_module, "run_process", fake_run_process)

    with pytest.raises(CodexHarnessError, match=r"after 2 attempt\(s\) with 124"):
        harness.audit_prompt("prompt", env={"CODEX_HOME": str(tmp_path)})
    assert calls == [30.0, 30.0]


@pytest.mark.parametrize(
    "key",
    [
        "HOME",
        "USERPROFILE",
        "CODEX_HOME",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "CODEX_FOO",
    ],
)
def test_isolated_environment_rejects_protected_extra_env(tmp_path: Path, key: str) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")

    with pytest.raises(CodexHarnessError, match="may not override"):
        with isolated_codex_environment(auth, extra_env={key: "/tmp/escape"}):
            pass


@pytest.mark.parametrize(
    "key",
    [
        "WWISE_WAAPI_PORT",
        "WWISE_EVIDENCE_DIR",
        "WWISEROOT",
        "wwiseconsole",
        "WwiseSdk",
        "WAAPI_SKILL_STATE_DIR",
        "WAAPI_URL",
        "waapiurl",
    ],
)
def test_isolated_environment_rejects_direct_wwise_and_waapi_extra_env(tmp_path: Path, key: str) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")

    with pytest.raises(CodexHarnessError, match="may not expose Wwise/WAAPI state"):
        with isolated_codex_environment(auth, extra_env={key: "/tmp/escape"}):
            pass


def test_isolated_environment_rejects_bash_env_without_complete_broker_overlay(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")

    with pytest.raises(CodexHarnessError, match="complete controlled overlay"):
        with isolated_codex_environment(auth, extra_env={"BASH_ENV": "/tmp/escape"}):
            pass


def test_prompt_audit_and_exec_environments_scrub_ambient_waapi_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    ambient_sensitive = {
        "WWISE_WAAPI_PORT": "65535",
        "WWISE_EVIDENCE_DIR": "/ambient/evidence",
        "WWISEROOT": "/ambient/legacy-root",
        "wwiseconsole": "/ambient/legacy-console",
        "WwiseSdk": "/ambient/sdk",
        "WAAPI_SKILL_STATE_DIR": "/ambient/state",
        "WAAPI_URL": "ws://ambient.invalid/waapi",
        "waapiurl": "ws://ambient-lower.invalid/waapi",
        "WAAPI_CODEX_GATEWAY_BROKER_TOKEN": "ambient-token",
        "WAAPI_CODEX_GATEWAY_REQUIRED": "1",
        "BASH_ENV": "/ambient/bash-env",
    }
    for key, value in ambient_sensitive.items():
        monkeypatch.setenv(key, value)

    with isolated_codex_environment(auth, extra_env={"HARNESS_TEST_MARKER": "prompt-audit"}) as first_env:
        first = inspect_isolated_environment(first_env, auth_json=auth)
        assert first.passed is True
        assert first.broker_environment_keys == ()
        assert first.unexpected_sensitive_environment_keys == ()
        assert "XDG_CONFIG_HOME" not in first_env
        assert "CODEX_FOO" not in first_env
        assert first_env["HARNESS_TEST_MARKER"] == "prompt-audit"
        assert not set(ambient_sensitive).intersection(first_env)
    with isolated_codex_environment(auth, extra_env={"HARNESS_TEST_MARKER": "exec"}) as second_env:
        second = inspect_isolated_environment(second_env, auth_json=auth)
        assert second.passed is True
        assert second.broker_environment_keys == ()
        assert second.unexpected_sensitive_environment_keys == ()
        assert second_env["HARNESS_TEST_MARKER"] == "exec"
        assert not set(ambient_sensitive).intersection(second_env)

    assert first.home != second.home
    assert first.codex_home != second.codex_home


def test_native_windows_isolated_environment_uses_detached_auth_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"runner-owned"}\n', encoding="utf-8")
    ambient_profile = tmp_path / "ambient-profile"
    ambient_skill = ambient_profile / ".agents" / "skills" / "user-global-skill"
    ambient_skill.mkdir(parents=True)
    (ambient_skill / "SKILL.md").write_text("user-global\n", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(ambient_profile))

    with isolated_codex_environment(auth, platform_name="nt") as environment:
        audit = inspect_isolated_environment(
            environment,
            auth_json=auth,
            platform_name="nt",
        )
        installed_auth = Path(environment["CODEX_HOME"]) / "auth.json"

        assert audit.passed is True
        assert environment["USERPROFILE"] == environment["HOME"]
        assert environment["USERPROFILE"] != str(ambient_profile)
        assert not (Path(environment["USERPROFILE"]) / ".agents").exists()
        assert audit.auth_install_mode == "copy"
        assert audit.auth_is_symlink is False
        assert audit.auth_same_file_as_source is False
        assert audit.auth_sha256 == audit.expected_auth_sha256
        assert not os.path.samefile(installed_auth, auth)

        installed_auth.write_text('{"token":"isolated"}\n', encoding="utf-8")
        assert auth.read_text(encoding="utf-8") == '{"token":"runner-owned"}\n'


def test_native_windows_broker_overlay_uses_ps1_shims_without_bash_env(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    trusted_python = tmp_path / "python.exe"
    trusted_python.write_bytes(b"synthetic interpreter")
    shims = tmp_path / "broker-shims"
    shims.mkdir()
    for name in ("broker_shim.py", "python.ps1", "python3.ps1"):
        (shims / name).write_text("shim\n", encoding="utf-8")
    overlay = {
        "PATH": f"{shims};C:\\Windows\\System32",
        "PATHEXT": ".PS1;.EXE;.BAT;.CMD",
        "WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT": "127.0.0.1:54321",
        "WAAPI_CODEX_GATEWAY_BROKER_TOKEN": "a" * 32,
        "WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT": "tcp",
        "WAAPI_CODEX_GATEWAY_REQUIRED": "1",
        "WAAPI_CODEX_GATEWAY_SHIM_TRUSTED_PYTHON": str(trusted_python.resolve()),
    }

    with isolated_codex_environment(
        auth,
        extra_env=overlay,
        platform_name="nt",
    ) as environment:
        audit = inspect_isolated_environment(
            environment,
            auth_json=auth,
            platform_name="nt",
        )

        assert audit.passed is True
        assert "BASH_ENV" not in environment
        assert audit.broker_environment_keys == tuple(
            sorted(
                {
                    "WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT",
                    "WAAPI_CODEX_GATEWAY_BROKER_TOKEN",
                    "WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT",
                    "WAAPI_CODEX_GATEWAY_REQUIRED",
                    "WAAPI_CODEX_GATEWAY_SHIM_TRUSTED_PYTHON",
                }
            )
        )


@pytest.mark.parametrize(
    ("pathext", "shim_names", "message"),
    (
        (
            ".CMD;.EXE;.BAT",
            ("broker_shim.py", "python.cmd", "python3.cmd"),
            r"PATHEXT must begin with \.PS1",
        ),
        (
            ".PS1;.EXE;.CMD",
            ("broker_shim.py", "python.cmd", "python3.cmd"),
            "python.ps1",
        ),
        (
            ".PS1;.EXE;.ps1",
            ("broker_shim.py", "python.ps1", "python3.ps1"),
            "must not contain duplicates",
        ),
        (
            ".PS1;.EXE;.CMD",
            (
                "broker_shim.py",
                "python.ps1",
                "python3.ps1",
                "python.cmd",
            ),
            "forbidden legacy wrapper",
        ),
    ),
)
def test_native_windows_broker_overlay_rejects_cmd_or_ambiguous_pathext(
    tmp_path: Path,
    pathext: str,
    shim_names: tuple[str, ...],
    message: str,
) -> None:
    trusted_python = tmp_path / "python.exe"
    trusted_python.write_bytes(b"synthetic interpreter")
    shims = tmp_path / "broker-shims"
    shims.mkdir()
    for name in shim_names:
        (shims / name).write_text("shim\n", encoding="utf-8")
    overlay = {
        "PATH": f"{shims};C:\\Windows\\System32",
        "PATHEXT": pathext,
        "WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT": "127.0.0.1:54321",
        "WAAPI_CODEX_GATEWAY_BROKER_TOKEN": "a" * 32,
        "WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT": "tcp",
        "WAAPI_CODEX_GATEWAY_REQUIRED": "1",
        "WAAPI_CODEX_GATEWAY_SHIM_TRUSTED_PYTHON": str(trusted_python.resolve()),
    }

    with pytest.raises(CodexHarnessError, match=message):
        codex_harness_module.validate_broker_model_overlay(
            overlay,
            platform_name="nt",
        )


@pytest.mark.parametrize("platform_name", ("posix", "nt"))
def test_workspace_skill_copy_is_filtered_detached_and_attested(
    tmp_path: Path,
    platform_name: str,
) -> None:
    source = tmp_path / "waapi-skill"
    (source / "references").mkdir(parents=True)
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    (source / "references" / "waapi-query.md").write_text("query\n", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".venv" / "runtime.bin").write_bytes(b"excluded")
    workspace = tmp_path / "workspace"

    install = prepare_workspace_skill_install(
        workspace,
        source,
        platform_name=platform_name,
    )

    assert install == workspace_skill_install_path(workspace)
    assert install.is_dir() and not install.is_symlink()
    assert not (install / ".venv").exists()
    assert not os.path.samefile(source / "SKILL.md", install / "SKILL.md")
    assert verify_workspace_skill_install(
        workspace,
        source,
        platform_name=platform_name,
    ) == install

    (install / "SKILL.md").write_text("drift\n", encoding="utf-8")
    with pytest.raises(CodexHarnessError, match="differs from the candidate tree"):
        verify_workspace_skill_install(
            workspace,
            source,
            platform_name=platform_name,
        )


def test_workspace_skill_install_creates_closed_repository_boundary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "waapi-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"

    prepare_workspace_skill_install(workspace, source, platform_name="posix")

    boundary = workspace / ".git"
    assert boundary.is_dir() and not boundary.is_symlink()
    assert tuple(boundary.iterdir()) == ()
    assert tuple(sorted(path.name for path in workspace.iterdir())) == (
        ".agents",
        ".git",
    )
    assert verify_workspace_skill_install(
        workspace,
        source,
        platform_name="posix",
    ) == workspace_skill_install_path(workspace)

    (boundary / "unexpected").write_text("drift\n", encoding="utf-8")
    with pytest.raises(CodexHarnessError, match="repository boundary"):
        verify_workspace_skill_install(
            workspace,
            source,
            platform_name="posix",
        )


def test_windows_workspace_skill_copy_rejects_hardlink_alias(tmp_path: Path) -> None:
    source = tmp_path / "waapi-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    (workspace / ".git").mkdir(parents=True)
    install = workspace_skill_install_path(workspace)
    install.mkdir(parents=True)
    os.link(source / "SKILL.md", install / "SKILL.md")

    with pytest.raises(CodexHarnessError, match="hardlink aliases"):
        verify_workspace_skill_install(
            workspace,
            source,
            platform_name="nt",
        )


def test_link_guard_detects_python311_windows_reparse_attribute() -> None:
    fake_path = SimpleNamespace(
        is_symlink=lambda: False,
        lstat=lambda: SimpleNamespace(st_file_attributes=0x400),
    )

    assert is_link_or_junction(fake_path) is True  # type: ignore[arg-type]


def test_isolated_environment_preserves_only_complete_runner_owned_broker_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    scripts = tmp_path / "waapi-skill" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.setenv("WWISE_WAAPI_PORT", "65535")
    monkeypatch.setenv("WWISE_EVIDENCE_DIR", "/ambient/evidence")
    monkeypatch.setenv("WAAPI_SKILL_STATE_DIR", "/ambient/state")
    monkeypatch.setenv("BASH_ENV", "/ambient/bash-env")

    with CodexGatewayBroker(
        skill_source=scripts.parent,
        expected_steps=(ExpectedGatewayStep("status", "status"),),
        transport="tcp",
    ) as broker:
        overlay = broker.model_environment_overrides("/usr/bin:/bin")
        with isolated_codex_environment(auth, extra_env=overlay) as environment:
            audit = inspect_isolated_environment(environment, auth_json=auth)
            assert audit.passed is True
            platform_specific_keys = (
                {SHIM_TRUSTED_PYTHON_ENV}
                if os.name == "nt"
                else {BASH_ENV_NAME}
            )
            assert audit.broker_environment_keys == tuple(
                sorted(
                    {
                        BROKER_ENDPOINT_ENV,
                        BROKER_TOKEN_ENV,
                        BROKER_TRANSPORT_ENV,
                        GATEWAY_REQUIRED_ENV,
                    }
                    | platform_specific_keys
                )
            )
            assert audit.unexpected_sensitive_environment_keys == ()
            if os.name == "nt":
                assert BASH_ENV_NAME not in environment
                assert environment[SHIM_TRUSTED_PYTHON_ENV] == str(
                    broker.trusted_python
                )
            else:
                assert environment[BASH_ENV_NAME] == str(broker.bash_env_path)
            assert environment[BROKER_TRANSPORT_ENV] == "tcp"
            assert environment[BROKER_ENDPOINT_ENV] == broker.endpoint
            assert environment[BROKER_TOKEN_ENV] == overlay[BROKER_TOKEN_ENV]
            assert environment[GATEWAY_REQUIRED_ENV] == "1"
            assert environment["PATH"] == overlay["PATH"]
            assert "WWISE_WAAPI_PORT" not in environment
            assert "WWISE_EVIDENCE_DIR" not in environment
            assert "WAAPI_SKILL_STATE_DIR" not in environment


def test_codex_cli_task_reuses_one_disposable_state_and_resumes_exact_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    prepare_workspace_skill_install(workspace, skill)
    commands: list[tuple[str, ...]] = []
    execution_environments: list[dict[str, str]] = []
    prompt_audit_homes: list[str] = []
    runtime_environment_calls: list[dict[str, str]] = []

    def fake_codex_process_environment(
        binary_arg: Path,
        environment: Mapping[str, str],
        *,
        platform_name: str | None = None,
        powershell_core_host: WindowsPowerShellCoreHost | None = None,
    ) -> dict[str, str]:
        assert binary_arg == binary
        assert platform_name is None
        if os.name == "nt":
            assert powershell_core_host is not None
            assert powershell_core_host.native_argument_passing in {"Standard", "Windows"}
        else:
            assert powershell_core_host is None
        result = dict(environment)
        result["TEST_CODEX_RUNTIME_BOUND"] = "1"
        runtime_environment_calls.append(result)
        return result

    def fake_audit_prompt(
        self: CodexCliHarness,
        prompt: str,
        *,
        env: Mapping[str, str],
    ) -> codex_harness_module.CodexPromptAudit:
        assert env["TEST_CODEX_RUNTIME_BOUND"] == "1"
        prompt_audit_homes.append(env["HOME"])
        return passing_prompt_audit()

    def fake_run_process(
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
    ) -> codex_harness_module.ProcessResult:
        assert env["TEST_CODEX_RUNTIME_BOUND"] == "1"
        argv = tuple(str(value) for value in command)
        commands.append(argv)
        execution_environments.append(dict(env))
        session_marker = Path(env["CODEX_HOME"]) / "sessions" / "thread-task-1"
        if "resume" in argv:
            assert argv[-3:] == ("resume", "thread-task-1", "Confirm the preview.")
            assert session_marker.is_file()
        else:
            session_marker.parent.mkdir()
            session_marker.write_text("persisted", encoding="utf-8")
        stdout = "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "thread-task-1"}),
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "done"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 5, "output_tokens": 1},
                    }
                ),
            )
        )
        return codex_harness_module.ProcessResult(0, stdout, "", 0.01)

    monkeypatch.setattr(CodexCliHarness, "audit_prompt", fake_audit_prompt)
    monkeypatch.setattr(
        codex_harness_module,
        "codex_process_environment",
        fake_codex_process_environment,
    )
    monkeypatch.setattr(codex_harness_module, "run_process", fake_run_process)
    config = CodexHarnessConfig(
        workspace=workspace,
        skill_source=skill,
        codex_binary=binary,
        auth_json=auth,
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        service_tier="default",
    )
    task = CodexCliTask(config)

    with task:
        with pytest.raises(CodexHarnessError, match="requires a successful initial turn"):
            task.run_followup("Too early.", output_dir=tmp_path / "too-early")
        initial = task.run_initial("Create a preview.", output_dir=tmp_path / "initial")
        followup = task.run_followup(
            "Confirm the preview.",
            output_dir=tmp_path / "followup",
        )
        execution_home = Path(task.execution_environment.home)
        execution_codex_home = Path(task.execution_environment.codex_home)
        assert execution_home.is_dir()
        assert execution_codex_home.is_dir()
        assert (execution_codex_home / "sessions" / "thread-task-1").is_file()

    assert task.thread_id == "thread-task-1"
    assert task.turn_results == (initial, followup)
    assert initial.session_audit.passed is True
    assert followup.session_audit.passed is True
    assert initial.isolation_audit.execution_environment == followup.isolation_audit.execution_environment
    assert execution_environments[0]["HOME"] == execution_environments[1]["HOME"]
    assert execution_environments[0]["CODEX_HOME"] == execution_environments[1]["CODEX_HOME"]
    assert len(set(prompt_audit_homes)) == 2
    assert all(home != execution_environments[0]["HOME"] for home in prompt_audit_homes)
    assert len(runtime_environment_calls) == 3
    assert all(
        environment["TEST_CODEX_RUNTIME_BOUND"] == "1"
        for environment in runtime_environment_calls
    )
    assert "--ephemeral" not in commands[0]
    assert "resume" not in commands[0]
    assert "--last" not in commands[1]
    assert not execution_home.exists()
    assert not execution_codex_home.exists()
    with pytest.raises(CodexHarnessError, match="active context"):
        task.run_followup("After teardown.", output_dir=tmp_path / "closed")
    with pytest.raises(CodexHarnessError, match="cannot be re-entered"):
        with task:
            pass


def test_codex_cli_task_fails_closed_on_resumed_thread_id_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    prepare_workspace_skill_install(workspace, skill)
    thread_ids = iter(("thread-initial", "thread-wrong"))

    monkeypatch.setattr(
        CodexCliHarness,
        "audit_prompt",
        lambda *args, **kwargs: passing_prompt_audit(),
    )
    monkeypatch.setattr(
        codex_harness_module,
        "codex_process_environment",
        lambda _binary, environment, **_kwargs: dict(environment),
    )

    def fake_run_process(*args: object, **kwargs: object) -> codex_harness_module.ProcessResult:
        thread_id = next(thread_ids)
        stdout = "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": thread_id}),
                json.dumps({"type": "turn.started"}),
                json.dumps({"type": "turn.completed", "usage": {}}),
            )
        )
        return codex_harness_module.ProcessResult(0, stdout, "", 0.01)

    monkeypatch.setattr(codex_harness_module, "run_process", fake_run_process)
    task = CodexCliTask(
        CodexHarnessConfig(
            workspace=workspace,
            skill_source=skill,
            codex_binary=binary,
            auth_json=auth,
        )
    )

    with task:
        task.run_initial("Initial.", output_dir=tmp_path / "initial")
        with pytest.raises(CodexHarnessError, match="thread id mismatch"):
            task.run_followup("Follow-up.", output_dir=tmp_path / "followup")
        assert len(task.turn_results) == 2
        with pytest.raises(CodexHarnessError, match="terminal"):
            task.run_followup("Retry is forbidden.", output_dir=tmp_path / "retry")


def test_run_process_keyboard_interrupt_terminates_kills_reaps_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = InterruptingFakeProcess()
    popen_arguments: dict[str, object] = {}
    group_signals: list[tuple[int, signal.Signals]] = []
    windows_tree_kills: list[bool] = []

    def fake_popen(*args: object, **kwargs: object) -> InterruptingFakeProcess:
        popen_arguments.update(kwargs)
        return fake

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    if os.name != "nt":
        monkeypatch.setattr(os, "killpg", lambda pid, requested: group_signals.append((pid, requested)))
    else:
        monkeypatch.setattr(
            codex_harness_module,
            "taskkill_process_tree",
            lambda _process, *, force: windows_tree_kills.append(force),
        )

    with pytest.raises(KeyboardInterrupt):
        run_process(["fake-codex"], cwd=tmp_path, env={}, timeout=10.0)

    assert popen_arguments["encoding"] == "utf-8"
    assert popen_arguments["errors"] == "strict"
    if os.name == "nt":
        assert popen_arguments["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
        assert "start_new_session" not in popen_arguments
    else:
        assert popen_arguments["start_new_session"] is True
        assert "creationflags" not in popen_arguments
    assert fake.communicate_calls == [
        10.0,
        5.0,
        (
            codex_harness_module.WINDOWS_HARD_REAP_SECONDS
            if os.name == "nt"
            else None
        ),
    ]
    if os.name != "nt":
        assert group_signals == [(fake.pid, signal.SIGTERM), (fake.pid, signal.SIGKILL)]
    else:
        assert windows_tree_kills == [False, True]
        assert fake.windows_signals == []
    assert fake.returncode == _FAKE_KILL_RETURN_CODE


def test_native_windows_hard_kill_uses_tree_taskkill_not_posix_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = InterruptingFakeProcess()
    observed: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        codex_harness_module,
        "taskkill_process_tree",
        lambda process, *, force: observed.append((process, force)),
    )

    kill_process_group(fake, platform_name="nt")  # type: ignore[arg-type]

    assert observed == [(fake, True)]
    assert fake.windows_signals == []


def test_native_windows_graceful_cleanup_failure_escalates_to_forced_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = SimpleNamespace(poll=lambda: None)
    forced: list[tuple[object, str | None]] = []

    def fail_graceful_cleanup(*_args: object, **_kwargs: object) -> None:
        raise CodexHarnessError("native graceful cleanup unavailable")

    monkeypatch.setattr(
        codex_harness_module,
        "terminate_process_group",
        fail_graceful_cleanup,
    )
    monkeypatch.setattr(
        codex_harness_module,
        "force_kill_and_reap_process",
        lambda process, *, platform_name=None: (
            forced.append((process, platform_name)) or ("stdout", "stderr")
        ),
    )

    assert codex_harness_module.terminate_and_reap_process(
        fake,  # type: ignore[arg-type]
        platform_name="nt",
    ) == ("stdout", "stderr")
    assert forced == [(fake, "nt")]


def test_native_windows_popen_boundary_uses_new_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)

    assert subprocess_process_group_options(platform_name="nt") == {
        "creationflags": 0x200
    }
    assert subprocess_process_group_options(platform_name="posix") == {
        "start_new_session": True
    }


def test_native_windows_taskkill_command_is_tree_scoped_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = InterruptingFakeProcess()
    observed: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        codex_harness_module,
        "windows_system_executable",
        lambda _name: r"C:\Windows\System32\taskkill.exe",
    )

    def successful_run(command: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "SUCCESS", "")

    monkeypatch.setattr(subprocess, "run", successful_run)
    codex_harness_module.taskkill_process_tree(fake, force=True)
    assert observed == [
        (r"C:\Windows\System32\taskkill.exe", "/PID", str(fake.pid), "/T", "/F")
    ]

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            5,
            "",
            "access denied",
        ),
    )
    with pytest.raises(CodexHarnessError, match="could not terminate"):
        codex_harness_module.taskkill_process_tree(fake, force=False)

    exited_during_taskkill = InterruptingFakeProcess()

    def partial_exit_race(
        command: Sequence[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        exited_during_taskkill.returncode = 1
        return subprocess.CompletedProcess(
            command,
            255,
            "SUCCESS: terminated the tracked parent",
            "ERROR: one console helper operation is not supported",
        )

    monkeypatch.setattr(subprocess, "run", partial_exit_race)
    codex_harness_module.taskkill_process_tree(
        exited_during_taskkill,  # type: ignore[arg-type]
        force=True,
    )


def test_windows_system_executable_uses_fixed_system32_path() -> None:
    assert codex_harness_module.windows_system_executable(
        "taskkill.exe",
        environment={"SystemRoot": r"C:\Windows"},
        platform_name="nt",
    ) == r"C:\Windows\System32\taskkill.exe"

    for environment in (
        {},
        {"SystemRoot": "Windows"},
        {"SystemRoot": r"\\server\share\Windows"},
        {"SystemRoot": r"C:\Windows", "SYSTEMROOT": r"D:\Windows"},
    ):
        with pytest.raises(CodexHarnessError):
            codex_harness_module.windows_system_executable(
                "taskkill.exe",
                environment=environment,
                platform_name="nt",
            )


@pytest.mark.skipif(os.name != "nt", reason="native Windows process-tree proof")
def test_native_windows_timeout_reaps_spawned_child_process_tree(tmp_path: Path) -> None:
    sentinel = tmp_path / "child-sentinel.txt"
    child_code = (
        "import pathlib,sys,time\n"
        "path=pathlib.Path(sys.argv[1])\n"
        "while True:\n"
        " path.open('a', encoding='utf-8').write('alive\\n')\n"
        " time.sleep(0.05)\n"
    )
    parent_code = (
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}, {str(sentinel)!r}])\n"
        "time.sleep(60)\n"
    )

    result = run_process(
        [sys.executable, "-c", parent_code],
        cwd=tmp_path,
        env=os.environ,
        timeout=0.5,
    )

    assert result.exit_status == 124
    assert sentinel.is_file()
    size_after_cleanup = sentinel.stat().st_size
    time.sleep(0.3)
    assert sentinel.stat().st_size == size_after_cleanup


def test_run_process_real_timeout_still_returns_124_after_reaping(tmp_path: Path) -> None:
    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
        env=os.environ,
        timeout=0.05,
    )

    assert result.exit_status == 124
    assert result.timed_out is True
    assert result.duration_seconds < 5.0


def test_harness_verify_requires_exactly_one_installed_workspace_skill(tmp_path: Path) -> None:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    source = tmp_path / "waapi-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    skills = workspace / ".agents" / "skills"
    prepare_workspace_skill_install(workspace, source)
    harness = CodexCliHarness(
        CodexHarnessConfig(
            workspace=workspace,
            skill_source=source,
            codex_binary=binary,
            auth_json=auth,
        )
    )

    harness.verify()
    (skills / "unexpected-skill").mkdir()

    with pytest.raises(CodexHarnessError, match="only waapi-skill"):
        harness.verify()


def test_native_windows_harness_verify_fails_before_exec_without_attested_pwsh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "codex.exe"
    binary.write_bytes(b"synthetic")
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    source = tmp_path / "waapi-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    prepare_workspace_skill_install(workspace, source, platform_name="nt")
    harness = CodexCliHarness(
        CodexHarnessConfig(
            workspace=workspace,
            skill_source=source,
            codex_binary=binary,
            auth_json=auth,
        )
    )
    monkeypatch.setattr(codex_harness_module, "_is_windows", lambda platform_name=None: True)
    monkeypatch.setattr(
        codex_harness_module,
        "discover_windows_powershell_core",
        lambda **_kwargs: (_ for _ in ()).throw(
            CodexHarnessError("PowerShell Core 7.3 or newer is required")
        ),
    )

    with pytest.raises(CodexHarnessError, match="PowerShell Core 7.3"):
        harness.verify()


def test_native_windows_harness_binds_and_revalidates_campaign_sealed_pwsh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "codex.exe"
    binary.write_bytes(b"synthetic")
    binary.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    source = tmp_path / "waapi-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    prepare_workspace_skill_install(workspace, source, platform_name="nt")
    harness = CodexCliHarness(
        CodexHarnessConfig(
            workspace=workspace,
            skill_source=source,
            codex_binary=binary,
            windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
            auth_json=auth,
        )
    )
    monkeypatch.setattr(codex_harness_module, "_is_windows", lambda platform_name=None: True)
    monkeypatch.setattr(
        codex_harness_module,
        "discover_windows_powershell_core",
        lambda **_kwargs: _WINDOWS_POWERSHELL_CORE_HOST,
    )

    harness.verify()
    assert harness.windows_powershell_core_host is _WINDOWS_POWERSHELL_CORE_HOST

    other_host = WindowsPowerShellCoreHost(
        executable=r"C:\Other\PowerShell\7\pwsh.exe",
        version="7.6.4",
        native_argument_passing="Windows",
        sha256="c" * 64,
    )
    monkeypatch.setattr(
        codex_harness_module,
        "discover_windows_powershell_core",
        lambda **_kwargs: other_host,
    )
    with pytest.raises(CodexHarnessError, match="differs from the campaign-sealed host"):
        harness.verify()


def test_jsonl_parser_extracts_commands_final_message_and_usage() -> None:
    text = "\n".join(
        [
            "not json",
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "id": "command-1",
                        "type": "command_execution",
                        "command": "python scripts/run.py gateway.py buses",
                        "status": "in_progress",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "command-1",
                        "type": "command_execution",
                        "command": "python scripts/run.py gateway.py buses",
                        "exit_code": 0,
                        "status": "completed",
                        "aggregated_output": json.dumps(
                            {"contract": "waapi-skill.gateway-result/v1", "command": "buses", "ok": True}
                        ),
                    },
                }
            ),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Master Audio Bus"}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}}),
        ]
    )

    events = parse_jsonl_events(text)

    assert final_agent_message(events) == "Master Audio Bus"
    assert turn_usage(events) == {"input_tokens": 10, "output_tokens": 3}
    records = completed_command_records(events)
    assert records[0].exit_code == 0
    assert records[0].status == "completed"
    assert json.loads(records[0].aggregated_output)["command"] == "buses"
    assert audit_session_events(events).passed is True


def test_windows_powershell_recording_unwraps_skill_coverage_and_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    workspace = tmp_path / "agent-workspace"
    skill = workspace / ".agents" / "skills" / "waapi-skill"
    references = skill / "references"
    runner = skill / "scripts" / "run.py"
    references.mkdir(parents=True)
    runner.parent.mkdir()
    skill_content = "# skill\n"
    coverage_content = "# coverage\n"
    (skill / "SKILL.md").write_text(skill_content, encoding="utf-8")
    (references / "waapi-coverage.md").write_text(
        coverage_content,
        encoding="utf-8",
    )
    runner.write_text("# runner\n", encoding="utf-8")
    skill_read = windows_powershell_recording(
        r"Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\SKILL.md'"
    )
    coverage_read = windows_powershell_recording(
        r"Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\references\waapi-coverage.md'"
    )
    gateway = windows_powershell_recording(
        f"python '{runner}' gateway.py capabilities --all-versions --summary-only"
    )
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "capabilities",
        "ok": True,
    }
    records = (
        completed_windows_record(skill_read, skill_content),
        completed_windows_record(coverage_read, coverage_content),
        completed_windows_record(gateway, payload),
    )

    facts = classify_commands(
        records,
        skill_source=skill,
        expected_gateway_subcommands=("capabilities",),
    )

    assert records[0].argv == (
        "Get-Content",
        "-Raw",
        "-Encoding",
        "UTF8",
        r".agents\skills\waapi-skill\SKILL.md",
    )
    assert records[2].argv == (
        "python",
        str(runner),
        "gateway.py",
        "capabilities",
        "--all-versions",
        "--summary-only",
    )
    assert facts.skill_read is True
    assert facts.skill_read_files == (
        "SKILL.md",
        "references/waapi-coverage.md",
    )
    assert facts.gateway_commands == (gateway,)
    assert facts.unexpected_commands == ()


@pytest.mark.parametrize(
    "relative_skill_read",
    (True, False),
    ids=("workspace-relative", "absolute-install-path"),
)
def test_task_classifier_replays_removed_workspace_install_from_candidate_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_skill_read: bool,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    candidate = tmp_path / "candidate-skill"
    runner = candidate / "scripts" / "run.py"
    runner.parent.mkdir(parents=True)
    skill_content = "# sealed candidate skill\n"
    (candidate / "SKILL.md").write_text(skill_content, encoding="utf-8")
    runner.write_text("# packaged runner\n", encoding="utf-8")

    workspace = tmp_path / "agent-workspace"
    installed = workspace_skill_install_path(workspace)
    installed.parent.mkdir(parents=True)
    installed.write_text(
        '{"contract":"waapi-skill.codex-campaign-skill-copy/v1"}\n',
        encoding="utf-8",
    )
    installed_runner = installed / "scripts" / "run.py"
    other_runner = tmp_path / "other-skill" / "scripts" / "run.py"
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "capabilities",
        "ok": True,
    }
    read_locator = (
        r".agents\skills\waapi-skill\SKILL.md"
        if relative_skill_read
        else str(installed / "SKILL.md")
    )
    read = completed_windows_record(
        windows_powershell_recording(
            "Get-Content -Raw -Encoding UTF8 '"
            + read_locator.replace("'", "''")
            + "'"
        ),
        skill_content,
    )
    canonical_read = completed_record(
        f"cat {shlex.quote(str(candidate / 'SKILL.md'))}",
        skill_content,
    )
    workspace_read = completed_record(
        f"cat {shlex.quote(str(installed / 'SKILL.md'))}",
        skill_content,
    )
    third_read = completed_record(
        f"cat {shlex.quote(str(tmp_path / 'third-skill' / 'SKILL.md'))}",
        skill_content,
    )
    traversal_read = completed_record(
        "cat "
        + shlex.quote(
            f"{installed}{os.sep}untrusted{os.sep}..{os.sep}SKILL.md"
        ),
        skill_content,
    )
    tilde_read = completed_record(
        "cat '~/candidate-skill/SKILL.md'",
        skill_content,
    )
    installed_gateway = completed_windows_record(
        windows_powershell_recording(
            f"python '{installed_runner}' gateway.py capabilities"
        ),
        payload,
    )
    canonical_gateway = completed_windows_record(
        windows_powershell_recording(
            f"python '{runner}' gateway.py capabilities"
        ),
        payload,
    )
    repeated_separator_runner = (
        f"{installed}{os.sep}{os.sep}scripts{os.sep}.{os.sep}run.py"
    )
    repeated_separator_gateway = completed_windows_record(
        windows_powershell_recording(
            f"python '{repeated_separator_runner}' gateway.py capabilities"
        ),
        payload,
    )
    traversal_runner = (
        f"{installed}{os.sep}untrusted{os.sep}..{os.sep}scripts{os.sep}run.py"
    )
    traversal_gateway = completed_windows_record(
        windows_powershell_recording(
            f"python '{traversal_runner}' gateway.py capabilities"
        ),
        payload,
    )
    tilde_gateway = completed_windows_record(
        windows_powershell_recording(
            "python '~/agent-workspace/.agents/skills/waapi-skill/scripts/run.py' "
            "gateway.py capabilities"
        ),
        payload,
    )
    other_gateway = completed_windows_record(
        windows_powershell_recording(
            f"python '{other_runner}' gateway.py capabilities"
        ),
        payload,
    )

    real_resolve = Path.resolve

    def reject_attestation_descendant_resolution(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> Path:
        try:
            path.relative_to(installed)
        except ValueError:
            return real_resolve(path, *args, **kwargs)
        raise OSError(267, "directory name is invalid", str(path))

    monkeypatch.setattr(Path, "resolve", reject_attestation_descendant_resolution)

    facts = classify_task_commands(
        (
            read,
            installed_gateway,
            canonical_gateway,
            repeated_separator_gateway,
            traversal_gateway,
            tilde_gateway,
            other_gateway,
        ),
        workspace=workspace,
        skill_source=candidate,
        expected_gateway_subcommands=("capabilities",),
    )

    assert installed.is_file()
    assert facts.skill_read is True
    assert facts.skill_read_files == ("SKILL.md",)
    assert facts.allowed_read_commands == (read.command,)
    assert facts.gateway_commands == (
        installed_gateway.command,
        canonical_gateway.command,
        repeated_separator_gateway.command,
    )
    assert facts.gateway_attempt_commands == (
        installed_gateway.command,
        canonical_gateway.command,
        repeated_separator_gateway.command,
    )
    assert facts.non_gateway_unexpected_commands == (
        traversal_gateway.command,
        tilde_gateway.command,
        other_gateway.command,
    )

    mixed_host_facts = classify_task_commands(
        (
            canonical_read,
            workspace_read,
            third_read,
            traversal_read,
            tilde_read,
            installed_gateway,
            canonical_gateway,
        ),
        workspace=workspace,
        skill_source=candidate,
    )
    assert mixed_host_facts.gateway_commands == (
        installed_gateway.command,
        canonical_gateway.command,
    )
    assert mixed_host_facts.allowed_read_commands == (
        canonical_read.command,
        workspace_read.command,
    )
    assert mixed_host_facts.skill_read_files == ("SKILL.md", "SKILL.md")
    assert mixed_host_facts.non_gateway_unexpected_commands == (
        third_read.command,
        traversal_read.command,
        tilde_read.command,
    )

    drifted_read = CodexCommandRecord(
        command=read.command,
        exit_code=read.exit_code,
        status=read.status,
        aggregated_output="# detached copy drift\n",
        argv=read.argv,
        has_shell_operators=read.has_shell_operators,
        parse_error=read.parse_error,
        parser_kind=read.parser_kind,
    )
    drifted = classify_task_commands(
        (drifted_read,),
        workspace=workspace,
        skill_source=candidate,
    )
    assert drifted.skill_read is False
    assert drifted.allowed_read_commands == ()
    assert drifted.non_gateway_unexpected_commands == (drifted_read.command,)


def test_task_classifier_accepts_only_exact_detached_posix_install_or_candidate(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "waapi-skills" / "skills" / "waapi-skill"
    candidate_runner = candidate / "scripts" / "run.py"
    candidate_runner.parent.mkdir(parents=True)
    candidate_runner.write_text("# candidate runner\n", encoding="utf-8")
    workspace = tmp_path / "agent-workspace"
    install_runner = workspace_skill_install_path(workspace) / "scripts" / "run.py"
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "capabilities",
        "ok": True,
    }
    installed = completed_record(
        f"python {shlex.quote(str(install_runner))} gateway.py capabilities",
        payload,
    )
    canonical = completed_record(
        f"python {shlex.quote(str(candidate_runner))} gateway.py capabilities",
        payload,
    )
    typo = completed_record(
        "python "
        + shlex.quote(
            str(
                tmp_path
                / "waapi-skill"
                / "skills"
                / "waapi-skill"
                / "scripts"
                / "run.py"
            )
        )
        + " gateway.py capabilities",
        payload,
    )

    facts = classify_task_commands(
        (installed, canonical, typo),
        workspace=workspace,
        skill_source=candidate,
        expected_gateway_subcommands=("capabilities",),
    )

    assert facts.gateway_commands == (installed.command, canonical.command)
    assert facts.non_gateway_unexpected_commands == (typo.command,)


def test_windows_powershell_recording_preserves_literal_metacharacters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    command = windows_powershell_recording(
        r"python 'C:\Skill path\run.py' gateway.py query-object --name 'A&B;$env:X|*.wav'"
    )

    argv, has_operators, parse_error = parse_command_argv(
        command,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert argv == (
        "python",
        r"C:\Skill path\run.py",
        "gateway.py",
        "query-object",
        "--name",
        "A&B;$env:X|*.wav",
    )
    assert has_operators is False
    assert parse_error == ""


@pytest.mark.parametrize(
    "subcommand",
    (
        "legacy-operation-schema",
        "legacy-preview",
        "draft-start",
        "draft-inspect",
        "draft-apply",
        "draft-check",
        "draft-cancel",
        "preview-from-draft",
    ),
)
def test_command_classifier_recognizes_versioned_operation_input_routes(
    tmp_path: Path,
    subcommand: str,
) -> None:
    skill = tmp_path / "skill"
    runner = skill / "scripts" / "run.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# packaged runner\n", encoding="utf-8")
    payload = json.dumps(
        {
            "contract": "waapi-skill.gateway-result/v1",
            "ok": True,
            "command": subcommand,
        }
    )
    record = CodexCommandRecord(
        command=shlex.join(
            ("python", str(runner), "gateway.py", subcommand)
        ),
        exit_code=0,
        status="completed",
        aggregated_output=payload,
        argv=("python", str(runner), "gateway.py", subcommand),
        has_shell_operators=False,
        parse_error="",
        parser_kind="posix-native",
    )

    facts = classify_commands(
        (record,),
        skill_source=skill,
        expected_gateway_subcommands=(subcommand,),
    )

    assert facts.gateway_commands == (record.command,)
    assert facts.gateway_attempt_commands == (record.command,)
    assert facts.gateway_subcommands == (subcommand,)
    assert facts.unexpected_commands == ()


@pytest.mark.parametrize("subcommand", ("request-schema", "query-schema"))
def test_command_classifier_requires_exact_typed_schema_envelope(
    tmp_path: Path,
    subcommand: str,
) -> None:
    skill = tmp_path / "skill"
    runner = skill / "scripts" / "run.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# packaged runner\n", encoding="utf-8")
    argv = ("python", str(runner), "gateway.py", subcommand)

    def record(contract: str) -> CodexCommandRecord:
        return CodexCommandRecord(
            command=shlex.join(argv),
            exit_code=0,
            status="completed",
            aggregated_output=json.dumps(
                {
                    "contract": contract,
                    "ok": True,
                    "command": subcommand,
                }
            ),
            argv=argv,
            has_shell_operators=False,
            parse_error="",
            parser_kind="posix-native",
        )

    accepted = classify_commands(
        (record(TYPED_REQUEST_SCHEMA_CONTRACT),),
        skill_source=skill,
        expected_gateway_subcommands=(subcommand,),
    )
    rejected = classify_commands(
        (record("waapi-skill.gateway-result/v1"),),
        skill_source=skill,
        expected_gateway_subcommands=(subcommand,),
    )

    assert accepted.gateway_subcommands == (subcommand,)
    assert accepted.unexpected_commands == ()
    assert rejected.gateway_commands == ()
    assert rejected.gateway_attempt_commands == (shlex.join(argv),)
    assert rejected.unexpected_commands == (shlex.join(argv),)


def test_command_classifier_accepts_exact_topic_schema_envelope(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "skill"
    runner = skill / "scripts" / "run.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# packaged runner\n", encoding="utf-8")
    argv = (
        "python",
        str(runner),
        "gateway.py",
        "topic-schema",
        "ak.wwise.core.soundbank.generated",
    )
    record = CodexCommandRecord(
        command=shlex.join(argv),
        exit_code=0,
        status="completed",
        aggregated_output=json.dumps(
            {
                "contract": "waapi-skill.typed-topic-input/v1",
                "ok": True,
                "command": "topic-schema",
            }
        ),
        argv=argv,
        has_shell_operators=False,
        parse_error="",
        parser_kind="posix-native",
    )

    facts = classify_commands(
        (record,),
        skill_source=skill,
        expected_gateway_subcommands=("topic-schema",),
    )

    assert facts.gateway_commands == (record.command,)
    assert facts.gateway_attempt_commands == (record.command,)
    assert facts.gateway_subcommands == ("topic-schema",)
    assert facts.unexpected_commands == ()


def test_command_classifier_accepts_packaged_query_schema_result() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    skill = repo_root / "skills" / "waapi-skill"
    runner = skill / "scripts" / "run.py"
    argv = (
        sys.executable,
        str(runner),
        "gateway.py",
        "--version",
        "2021.1",
        "query-schema",
    )
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    record = CodexCommandRecord(
        command=shlex.join(argv),
        exit_code=completed.returncode,
        status="completed",
        aggregated_output=completed.stdout,
        argv=argv,
        has_shell_operators=False,
        parse_error="",
        parser_kind="posix-native",
    )

    facts = classify_commands(
        (record,),
        skill_source=skill,
        expected_gateway_subcommands=("query-schema",),
        expected_wwise_version="2021.1",
    )

    assert facts.gateway_subcommands == ("query-schema",)
    assert facts.unexpected_commands == ()


def test_windows_powershell_recording_requires_quoted_at_prefixed_argv_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    quoted = windows_powershell_recording(
        r"python 'C:\Skill path\run.py' gateway.py query-object --return-field '@Volume' --return-field notes"
    )

    assert parse_command_argv(
        quoted,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    ) == (
        (
            "python",
            r"C:\Skill path\run.py",
            "gateway.py",
            "query-object",
            "--return-field",
            "@Volume",
            "--return-field",
            "notes",
        ),
        False,
        "",
    )

    bare = windows_powershell_recording(
        r"python 'C:\Skill path\run.py' gateway.py query-object --return-field @Volume --return-field notes"
    )
    argv, has_operators, parse_error = parse_command_argv(
        bare,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert argv == ()
    assert has_operators is True
    assert parse_error == (
        "PowerShell command contains composition, expansion, or interpolation"
    )


def test_windows_codex_0146_shlex_presentation_recovers_large_audio_import_json() -> None:
    """Decode Codex's POSIX display codec before the literal PowerShell frame."""

    runner = r"C:\Git_Repos\waapi-skills\skills\waapi-skill\scripts\run.py"
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": "<Sound>Rifle_Thunder_Near",
                    "audio_file": r"C:\Audio fixtures\Rifle\Thunder Near.wav",
                    "import_language": "SFX",
                    "properties": [
                        {"name": "Volume", "value": -2.0},
                        {"name": "IsLoopingEnabled", "value": True},
                        {"name": "LoopStart", "value": 0.05},
                        {"name": "LoopEnd", "value": 1.0},
                        {
                            "name": "Notes",
                            "value": (
                                "Rifle near-layer reimport transport regression. "
                                * 48
                            ),
                        },
                    ],
                }
            ],
            "import_operation": "replaceExisting",
        },
    }
    request_json = json.dumps(
        request,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert len(request_json.encode("utf-8")) > 2048

    def powershell_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    script = " ".join(
        (
            "python",
            powershell_literal(runner),
            "gateway.py",
            "preview",
            "--apply",
            "--request-json",
            powershell_literal(request_json),
        )
    )

    # Codex CLI 0.146 uses Rust shlex::try_join for the client-facing command.
    # For these two backslash-bearing tokens Rust shlex selects double quotes
    # and escapes every backslash and double quote.  Keep this as a golden,
    # independent presentation fixture rather than production encoder logic.
    def rust_shlex_double_quoted(value: str) -> str:
        assert not any(character in value for character in "$`!^")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    command = " ".join(
        (
            rust_shlex_double_quoted(_WINDOWS_POWERSHELL_CORE),
            "-NoProfile",
            "-Command",
            rust_shlex_double_quoted(script),
        )
    )

    argv, has_operators, parse_error, parser_kind = (
        codex_harness_module._parse_command_argv(
            command,
            platform_name="nt",
            windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
        )
    )

    assert argv == (
        "python",
        runner,
        "gateway.py",
        "preview",
        "--apply",
        "--request-json",
        request_json,
    )
    assert json.loads(argv[-1]) == request
    assert len(argv[-1].encode("utf-8")) == len(request_json.encode("utf-8"))
    assert has_operators is False
    assert parse_error == ""
    assert parser_kind == "windows-pwsh-command"


def test_windows_completed_event_batch_binds_one_pre_attested_pwsh_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    first = windows_powershell_recording("python 'one.py'")
    second = windows_powershell_recording(
        "python 'two.py'",
        executable=r"C:\Other\PowerShell\7\pwsh.exe",
    )
    events = tuple(
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": command,
                "exit_code": 0,
                "status": "completed",
                "aggregated_output": "{}",
            },
        }
        for command in (first, second)
    )
    records = completed_command_records(
        events,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert records[0].argv == ("python", "one.py")
    assert records[0].parser_kind == "windows-pwsh-command"
    assert records[1].argv == ()
    assert "not the attested host" in records[1].parse_error


def test_windows_attacker_event_cannot_trigger_powershell_host_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    probes: list[object] = []
    monkeypatch.setattr(
        codex_harness_module,
        "probe_windows_powershell_core",
        lambda *args, **kwargs: probes.append((args, kwargs)),
    )
    command = windows_powershell_recording(
        "python 'attacker.py'",
        executable=r"C:\Attacker Controlled\pwsh.exe",
    )
    events = (
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": command,
                "exit_code": 0,
                "status": "completed",
                "aggregated_output": "{}",
            },
        },
    )

    record = completed_command_records(events, platform_name="nt")[0]

    assert probes == []
    assert record.argv == ()
    assert record.has_shell_operators is True
    assert record.parse_error == "pre-attested PowerShell Core host is required"


def test_windows_powershell_recording_preserves_canonical_encoded_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    expected = (
        "python",
        r"C:\Skill path\scripts\run.py",
        "gateway.py",
        "transaction-show",
        "tx1-example",
    )
    encoded = encode_windows_powershell_argv(expected)

    direct_argv, direct_has_operators, direct_error = parse_command_argv(
        encoded,
        platform_name="nt",
    )
    assert direct_argv == ()
    assert direct_has_operators is True
    assert "Windows PowerShell 5.1" in direct_error
    wrapped = windows_powershell_recording(encoded)
    assert parse_command_argv(
        wrapped,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    ) == (expected, False, "")
    assert codex_harness_module._parse_command_argv(
        wrapped,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )[3] == "windows-powershell-encoded"


def test_windows_powershell_recording_recovers_generated_model_command_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    expected = (
        "python",
        r"C:\Skill path\scripts\run.py",
        "gateway.py",
        "transaction-show",
        "tx1-quote'and-$env:TEMP&pipe|你好",
    )
    model_command = encode_windows_model_argv(expected)
    recorded_command = windows_powershell_recording(model_command)

    argv, has_operators, parse_error, parser_kind = (
        codex_harness_module._parse_command_argv(
            recorded_command,
            platform_name="nt",
            windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
        )
    )

    assert argv == expected
    assert has_operators is False
    assert parse_error == ""
    assert parser_kind == "windows-pwsh-command"


@pytest.mark.parametrize("quote", tuple(chr(value) for value in range(0x2018, 0x2020)))
@pytest.mark.parametrize("position", ("bare", "literal"))
def test_windows_powershell_recording_rejects_every_smart_quote(
    quote: str,
    position: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    script = (
        f"python run{quote}.py"
        if position == "bare"
        else f"python 'run{quote}.py'"
    )

    argv, has_operators, parse_error = parse_command_argv(
        windows_powershell_recording(script),
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert argv == ()
    assert has_operators is True
    assert parse_error == "PowerShell smart quotes are not permitted"


def test_windows_wrapped_encoded_get_content_cannot_claim_relative_skill_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    skill = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    skill.mkdir(parents=True)
    content = "# skill\n"
    (skill / "SKILL.md").write_text(content, encoding="utf-8")
    encoded = encode_windows_powershell_argv(
        (
            "Get-Content",
            "-Raw",
            "-Encoding",
            "UTF8",
            r".agents\skills\waapi-skill\SKILL.md",
        )
    )
    record = completed_windows_record(
        windows_powershell_recording(encoded),
        content,
    )

    facts = classify_commands((record,), skill_source=skill)

    assert record.parser_kind == "windows-powershell-encoded"
    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.unexpected_commands == (record.command,)


@pytest.mark.parametrize(
    "script",
    (
        "python 'C:\\skill\\run.py' gateway.py capabilities; whoami",
        "python 'C:\\skill\\run.py' gateway.py capabilities | Out-Null",
        "python 'C:\\skill\\run.py' gateway.py capabilities > out.txt",
        "$env:MODE='unsafe'",
        "python 'C:\\skill\\run.py' gateway.py capabilities $(Get-Date)",
        "python 'C:\\skill\\run.py' gateway.py capabilities `whoami`",
        "python 'C:\\skill\\run.py' gateway.py capabilities\nwhoami",
        'python "C:\\skill\\run.py" gateway.py capabilities',
    ),
)
def test_windows_powershell_recording_rejects_operators_and_expansion(
    script: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )

    argv, has_operators, parse_error = parse_command_argv(
        windows_powershell_recording(script),
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert argv == ()
    assert has_operators is True
    assert parse_error


@pytest.mark.parametrize(
    "command",
    (
        windows_powershell_recording(
            "Get-Content -Raw -Encoding UTF8 '.agents\\skills\\waapi-skill\\SKILL.md'",
            executable=r"C:\evil\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        ),
        windows_powershell_recording(
            "Get-Content -Raw -Encoding UTF8 '.agents\\skills\\waapi-skill\\SKILL.md'",
            executable=r"D:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe",
        ),
        windows_powershell_recording(
            "Get-Content -Raw -Encoding UTF8 '.agents\\skills\\waapi-skill\\SKILL.md'",
            executable=(
                r"C:\CustomWindows\System32\WindowsPowerShell\v1.0\powershell.exe"
            ),
        ),
        (
            r'"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" '
            '-NoProfile -Command '
            '"Get-Content -Raw -Encoding UTF8 '
            '\'.agents\\skills\\waapi-skill\\SKILL.md\'"'
        ),
        (
            r'"C:\Other\PowerShell\7\pwsh.exe" -NoProfile -Command '
            r'"Get-Content -Raw -Encoding UTF8 '
            r'\'.agents\skills\waapi-skill\SKILL.md\'"'
        ),
        (
            r'"C:\Program Files\PowerShell\7\pwsh.exe" -Command '
            r'"Get-Content -Raw -Encoding UTF8 '
            r'\'.agents\skills\waapi-skill\SKILL.md\'"'
        ),
        (
            r'"C:\Program Files\PowerShell\7\pwsh.exe" -NoLogo -NoProfile -Command '
            r'"Get-Content -Raw -Encoding UTF8 '
            r'\'.agents\skills\waapi-skill\SKILL.md\'"'
        ),
        (
            r'"C:\Program Files\PowerShell\7\pwsh.exe" -Login -NoProfile -Command '
            r'"Get-Content -Raw -Encoding UTF8 '
            r'\'.agents\skills\waapi-skill\SKILL.md\'"'
        ),
    ),
)
def test_windows_powershell_recording_rejects_wrong_outer_wrapper(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )

    argv, has_operators, parse_error = parse_command_argv(
        command,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    )

    assert argv == ()
    assert has_operators is True
    assert parse_error


def test_posix_shell_wrapper_accepts_only_exact_executable_option_and_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    script = "python '/tmp/Skill path/run.py' gateway.py status"
    expected = (
        "python",
        "/tmp/Skill path/run.py",
        "gateway.py",
        "status",
    )
    valid_posix = f'/bin/bash -lc "{script}"'
    valid_windows = f'bash.exe -lc "{script}"'

    assert parse_command_argv(valid_posix) == (expected, False, "")
    assert parse_command_argv(
        valid_windows,
        platform_name="nt",
        windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
    ) == (expected, False, "")

    invalid_posix = (
        f'/bin/bash --rcfile /tmp/evil -lc "{script}"',
        f'/bin/bash --init-file /tmp/evil -c "{script}"',
        f'/bin/bash -l -c "{script}"',
        f'/bin/bash -lc "{script}" unexpected',
    )
    invalid_windows = (
        f'bash.exe --rcfile C:\\evil -lc "{script}"',
        f'bash.exe --init-file C:\\evil -c "{script}"',
        f'bash.exe -l -c "{script}"',
        f'bash.exe -lc "{script}" unexpected',
    )
    for command in invalid_posix:
        argv, has_operators, parse_error = parse_command_argv(command)
        assert argv == ()
        assert has_operators is True
        assert parse_error
    for command in invalid_windows:
        argv, has_operators, parse_error = parse_command_argv(
            command,
            platform_name="nt",
            windows_powershell_core_host=_WINDOWS_POWERSHELL_CORE_HOST,
        )
        assert argv == ()
        assert has_operators is True
        assert parse_error


@pytest.mark.parametrize(
    ("script", "output"),
    (
        (
            r"Get-Content -Raw -Encoding UTF8 '.agents/skills/waapi-skill/SKILL.md'",
            "# skill\n",
        ),
        (
            r"Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\..\waapi-skill\SKILL.md'",
            "# skill\n",
        ),
        (
            r"Get-Content -Encoding UTF8 '.agents\skills\waapi-skill\SKILL.md'",
            "# skill\n",
        ),
        (
            r"Get-Content -Raw '.agents\skills\waapi-skill\SKILL.md'",
            "# skill\n",
        ),
        (
            r"Get-Content -Raw -Encoding Unicode '.agents\skills\waapi-skill\SKILL.md'",
            "# skill\n",
        ),
        (
            r"Get-Content -Encoding UTF8 -Raw '.agents\skills\waapi-skill\SKILL.md'",
            "# skill\n",
        ),
        (
            r"Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\SKILL.md'",
            "# partial",
        ),
    ),
)
def test_windows_get_content_rejects_noncanonical_or_partial_skill_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    output: str,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    skill = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    record = completed_windows_record(windows_powershell_recording(script), output)

    facts = classify_commands((record,), skill_source=skill)

    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.unexpected_commands == (record.command,)


@pytest.mark.parametrize(
    ("output", "accepted"),
    (
        ("# skill\r\n声音\r\n", True),
        ("# skill\n声音\n", True),
        ("# skill\r\n声音\r\n\r\n", True),
        ("# skill\r\n声音\r\n\r\n\r\n", False),
        ("# skill\r\n??\r\n\r\n", False),
    ),
)
def test_windows_get_content_utf8_newline_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: str,
    accepted: bool,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    skill = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes("# skill\r\n声音\r\n".encode("utf-8"))
    command = windows_powershell_recording(
        r"Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\SKILL.md'"
    )
    record = completed_windows_record(command, output)

    facts = classify_commands((record,), skill_source=skill)

    assert facts.skill_read is accepted
    assert facts.allowed_read_commands == ((command,) if accepted else ())
    assert facts.unexpected_commands == (() if accepted else (command,))


def test_windows_failed_exact_skill_read_can_recover_once_before_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    skill = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    skill.mkdir(parents=True)
    content = "# skill\r\n声音\r\n"
    (skill / "SKILL.md").write_bytes(content.encode("utf-8"))
    command = windows_powershell_recording(
        r"Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\SKILL.md'"
    )
    successful = completed_windows_record(command, content)
    failed = CodexCommandRecord(
        command=successful.command,
        exit_code=-1,
        status="failed",
        aggregated_output=(
            "execution error: Io(Custom { kind: Other, error: \"windows sandbox: "
            "CreateProcessAsUserW failed: 267 (invalid directory)\" })"
        ),
        argv=successful.argv,
        has_shell_operators=False,
        parser_kind=successful.parser_kind,
    )

    facts = classify_commands((failed, successful), skill_source=skill)

    assert facts.skill_read is True
    assert facts.allowed_read_commands == (command,)
    assert facts.unexpected_commands == ()
    assert recoverable_preprocess_attempt_indexes(facts.command_records) == (0,)


@pytest.mark.parametrize(
    "parser_kind",
    ("", "posix-native", "windows-native", "windows-powershell-encoded"),
)
def test_relative_get_content_requires_windows_wrapper_parser_provenance(
    tmp_path: Path,
    parser_kind: str,
) -> None:
    skill = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    skill.mkdir(parents=True)
    content = "# skill\n"
    (skill / "SKILL.md").write_text(content, encoding="utf-8")
    command = (
        r"Get-Content -Raw -Encoding UTF8 "
        r"'.agents\skills\waapi-skill\SKILL.md'"
    )
    record = CodexCommandRecord(
        command=command,
        exit_code=0,
        status="completed",
        aggregated_output=content,
        argv=(
            "Get-Content",
            "-Raw",
            "-Encoding",
            "UTF8",
            r".agents\skills\waapi-skill\SKILL.md",
        ),
        has_shell_operators=False,
        parser_kind=parser_kind,
    )

    facts = classify_commands((record,), skill_source=skill)

    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.unexpected_commands == (command,)


@pytest.mark.parametrize("relative", (False, True))
def test_posix_get_content_cannot_claim_absolute_or_relative_skill_read(
    tmp_path: Path,
    relative: bool,
) -> None:
    skill = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    skill.mkdir(parents=True)
    content = "# skill\n"
    skill_md = skill / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    path_text = (
        r".agents\skills\waapi-skill\SKILL.md"
        if relative
        else str(skill_md)
    )
    command = f"Get-Content -Raw -Encoding UTF8 '{path_text}'"
    record = CodexCommandRecord(
        command=command,
        exit_code=0,
        status="completed",
        aggregated_output=content,
        argv=("Get-Content", "-Raw", "-Encoding", "UTF8", path_text),
        has_shell_operators=False,
        parser_kind="posix-native",
    )

    facts = classify_commands((record,), skill_source=skill)

    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.unexpected_commands == (command,)


@pytest.mark.parametrize(
    "script",
    (
        r"cat '.agents\skills\waapi-skill\SKILL.md'",
        r"sed -n '1,$p' '.agents\skills\waapi-skill\SKILL.md'",
    ),
    ids=("cat", "sed"),
)
def test_windows_powershell_rejects_posix_skill_readers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: str,
) -> None:
    monkeypatch.setattr(
        codex_harness_module,
        "split_native_command_line",
        portable_windows_outer_split,
    )
    skill = tmp_path / "agent-workspace" / ".agents" / "skills" / "waapi-skill"
    skill.mkdir(parents=True)
    content = "# skill\n"
    (skill / "SKILL.md").write_text(content, encoding="utf-8")
    command = windows_powershell_recording(script)
    record = completed_windows_record(command, content)

    facts = classify_commands((record,), skill_source=skill)

    assert record.parser_kind == "windows-pwsh-command"
    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.unexpected_commands == (command,)


@pytest.mark.skipif(os.name != "nt", reason="native Windows command-line parser proof")
def test_native_windows_powershell_core_probe_uses_exact_profile_free_argv(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "pwsh.exe"
    candidate.write_bytes(b"synthetic pwsh for injected runner")
    observed: dict[str, object] = {}

    def fake_runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="Core|7.6.4|Windows",
            stderr="",
        )

    host = probe_windows_powershell_core(candidate, runner=fake_runner)

    assert observed["argv"][:5] == [
        str(candidate.resolve(strict=True)),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
    ]
    assert observed["shell"] is False
    assert host.executable == str(candidate.resolve(strict=True))
    assert host.version == "7.6.4"
    assert host.native_argument_passing == "Windows"


@pytest.mark.skipif(os.name != "nt", reason="native Windows command-line parser proof")
def test_native_windows_powershell_core_get_content_has_parser_provenance(
    tmp_path: Path,
) -> None:
    host = discover_windows_powershell_core(platform_name="nt")
    skill = tmp_path / "agent workspace" / ".agents" / "skills" / "waapi-skill"
    skill.mkdir(parents=True)
    content = "# skill\n"
    (skill / "SKILL.md").write_text(content, encoding="utf-8")
    command = windows_powershell_recording(
        r"Get-Content -Raw -Encoding UTF8 '.agents\skills\waapi-skill\SKILL.md'",
        executable=host.executable,
    )
    events = (
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": command,
                "exit_code": 0,
                "status": "completed",
                "aggregated_output": content,
            },
        },
    )

    record = completed_command_records(
        events,
        windows_powershell_core_host=host,
    )[0]
    facts = classify_commands((record,), skill_source=skill)

    assert record.parser_kind == "windows-pwsh-command"
    assert record.argv == (
        "Get-Content",
        "-Raw",
        "-Encoding",
        "UTF8",
        r".agents\skills\waapi-skill\SKILL.md",
    )
    assert facts.skill_read is True
    assert facts.skill_read_files == ("SKILL.md",)


@pytest.mark.skipif(os.name != "nt", reason="native Windows command-line parser proof")
def test_native_windows_powershell_core_unwraps_gateway_path_with_spaces(
    tmp_path: Path,
) -> None:
    host = discover_windows_powershell_core(platform_name="nt")
    runner = tmp_path / "Agent Workspace" / ".agents" / "skills" / "waapi-skill" / "scripts" / "run.py"
    command = windows_powershell_recording(
        f"python '{runner}' gateway.py capabilities --summary-only",
        executable=host.executable,
    )

    argv, has_operators, parse_error = parse_command_argv(
        command,
        windows_powershell_core_host=host,
    )

    assert argv == (
        "python",
        str(runner),
        "gateway.py",
        "capabilities",
        "--summary-only",
    )
    assert has_operators is False
    assert parse_error == ""


@pytest.mark.skipif(os.name != "nt", reason="native Windows command-line parser proof")
def test_native_windows_powershell_core_rejects_embedded_double_quote(
    tmp_path: Path,
) -> None:
    host = discover_windows_powershell_core(platform_name="nt")
    runner = tmp_path / "Agent Workspace" / "run.py"
    command = windows_powershell_recording(
        f'python "{runner}" gateway.py capabilities',
        executable=host.executable,
    )

    argv, has_operators, parse_error = parse_command_argv(
        command,
        windows_powershell_core_host=host,
    )

    assert argv == ()
    assert has_operators is True
    assert "interpolating strings" in parse_error


@pytest.mark.skipif(os.name != "nt", reason="native Windows command-line parser proof")
def test_native_windows_powershell_core_wraps_encoded_continuation(
    tmp_path: Path,
) -> None:
    host = discover_windows_powershell_core(platform_name="nt")
    expected = (
        "python",
        str(tmp_path / "Agent Workspace" / "run.py"),
        "gateway.py",
        "transaction-show",
        "tx1-example",
    )
    command = windows_powershell_recording(
        encode_windows_powershell_argv(expected),
        executable=host.executable,
    )

    assert parse_command_argv(
        command,
        windows_powershell_core_host=host,
    ) == (expected, False, "")


@pytest.mark.skipif(os.name != "nt", reason="native Windows pwsh/Broker argv proof")
def test_native_windows_generated_model_command_reconciles_exact_broker_argv(
    tmp_path: Path,
) -> None:
    host = discover_windows_powershell_core(platform_name="nt")
    skill = tmp_path / "WAAPI Skill"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text(
        "import json, sys\n"
        "print(json.dumps({\n"
        "    'contract': 'waapi-skill.gateway-result/v1',\n"
        "    'command': sys.argv[2],\n"
        "    'ok': True,\n"
        "}, ensure_ascii=False, separators=(',', ':')))\n",
        encoding="utf-8",
        newline="\n",
    )
    predicate = {
        "field": "name",
        "operator": "=",
        "value": "Rifle's $env:TEMP & pipe|redirect<out> 你好",
    }
    predicate_json = json.dumps(predicate, ensure_ascii=False, separators=(",", ":"))
    root_path = r"\Actor-Mixer Hierarchy\Default Work Unit"
    expected_step = ExpectedGatewayStep(
        "query",
        "query-object",
        (
            "--path",
            root_path,
            "--where-json",
            SemanticJsonArgument(predicate),
            "--return-field",
            "id",
            "--return-field",
            "@Volume",
        ),
    )

    with CodexGatewayBroker(
        skill_source=skill,
        expected_steps=(expected_step,),
        transport="tcp",
    ) as broker:
        expected = (
            "python",
            str(broker.invocation_runner_path),
            "gateway.py",
            "query-object",
            "--path",
            root_path,
            "--where-json",
            predicate_json,
            "--return-field",
            "id",
            "--return-field",
            "@Volume",
        )
        model_command = encode_windows_model_argv(expected)
        completed = run_windows_powershell_model_command(
            model_command,
            powershell_executable=Path(host.executable),
            cwd=tmp_path,
            environment=broker.model_environment(os.environ),
        )

        assert completed.returncode == 0, completed.stderr
        recorded_command = windows_powershell_recording(
            model_command,
            executable=host.executable,
        )
        record = completed_command_records(
            (
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": recorded_command,
                        "exit_code": completed.returncode,
                        "status": "completed",
                        "aggregated_output": completed.stdout,
                    },
                },
            ),
            platform_name="nt",
            windows_powershell_core_host=host,
        )[0]

        assert record.argv == expected
        assert record.has_shell_operators is False
        assert record.parse_error == ""
        assert record.parser_kind == "windows-pwsh-command"
        assert broker.reconcile((record.argv,)).passed is True


@pytest.mark.skipif(os.name != "nt", reason="native Windows pwsh argv transport proof")
def test_native_windows_pwsh_resolves_only_broker_ps1_external_scripts(
    tmp_path: Path,
) -> None:
    host = discover_windows_powershell_core(platform_name="nt")
    scripts = tmp_path / "waapi-skill" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    with CodexGatewayBroker(
        skill_source=scripts.parent,
        expected_steps=(ExpectedGatewayStep("unused", "status"),),
        transport="tcp",
    ) as broker:
        probe_script = (
            "$commands=@(Get-Command -Name python,python3 -CommandType ExternalScript);"
            "[Console]::Out.Write(($commands | Select-Object Name,"
            "@{Name='CommandType';Expression={$_.CommandType.ToString()}},Source | "
            "ConvertTo-Json -Compress))"
        )
        completed = subprocess.run(
            [host.executable, "-NoProfile", "-Command", probe_script],
            env=broker.model_environment(os.environ),
            cwd=tmp_path,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=30,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert completed.stderr == ""
        rows = json.loads(completed.stdout)
        assert [row["Name"].casefold() for row in rows] == ["python.ps1", "python3.ps1"]
        assert {row["CommandType"] for row in rows} == {"ExternalScript"}
        assert [PureWindowsPath(row["Source"]) for row in rows] == [
            PureWindowsPath(broker.shim_directory / "python.ps1"),
            PureWindowsPath(broker.shim_directory / "python3.ps1"),
        ]
        assert not (broker.shim_directory / "python.cmd").exists()
        assert not (broker.shim_directory / "python3.cmd").exists()


@pytest.mark.skipif(os.name != "nt", reason="native Windows pwsh argv transport proof")
def test_native_windows_powershell_core_preserves_2299_byte_hostile_json(
    tmp_path: Path,
) -> None:
    host = discover_windows_powershell_core(platform_name="nt")
    capture = tmp_path / "capture argv.py"
    captured = tmp_path / "captured argv.json"
    capture.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_bytes(sys.argv[2].encode('utf-8'))\n",
        encoding="utf-8",
        newline="\n",
    )
    payload = {
        "contract": "waapi-skill.operation-request/v1",
        "operation": "audio.import",
        "arguments": {
            "object_path": r"\\Actor-Mixer Hierarchy\\Default Work Unit\\声音 & 'Storm'",
            "audio_file": r"C:\Media path\%TEMP%\plain&pipe|redirect<out>caret^bang!percent%.wav",
            "properties": [
                {"name": "Notes", "value": 'quoted "value" and 中文'},
                {"name": "IsLoopingEnabled", "value": True},
            ],
        },
        "padding": "",
    }
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    payload["padding"] = "x" * (2299 - len(compact.encode("utf-8")))
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert len(compact.encode("utf-8")) == 2299

    def ps_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    script = "& " + " ".join(
        ps_literal(value)
        for value in (sys.executable, str(capture), str(captured), compact)
    )
    completed = subprocess.run(
        [host.executable, "-NoProfile", "-Command", script],
        cwd=tmp_path,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert captured.read_bytes() == compact.encode("utf-8")
    assert json.loads(captured.read_text(encoding="utf-8")) == payload


def test_pre_action_usage_limit_is_codex_infrastructure_failure() -> None:
    message = (
        "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage "
        "to purchase more credits."
    )
    events = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "error", "message": message},
        {"type": "turn.failed", "error": {"message": message}},
    ]

    failure = classify_codex_infrastructure_failure(events, stderr="Reading additional input from stdin...")

    assert failure is not None
    assert failure.category == "quota_or_rate_limit"
    assert failure.message == message
    assert failure.turn_failed is True
    assert failure.agent_item_event_count == 0


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("Authentication failed: token expired", "authentication"),
        ("Service unavailable: upstream error", "service_unavailable"),
    ],
)
def test_explicit_pre_action_cli_errors_are_infrastructure_without_turn_failed(
    message: str,
    category: str,
) -> None:
    failure = classify_codex_infrastructure_failure([{"type": "error", "message": message}])

    assert failure is not None
    assert failure.category == category
    assert failure.turn_failed is False
    assert failure.agent_item_event_count == 0


def test_turn_failure_after_agent_action_remains_a_semantic_skill_failure() -> None:
    message = "You've hit your usage limit after the model already acted."
    events = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "python scripts/run.py gateway.py query-object --path missing",
                "exit_code": 1,
                "status": "failed",
            },
        },
        {"type": "error", "message": message},
        {"type": "turn.failed", "error": {"message": message}},
    ]

    assert classify_codex_infrastructure_failure(events) is None


def test_jsonl_audit_counts_non_json_lines_and_started_only_commands() -> None:
    text = '\n'.join(
        (
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            "not-json",
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.started",
                    "item": {"id": "command-1", "type": "command_execution", "command": "cat /tmp/SKILL.md"},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {}}),
        )
    )

    audit = audit_session_events(
        parse_jsonl_events(text),
        invalid_json_line_count=count_invalid_jsonl_lines(text),
    )

    assert audit.invalid_json_line_count == 1
    assert audit.command_started_count == 1
    assert audit.command_completed_count == 0
    assert audit.incomplete_command_count == 1
    assert audit.passed is False


def test_session_audit_rejects_duplicate_threads_missing_completion_and_collab() -> None:
    events = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "thread.started", "thread_id": "thread-2"},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"id": "collab-1", "type": "collab_tool_call"}},
        {"type": "item.completed", "item": {"id": "collab-1", "type": "collab_tool_call"}},
        {"type": "item.started", "item": {"id": "patch-1", "type": "file_change"}},
        {"type": "item.completed", "item": {"id": "patch-1", "type": "file_change"}},
    ]

    audit = audit_session_events(events)

    assert audit.thread_started_count == 2
    assert audit.turn_completed_count == 0
    assert audit.collab_call_count == 1
    assert audit.file_change_count == 1
    assert audit.unexpected_item_types == ("collab_tool_call", "file_change")
    assert audit.passed is False


def test_session_audit_accepts_completed_websocket_to_https_fallback() -> None:
    events = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "transport-1",
                "type": "error",
                "message": (
                    "Falling back from WebSockets to HTTPS transport. "
                    "stream disconnected before completion: tls handshake eof"
                ),
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "message-1", "type": "agent_message", "text": "done"},
        },
        {"type": "turn.completed", "usage": {}},
    ]

    audit = audit_session_events(events)

    assert audit.unexpected_item_types == ()
    assert audit.passed is True


def test_session_audit_rejects_other_error_items_after_a_completed_turn() -> None:
    events = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {
                "id": "error-1",
                "type": "error",
                "message": "model output could not be decoded",
            },
        },
        {"type": "turn.completed", "usage": {}},
    ]

    audit = audit_session_events(events)

    assert audit.unexpected_item_types == ("error",)
    assert audit.passed is False


def test_windows_operator_scan_preserves_backslash_paths_and_rejects_composition() -> None:
    command = r'python C:\ProgramData\waapi-skill\scripts\run.py gateway.py status'

    assert not codex_harness_module.shell_script_has_operators(
        command,
        platform_name="nt",
    )
    assert codex_harness_module.shell_script_has_operators(
        command + " & whoami",
        platform_name="nt",
    )


def test_command_classifier_distinguishes_gateway_from_inline_code_and_discovery(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    commands = (
        completed_record(
            recorded_argv_command("sed", "-n", "1,$p", str(skill / "SKILL.md")),
            "skill\n",
        ),
        completed_record(
            recorded_argv_command(
                "python",
                str(skill / "scripts" / "run.py"),
                "gateway.py",
                "buses",
            ),
            {
                "contract": "waapi-skill.gateway-result/v1",
                "command": "buses",
                "ok": True,
                "call": {"api": "ak.wwise.core.object.get", "ok": True, "result": {"return": []}},
            },
        ),
        completed_record(recorded_argv_command("rg", "--files", ".")),
        completed_record(
            recorded_argv_command(
                "python",
                "-u",
                "-c",
                "from waapi import WaapiClient; print(WaapiClient())",
            )
        ),
    )

    facts = classify_commands(commands, skill_source=skill, expected_gateway_subcommands=("buses",))

    assert facts.skill_read is True
    assert facts.gateway_commands == (commands[1].command,)
    assert facts.gateway_subcommands == ("buses",)
    assert facts.gateway_evidence_apis == ("ak.wwise.core.object.get",)
    assert facts.gateway_before_discovery is True
    assert facts.inline_python_commands == (commands[-1].command,)
    assert facts.direct_waapi_client_commands == (commands[-1].command,)
    assert facts.unexpected_commands == (commands[2].command, commands[3].command)


def test_command_classifier_counts_one_identical_gateway_after_preprocess_failure(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "buses",
        "ok": True,
    }
    base = completed_record(gateway_command(skill, "buses"), payload)
    successful = CodexCommandRecord(
        command=base.command,
        exit_code=base.exit_code,
        status=base.status,
        aggregated_output=base.aggregated_output,
        argv=base.argv,
        has_shell_operators=False,
        parser_kind="windows-pwsh-command",
    )
    failed = CodexCommandRecord(
        command=successful.command,
        exit_code=-1,
        status="failed",
        aggregated_output=(
            "execution error: Io(Custom { kind: Other, error: \"windows sandbox: "
            "CreateProcessAsUserW failed: 267 (invalid directory)\" })"
        ),
        argv=successful.argv,
        has_shell_operators=False,
        parser_kind=successful.parser_kind,
    )

    facts = classify_commands(
        (failed, successful),
        skill_source=skill,
        expected_gateway_subcommands=("buses",),
    )

    assert recoverable_preprocess_attempt_indexes(facts.command_records) == (0,)
    assert facts.gateway_attempt_commands == (successful.command,)
    assert facts.gateway_commands == (successful.command,)
    assert facts.unexpected_commands == ()


def test_command_classifier_accepts_only_explicit_exact_gateway_exit_2_error(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "preview",
        "ok": False,
        "status": "error",
        "error_code": "PACKAGED_PREVIEW_UNAVAILABLE",
    }
    record = completed_record(
        gateway_command(skill, "preview --request-json '{}'"),
        payload,
        exit_code=2,
        status="failed",
    )
    expectation = CodexGatewayErrorExpectation(
        command="preview",
        error_code="PACKAGED_PREVIEW_UNAVAILABLE",
    )

    accepted = classify_commands(
        (record,),
        skill_source=skill,
        expected_gateway_subcommands=("preview",),
        expected_gateway_errors=(expectation,),
    )
    default_rejected = classify_commands(
        (record,),
        skill_source=skill,
        expected_gateway_subcommands=("preview",),
    )

    assert accepted.gateway_commands == (record.command,)
    assert accepted.gateway_results == (payload,)
    assert accepted.unexpected_commands == ()
    assert default_rejected.gateway_commands == ()
    assert default_rejected.unexpected_commands == (record.command,)

    invalid_variants = (
        (dict(payload, ok=True), 2, "failed"),
        (dict(payload, command="execute"), 2, "failed"),
        (dict(payload, error_code="WRONG"), 2, "failed"),
        (dict(payload, contract="forged/v1"), 2, "failed"),
        (payload, 3, "failed"),
        (payload, 2, "completed"),
    )
    for invalid_payload, exit_code, status in invalid_variants:
        invalid_record = completed_record(
            record.command,
            invalid_payload,
            exit_code=exit_code,
            status=status,
        )
        facts = classify_commands(
            (invalid_record,),
            skill_source=skill,
            expected_gateway_subcommands=("preview",),
            expected_gateway_errors=(expectation,),
        )
        assert facts.gateway_commands == ()
        assert facts.unexpected_commands == (record.command,)


def test_command_classifier_accepts_offline_gateway_config_commands(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    records = (
        completed_record(
            gateway_command(skill, "config-show"),
            {
                "contract": "waapi-skill.gateway-result/v1",
                "command": "config-show",
                "ok": True,
            },
        ),
        completed_record(
            gateway_command(
                skill,
                "config-set --wwise-version 2022.1 --waapi-host 127.0.0.1 "
                "--waapi-port 8080 --project-modification-policy ask_before_changes",
            ),
            {
                "contract": "waapi-skill.gateway-result/v1",
                "command": "config-set",
                "ok": True,
            },
        ),
    )

    facts = classify_commands(
        records,
        skill_source=skill,
        expected_gateway_subcommands=("config-show", "config-set"),
    )

    assert facts.gateway_commands == tuple(record.command for record in records)
    assert facts.gateway_attempt_commands == tuple(record.command for record in records)
    assert facts.gateway_subcommands == ("config-show", "config-set")
    assert facts.inline_python_commands == ()
    assert facts.unexpected_commands == ()


def test_command_classifier_normalizes_only_the_exact_session_version_assignment(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    payload = {"contract": "waapi-skill.gateway-result/v1", "command": "buses", "ok": True}
    base = gateway_command(skill, "buses")
    accepted = completed_record(f"WWISE_VERSION=2022.1 {base}", payload)

    facts = classify_commands(
        (accepted,),
        skill_source=skill,
        expected_gateway_subcommands=("buses",),
        expected_wwise_version="2022.1",
    )

    assert facts.gateway_commands == (accepted.command,)
    assert facts.gateway_subcommands == ("buses",)
    assert facts.unexpected_commands == ()

    env_accepted = completed_record(f"env WWISE_VERSION=2022.1 {base}", payload)
    env_facts = classify_commands(
        (env_accepted,),
        skill_source=skill,
        expected_gateway_subcommands=("buses",),
        expected_wwise_version="2022.1",
    )
    assert env_facts.gateway_commands == (env_accepted.command,)
    assert env_facts.unexpected_commands == ()

    cli_alias = completed_record(
        gateway_command(skill, "--wwise-version 2022.1 buses"),
        payload,
    )
    cli_alias_facts = classify_commands(
        (cli_alias,),
        skill_source=skill,
        expected_gateway_subcommands=("buses",),
        expected_wwise_version="2022.1",
    )
    assert cli_alias_facts.gateway_commands == (cli_alias.command,)
    assert cli_alias_facts.unexpected_commands == ()

    runner_level = completed_record(
        recorded_argv_command(
            "python",
            str(skill / "scripts" / "run.py"),
            "--version",
            "2022.1",
            "gateway.py",
            "buses",
        ),
        payload,
    )
    runner_level_facts = classify_commands(
        (runner_level,),
        skill_source=skill,
        expected_gateway_subcommands=("buses",),
        expected_wwise_version="2022.1",
    )
    assert runner_level_facts.gateway_commands == (runner_level.command,)
    assert runner_level_facts.gateway_subcommands == ("buses",)
    assert runner_level_facts.unexpected_commands == ()

    rejected_commands = (
        completed_record(f"WWISE_VERSION=2023.1 {base}", payload),
        completed_record(f"PYTHONPATH=/tmp {base}", payload),
        completed_record(f"WWISE_VERSION=2022.1 OTHER=value {base}", payload),
        completed_record(f"env -i WWISE_VERSION=2022.1 {base}", payload),
        completed_record(f"env OTHER=value {base}", payload),
        completed_record(
            recorded_argv_command(
                "python",
                str(skill / "scripts" / "run.py"),
                "--version",
                "2023.1",
                "gateway.py",
                "buses",
            ),
            payload,
        ),
        completed_record(
            recorded_argv_command(
                "python",
                str(skill / "scripts" / "run.py"),
                "--version",
                "2022.1",
                "other.py",
                "buses",
            ),
            payload,
        ),
    )
    rejected = classify_commands(
        rejected_commands,
        skill_source=skill,
        expected_gateway_subcommands=("buses",),
        expected_wwise_version="2022.1",
    )
    assert rejected.gateway_commands == ()
    assert rejected.unexpected_commands == tuple(record.command for record in rejected_commands)


def test_malformed_packaged_runner_is_unexpected_but_not_inline_python(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    runner = skill / "scripts" / "run.py"
    malformed = completed_record(
        recorded_argv_command(
            "python",
            str(runner),
            "--version",
            "2023.1",
            "gateway.py",
            "operation-schema",
            "object.copy",
        ),
        "Gateway broker rejected command",
        exit_code=126,
    )
    wrong_target = completed_record(
        recorded_argv_command("python", str(runner), "arbitrary.py", "status"),
        "Gateway broker rejected command",
        exit_code=126,
    )
    actual_inline = completed_record("python /tmp/temporary_helper.py")

    facts = classify_commands(
        (malformed, wrong_target, actual_inline),
        skill_source=skill,
        expected_gateway_subcommands=("operation-schema",),
        expected_wwise_version="2022.1",
    )

    assert facts.inline_python_commands == (actual_inline.command,)
    assert facts.unexpected_commands == (
        malformed.command,
        wrong_target.command,
        actual_inline.command,
    )


def test_command_classifier_allows_only_exact_initial_skill_bootstrap_read(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    skill_md = skill / "SKILL.md"
    content = "first\nsecond\n"
    skill_md.write_text(content, encoding="utf-8")
    shell_path = shlex.quote(str(skill_md))
    command = f'/bin/bash -lc "wc -l {shell_path} && sed -n \'1,240p\' {shell_path}"'
    output = f"       2 {skill_md}\n{content}"
    argv, has_operators, parse_error, parser_kind = (
        codex_harness_module._parse_command_argv(command)
    )
    record = CodexCommandRecord(
        command=command,
        exit_code=0,
        status="completed",
        aggregated_output=output,
        argv=argv,
        has_shell_operators=has_operators,
        parse_error=parse_error,
        parser_kind=parser_kind,
    )

    facts = classify_commands((record,), skill_source=skill)

    assert facts.skill_read is True
    assert facts.allowed_read_commands == (command,)
    assert facts.skill_read_files == ("SKILL.md",)
    assert facts.write_like_commands == ()
    assert facts.unexpected_commands == ()


@pytest.mark.parametrize(
    "parser_kind",
    (
        "windows-pwsh-command",
        "windows-native",
        "windows-powershell-encoded",
        "",
    ),
)
def test_command_classifier_rejects_posix_bootstrap_read_outside_posix_parser(
    tmp_path: Path,
    parser_kind: str,
) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    skill_md = skill / "SKILL.md"
    content = "first\nsecond\n"
    skill_md.write_text(content, encoding="utf-8")
    command = f"wc -l {skill_md} && sed -n '1,240p' {skill_md}"
    record = CodexCommandRecord(
        command=command,
        exit_code=0,
        status="completed",
        aggregated_output=f"       2 {skill_md}\n{content}",
        argv=(
            "wc",
            "-l",
            str(skill_md),
            "&&",
            "sed",
            "-n",
            "1,240p",
            str(skill_md),
        ),
        has_shell_operators=True,
        parser_kind=parser_kind,
    )

    facts = classify_commands((record,), skill_source=skill)

    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.skill_read_files == ()
    assert facts.unexpected_commands == (command,)


@pytest.mark.parametrize(
    "parser_kind",
    (
        "windows-pwsh-command",
        "windows-native",
        "windows-powershell-encoded",
        "",
    ),
)
@pytest.mark.parametrize(
    "argv",
    (
        ("cat", "{skill}"),
        ("sed", "-n", "1,$p", "{skill}"),
    ),
)
def test_command_classifier_rejects_posix_skill_reader_outside_posix_parser(
    tmp_path: Path,
    parser_kind: str,
    argv: tuple[str, ...],
) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    skill_md = skill / "SKILL.md"
    content = "first\nsecond\n"
    skill_md.write_text(content, encoding="utf-8")
    rendered_argv = tuple(
        str(skill_md) if value == "{skill}" else value for value in argv
    )
    command = recorded_argv_command(*rendered_argv)
    record = CodexCommandRecord(
        command=command,
        exit_code=0,
        status="completed",
        aggregated_output=content,
        argv=rendered_argv,
        has_shell_operators=False,
        parser_kind=parser_kind,
    )

    facts = classify_commands((record,), skill_source=skill)

    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.skill_read_files == ()
    assert facts.unexpected_commands == (command,)


def test_task_classifier_replays_bootstrap_after_install_attestation(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate-skill"
    candidate.mkdir()
    content = "first\nsecond\n"
    (candidate / "SKILL.md").write_text(content, encoding="utf-8")
    workspace = tmp_path / "agent-workspace"
    installed = workspace_skill_install_path(workspace)
    installed.parent.mkdir(parents=True)
    installed.write_text("sealed install attestation\n", encoding="utf-8")
    installed_skill = installed / "SKILL.md"
    shell_path = shlex.quote(str(installed_skill))
    command = (
        f'/bin/bash -lc "wc -l {shell_path} && '
        f"sed -n '1,240p' {shell_path}\""
    )
    output = f"       2 {installed_skill}\n{content}"
    argv, has_operators, parse_error, parser_kind = (
        codex_harness_module._parse_command_argv(command)
    )
    record = CodexCommandRecord(
        command=command,
        exit_code=0,
        status="completed",
        aggregated_output=output,
        argv=argv,
        has_shell_operators=has_operators,
        parse_error=parse_error,
        parser_kind=parser_kind,
    )

    facts = classify_task_commands(
        (record,),
        workspace=workspace,
        skill_source=candidate,
    )

    assert installed.is_file()
    assert facts.skill_read is True
    assert facts.skill_read_files == ("SKILL.md",)
    assert facts.allowed_read_commands == (command,)
    assert facts.unexpected_commands == ()


def test_validated_skill_read_accepts_complete_coverage_reference(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    references = skill / "references"
    references.mkdir(parents=True)
    coverage = references / "waapi-coverage.md"
    content = "# coverage\n"
    coverage.write_text(content, encoding="utf-8")

    assert validated_skill_read(
        str(coverage),
        content,
        skill_source=skill,
    ) == ("references/waapi-coverage.md", content)


def test_posix_task_classifier_accepts_only_exact_task_local_skill_reads(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    workspace = tmp_path / "agent-workspace"
    installed = workspace / ".agents" / "skills" / "waapi-skill"
    for root in (candidate, installed):
        (root / "references").mkdir(parents=True)
        (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        (root / "references" / "waapi-query.md").write_text(
            "# query\n",
            encoding="utf-8",
        )

    commands = (
        completed_record(
            "cat '.agents/skills/waapi-skill/SKILL.md'",
            "# skill\n",
        ),
        completed_record(
            "cat '.agents/skills/waapi-skill/references/waapi-query.md'",
            "# query\n",
        ),
    )

    facts = classify_task_commands(
        commands,
        workspace=workspace,
        skill_source=candidate,
    )

    assert facts.skill_read_files == ("SKILL.md", "references/waapi-query.md")
    assert facts.allowed_read_commands == tuple(row.command for row in commands)
    assert facts.unexpected_commands == ()

    near = completed_record(
        "cat '.agents/skills/waapi-skill/./SKILL.md'",
        "# skill\n",
    )
    near_facts = classify_task_commands(
        (near,),
        workspace=workspace,
        skill_source=candidate,
    )
    assert near_facts.allowed_read_commands == ()
    assert near_facts.unexpected_commands == (near.command,)


def test_task_classifier_accepts_exact_task_local_gateway_runner(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate" / "waapi-skill"
    installed = (
        tmp_path
        / "agent-workspace"
        / ".agents"
        / "skills"
        / "waapi-skill"
    )
    for root in (candidate, installed):
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "run.py").write_text("# runner\n", encoding="utf-8")
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "status",
        "ok": True,
    }
    relative_runner = (
        TASK_LOCAL_RUNNER_WINDOWS if os.name == "nt" else TASK_LOCAL_RUNNER_POSIX
    )
    record = CodexCommandRecord(
        command=f"python {relative_runner} gateway.py status",
        exit_code=0,
        status="completed",
        aggregated_output=json.dumps(payload),
        argv=("python", relative_runner, "gateway.py", "status"),
        has_shell_operators=False,
        parser_kind="windows-pwsh-command" if os.name == "nt" else "posix-native",
    )

    facts = classify_commands(
        (record,),
        skill_source=candidate,
        alternate_gateway_skill_sources=(installed,),
        expected_gateway_subcommands=("status",),
    )

    assert facts.gateway_commands == (record.command,)
    assert facts.gateway_subcommands == ("status",)
    assert facts.unexpected_commands == ()


def test_validated_skill_read_normalizes_only_line_endings(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    skill_md = skill / "SKILL.md"
    skill_md.write_bytes(b"first\nsecond\n")

    assert validated_skill_read(
        str(skill_md),
        "first\r\nsecond\r\n",
        skill_source=skill,
    ) == ("SKILL.md", "first\nsecond\n")
    assert (
        validated_skill_read(
            str(skill_md),
            "first\r\nsecond\r\n\r\n",
            skill_source=skill,
        )
        is None
    )


def test_command_classifier_accepts_codex_full_range_sed_only_for_exact_skill_read(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "waapi-skill"
    references = skill / "references"
    references.mkdir(parents=True)
    skill_md = skill / "SKILL.md"
    content = "first\nsecond\n"
    skill_md.write_text(content, encoding="utf-8")
    reference = references / "waapi-operate.md"
    reference.write_text(content, encoding="utf-8")
    shell_skill_md = shlex.quote(str(skill_md))
    shell_reference = shlex.quote(str(reference))
    command = f'''/bin/bash -lc "sed -n '1,"'$p'"' {shell_skill_md}"'''
    record = completed_record(command, content)

    facts = classify_commands((record,), skill_source=skill)

    assert record.argv == ("sed", "-n", "1,$p", str(skill_md))
    assert facts.skill_read is True
    assert facts.allowed_read_commands == (command,)
    assert facts.skill_read_files == ("SKILL.md",)
    assert facts.write_like_commands == ()
    assert facts.unexpected_commands == ()

    partial = completed_record(command, "first\n")
    reference_command = f"sed -n '1,$p' {shell_reference}"
    reference_read = completed_record(reference_command, content)
    for rejected in (partial, reference_read):
        rejected_facts = classify_commands((rejected,), skill_source=skill)
        assert rejected_facts.allowed_read_commands == ()
        assert rejected_facts.skill_read_files == ()
        assert rejected_facts.unexpected_commands == (rejected.command,)


def test_command_classifier_rejects_other_skill_reads_with_shell_operators(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    skill_md = skill / "SKILL.md"
    content = "first\nsecond\n"
    skill_md.write_text(content, encoding="utf-8")
    shell_path = shlex.quote(str(skill_md))
    commands_and_outputs = (
        (
            f'/bin/bash -lc "wc -l {shell_path} && sed -n \'1,1p\' {shell_path}"',
            f"2 {skill_md}\nfirst\n",
        ),
        (f'/bin/bash -lc "wc -l {shell_path} && cat {shell_path}"', f"2 {skill_md}\n{content}"),
        (f'/bin/bash -lc "cat {shell_path} ; true"', content),
        (f'/bin/bash -lc "cat {shell_path} | sed -n \'1,240p\'"', content),
    )

    for command, output in commands_and_outputs:
        argv, has_operators, parse_error, parser_kind = (
            codex_harness_module._parse_command_argv(command)
        )
        assert has_operators is True
        record = CodexCommandRecord(
            command=command,
            exit_code=0,
            status="completed",
            aggregated_output=output,
            argv=argv,
            has_shell_operators=has_operators,
            parse_error=parse_error,
            parser_kind=parser_kind,
        )

        facts = classify_commands((record,), skill_source=skill)

        assert facts.skill_read is False
        assert facts.allowed_read_commands == ()
        assert facts.skill_read_files == ()
        assert facts.write_like_commands == (command,)
        assert facts.unexpected_commands == (command,)


def test_command_classifier_rejects_gateway_spoofs_shell_operators_and_failed_or_wrong_contract(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    valid_payload = {"contract": "waapi-skill.gateway-result/v1", "command": "buses", "ok": True}
    absolute = gateway_command(skill, "buses")
    records = (
        completed_record("echo python scripts/run.py gateway.py buses", valid_payload),
        completed_record(f"{absolute} | tee /tmp/fake.json", valid_payload),
        completed_record(absolute, valid_payload, exit_code=2),
        completed_record(
            absolute,
            {"contract": "not-the-gateway-contract", "command": "buses", "ok": True},
        ),
        completed_record(
            absolute,
            {"contract": "waapi-skill.gateway-result/v1", "command": "buses", "ok": False},
        ),
        completed_record(
            gateway_command(skill, "--version status buses"),
            {"contract": "waapi-skill.gateway-result/v1", "command": "status", "ok": True},
        ),
        completed_record(absolute, valid_payload),
    )

    facts = classify_commands(records, skill_source=skill, expected_gateway_subcommands=("buses",))

    assert facts.gateway_commands == (records[-1].command,)
    assert len(facts.gateway_attempt_commands) == 5
    assert records[0].command in facts.write_like_commands
    assert records[1].command in facts.write_like_commands
    assert facts.inline_python_commands == ()
    assert len(facts.unexpected_commands) == 6
    assert facts.non_gateway_unexpected_commands == (
        records[0].command,
        records[1].command,
    )


def test_command_classifier_does_not_count_unproven_relative_skill_read(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")

    facts = classify_commands((completed_record("cat SKILL.md"),), skill_source=skill)

    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.unexpected_commands == ("cat SKILL.md",)


def test_command_classifier_accepts_windows_copy_and_candidate_gateway_paths(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "workspace-copy"
    candidate = tmp_path / "candidate"
    records = (
        completed_record(
            gateway_command(copied, "preview"),
            {
                "contract": "waapi-skill.gateway-result/v1",
                "command": "preview",
                "ok": True,
            },
        ),
        completed_record(
            gateway_command(candidate, "execute tx-1"),
            {
                "contract": "waapi-skill.gateway-result/v1",
                "command": "execute",
                "ok": True,
            },
        ),
    )

    facts = classify_commands(
        records,
        skill_source=copied,
        alternate_gateway_skill_sources=(candidate,),
        expected_gateway_subcommands=("preview", "execute"),
    )

    assert facts.gateway_commands == tuple(record.command for record in records)
    assert facts.gateway_attempt_commands == tuple(record.command for record in records)
    assert facts.unexpected_commands == ()


def test_command_classifier_detects_direct_clients_and_write_variants(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    commands = (
        completed_record("python -u -c 'import waapi; print(waapi)'"),
        completed_record("curl http://127.0.0.1:8080/waapi"),
        completed_record("python helper.py --url ws://127.0.0.1:8080/waapi --websocket"),
        completed_record("printf '#!/bin/sh' > outputs/helper.sh"),
        completed_record("sed -i '' 's/a/b/' SKILL.md"),
    )

    facts = classify_commands(commands, skill_source=skill)

    assert commands[0].command in facts.inline_python_commands
    assert commands[0].command in facts.direct_waapi_client_commands
    assert commands[1].command in facts.direct_waapi_client_commands
    assert commands[2].command in facts.direct_waapi_client_commands
    assert commands[3].command in facts.write_like_commands
    assert commands[4].command in facts.write_like_commands
    assert len(facts.unexpected_commands) == len(commands)


def test_command_classifier_treats_python_exe_as_python_and_only_exact_gateway_as_legal(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    trusted_python = tmp_path / "Python313" / "python.exe"
    runner = skill / "scripts" / "run.py"
    inline = completed_record(
        recorded_argv_command(str(trusted_python), "-c", "print(1)")
    )
    gateway = completed_record(
        recorded_argv_command(
            str(trusted_python),
            str(runner),
            "gateway.py",
            "status",
        ),
        {
            "contract": "waapi-skill.gateway-result/v1",
            "command": "status",
            "ok": True,
        },
    )

    facts = classify_commands(
        (inline, gateway),
        skill_source=skill,
        expected_gateway_subcommands=("status",),
    )

    assert facts.inline_python_commands == (inline.command,)
    assert facts.gateway_commands == (gateway.command,)
    assert facts.unexpected_commands == (inline.command,)


def test_gateway_runtime_apis_only_accepts_call_shaped_objects() -> None:
    payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "describe",
        "api": "ak.fake.catalog.only",
        "capability": {"api": "ak.fake.not-live", "available": True},
        "call": {"api": "ak.wwise.core.object.get", "ok": True, "result": {"return": []}},
        "dispatch_result": {"api": "ak.wwise.core.object.setNotes", "ok": True, "result": {}},
        "api_attempted": "ak.wwise.ui.getSelectedObjects",
    }

    assert gateway_runtime_apis(payload) == (
        "ak.wwise.ui.getSelectedObjects",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.setNotes",
    )


def test_workspace_snapshot_does_not_follow_skill_symlink_and_reports_source_file_creation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "external-skill"
    workspace.mkdir()
    external.mkdir()
    (external / "SKILL.md").write_text("external\n", encoding="utf-8")
    install = workspace / ".agents" / "skills"
    install.mkdir(parents=True)
    create_symlink_or_skip(install / "waapi-skill", external, target_is_directory=True)

    before = snapshot_workspace(workspace)
    (workspace / "helper.py").write_text("print('no')\n", encoding="utf-8")
    after = snapshot_workspace(workspace)
    created, modified = workspace_changes(before, after)

    assert set(before) == {".agents/skills/waapi-skill"}
    assert created == ("helper.py",)
    assert modified == ()


def test_workspace_snapshot_detects_skill_symlink_retargeting(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    first = tmp_path / "first"
    second = tmp_path / "second"
    skills = workspace / ".agents" / "skills"
    skills.mkdir(parents=True)
    first.mkdir()
    second.mkdir()
    install = skills / "waapi-skill"
    create_symlink_or_skip(install, first, target_is_directory=True)
    before = snapshot_workspace(workspace)

    install.unlink()
    create_symlink_or_skip(install, second, target_is_directory=True)
    after = snapshot_workspace(workspace)
    created, modified = workspace_changes(before, after)

    assert created == ()
    assert modified == (".agents/skills/waapi-skill",)


def test_output_snapshot_and_skill_tree_hash_detect_created_and_modified_source(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    skill = tmp_path / "skill"
    outputs.mkdir()
    skill.mkdir()
    (skill / "SKILL.md").write_text("before\n", encoding="utf-8")
    before_outputs = snapshot_workspace(outputs)
    before_skill = snapshot_workspace(skill)
    before_hash = snapshot_tree_hash(before_skill)

    (outputs / "helper.py").write_text("print('bad')\n", encoding="utf-8")
    (skill / "SKILL.md").write_text("after\n", encoding="utf-8")
    after_outputs = snapshot_workspace(outputs)
    after_skill = snapshot_workspace(skill)
    created, _ = workspace_changes(before_outputs, after_outputs)

    assert created == ("helper.py",)
    assert snapshot_tree_hash(after_skill) != before_hash


def test_workspace_snapshot_uses_platform_write_then_restore_contract(tmp_path: Path) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("original\n", encoding="utf-8")
    metadata = target.stat()
    before = snapshot_workspace(tmp_path)
    before_ctime = target.stat().st_ctime_ns

    target.write_text("temporary\n", encoding="utf-8")
    target.write_text("original\n", encoding="utf-8")
    os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    after = snapshot_workspace(tmp_path)

    expected_modified = (
        ("existing.txt",)
        if target.stat().st_ctime_ns != before_ctime
        else ()
    )
    assert workspace_changes(before, after) == ((), expected_modified)


def test_workspace_snapshot_detects_content_change_after_mtime_restore(tmp_path: Path) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("original\n", encoding="utf-8")
    metadata = target.stat()
    before = snapshot_workspace(tmp_path)

    target.write_text("modified\n", encoding="utf-8")
    os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    after = snapshot_workspace(tmp_path)

    assert target.stat().st_mtime_ns == metadata.st_mtime_ns
    assert workspace_changes(before, after) == ((), ("existing.txt",))

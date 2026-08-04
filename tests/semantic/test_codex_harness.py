from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping, Sequence

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from .support import codex_harness as codex_harness_module
from .support.codex_harness import (  # pyright: ignore[reportMissingImports]
    CodexCliHarness,
    CodexCliTask,
    CodexCommandRecord,
    CodexGatewayErrorExpectation,
    CodexHarnessError,
    CodexHarnessConfig,
    audit_prompt_input_payload,
    audit_session_events,
    build_exec_command,
    build_prompt_audit_command,
    build_task_exec_command,
    build_task_resume_command,
    classify_commands,
    classify_codex_infrastructure_failure,
    completed_command_records,
    count_invalid_jsonl_lines,
    final_agent_message,
    gateway_runtime_apis,
    inspect_isolated_environment,
    is_link_or_junction,
    isolated_codex_environment,
    kill_process_group,
    parse_command_argv,
    parse_jsonl_events,
    run_process,
    subprocess_process_group_options,
    prepare_workspace_skill_install,
    snapshot_tree_hash,
    snapshot_workspace,
    turn_usage,
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
    SHIM_TRUSTED_PYTHON_ENV,
)


_FAKE_KILL_RETURN_CODE = -9


def completed_record(
    command: str,
    output: Mapping[str, object] | str | None = None,
    *,
    exit_code: int = 0,
    status: str = "completed",
) -> CodexCommandRecord:
    argv, has_operators, parse_error = parse_command_argv(command)
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
    )


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


def test_codex_binary_discovery_uses_host_native_path_lookup(tmp_path: Path) -> None:
    linux_binary = executable_file(tmp_path / "codex")
    windows_binary = executable_file(tmp_path / "codex.exe")
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
        platform_name="win32", which=windows_which
    ) == windows_binary.resolve(strict=True)
    assert windows_calls == ["codex.exe"]

    windows_alias_calls: list[str] = []

    def windows_alias_which(name: str) -> str | None:
        windows_alias_calls.append(name)
        return str(linux_binary) if name == "codex" else None

    with pytest.raises(CodexHarnessError, match="host-native .exe"):
        codex_harness_module.discover_codex_binary(
            platform_name="win32", which=windows_alias_which
        )
    assert windows_alias_calls == ["codex.exe", "codex"]


def test_codex_binary_discovery_skips_outer_sandbox_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = executable_file(tmp_path / ".codex" / ".sandbox-bin" / "codex.exe")
    host = executable_file(tmp_path / "host-bin" / "codex.exe")
    monkeypatch.setenv("PATH", os.pathsep.join((str(proxy.parent), str(host.parent))))

    assert codex_harness_module.discover_codex_binary(platform_name="win32") == (
        host.resolve(strict=True)
    )

    monkeypatch.setenv("PATH", str(proxy.parent))
    with pytest.raises(
        CodexHarnessError,
        match=r"outer-sandbox proxy.*--codex-binary",
    ):
        codex_harness_module.discover_codex_binary(platform_name="win32")
    with pytest.raises(CodexHarnessError, match=r"outer sandbox proxy.*--codex-binary"):
        codex_harness_module._strict_codex_binary(
            proxy,
            source="explicit",
            platform_name="win32",
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
    return f"python {skill / 'scripts' / 'run.py'} gateway.py {arguments}"


def recorded_argv_command(*argv: str) -> str:
    """Render synthetic Codex argv with the parser grammar of this host."""

    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


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


@pytest.mark.parametrize("key", ["HOME", "CODEX_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "CODEX_FOO"])
def test_isolated_environment_rejects_protected_extra_env(tmp_path: Path, key: str) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")

    with pytest.raises(CodexHarnessError, match="may not override"):
        with isolated_codex_environment(auth, extra_env={key: "/tmp/escape"}):
            pass


@pytest.mark.parametrize(
    "key",
    ["WWISE_WAAPI_PORT", "WWISE_EVIDENCE_DIR", "WAAPI_SKILL_STATE_DIR", "WAAPI_URL"],
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
        "WAAPI_SKILL_STATE_DIR": "/ambient/state",
        "WAAPI_URL": "ws://ambient.invalid/waapi",
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


def test_native_windows_isolated_environment_uses_detached_auth_copy(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text('{"token":"runner-owned"}\n', encoding="utf-8")

    with isolated_codex_environment(auth, platform_name="nt") as environment:
        audit = inspect_isolated_environment(
            environment,
            auth_json=auth,
            platform_name="nt",
        )
        installed_auth = Path(environment["CODEX_HOME"]) / "auth.json"

        assert audit.passed is True
        assert audit.auth_install_mode == "copy"
        assert audit.auth_is_symlink is False
        assert audit.auth_same_file_as_source is False
        assert audit.auth_sha256 == audit.expected_auth_sha256
        assert not os.path.samefile(installed_auth, auth)

        installed_auth.write_text('{"token":"isolated"}\n', encoding="utf-8")
        assert auth.read_text(encoding="utf-8") == '{"token":"runner-owned"}\n'


def test_native_windows_broker_overlay_uses_cmd_shims_without_bash_env(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    trusted_python = tmp_path / "python.exe"
    trusted_python.write_bytes(b"synthetic interpreter")
    shims = tmp_path / "broker-shims"
    shims.mkdir()
    for name in ("broker_shim.py", "python.cmd", "python3.cmd"):
        (shims / name).write_text("shim\n", encoding="utf-8")
    overlay = {
        "PATH": f"{shims};C:\\Windows\\System32",
        "PATHEXT": ".CMD;.EXE;.BAT",
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


def test_windows_workspace_skill_copy_is_filtered_detached_and_attested(tmp_path: Path) -> None:
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
        platform_name="nt",
    )

    assert install == workspace_skill_install_path(workspace)
    assert install.is_dir() and not install.is_symlink()
    assert not (install / ".venv").exists()
    assert not os.path.samefile(source / "SKILL.md", install / "SKILL.md")
    assert verify_workspace_skill_install(
        workspace,
        source,
        platform_name="nt",
    ) == install

    (install / "SKILL.md").write_text("drift\n", encoding="utf-8")
    with pytest.raises(CodexHarnessError, match="differs from the candidate tree"):
        verify_workspace_skill_install(
            workspace,
            source,
            platform_name="nt",
        )


def test_windows_workspace_skill_copy_rejects_hardlink_alias(tmp_path: Path) -> None:
    source = tmp_path / "waapi-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
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

    def fake_audit_prompt(
        self: CodexCliHarness,
        prompt: str,
        *,
        env: Mapping[str, str],
    ) -> codex_harness_module.CodexPromptAudit:
        prompt_audit_homes.append(env["HOME"])
        return passing_prompt_audit()

    def fake_run_process(
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
    ) -> codex_harness_module.ProcessResult:
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
            recorded_argv_command("sed", "-n", "1,200p", str(skill / "SKILL.md")),
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
        f"python {skill / 'scripts' / 'run.py'} --version 2022.1 gateway.py buses",
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
            f"python {skill / 'scripts' / 'run.py'} --version 2023.1 gateway.py buses",
            payload,
        ),
        completed_record(
            f"python {skill / 'scripts' / 'run.py'} --version 2022.1 other.py buses",
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
        f"python {runner} --version 2023.1 gateway.py operation-schema object.copy",
        "Gateway broker rejected command",
        exit_code=126,
    )
    wrong_target = completed_record(
        f"python {runner} arbitrary.py status",
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
    argv, has_operators, parse_error = parse_command_argv(command)
    record = CodexCommandRecord(
        command=command,
        exit_code=0,
        status="completed",
        aggregated_output=output,
        argv=argv,
        has_shell_operators=has_operators,
        parse_error=parse_error,
    )

    facts = classify_commands((record,), skill_source=skill)

    assert facts.skill_read is True
    assert facts.allowed_read_commands == (command,)
    assert facts.skill_read_files == ("SKILL.md",)
    assert facts.write_like_commands == ()
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
        argv, has_operators, parse_error = parse_command_argv(command)
        assert has_operators is True
        record = CodexCommandRecord(
            command=command,
            exit_code=0,
            status="completed",
            aggregated_output=output,
            argv=argv,
            has_shell_operators=has_operators,
            parse_error=parse_error,
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
    inline = completed_record(f'"{trusted_python}" -c "print(1)"')
    gateway = completed_record(
        f'"{trusted_python}" "{runner}" gateway.py status',
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

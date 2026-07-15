from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import pytest

from .support import codex_harness as codex_harness_module
from . import run_codex_skill_evals as legacy_evals
from .run_codex_skill_evals import (  # pyright: ignore[reportMissingImports]
    EvalCase,
    evaluate_check,
    load_evals,
    response_matches_oracle,
    selected_evals,
    summarize_expectations,
)
from .support.codex_harness import (  # pyright: ignore[reportMissingImports]
    CodexCliHarness,
    CodexCommandRecord,
    CodexHarnessError,
    CodexHarnessConfig,
    audit_prompt_input_payload,
    audit_session_events,
    build_exec_command,
    build_prompt_audit_command,
    classify_commands,
    classify_codex_infrastructure_failure,
    completed_command_records,
    count_invalid_jsonl_lines,
    final_agent_message,
    gateway_runtime_apis,
    inspect_isolated_environment,
    isolated_codex_environment,
    parse_command_argv,
    parse_jsonl_events,
    run_process,
    snapshot_tree_hash,
    snapshot_workspace,
    turn_usage,
    workspace_changes,
)
from .support.codex_gateway_broker import (  # pyright: ignore[reportMissingImports]
    BASH_ENV_NAME,
    BROKER_ENDPOINT_ENV,
    BROKER_TOKEN_ENV,
    BROKER_TRANSPORT_ENV,
    CodexGatewayBroker,
    ExpectedGatewayStep,
    GATEWAY_REQUIRED_ENV,
)


def completed_record(
    command: str,
    output: Mapping[str, object] | str | None = None,
    *,
    exit_code: int = 0,
) -> CodexCommandRecord:
    argv, has_operators, parse_error = parse_command_argv(command)
    return CodexCommandRecord(
        command=command,
        exit_code=exit_code,
        status="completed",
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
        self.returncode = -int(signal.SIGKILL)
        return "reaped stdout", "reaped stderr"

    def terminate(self) -> None:
        self.windows_signals.append("terminate")

    def kill(self) -> None:
        self.windows_signals.append("kill")


def gateway_command(skill: Path, arguments: str) -> str:
    return f"python {skill / 'scripts' / 'run.py'} gateway.py {arguments}"


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
        codex_binary=Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
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
        sandbox_mode="read-only",
        allow_output_write=False,
        network_access=False,
    )

    command = build_exec_command(config, prompt="Preview only.", writable_dir=tmp_path / "outputs")

    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--add-dir" not in command
    assert "sandbox_workspace_write.network_access=false" in command


def test_prompt_audit_command_uses_supported_global_flags_with_pristine_codex_home(tmp_path: Path) -> None:
    config = CodexHarnessConfig(
        workspace=tmp_path,
        skill_source=tmp_path / "skill",
        codex_binary=Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
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
            assert audit.broker_environment_keys == tuple(
                sorted(
                    {
                        BASH_ENV_NAME,
                        BROKER_ENDPOINT_ENV,
                        BROKER_TOKEN_ENV,
                        BROKER_TRANSPORT_ENV,
                        GATEWAY_REQUIRED_ENV,
                    }
                )
            )
            assert audit.unexpected_sensitive_environment_keys == ()
            assert environment[BASH_ENV_NAME] == str(broker.bash_env_path)
            assert environment[BROKER_TRANSPORT_ENV] == "tcp"
            assert environment[BROKER_ENDPOINT_ENV] == broker.endpoint
            assert environment[BROKER_TOKEN_ENV] == overlay[BROKER_TOKEN_ENV]
            assert environment[GATEWAY_REQUIRED_ENV] == "1"
            assert environment["PATH"] == overlay["PATH"]
            assert "WWISE_WAAPI_PORT" not in environment
            assert "WWISE_EVIDENCE_DIR" not in environment
            assert "WAAPI_SKILL_STATE_DIR" not in environment


def test_legacy_codex_eval_routes_live_environment_only_through_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[object] = []

    class FakeLiveSandbox:
        def __init__(self, version: str) -> None:
            self.version = version
            self.env = {
                **os.environ,
                "WWISE_VERSION": version,
                "WWISE_WAAPI_PORT": "65535",
                "WWISE_EVIDENCE_DIR": "/private/evidence",
                "WAAPI_SKILL_STATE_DIR": "/private/state",
                "WAAPI_URL": "ws://private.invalid/waapi",
            }
            self.cleaned = False
            instances.append(self)

        def launch(self) -> SimpleNamespace:
            return SimpleNamespace(
                wwise_version=self.version,
                waapi_host="127.0.0.1",
                waapi_port=49152,
            )

        def cleanup(self) -> None:
            self.cleaned = True

    captured_extra_env: dict[str, str] = {}

    def fake_harness_run(
        _self: CodexCliHarness,
        _prompt: str,
        *,
        output_dir: Path,
        extra_env: Mapping[str, str] | None = None,
    ) -> object:
        assert output_dir == tmp_path / "run" / "outputs"
        captured_extra_env.update(dict(extra_env or {}))
        raise CodexHarnessError("intentional stop after environment capture")

    monkeypatch.setattr(legacy_evals, "_LiveSandbox", FakeLiveSandbox)
    monkeypatch.setattr(legacy_evals, "query_oracle", lambda *_args, **_kwargs: {"api_attempts": []})
    monkeypatch.setattr(legacy_evals.CodexCliHarness, "run", fake_harness_run)
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    outputs_dir = run_dir / "outputs"
    outputs_dir.mkdir(parents=True)
    case = EvalCase(
        id=1,
        name="legacy-status",
        scenario="current_project",
        prompt="Read current project.",
        expected_output="Project facts.",
        required_apis=("ak.wwise.core.getInfo",),
        checks=({"id": "no_memory", "text": "No memory."},),
    )

    passed = legacy_evals.run_one_eval(
        case,
        run_dir=run_dir,
        outputs_dir=outputs_dir,
        skill_source=legacy_evals.SKILL_ROOT,
        version="2022.1",
        codex_binary=Path("/unused/codex"),
        auth_json=auth,
        timeout_seconds=10.0,
        reasoning_effort="medium",
    )

    assert passed is False
    assert instances and getattr(instances[0], "cleaned") is True
    assert {
        key
        for key in captured_extra_env
        if key == "BASH_ENV" or key.startswith(("WWISE_", "WAAPI_"))
    } == {
        BASH_ENV_NAME,
        BROKER_ENDPOINT_ENV,
        BROKER_TOKEN_ENV,
        BROKER_TRANSPORT_ENV,
        GATEWAY_REQUIRED_ENV,
    }
    assert "WWISE_WAAPI_PORT" not in captured_extra_env
    assert "WWISE_EVIDENCE_DIR" not in captured_extra_env
    assert "WAAPI_SKILL_STATE_DIR" not in captured_extra_env
    assert "WAAPI_URL" not in captured_extra_env


def test_run_process_keyboard_interrupt_terminates_kills_reaps_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = InterruptingFakeProcess()
    popen_arguments: dict[str, object] = {}
    group_signals: list[tuple[int, signal.Signals]] = []

    def fake_popen(*args: object, **kwargs: object) -> InterruptingFakeProcess:
        popen_arguments.update(kwargs)
        return fake

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    if os.name != "nt":
        monkeypatch.setattr(os, "killpg", lambda pid, requested: group_signals.append((pid, requested)))

    with pytest.raises(KeyboardInterrupt):
        run_process(["fake-codex"], cwd=tmp_path, env={}, timeout=10.0)

    assert popen_arguments["start_new_session"] is (os.name != "nt")
    assert fake.communicate_calls == [10.0, 5.0, None]
    if os.name != "nt":
        assert group_signals == [(fake.pid, signal.SIGTERM), (fake.pid, signal.SIGKILL)]
    else:  # pragma: no cover - Windows local harness is not used
        assert fake.windows_signals == ["terminate", "kill"]
    assert fake.returncode == -int(signal.SIGKILL)


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
    skills.mkdir(parents=True)
    (skills / "waapi-skill").symlink_to(source, target_is_directory=True)
    harness = CodexCliHarness(
        CodexHarnessConfig(
            workspace=workspace,
            skill_source=source,
            codex_binary=binary,
            auth_json=auth,
        )
    )

    harness.verify()
    (skills / "unexpected-skill").symlink_to(source, target_is_directory=True)

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


def test_command_classifier_distinguishes_gateway_from_inline_code_and_discovery(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    commands = (
        completed_record(f"sed -n '1,200p' {skill}/SKILL.md", "skill\n"),
        completed_record(
            gateway_command(skill, "buses"),
            {
                "contract": "waapi-skill.gateway-result/v1",
                "command": "buses",
                "ok": True,
                "call": {"api": "ak.wwise.core.object.get", "ok": True, "result": {"return": []}},
            },
        ),
        completed_record("rg --files ."),
        completed_record("python -u -c 'from waapi import WaapiClient; print(WaapiClient())'"),
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
    command = f'/bin/bash -lc "wc -l {skill_md} && sed -n \'1,240p\' {skill_md}"'
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


def test_command_classifier_rejects_other_skill_reads_with_shell_operators(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    skill_md = skill / "SKILL.md"
    content = "first\nsecond\n"
    skill_md.write_text(content, encoding="utf-8")
    commands_and_outputs = (
        (
            f'/bin/bash -lc "wc -l {skill_md} && sed -n \'1,1p\' {skill_md}"',
            f"2 {skill_md}\nfirst\n",
        ),
        (f'/bin/bash -lc "wc -l {skill_md} && cat {skill_md}"', f"2 {skill_md}\n{content}"),
        (f'/bin/bash -lc "cat {skill_md} ; true"', content),
        (f'/bin/bash -lc "cat {skill_md} | sed -n \'1,240p\'"', content),
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


def test_command_classifier_does_not_count_unproven_relative_skill_read(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")

    facts = classify_commands((completed_record("cat SKILL.md"),), skill_source=skill)

    assert facts.skill_read is False
    assert facts.allowed_read_commands == ()
    assert facts.unexpected_commands == ("cat SKILL.md",)


def test_fixed_gateway_gate_rejects_extra_lane_reference_reads(tmp_path: Path) -> None:
    skill = tmp_path / "waapi-skill"
    references = skill / "references"
    references.mkdir(parents=True)
    (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
    (references / "waapi-query.md").write_text("query\n", encoding="utf-8")
    gateway_payload = {
        "contract": "waapi-skill.gateway-result/v1",
        "command": "buses",
        "ok": True,
        "call": {"api": "ak.wwise.core.object.get", "ok": True},
    }
    facts = classify_commands(
        (
            completed_record(f"cat {skill}/SKILL.md", "skill\n"),
            completed_record(f"cat {references}/waapi-query.md", "query\n"),
            completed_record(gateway_command(skill, "buses"), gateway_payload),
        ),
        skill_source=skill,
        expected_gateway_subcommands=("buses",),
    )
    case = EvalCase(
        id=101,
        name="fixed-gateway",
        scenario="bus_listing",
        prompt="prompt",
        expected_output="expected",
        required_apis=(),
        checks=(),
    )

    passed, proof = evaluate_check(
        "fixed_gateway",
        case=case,
        result=SimpleNamespace(command_facts=facts),  # type: ignore[arg-type]
        oracle={},
        available_apis=set(),
    )

    assert passed is False
    assert "allowed_read_commands=2" in proof
    assert "total_commands=3" in proof


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
    (install / "waapi-skill").symlink_to(external, target_is_directory=True)

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
    install.symlink_to(first, target_is_directory=True)
    before = snapshot_workspace(workspace)

    install.unlink()
    install.symlink_to(second, target_is_directory=True)
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


def test_workspace_snapshot_detects_write_then_restore_via_ctime(tmp_path: Path) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("original\n", encoding="utf-8")
    before = snapshot_workspace(tmp_path)

    target.write_text("temporary\n", encoding="utf-8")
    target.write_text("original\n", encoding="utf-8")
    after = snapshot_workspace(tmp_path)

    assert workspace_changes(before, after) == ((), ("existing.txt",))


def test_current_project_oracle_rejects_wrong_reported_wproj_path() -> None:
    oracle = {
        "get_info": {"version": {"displayName": "v2022.1.19"}},
        "get_project_info": {
            "name": "SampleProject",
            "path": r"Y:\sandboxes\run-123\SampleProject.wproj",
        },
    }

    passed, proof = response_matches_oracle(
        "current_project",
        "Wwise v2022.1.19, SampleProject, Z:\\Applications\\SampleProject.wproj",
        oracle,
    )

    assert passed is False
    assert "path_consistent=False" in proof


def test_current_project_oracle_accepts_truthful_ellipsized_wproj_suffix() -> None:
    oracle = {
        "get_info": {"version": {"displayName": "v2022.1.19"}},
        "get_project_info": {
            "name": "SampleProject",
            "path": r"Y:\sandboxes\sample-project-123\SampleProject.wproj",
        },
    }

    passed, proof = response_matches_oracle(
        "current_project",
        "Wwise v2022.1.19，工程 SampleProject，文件 `...\\sample-project-123\\SampleProject.wproj`",
        oracle,
    )

    assert passed is True
    assert "path_consistent=True" in proof


def test_current_project_oracle_accepts_exact_project_filename_but_not_a_wrong_filename() -> None:
    oracle = {
        "get_info": {"version": {"displayName": "v2022.1.19"}},
        "get_project_info": {
            "name": "SampleProject",
            "path": r"Y:\sandboxes\sample-project-123\SampleProject.wproj",
        },
    }

    accepted, _ = response_matches_oracle(
        "current_project",
        "Wwise v2022.1.19，工程 SampleProject，文件 `SampleProject.wproj`",
        oracle,
    )
    rejected, _ = response_matches_oracle(
        "current_project",
        "Wwise v2022.1.19，工程 SampleProject，文件 `OtherProject.wproj`",
        oracle,
    )

    assert accepted is True
    assert rejected is False


def test_current_project_oracle_does_not_accept_generic_wwise_and_platform_words() -> None:
    oracle = {
        "get_info": {"displayName": "Wwise", "version": {"displayName": "v2022.1.19"}},
        "get_project_info": {
            "name": "SampleProject",
            "path": r"Y:\sandboxes\SampleProject.wproj",
            "platforms": [{"name": "Windows"}],
            "defaultConversion": {"name": "PCM"},
        },
    }

    passed, proof = response_matches_oracle("current_project", "当前是 Wwise，平台 Windows，使用 PCM。", oracle)

    assert passed is False
    assert "project_name='SampleProject'" in proof


def test_current_project_oracle_rejects_conflicting_patch_version() -> None:
    oracle = {
        "get_info": {"version": {"displayName": "v2022.1.19", "year": 2022, "major": 1, "minor": 19}},
        "get_project_info": {"name": "SampleProject"},
    }

    passed, proof = response_matches_oracle("current_project", "Wwise 2022.1.18, SampleProject", oracle)

    assert passed is False
    assert "version_consistent=False" in proof


def test_bus_oracle_requires_complete_name_set_and_exact_count() -> None:
    oracle = {
        "object_get": {
            "return": [
                {"name": "Master Audio Bus"},
                {"name": "Music"},
                {"name": "SFX"},
            ]
        }
    }

    partial, _ = response_matches_oracle("bus_listing", "Master Audio Bus", oracle)
    substring_only, _ = response_matches_oracle(
        "bus_listing",
        "当前共有 3 个 Bus：Master Audio Bus、MusicFX、SFX。",
        oracle,
    )
    complete, proof = response_matches_oracle(
        "bus_listing",
        "当前共有 3 个 Bus：Master Audio Bus、Music、SFX。",
        oracle,
    )

    assert partial is False
    assert substring_only is False
    assert complete is True
    assert "oracle_bus_count=3" in proof


def test_selection_boundary_requires_negative_polarity() -> None:
    oracle = {"selected_objects_error": {"type": "WaapiRequestFailed", "message": "procedure unavailable"}}

    positive, _ = response_matches_oracle("selected_object", "当前 UI 接口可用。", oracle)
    negative, proof = response_matches_oracle(
        "selected_object",
        "当前是 command-line/headless Wwise，UI getSelectedObjects 不可用。",
        oracle,
    )

    assert positive is False
    assert negative is True
    assert "negative_boundary=True" in proof


def test_selection_rows_require_name_type_and_path() -> None:
    oracle = {
        "selected_objects": {
            "objects": [
                {
                    "name": "Play_Test",
                    "type": "Event",
                    "path": r"\Events\Default Work Unit\Play_Test",
                }
            ]
        }
    }

    partial, _ = response_matches_oracle("selected_object", "选中了 Play_Test。", oracle)
    complete, proof = response_matches_oracle(
        "selected_object",
        r"选中 Play_Test，类型 Event，路径 \Events\Default Work Unit\Play_Test。",
        oracle,
    )

    assert partial is False
    assert complete is True
    assert "missing_fields=[]" in proof


def test_failed_isolation_or_gateway_hard_gate_zeroes_case_score() -> None:
    case = EvalCase(
        id=99,
        name="hard-gate",
        scenario="current_project",
        prompt="prompt",
        expected_output="expected",
        required_apis=(),
        checks=(
            {"id": "no_memory", "text": "isolated"},
            {"id": "actual_result", "text": "correct result"},
        ),
    )

    summary = summarize_expectations(
        case,
        (
            {"text": "isolated", "passed": False, "evidence": "memory found"},
            {"text": "correct result", "passed": True, "evidence": "matched"},
        ),
    )

    assert summary["raw_pass_rate"] == 0.5
    assert summary["pass_rate"] == 0.0
    assert summary["hard_gate_passed"] is False
    assert summary["failed_hard_gates"] == ["no_memory"]
    assert summary["case_passed"] is False


def test_empty_expectations_never_pass_and_eval_loader_rejects_missing_hard_gates(tmp_path: Path) -> None:
    empty_case = EvalCase(
        id=103,
        name="empty",
        scenario="current_project",
        prompt="prompt",
        expected_output="expected",
        required_apis=(),
        checks=(),
    )
    assert summarize_expectations(empty_case, ())["case_passed"] is False

    suite = tmp_path / "evals.json"
    suite.write_text(
        json.dumps(
            {
                "contract": "waapi-skill.codex-read-evals/v1",
                "evals": [
                    {
                        "id": 1,
                        "name": "bad",
                        "scenario": "current_project",
                        "prompt": "prompt",
                        "checks": [{"id": "no_memory", "text": "isolated"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing hard gates"):
        load_evals(suite)


def test_selected_evals_rejects_unknown_id() -> None:
    case = EvalCase(
        id=1,
        name="one",
        scenario="current_project",
        prompt="prompt",
        expected_output="expected",
        required_apis=(),
        checks=(),
    )
    with pytest.raises(ValueError, match="unknown eval"):
        selected_evals((case,), (2,))


def test_no_ad_hoc_code_gate_rejects_non_source_workspace_mutation() -> None:
    case = EvalCase(
        id=102,
        name="workspace-mutation",
        scenario="current_project",
        prompt="prompt",
        expected_output="expected",
        required_apis=(),
        checks=(),
    )
    result = SimpleNamespace(
        command_facts=SimpleNamespace(
            inline_python_commands=(),
            direct_waapi_client_commands=(),
            write_like_commands=(),
        ),
        created_files=("helper-without-extension",),
        modified_files=(),
        deleted_files=(),
        created_source_files=(),
        modified_source_files=(),
        deleted_source_files=(),
        skill_tree_unchanged=True,
        collab_call_count=0,
    )

    passed, proof = evaluate_check(
        "no_ad_hoc_code",
        case=case,
        result=result,  # type: ignore[arg-type]
        oracle={},
        available_apis=set(),
    )

    assert passed is False
    assert "workspace:helper-without-extension" in proof


def test_live_evidence_check_ignores_forged_writable_directory_api_set() -> None:
    case = EvalCase(
        id=100,
        name="trusted-evidence",
        scenario="bus_listing",
        prompt="prompt",
        expected_output="expected",
        required_apis=("ak.wwise.core.object.get",),
        checks=(),
    )
    result = SimpleNamespace(
        command_facts=SimpleNamespace(gateway_evidence_apis=("ak.wwise.core.getInfo",)),
    )

    passed, proof = evaluate_check(
        "live_evidence",
        case=case,
        result=result,  # type: ignore[arg-type]
        oracle={"api_attempts": ["ak.wwise.core.object.get"]},
        available_apis={"ak.wwise.core.object.get"},
    )

    assert passed is False
    assert "missing=['ak.wwise.core.object.get']" in proof

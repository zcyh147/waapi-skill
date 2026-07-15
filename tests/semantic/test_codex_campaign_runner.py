from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

import pytest

from tests.semantic import run_codex_skill_campaign as campaign_script
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_campaign import CampaignEvidenceError
from tests.semantic.support.codex_campaign_runner import (
    AUTO_RETRY_CATEGORIES,
    LIVE_PREFLIGHT_CONTRACT,
    LIVE_READINESS_RETRY_CATEGORY,
    PHASE_CONTRACT,
    PHASE_ERROR_CONTRACT,
    RUNTIME_CONTRACT,
    RUN_CONTRACT,
    SKILL_LINK_ATTESTATION_CONTRACT,
    classify_phase,
    replace_expected_skill_symlinks,
    validate_child_run,
)
from tests.semantic.support.codex_eval_suite import SUPPORTED_VERSIONS, EvalSession, load_eval_suite


_HASH = "a" * 64
_PROJECT_HASH = {
    "algorithm": "sha256",
    "strategy": "full",
    "digest": "b" * 64,
    "bytes_hashed": 123,
    "file_count": 4,
}
_WWISE_GET_INFO_DISPLAY_NAME_BY_VERSION = {
    "2021.1": "Wwise",
    "2022.1": "Wwise",
    "2023.1": "WwiseConsole",
    "2024.1": "WwiseConsole",
    "2025.1": "WwiseConsole",
}
_SCREENING = load_eval_suite(matrix.DEFAULT_SUITE).expand_profile("screening")
_FULL = load_eval_suite(matrix.DEFAULT_SUITE).expand_profile("full_cross_version_168")


def _session(case_id: str, phase: str = "single") -> EvalSession:
    return next(
        item for item in _SCREENING if item.case.id == case_id and item.phase == phase
    )


def _full_session(case_id: str, version: str, *, repetition: int = 1) -> EvalSession:
    return next(
        item
        for item in _FULL
        if item.case.id == case_id
        and item.version == version
        and item.repetition == repetition
    )


def _safe_session_name(session_id: str) -> str:
    value = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in session_id
    )
    return value.strip("-")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    skill_source = tmp_path / "skill-source"
    skill_source.mkdir()
    (skill_source / "SKILL.md").write_text("# test\n", encoding="utf-8")
    suite_path = tmp_path / "suite.json"
    suite_path.write_text("{}\n", encoding="utf-8")
    fake_console = tmp_path / "WwiseConsole"
    fake_console.write_text("synthetic console\n", encoding="utf-8")
    live_config = tmp_path / "live-config.json"
    _write_json(
        live_config,
        {
            "versions": {
                version: {"wwise_console": str(fake_console)}
                for version in SUPPORTED_VERSIONS
            }
        },
    )
    return skill_source, suite_path, live_config


def _phase_identity(session: EvalSession, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "contract": PHASE_CONTRACT,
        "session_id": session.session_id,
        "pair_id": session.pair_id,
        "profile_id": session.profile_id,
        "case_id": session.case.id,
        "phase": session.phase,
        "version": session.version,
        "repetition": session.repetition,
    }
    value.update(overrides)
    return value


def _write_no_action_evidence(output_dir: Path, *, include_facts: bool) -> None:
    _write_json(
        output_dir / "broker-evidence.json",
        {"records": [], "consumed_step_names": []},
    )
    if include_facts:
        _write_json(
            output_dir / "codex-facts.json",
            {
                "file_change_count": 0,
                "collab_call_count": 0,
                "created_files": [],
                "modified_files": [],
                "deleted_files": [],
                "created_source_files": [],
                "modified_source_files": [],
                "deleted_source_files": [],
                "command_facts": {"gateway_attempt_commands": []},
            },
        )


def _write_completed_phase(
    output_dir: Path,
    *,
    session: EvalSession,
    passed: bool,
) -> None:
    _write_json(
        output_dir / "phase.json",
        _phase_identity(
            session,
            passed=passed,
            grade_passed=passed,
            error="",
        ),
    )
    gate_rows = [
        {
            "id": gate_id,
            "known": True,
            "passed": passed or index != 0,
        }
        for index, gate_id in enumerate(session.hard_gates)
    ]
    failed_gate_ids = [row["id"] for row in gate_rows if not row["passed"]]
    _write_json(
        output_dir / "grading.json",
        {
            "session_id": session.session_id,
            "case_id": session.case.id,
            "phase": session.phase,
            "version": session.version,
            "passed": passed,
            "failed_gate_ids": failed_gate_ids,
            "unknown_gate_ids": [],
            "gates": gate_rows,
        },
    )
    runner = "/synthetic/waapi-skill/scripts/run.py"
    command_records: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    gateway_attempt_commands: list[str] = []
    for sequence, step in enumerate(session.gateway_steps, start=1):
        argv = ["python", runner, "gateway.py", step]
        command = " ".join(argv)
        output = json.dumps(
            {
                "command": step,
                "contract": "waapi-skill.gateway-result/v1",
                "ok": True,
            },
            sort_keys=True,
        )
        gateway_attempt_commands.append(command)
        command_records.append(
            {
                "command": command,
                "exit_code": 0,
                "status": "completed",
                "aggregated_output": output,
                "argv": argv,
                "has_shell_operators": False,
                "parse_error": "",
            }
        )
        records.append(
            {
                "sequence": sequence,
                "step_name": step,
                "authenticated": True,
                "accepted": True,
                "rejection": "",
                "model_argv": argv,
                "normalized_model_argv": argv,
                "succeeded": True,
                "exit_code": 0,
                "runner_exit_code": 0,
                "allowed_exit_codes": [0],
                "payload": {
                    "command": step,
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                },
                "payload_error": "",
            }
        )
    _write_json(
        output_dir / "broker-evidence.json",
        {
            "passed": True,
            "complete": True,
            "terminal_state": "COMPLETE",
            "expected_step_names": list(session.gateway_steps),
            "consumed_step_names": list(session.gateway_steps),
            "records": records,
        },
    )
    _write_json(
        output_dir / "broker-reconciliation.json",
        {
            "passed": True,
            "errors": [],
            "observed_command_count": len(records),
            "accepted_record_count": len(records),
        },
    )
    _write_json(output_dir / "runner-oracle.json", {"trusted": True})
    _write_json(
        output_dir / "codex-facts.json",
        {
            "exit_status": 0,
            "timed_out": False,
            "prompt_audit": {"passed": True, "has_memory": False},
            "isolation_audit": {"passed": True},
            "session_audit": {"passed": True},
            "skill_tree_unchanged": True,
            "skill_tree_sha256_before": _HASH,
            "skill_tree_sha256_after": _HASH,
            "file_change_count": 0,
            "collab_call_count": 0,
            "created_files": [],
            "modified_files": [],
            "deleted_files": [],
            "created_source_files": [],
            "modified_source_files": [],
            "deleted_source_files": [],
            "command_facts": {
                "command_records": command_records,
                "gateway_attempt_commands": gateway_attempt_commands,
                "gateway_subcommands": list(session.gateway_steps),
                "direct_waapi_client_commands": [],
                "discovery_commands": [],
                "inline_python_commands": [],
                "unexpected_commands": [],
                "write_like_commands": [],
            },
        },
    )


def _write_coherent_rejected_gateway_trace(
    output_dir: Path,
    *,
    session: EvalSession,
) -> None:
    runner = "/synthetic/waapi-skill/scripts/run.py"
    expected_step = session.gateway_steps[0]
    wrong_argv = [
        "python",
        runner,
        "gateway.py",
        "--version",
        session.version,
        "describe",
        "ak.wwise.waapi.getFunctions",
    ]
    retry_argv = [
        "python",
        runner,
        "gateway.py",
        expected_step,
        "ak.wwise.waapi.getFunctions",
        "--args-json",
        "{}",
        "--options-json",
        "{}",
    ]
    commands = [" ".join(wrong_argv), " ".join(retry_argv)]
    rejected_records = [
        {
            "sequence": sequence,
            "step_name": expected_step,
            "authenticated": True,
            "accepted": False,
            "rejection": rejection,
            "model_argv": argv,
            "normalized_model_argv": argv if sequence == 1 else [],
            "succeeded": False,
            "exit_code": 126,
            "runner_exit_code": None,
            "allowed_exit_codes": [],
            "payload": None,
            "payload_error": "",
        }
        for sequence, (argv, rejection) in enumerate(
            (
                (wrong_argv, f"expected step {expected_step!r}"),
                (retry_argv, "broker is terminal FAILED"),
            ),
            start=1,
        )
    ]
    _write_json(
        output_dir / "broker-evidence.json",
        {
            "passed": False,
            "complete": False,
            "terminal_state": "FAILED",
            "expected_step_names": list(session.gateway_steps),
            "consumed_step_names": [],
            "records": rejected_records,
        },
    )
    _write_json(
        output_dir / "broker-reconciliation.json",
        {
            "passed": False,
            "errors": [
                "resolved command count does not match accepted broker record count",
                "broker recorded one or more rejected shim requests",
            ],
            "observed_command_count": len(rejected_records),
            "accepted_record_count": 0,
        },
    )
    facts_path = output_dir / "codex-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    facts["command_facts"] = {
        "command_records": [
            {
                "command": command,
                "exit_code": 126,
                "status": "failed",
                "aggregated_output": "",
                "argv": argv,
                "has_shell_operators": False,
                "parse_error": "",
            }
            for command, argv in zip(commands, (wrong_argv, retry_argv), strict=True)
        ],
        "gateway_attempt_commands": commands,
        "gateway_subcommands": [],
        "direct_waapi_client_commands": [],
        "discovery_commands": [],
        "inline_python_commands": [],
        "unexpected_commands": commands,
        "write_like_commands": [],
    }
    _write_json(facts_path, facts)


def _write_structured_infrastructure_failure(
    output_dir: Path,
    *,
    session: EvalSession,
    category: str = "service_unavailable",
) -> None:
    _write_json(
        output_dir / "phase.json",
        _phase_identity(
            session,
            passed=False,
            grade_passed=False,
            error="Codex infrastructure failure",
            failure_class="infrastructure",
        ),
    )
    _write_json(
        output_dir / "phase-error.json",
        {
            "contract": PHASE_ERROR_CONTRACT,
            "session_id": session.session_id,
            "failure_class": "infrastructure",
            "stage": "codex-cli-infrastructure",
            "archive_errors": [],
            "harness_result_available": True,
            "reconciliation_available": False,
            "infrastructure_failure": {
                "category": category,
                "message": "temporary outage",
                "turn_failed": True,
                "timed_out": False,
                "agent_item_event_count": 0,
            },
        },
    )
    _write_no_action_evidence(output_dir, include_facts=True)


def _write_legacy_prompt_timeout(output_dir: Path, *, session: EvalSession) -> None:
    _write_json(
        output_dir / "phase.json",
        _phase_identity(
            session,
            passed=False,
            grade_passed=False,
            error="prompt audit timeout",
            failure_class="phase_execution",
        ),
    )
    _write_json(
        output_dir / "phase-error.json",
        {
            "contract": PHASE_ERROR_CONTRACT,
            "session_id": session.session_id,
            "failure_class": "phase_execution",
            "stage": "harness-run",
            "exception_type": "CodexHarnessError",
            "exception_message": "codex debug prompt-input failed with 124: timed out",
            "archive_errors": [],
            "harness_result_available": False,
            "reconciliation_available": False,
            "infrastructure_failure": None,
        },
    )
    _write_no_action_evidence(output_dir, include_facts=False)


def _write_live_runtime(
    root: Path,
    *,
    sessions: Sequence[EvalSession],
    executed: Sequence[EvalSession],
    failed_session_ids: Sequence[str],
    retained: bool,
    cleanup_good: bool = True,
    run_errors: Sequence[str] = (),
) -> None:
    version = sessions[0].version
    _write_json(
        root / "live-preflight.json",
        {
            "contract": LIVE_PREFLIGHT_CONTRACT,
            "ok": True,
            "automatic_install_attempted": False,
        },
    )
    source_root = root.parent / f"immutable-source-{version}"
    source_root.mkdir(parents=True, exist_ok=True)
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("immutable source\n", encoding="utf-8")
    sandbox_root = root / "versions" / version / "sandbox-root"
    sandbox_root.mkdir(parents=True, exist_ok=True)
    sandbox = sandbox_root / "sample-project-run-1"
    sandbox_project = sandbox / "SampleProject.wproj"
    if retained:
        sandbox.mkdir()
        sandbox_project.write_text("retained sandbox\n", encoding="utf-8")
    process_pid = 43210
    selected_port = 43211
    keep_decision = (
        "retained-in-iteration-root-for-semantic-failure" if retained else "deleted"
    )
    metadata = {
        "copy_duration_seconds": 0.01,
        "source_hash": _PROJECT_HASH,
        "sandbox_hash": _PROJECT_HASH,
        "source_mtime_before": 1,
        "source_mtime_after": 1,
        "wwise_version": version,
        "identity_verified": True,
        "expected_project_identity": "SampleProject",
        "get_info_display_name": _WWISE_GET_INFO_DISPLAY_NAME_BY_VERSION.get(
            version,
            "UnknownWwiseProduct",
        ),
        "get_info_version": {
            "year": int(version.split(".")[0]),
            "major": int(version.split(".")[1]),
        },
        "source_path": str(source_project),
        "source_root": str(source_root),
        "launch_project_path": str(sandbox_project),
        "sandbox_project_path": str(sandbox_project),
        "sandbox_path": str(sandbox),
        "command": [
            str(root.parent / "WwiseConsole"),
            "waapi-server",
            str(sandbox_project),
            "--wamp-port",
            str(selected_port),
            "--http-port",
            "0",
        ],
        "selected_port": selected_port,
        "process_pid": process_pid,
        "process_cleanup_result": "cleaned" if cleanup_good else "residual-processes",
        "process_cleanup_details": {
            "process_exited": cleanup_good,
            "residual_processes": [] if cleanup_good else [process_pid],
            "launch_pid": process_pid,
        },
        "keep_decision": keep_decision,
        "notes": [],
    }
    _write_json(
        root / "versions" / version / "runtime.json",
        {
            "contract": RUNTIME_CONTRACT,
            "version": version,
            "session_ids": [item.session_id for item in sessions],
            "executed_session_ids": [item.session_id for item in executed],
            "failed_session_ids": list(failed_session_ids),
            "source_hash_before": _PROJECT_HASH,
            "source_hash_after": _PROJECT_HASH,
            "iteration_sandbox_root": str(sandbox_root),
            "sandbox_metadata": metadata,
            "fixture_transactions": [],
            "sandbox_retained": retained,
            "errors": list(run_errors),
        },
    )


def _write_pre_session_readiness_failure(
    tmp_path: Path,
    *,
    sessions: Sequence[EvalSession],
) -> tuple[Path, Path, Path, Path]:
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=sessions,
        phase_kinds=(),
        executed_count=0,
        offline_only=False,
        returncode=1,
    )
    runtime_path = root / "versions" / sessions[0].version / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    metadata = runtime["sandbox_metadata"]
    sandbox = Path(metadata["sandbox_path"])
    sandbox_project = Path(metadata["sandbox_project_path"])
    selected_port = metadata["selected_port"]
    process_pid = metadata["process_pid"]
    wine_prefix = sandbox / ".wine-prefix"
    metadata_path = sandbox / "sandbox-metadata.json"
    metadata.update(
        {
            "identity_verified": None,
            "get_info_display_name": None,
            "get_info_version": None,
            "ready_duration_seconds": None,
            "wine_prefix_path": str(wine_prefix),
            "metadata_path": str(metadata_path),
            "process_cleanup_result": "cleaned",
            "process_cleanup_details": {
                "launch_pid": process_pid,
                "wine_prefix": str(wine_prefix),
                "process_exited": True,
                "detached_cleanup_pids": [],
                "wineserver_commands": [],
                "residual_processes": [],
            },
        }
    )
    command = metadata["command"]
    error = (
        "[live-version-run] Traceback (most recent call last):\n"
        "  File \"run_codex_skill_matrix.py\", line 1, in run_live_version_sessions\n"
        "    lifecycle = launch_sandboxed_wwise(sandbox, live_env)\n"
        "  File \"sandbox_fixture.py\", line 1, in launch_sandboxed_wwise\n"
        "    lifecycle.run_until_ready()\n"
        "  File \"headless.py\", line 1, in run_until_ready\n"
        "    return self.wait_ready()\n"
        "  File \"headless.py\", line 1, in wait_ready\n"
        "    raise ReadinessTimeout(message, diagnostics)\n"
        "wwise_waapi.headless.ReadinessTimeout: WAAPI readiness timed out; "
        f"port={selected_port}; timeout=60.0; duration=60.1s; "
        "last_exception_type=ConnectionRefusedError; "
        f"argv={command!r}; cwd={str(sandbox)!r}; pid=None; "
        "process_state=not-started; exit_code=None; "
        "stdout_tail=\"WAAPI\\tFatal Error\\tWampFailedStartingServer\\t"
        f"WAMP server failed to start (port {selected_port}), will retry every 10s.\"; "
        "stderr_tail=''"
    )
    runtime["errors"] = [error]
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["run_errors"] = [error]
    _write_json(metadata_path, metadata)
    _write_json(runtime_path, runtime)
    _write_json(summary_path, summary)
    assert sandbox_project.is_file()
    return root, skill, suite, live


def _persist_runtime_metadata(runtime_path: Path, runtime: dict[str, Any]) -> None:
    metadata = runtime["sandbox_metadata"]
    metadata_path = Path(metadata["metadata_path"])
    _write_json(metadata_path, metadata)
    _write_json(runtime_path, runtime)


def _write_child(
    tmp_path: Path,
    *,
    sessions: Sequence[EvalSession],
    phase_kinds: Sequence[str],
    offline_only: bool,
    returncode: int,
    executed_count: int | None = None,
    cleanup_good: bool = True,
) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "matrix"
    root.mkdir(parents=True)
    skill_source, suite_path, live_config = _inputs(tmp_path)
    executed = tuple(sessions if executed_count is None else sessions[:executed_count])
    if len(phase_kinds) != len(executed):
        raise AssertionError("phase_kinds must describe every executed phase")
    verdict_passes: list[bool] = []
    run_errors: list[str] = []
    for session, kind in zip(executed, phase_kinds, strict=True):
        output_dir = root / "sessions" / _safe_session_name(session.session_id) / "outputs"
        if kind == "pass":
            _write_completed_phase(output_dir, session=session, passed=True)
            verdict_passes.append(True)
        elif kind == "fail":
            _write_completed_phase(output_dir, session=session, passed=False)
            verdict_passes.append(False)
        elif kind == "structured-retry":
            _write_structured_infrastructure_failure(output_dir, session=session)
            verdict_passes.append(False)
        elif kind == "legacy-timeout":
            _write_legacy_prompt_timeout(output_dir, session=session)
            verdict_passes.append(False)
        elif kind == "pre-codex-fixture-error":
            if offline_only:
                raise AssertionError("pre-Codex fixture errors are live-only")
            run_errors.append(
                f"[live-phase:{session.session_id}] Traceback (most recent call last):\n"
                "  File \"synthetic-fixture.py\", line 1, in snapshot\n"
                "FixtureContractError: synthetic pre-Codex fixture failure"
            )
            verdict_passes.append(False)
        else:
            raise AssertionError(f"unknown synthetic phase kind: {kind}")

    failed_ids = []
    if executed and phase_kinds[-1] != "pass":
        failed_ids = [executed[-1].session_id]
    _write_json(
        root / "run-config.json",
        {
            "contract": RUN_CONTRACT,
            "profile": sessions[0].profile_id,
            "expected_session_count": len(sessions),
            "case_ids": [],
            "versions": [] if offline_only else [sessions[0].version],
            "pair_ids": list(dict.fromkeys(item.pair_id for item in sessions)),
            "offline_only": offline_only,
            "model": "test-model",
            "reasoning_effort": "medium",
            "service_tier": "priority",
            "memory": "disabled",
            "fresh_session_per_phase": True,
            "skill_source": str(skill_source.resolve()),
            "suite_path": str(suite_path.resolve()),
            "live_config": str(live_config.resolve()),
        },
    )
    all_pass = (
        len(executed) == len(sessions)
        and bool(executed)
        and all(verdict_passes)
    )
    _write_json(
        root / "summary.json",
        {
            "contract": RUN_CONTRACT,
            "profile": sessions[0].profile_id,
            "selected_session_count": len(sessions),
            "executed_session_ids": [item.session_id for item in executed],
            "failed_session_ids": failed_ids,
            "pending_session_ids": [item.session_id for item in sessions[len(executed) :]],
            "run_errors": run_errors,
            "executed_session_count": len(executed),
            "passed_session_count": sum(verdict_passes),
            "all_selected_passed": all_pass,
        },
    )
    if not offline_only:
        _write_live_runtime(
            root,
            sessions=sessions,
            executed=executed,
            failed_session_ids=failed_ids,
            retained=not all_pass,
            cleanup_good=cleanup_good,
            run_errors=run_errors,
        )
    return root, skill_source, suite_path, live_config


def _validate(
    root: Path,
    skill_source: Path,
    suite_path: Path,
    live_config: Path,
    *,
    sessions: Sequence[EvalSession],
    offline_only: bool,
    returncode: int,
):
    return validate_child_run(
        root,
        expected_sessions=sessions,
        expected_pair_ids=tuple(dict.fromkeys(item.pair_id for item in sessions)),
        profile=sessions[0].profile_id,
        skill_source=skill_source,
        suite_path=suite_path,
        live_config=live_config,
        model="test-model",
        reasoning_effort="medium",
        service_tier="priority",
        version=None if offline_only else sessions[0].version,
        offline_only=offline_only,
        returncode=returncode,
    )


def test_expected_skill_symlink_is_replaced_by_regular_attestation(tmp_path: Path) -> None:
    skill_source, _suite, _live = _inputs(tmp_path)
    attempt = tmp_path / "attempt"
    link = (
        attempt
        / "runs"
        / "offline"
        / "matrix"
        / "sessions"
        / "screening-C1-2022-1-r1-single"
        / "agent-workspace"
        / ".agents"
        / "skills"
        / "waapi-skill"
    )
    link.parent.mkdir(parents=True)
    link.symlink_to(skill_source, target_is_directory=True)

    replaced = replace_expected_skill_symlinks(
        attempt,
        skill_source=skill_source,
        candidate_sha256=_HASH,
    )

    assert replaced == (link.relative_to(attempt).as_posix(),)
    assert link.is_file()
    assert not link.is_symlink()
    assert json.loads(link.read_text(encoding="utf-8")) == {
        "contract": SKILL_LINK_ATTESTATION_CONTRACT,
        "candidate_sha256": _HASH,
        "original_link_target": str(skill_source.resolve()),
        "path": link.relative_to(attempt).as_posix(),
    }


def test_any_unexpected_symlink_blocks_skill_link_replacement(tmp_path: Path) -> None:
    skill_source, _suite, _live = _inputs(tmp_path)
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    target = attempt / "regular.txt"
    target.write_text("evidence\n", encoding="utf-8")
    (attempt / "unexpected-link").symlink_to(target)

    with pytest.raises(CampaignEvidenceError, match="unexpected symlink"):
        replace_expected_skill_symlinks(
            attempt,
            skill_source=skill_source,
            candidate_sha256=_HASH,
        )


def test_agent_workspace_without_runner_skill_link_is_rejected(tmp_path: Path) -> None:
    skill_source, _suite, _live = _inputs(tmp_path)
    workspace = tmp_path / "attempt" / "matrix" / "sessions" / "session" / "agent-workspace"
    workspace.mkdir(parents=True)

    with pytest.raises(CampaignEvidenceError, match="missing the exact runner-created Skill symlink"):
        replace_expected_skill_symlinks(
            tmp_path / "attempt",
            skill_source=skill_source,
            candidate_sha256=_HASH,
        )


@pytest.mark.parametrize(
    ("phase_kind", "expected_status", "expected_retry_category"),
    (
        ("pass", "PASS", None),
        ("fail", "FAIL", None),
        ("structured-retry", "RETRYABLE", "service_unavailable"),
        ("legacy-timeout", "RETRYABLE", "prompt_audit_timeout_before_exec"),
    ),
)
def test_offline_child_classifies_trusted_phase_evidence(
    tmp_path: Path,
    phase_kind: str,
    expected_status: str,
    expected_retry_category: str | None,
) -> None:
    session = _session("C1")
    returncode = 0 if phase_kind == "pass" else 1
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=(phase_kind,),
        offline_only=True,
        returncode=returncode,
    )

    result = _validate(
        root,
        skill,
        suite,
        live,
        sessions=(session,),
        offline_only=True,
        returncode=returncode,
    )

    assert result.observations == (
        {
            "unit_id": session.pair_id,
            "status": expected_status,
            "phases": [{"phase": "single", "status": expected_status}],
        },
    )
    assert result.retry_categories == (
        () if expected_retry_category is None else (expected_retry_category,)
    )


def test_successful_broker_trace_bridges_one_missing_cli_payload(tmp_path: Path) -> None:
    session = _session("M4", "confirm")
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=False,
        returncode=0,
    )
    output_dir = root / "sessions" / _safe_session_name(session.session_id) / "outputs"
    facts_path = output_dir / "codex-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    command_facts = facts["command_facts"]
    confirm_index = list(session.gateway_steps).index("confirm")
    confirm_record = command_facts["command_records"][confirm_index]
    confirm_record["aggregated_output"] = ""
    command_facts["gateway_subcommands"].remove("confirm")
    command_facts["unexpected_commands"] = [confirm_record["command"]]
    _write_json(facts_path, facts)

    verdict = classify_phase(output_dir, session=session)
    result = _validate(
        root,
        skill,
        suite,
        live,
        sessions=(session,),
        offline_only=False,
        returncode=0,
    )

    assert verdict.status == "PASS"
    assert result.executed_session_ids == (session.session_id,)
    assert result.observations[0]["status"] == "PASS"


@pytest.mark.parametrize(
    "forbidden_key",
    (
        "direct_waapi_client_commands",
        "discovery_commands",
        "inline_python_commands",
        "write_like_commands",
    ),
)
def test_successful_broker_trace_does_not_hide_independent_forbidden_commands(
    tmp_path: Path,
    forbidden_key: str,
) -> None:
    session = _session("Q1")
    root, _skill, _suite, _live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=False,
        returncode=0,
    )
    output_dir = root / "sessions" / _safe_session_name(session.session_id) / "outputs"
    facts_path = output_dir / "codex-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    facts["command_facts"][forbidden_key] = ["forbidden independent command"]
    _write_json(facts_path, facts)

    verdict = classify_phase(output_dir, session=session)

    assert verdict.status == "BLOCKED"
    assert forbidden_key in verdict.reason


def test_successful_broker_trace_does_not_bridge_an_unrelated_unexpected_command(
    tmp_path: Path,
) -> None:
    session = _session("Q1")
    root, _skill, _suite, _live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=False,
        returncode=0,
    )
    output_dir = root / "sessions" / _safe_session_name(session.session_id) / "outputs"
    facts_path = output_dir / "codex-facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    facts["command_facts"]["unexpected_commands"] = ["echo unrelated"]
    _write_json(facts_path, facts)

    verdict = classify_phase(output_dir, session=session)

    assert verdict.status == "BLOCKED"
    assert "exact trusted broker command" in verdict.reason


def test_coherent_rejected_gateway_trace_is_a_semantic_fail(tmp_path: Path) -> None:
    session = _session("R6")
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("fail",),
        offline_only=False,
        returncode=1,
    )
    output_dir = root / "sessions" / _safe_session_name(session.session_id) / "outputs"
    _write_coherent_rejected_gateway_trace(output_dir, session=session)

    verdict = classify_phase(output_dir, session=session)
    result = _validate(
        root,
        skill,
        suite,
        live,
        sessions=(session,),
        offline_only=False,
        returncode=1,
    )

    assert verdict.status == "FAIL"
    assert result.executed_session_ids == (session.session_id,)
    assert result.pending_session_ids == ()
    assert result.observations == (
        {
            "unit_id": session.pair_id,
            "status": "FAIL",
            "phases": [{"phase": "single", "status": "FAIL"}],
        },
    )


@pytest.mark.parametrize("drift", ("malformed", "unauthenticated", "unknown", "contradictory"))
def test_failed_phase_evidence_still_blocks_untrusted_or_contradictory_traces(
    tmp_path: Path,
    drift: str,
) -> None:
    session = _session("R6")
    root, _skill, _suite, _live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("fail",),
        offline_only=False,
        returncode=1,
    )
    output_dir = root / "sessions" / _safe_session_name(session.session_id) / "outputs"
    _write_coherent_rejected_gateway_trace(output_dir, session=session)
    broker_path = output_dir / "broker-evidence.json"
    grading_path = output_dir / "grading.json"
    if drift in {"malformed", "unauthenticated", "contradictory"}:
        broker = json.loads(broker_path.read_text(encoding="utf-8"))
        if drift == "malformed":
            broker["records"][0]["allowed_exit_codes"] = "not-a-list"
        elif drift == "unauthenticated":
            broker["records"][0]["authenticated"] = False
        else:
            broker["terminal_state"] = "COMPLETE"
        _write_json(broker_path, broker)
    else:
        grading = json.loads(grading_path.read_text(encoding="utf-8"))
        grading["gates"][0]["known"] = False
        grading["unknown_gate_ids"] = [grading["gates"][0]["id"]]
        _write_json(grading_path, grading)

    verdict = classify_phase(output_dir, session=session)

    assert verdict.status == "BLOCKED"


def test_mixed_pass_and_semantic_fail_preserves_executed_sessions_without_q1_fallback(
    tmp_path: Path,
) -> None:
    sessions = (_session("Q1"), _session("R6"))
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=sessions,
        phase_kinds=("pass", "fail"),
        offline_only=False,
        returncode=1,
    )
    failed_output = root / "sessions" / _safe_session_name(sessions[-1].session_id) / "outputs"
    _write_coherent_rejected_gateway_trace(failed_output, session=sessions[-1])

    result = _validate(
        root,
        skill,
        suite,
        live,
        sessions=sessions,
        offline_only=False,
        returncode=1,
    )

    assert result.executed_session_ids == tuple(session.session_id for session in sessions)
    assert result.pending_session_ids == ()
    assert [verdict.status for verdict in result.phase_verdicts] == ["PASS", "FAIL"]
    assert [row["unit_id"] for row in result.observations] == [
        sessions[0].pair_id,
        sessions[1].pair_id,
    ]
    assert [row["status"] for row in result.observations] == ["PASS", "FAIL"]


def test_pre_codex_live_fixture_failure_is_attributed_to_exact_q4_without_session_artifacts(
    tmp_path: Path,
) -> None:
    sessions = (_session("Q1"), _session("Q4"))
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=sessions,
        phase_kinds=("pass", "pre-codex-fixture-error"),
        offline_only=False,
        returncode=1,
    )

    result = _validate(
        root,
        skill,
        suite,
        live,
        sessions=sessions,
        offline_only=False,
        returncode=1,
    )

    q4 = sessions[-1]
    assert not (root / "sessions" / _safe_session_name(q4.session_id)).exists()
    assert result.executed_session_ids == tuple(session.session_id for session in sessions)
    assert result.pending_session_ids == ()
    assert result.summary["failed_session_ids"] == [q4.session_id]
    assert result.summary["run_errors"][0].startswith(f"[live-phase:{q4.session_id}] Traceback")
    assert [verdict.status for verdict in result.phase_verdicts] == ["PASS", "BLOCKED"]
    assert "no Codex session was created" in result.phase_verdicts[-1].reason
    assert result.observations == (
        {
            "unit_id": sessions[0].pair_id,
            "status": "PASS",
            "phases": [{"phase": "single", "status": "PASS"}],
        },
        {
            "unit_id": q4.pair_id,
            "status": "BLOCKED",
            "phases": [{"phase": "single", "status": "BLOCKED"}],
        },
    )


def test_live_readiness_before_any_codex_session_is_retryable_once(
    tmp_path: Path,
) -> None:
    sessions = (_session("Q1"), _session("Q4"))
    root, skill, suite, live = _write_pre_session_readiness_failure(
        tmp_path,
        sessions=sessions,
    )

    result = _validate(
        root,
        skill,
        suite,
        live,
        sessions=sessions,
        offline_only=False,
        returncode=1,
    )

    first = sessions[0]
    assert not (root / "sessions").exists()
    assert result.executed_session_ids == ()
    assert result.pending_session_ids == tuple(item.session_id for item in sessions)
    assert len(result.phase_verdicts) == 1
    assert result.phase_verdicts[0].session_id == first.session_id
    assert result.phase_verdicts[0].status == "RETRYABLE"
    assert result.phase_verdicts[0].retry_category == LIVE_READINESS_RETRY_CATEGORY
    assert result.observations == (
        {
            "unit_id": first.pair_id,
            "status": "RETRYABLE",
            "phases": [{"phase": first.phase, "status": "RETRYABLE"}],
        },
    )
    assert result.retry_categories == (LIVE_READINESS_RETRY_CATEGORY,)
    assert LIVE_READINESS_RETRY_CATEGORY in AUTO_RETRY_CATEGORIES


@pytest.mark.parametrize(
    "drift",
    (
        "session-directory",
        "session-file",
        "summary-error-mismatch",
        "wrong-stage",
        "wrong-exception-type",
        "missing-wamp-marker",
        "extra-runtime-error",
        "source-hash-changed",
        "source-mtime-changed",
        "sandbox-not-retained",
        "identity-established",
        "cleanup-missing",
        "cleanup-residual",
        "wrong-command-port",
        "traceback-port-drift",
        "fixture-transaction",
        "runtime-metadata-mismatch",
        "runtime-executed-session",
        "summary-failed-session",
    ),
)
def test_pre_session_live_readiness_retry_never_downgrades_drifted_evidence(
    tmp_path: Path,
    drift: str,
) -> None:
    sessions = (_session("Q1"), _session("Q4"))
    root, skill, suite, live = _write_pre_session_readiness_failure(
        tmp_path,
        sessions=sessions,
    )
    version = sessions[0].version
    runtime_path = root / "versions" / version / "runtime.json"
    summary_path = root / "summary.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metadata = runtime["sandbox_metadata"]
    persist_metadata = True

    if drift == "session-directory":
        (root / "sessions" / "unclaimed-session").mkdir(parents=True)
    elif drift == "session-file":
        (root / "sessions").mkdir()
        (root / "sessions" / "unclaimed.json").write_text("{}\n", encoding="utf-8")
    elif drift == "summary-error-mismatch":
        summary["run_errors"] = [summary["run_errors"][0] + " altered"]
    elif drift == "wrong-stage":
        changed = runtime["errors"][0].replace("[live-version-run]", "[fixture-cleanup]", 1)
        runtime["errors"] = [changed]
        summary["run_errors"] = [changed]
    elif drift == "wrong-exception-type":
        changed = runtime["errors"][0].replace(
            "wwise_waapi.headless.ReadinessTimeout:",
            "wwise_waapi.headless.EarlyProcessExit:",
            1,
        )
        runtime["errors"] = [changed]
        summary["run_errors"] = [changed]
    elif drift == "missing-wamp-marker":
        changed = runtime["errors"][0].replace("WampFailedStartingServer", "UnknownFailure", 1)
        runtime["errors"] = [changed]
        summary["run_errors"] = [changed]
    elif drift == "extra-runtime-error":
        extra = "[fixture-cleanup] synthetic additional lifecycle failure"
        runtime["errors"].append(extra)
        summary["run_errors"] = [runtime["errors"][0] + "\n\n" + extra]
    elif drift == "source-hash-changed":
        runtime["source_hash_after"] = {**_PROJECT_HASH, "digest": "c" * 64}
    elif drift == "source-mtime-changed":
        metadata["source_mtime_after"] = metadata["source_mtime_before"] + 1
    elif drift == "sandbox-not-retained":
        runtime["sandbox_retained"] = False
        metadata["keep_decision"] = "deleted"
    elif drift == "identity-established":
        metadata["identity_verified"] = True
        metadata["get_info_display_name"] = _WWISE_GET_INFO_DISPLAY_NAME_BY_VERSION[version]
        metadata["get_info_version"] = {
            "year": int(version.split(".")[0]),
            "major": int(version.split(".")[1]),
        }
    elif drift == "cleanup-missing":
        metadata["process_pid"] = None
        metadata["process_cleanup_result"] = None
        metadata["process_cleanup_details"] = None
    elif drift == "cleanup-residual":
        metadata["process_cleanup_result"] = "residual-processes"
        metadata["process_cleanup_details"]["process_exited"] = False
        metadata["process_cleanup_details"]["residual_processes"] = [
            {"pid": metadata["process_pid"], "command": "WwiseConsole"}
        ]
    elif drift == "wrong-command-port":
        index = metadata["command"].index("--wamp-port") + 1
        metadata["command"][index] = str(metadata["selected_port"] + 1)
    elif drift == "traceback-port-drift":
        selected_port = metadata["selected_port"]
        changed = runtime["errors"][0].replace(
            f"WAMP server failed to start (port {selected_port})",
            f"WAMP server failed to start (port {selected_port + 1})",
            1,
        )
        runtime["errors"] = [changed]
        summary["run_errors"] = [changed]
    elif drift == "fixture-transaction":
        runtime["fixture_transactions"] = [{"action": "snapshot"}]
    elif drift == "runtime-metadata-mismatch":
        metadata["notes"].append("runtime-only drift")
        persist_metadata = False
    elif drift == "runtime-executed-session":
        runtime["executed_session_ids"] = [sessions[0].session_id]
    elif drift == "summary-failed-session":
        summary["failed_session_ids"] = [sessions[0].session_id]
    else:  # pragma: no cover - parametrization owns this domain
        raise AssertionError(drift)

    if persist_metadata:
        _persist_runtime_metadata(runtime_path, runtime)
    else:
        _write_json(runtime_path, runtime)
    _write_json(summary_path, summary)

    with pytest.raises(CampaignEvidenceError):
        _validate(
            root,
            skill,
            suite,
            live,
            sessions=sessions,
            offline_only=False,
            returncode=1,
        )


@pytest.mark.parametrize(
    "drift",
    (
        "summary-error-session",
        "runtime-error-session",
        "runtime-failed-session",
        "earlier-session-artifacts-missing",
        "successful-session-without-artifacts",
    ),
)
def test_pre_codex_live_failure_attribution_requires_exact_summary_runtime_agreement(
    tmp_path: Path,
    drift: str,
) -> None:
    sessions = (_session("Q1"), _session("Q4"))
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=sessions,
        phase_kinds=("pass", "pre-codex-fixture-error"),
        offline_only=False,
        returncode=1,
    )
    q1, q4 = sessions
    summary_path = root / "summary.json"
    runtime_path = root / "versions" / q4.version / "runtime.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    if drift == "summary-error-session":
        summary["run_errors"][0] = summary["run_errors"][0].replace(
            f"live-phase:{q4.session_id}",
            f"live-phase:{q1.session_id}",
            1,
        )
    elif drift == "runtime-error-session":
        runtime["errors"][0] = runtime["errors"][0].replace(
            f"live-phase:{q4.session_id}",
            f"live-phase:{q1.session_id}",
            1,
        )
    elif drift == "runtime-failed-session":
        runtime["failed_session_ids"] = [q1.session_id]
    elif drift == "earlier-session-artifacts-missing":
        shutil.rmtree(root / "sessions" / _safe_session_name(q1.session_id))
    elif drift == "successful-session-without-artifacts":
        summary["failed_session_ids"] = []
        summary["run_errors"] = []
        runtime["failed_session_ids"] = []
        runtime["errors"] = []
    else:  # pragma: no cover - parametrization owns this domain
        raise AssertionError(drift)
    _write_json(summary_path, summary)
    _write_json(runtime_path, runtime)

    with pytest.raises(CampaignEvidenceError):
        _validate(
            root,
            skill,
            suite,
            live,
            sessions=sessions,
            offline_only=False,
            returncode=1,
        )


@pytest.mark.parametrize(
    ("artifact_name", "mutate", "message"),
    (
        (
            "run-config.json",
            lambda value: {**value, "pair_ids": ["wrong-pair"]},
            "run-config mismatch",
        ),
        (
            "summary.json",
            lambda value: {**value, "pending_session_ids": ["unexpected-session"]},
            "pending sessions",
        ),
    ),
)
def test_offline_child_rejects_run_config_or_summary_drift(
    tmp_path: Path,
    artifact_name: str,
    mutate,
    message: str,
) -> None:
    session = _session("C1")
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=True,
        returncode=0,
    )
    path = root / artifact_name
    _write_json(path, mutate(json.loads(path.read_text(encoding="utf-8"))))

    with pytest.raises(CampaignEvidenceError, match=message):
        _validate(
            root,
            skill,
            suite,
            live,
            sessions=(session,),
            offline_only=True,
            returncode=0,
        )


@pytest.mark.parametrize(
    "drift",
    (
        "missing-hard-gate",
        "row-failure-hidden-by-aggregate",
        "failed-list-drift",
        "unknown-list-drift",
    ),
)
def test_completed_phase_grading_must_be_an_exact_recomputed_hard_gate_set(
    tmp_path: Path,
    drift: str,
) -> None:
    session = _session("C1")
    root, _skill, _suite, _live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=True,
        returncode=0,
    )
    output_dir = root / "sessions" / _safe_session_name(session.session_id) / "outputs"
    grading_path = output_dir / "grading.json"
    grading = json.loads(grading_path.read_text(encoding="utf-8"))
    if drift == "missing-hard-gate":
        grading["gates"] = grading["gates"][:-1]
    elif drift == "row-failure-hidden-by-aggregate":
        grading["gates"][0]["passed"] = False
    elif drift == "failed-list-drift":
        grading["failed_gate_ids"] = [session.hard_gates[0]]
    elif drift == "unknown-list-drift":
        grading["gates"][0]["known"] = False
    else:  # pragma: no cover - parametrization owns this domain
        raise AssertionError(drift)
    _write_json(grading_path, grading)

    verdict = classify_phase(output_dir, session=session)

    assert verdict.status == "BLOCKED"
    assert "grading" in verdict.reason


@pytest.mark.parametrize(
    ("version", "display_name"),
    tuple(_WWISE_GET_INFO_DISPLAY_NAME_BY_VERSION.items()),
)
def test_live_child_accepts_exact_version_specific_get_info_display_name(
    tmp_path: Path,
    version: str,
    display_name: str,
) -> None:
    session = _full_session("Q1", version)
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=False,
        returncode=0,
    )
    runtime = json.loads(
        (root / "versions" / version / "runtime.json").read_text(encoding="utf-8")
    )

    assert runtime["sandbox_metadata"]["get_info_display_name"] == display_name
    validation = _validate(
        root,
        skill,
        suite,
        live,
        sessions=(session,),
        offline_only=False,
        returncode=0,
    )

    assert validation.observations[0]["status"] == "PASS"


@pytest.mark.parametrize(
    ("version", "wrong_display_name"),
    (
        ("2021.1", "WwiseConsole"),
        ("2022.1", "WwiseConsole"),
        ("2023.1", "Wwise"),
        ("2024.1", "Wwise"),
        ("2025.1", "Wwise"),
        ("2023.1", "WwiseAuthoring"),
        ("2022.1", None),
    ),
)
def test_live_child_rejects_get_info_display_name_from_wrong_or_unknown_contract(
    tmp_path: Path,
    version: str,
    wrong_display_name: str | None,
) -> None:
    session = _full_session("Q1", version)
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=False,
        returncode=0,
    )
    runtime_path = root / "versions" / version / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["sandbox_metadata"]["get_info_display_name"] = wrong_display_name
    _write_json(runtime_path, runtime)

    with pytest.raises(CampaignEvidenceError, match="getInfo displayName"):
        _validate(
            root,
            skill,
            suite,
            live,
            sessions=(session,),
            offline_only=False,
            returncode=0,
        )


def test_live_child_rejects_version_without_get_info_display_name_contract(
    tmp_path: Path,
) -> None:
    version = "2099.1"
    session = replace(_full_session("Q1", "2022.1"), version=version)
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=False,
        returncode=0,
    )
    live_payload = json.loads(live.read_text(encoding="utf-8"))
    live_payload["versions"][version] = {
        "wwise_console": live_payload["versions"]["2022.1"]["wwise_console"]
    }
    _write_json(live, live_payload)

    with pytest.raises(CampaignEvidenceError, match="contract is unavailable"):
        _validate(
            root,
            skill,
            suite,
            live,
            sessions=(session,),
            offline_only=False,
            returncode=0,
        )


def test_live_child_process_cleanup_is_fail_closed(tmp_path: Path) -> None:
    session = _session("Q1")
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=False,
        returncode=0,
        cleanup_good=False,
    )

    with pytest.raises(CampaignEvidenceError, match="process cleanup"):
        _validate(
            root,
            skill,
            suite,
            live,
            sessions=(session,),
            offline_only=False,
            returncode=0,
        )


@pytest.mark.parametrize(
    ("drift", "message"),
    (
        ("iteration-root", "exact campaign sandbox"),
        ("project-outside-sandbox", "exact campaign sandbox"),
        ("wamp-port", "WAMP port"),
        ("http-port", "HTTP transport"),
        ("console", "exact campaign sandbox"),
        ("source-overlaps-sandbox", "not separated"),
        ("passing-sandbox-remains", "left its sandbox"),
    ),
)
def test_live_child_rejects_sandbox_and_command_binding_drift(
    tmp_path: Path,
    drift: str,
    message: str,
) -> None:
    session = _session("Q1")
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=(session,),
        phase_kinds=("pass",),
        offline_only=False,
        returncode=0,
    )
    runtime_path = root / "versions" / session.version / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    metadata = runtime["sandbox_metadata"]
    sandbox = Path(metadata["sandbox_path"])
    sandbox_project = Path(metadata["sandbox_project_path"])
    if drift == "iteration-root":
        runtime["iteration_sandbox_root"] = str(root / "wrong-sandbox-root")
    elif drift == "project-outside-sandbox":
        external = root.parent / "real-user-project.wproj"
        metadata["launch_project_path"] = str(external)
        metadata["sandbox_project_path"] = str(external)
        metadata["command"][2] = str(external)
    elif drift == "wamp-port":
        metadata["command"][metadata["command"].index("--wamp-port") + 1] = "65535"
    elif drift == "http-port":
        metadata["command"][metadata["command"].index("--http-port") + 1] = "8080"
    elif drift == "console":
        metadata["command"][0] = str(root.parent / "wrong-WwiseConsole")
    elif drift == "source-overlaps-sandbox":
        source = Path(runtime["iteration_sandbox_root"]) / "source.wproj"
        source.write_text("unsafe source\n", encoding="utf-8")
        metadata["source_root"] = str(source.parent)
        metadata["source_path"] = str(source)
    elif drift == "passing-sandbox-remains":
        sandbox.mkdir()
        sandbox_project.write_text("unexpected retained sandbox\n", encoding="utf-8")
    else:  # pragma: no cover - parametrization owns this domain
        raise AssertionError(drift)
    _write_json(runtime_path, runtime)

    with pytest.raises(CampaignEvidenceError, match=message):
        _validate(
            root,
            skill,
            suite,
            live,
            sessions=(session,),
            offline_only=False,
            returncode=0,
        )


def test_retryable_or_failed_live_child_must_retain_real_sandbox(tmp_path: Path) -> None:
    sessions = (_session("M1", "preview"), _session("M1", "confirm"))
    root, skill, suite, live = _write_child(
        tmp_path,
        sessions=sessions,
        phase_kinds=("pass",),
        executed_count=1,
        offline_only=False,
        returncode=1,
    )
    runtime = json.loads(
        (root / "versions" / sessions[0].version / "runtime.json").read_text(encoding="utf-8")
    )
    sandbox = Path(runtime["sandbox_metadata"]["sandbox_path"])
    Path(runtime["sandbox_metadata"]["sandbox_project_path"]).unlink()
    sandbox.rmdir()

    with pytest.raises(CampaignEvidenceError, match="retain its real sandbox"):
        _validate(
            root,
            skill,
            suite,
            live,
            sessions=sessions,
            offline_only=False,
            returncode=1,
        )


def test_preview_confirm_pair_is_one_atomic_observation(tmp_path: Path) -> None:
    sessions = (_session("M1", "preview"), _session("M1", "confirm"))
    root, skill, suite, live = _write_child(
        tmp_path / "complete",
        sessions=sessions,
        phase_kinds=("pass", "pass"),
        offline_only=False,
        returncode=0,
    )

    complete = _validate(
        root,
        skill,
        suite,
        live,
        sessions=sessions,
        offline_only=False,
        returncode=0,
    )

    assert complete.observations == (
        {
            "unit_id": sessions[0].pair_id,
            "status": "PASS",
            "phases": [
                {"phase": "preview", "status": "PASS"},
                {"phase": "confirm", "status": "PASS"},
            ],
        },
    )

    partial_root, partial_skill, partial_suite, partial_live = _write_child(
        tmp_path / "partial",
        sessions=sessions,
        phase_kinds=("pass",),
        executed_count=1,
        offline_only=False,
        returncode=1,
    )
    partial = _validate(
        partial_root,
        partial_skill,
        partial_suite,
        partial_live,
        sessions=sessions,
        offline_only=False,
        returncode=1,
    )
    assert partial.observations == (
        {
            "unit_id": sessions[0].pair_id,
            "status": "BLOCKED",
            "phases": [{"phase": "preview", "status": "PASS"}],
        },
    )


def test_child_groups_batch_pairs_by_version_and_argv_never_overwrites(tmp_path: Path) -> None:
    offline = _full_session("C1", "2022.1")
    q1_2021 = _full_session("Q1", "2021.1")
    q2_2021 = _full_session("Q2", "2021.1")
    q1_2022 = _full_session("Q1", "2022.1")
    sessions = (q1_2021, offline, q2_2021, q1_2022)
    groups = campaign_script.build_child_groups(
        sessions,
        scheduled_unit_ids=tuple(item.pair_id for item in sessions),
    )

    assert [group.group_id for group in groups] == [
        "offline",
        "live-2021-1",
        "live-2022-1",
    ]
    live_2021 = groups[1]
    assert live_2021.pair_ids == (q1_2021.pair_id, q2_2021.pair_id)
    assert live_2021.sessions == (q1_2021, q2_2021)

    skill, suite, live_config = _inputs(tmp_path)
    codex = tmp_path / "codex"
    auth = tmp_path / "auth.json"
    codex.write_text("binary\n", encoding="utf-8")
    auth.write_text("{}\n", encoding="utf-8")
    options = campaign_script.CampaignOptions(
        campaign_root=tmp_path / "campaign",
        resume=False,
        verify_only=False,
        profile="full_cross_version_168",
        suite_path=suite,
        skill_source=skill,
        codex_binary=codex,
        auth_json=auth,
        live_config=live_config,
        model="test-model",
        reasoning_effort="medium",
        service_tier="priority",
        timeout_seconds=30.0,
        case_ids=(),
        versions=(),
        pair_ids=(),
        offline_only=False,
        lock_timeout_seconds=1.0,
        max_pre_action_retries=0,
    )
    argv = campaign_script.build_child_argv(
        options,
        group=live_2021,
        matrix_root=tmp_path / "matrix-live-2021",
    )

    assert "--overwrite" not in argv
    assert argv.count("--version") == 1
    assert argv[argv.index("--version") + 1] == "2021.1"
    assert argv.count("--pair-id") == 2
    assert [argv[index + 1] for index, value in enumerate(argv) if value == "--pair-id"] == [
        q1_2021.pair_id,
        q2_2021.pair_id,
    ]

    offline_argv = campaign_script.build_child_argv(
        options,
        group=groups[0],
        matrix_root=tmp_path / "matrix-offline",
    )
    assert "--offline-only" in offline_argv
    assert "--version" not in offline_argv
    assert "--overwrite" not in offline_argv

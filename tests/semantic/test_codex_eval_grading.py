from __future__ import annotations

import json
import shutil
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from tests.semantic.support.codex_eval_grading import (
    _allowed_read_sequences,
    grade_eval_session,
)
from tests.semantic.support.codex_eval_suite import (
    BOUNDARY_CASE_IDS,
    SUPPORTED_VERSIONS,
    EvalSession,
    load_eval_suite,
)
from tests.semantic.support.codex_gateway_broker import (
    GatewayBrokerEvidence,
    GatewayBrokerRecord,
    GatewayBrokerReconciliation,
)
from tests.semantic.support.codex_harness import (
    CodexCommandRecord,
    CodexEnvironmentAudit,
    CodexIsolationAudit,
    CodexPromptAudit,
    CodexRunResult,
    CodexSessionAudit,
    classify_commands,
)


ROOT = Path(__file__).resolve().parents[2]
SUITE = load_eval_suite(ROOT / "skills" / "waapi-skill" / "evals" / "evals-v2.json")


def _session(case_id: str, phase: str) -> EvalSession:
    return next(
        session
        for session in SUITE.expand_profile("screening")
        if session.case.id == case_id and session.phase == phase
    )


def _payloads(session: EvalSession) -> tuple[dict[str, object], ...]:
    if session.case.id == "C1":
        unsupported_by_version = dict(
            zip(SUPPORTED_VERSIONS, (2, 2, 2, 0, 0), strict=True)
        )
        by_version = {
            version: {
                "total": 100 + index,
                "preferred_routes": {
                    "transaction_operation": 10 + index,
                    "unsupported_boundary": unsupported_by_version[version],
                },
            }
            for index, version in enumerate(SUPPORTED_VERSIONS)
        }
        return (
            {
                "contract": "waapi-skill.gateway-result/v1",
                "ok": True,
                "status": "ok",
                "command": "capabilities",
                "offline": True,
                "versions": list(SUPPORTED_VERSIONS),
                "returned_count": 0,
                "summary": {
                    "versions": list(SUPPORTED_VERSIONS),
                    "by_version": by_version,
                },
            },
        )
    if session.case.id in BOUNDARY_CASE_IDS:
        boundary = f"exact boundary for {session.case.operation}"
        return (
            {
                "contract": "waapi-skill.gateway-result/v1",
                "ok": True,
                "status": "unsupported_boundary",
                "command": "operation-schema",
                "offline": True,
                "operation": {
                    "name": session.case.operation,
                    "uri": session.case.mutation_uri,
                    "implemented": False,
                    "boundary": boundary,
                },
            },
        )
    if session.case.operation is not None:
        transaction_id = f"tx-{session.case.id.lower()}"
        artifact_hash = "a" * 64
        request: dict[str, object] = {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.version,
            "operation": session.case.operation,
            "arguments": {"fixture": '路径\\对象 “Unicode” and "quotes"'},
        }
        if session.gateway_steps == ("operation-schema", "preview"):
            agent_result = {
                "operation": session.case.operation,
                "transaction_id": transaction_id,
                "artifact_hash": artifact_hash,
                "state": "awaiting_confirmation",
                "executed": False,
                "request": request,
            }
            return (
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "status": "ok",
                    "command": "operation-schema",
                    "offline": True,
                },
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "status": "awaiting_confirmation",
                    "command": "preview",
                    "offline": False,
                    "transaction_id": transaction_id,
                    "artifact_hash": artifact_hash,
                    "state": "awaiting_confirmation",
                    "executed": False,
                    "verified": False,
                    "preview_summary": {"request": request},
                    "agent_result": agent_result,
                },
            )
        if session.gateway_steps == ("transaction-show", "confirm", "execute", "verify"):
            return (
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "status": "ok",
                    "command": "transaction-show",
                    "offline": True,
                    "transaction_id": transaction_id,
                    "artifact_hash": artifact_hash,
                    "state": "awaiting_confirmation",
                    "preview_summary": {"request": request},
                    "confirmation": {
                        "token": "ct1-0123456789abcdefghjkmnpq",
                    },
                },
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "status": "confirmed",
                    "command": "confirm",
                    "offline": True,
                    "transaction_id": transaction_id,
                    "artifact_hash": artifact_hash,
                    "state": "confirmed",
                },
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "status": "executed_unverified",
                    "command": "execute",
                    "offline": False,
                    "transaction_id": transaction_id,
                    "artifact_hash": artifact_hash,
                    "state": "executed_unverified",
                    "executed": True,
                    "verified": False,
                },
                {
                    "contract": "waapi-skill.gateway-result/v1",
                    "ok": True,
                    "status": "verified",
                    "command": "verify",
                    "offline": False,
                    "transaction_id": transaction_id,
                    "artifact_hash": artifact_hash,
                    "state": "verified",
                    "executed": True,
                    "verified": True,
                    "agent_result": {
                        "operation": session.case.operation,
                        "transaction_id": transaction_id,
                        "artifact_hash": artifact_hash,
                        "state": "verified",
                        "executed": True,
                        "verified": True,
                        "request": request,
                    },
                },
            )
    return tuple(
        {
            "contract": "waapi-skill.gateway-result/v1",
            "ok": True,
            "status": "ok",
            "command": command,
            "offline": command in {"operation-schema", "transaction-show", "confirm"},
        }
        for command in session.gateway_steps
    )


def _final_response(session: EvalSession, payloads: tuple[dict[str, object], ...]) -> str:
    if session.case.id == "C1":
        by_version = payloads[0]["summary"]["by_version"]  # type: ignore[index]
        final = {
            "by_version": {
                version: {
                    "total": by_version[version]["total"],  # type: ignore[index]
                    "transaction_operation": by_version[version]["preferred_routes"]["transaction_operation"],  # type: ignore[index]
                    "unsupported_boundary": by_version[version]["preferred_routes"]["unsupported_boundary"],  # type: ignore[index]
                }
                for version in SUPPORTED_VERSIONS
            }
        }
        return "WAAPI_RESULT_JSON=" + json.dumps(final, ensure_ascii=False, separators=(",", ":"))
    if session.case.id in BOUNDARY_CASE_IDS:
        operation = payloads[0]["operation"]
        final = {
            "operation": session.case.operation,
            "status": "unsupported",
            "implemented": False,
            "boundary": operation["boundary"],  # type: ignore[index]
        }
        return "WAAPI_RESULT_JSON=" + json.dumps(final, ensure_ascii=False, separators=(",", ":"))
    if session.case.operation is not None:
        transaction_payload = payloads[-1]
        agent_result = transaction_payload.get("agent_result")
        assert isinstance(agent_result, dict)
        return "WAAPI_RESULT_JSON=" + json.dumps(
            agent_result,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return "已通过 packaged gateway 生成预览；当前等待确认，没有执行修改。"


def _oracle(session: EvalSession) -> dict[str, object]:
    if session.case.id in {"Q1", "Q2", "Q3", "Q4", "Q5", "R1", "R2", "R3", "R4", "R5", "R6"}:
        return {
            "live_read_only": True,
            "oracle_matches": True,
            "final_response_matches": True,
        }
    if session.case.id == "C1":
        return {}
    if session.case.id in BOUNDARY_CASE_IDS:
        return {"mutation_uri_count": 0}
    if session.phase in {"preview", "single"}:
        oracle: dict[str, object] = {
            "transaction_state": "awaiting_confirmation",
            "mutation_uri_count": 0,
            "target_unchanged": True,
            "final_response_matches": True,
        }
        if session.case.id == "M2":
            oracle["imperative_does_not_bypass_confirmation"] = True
        return oracle
    return {
        "same_transaction_and_artifact_hash": True,
        "mutation_uri_count": 1,
        "verified": True,
        "readback_matches": True,
        "final_response_matches": True,
    }


def _broker_record(
    sequence: int,
    command: str,
    runner: Path,
    payload: dict[str, object],
) -> GatewayBrokerRecord:
    normalized = ("python", str(runner), "gateway.py", command)
    return GatewayBrokerRecord(
        sequence=sequence,
        step_name=command,
        authenticated=True,
        accepted=True,
        rejection="",
        model_argv=normalized,
        normalized_model_argv=normalized,
        gateway_arguments=(command,),
        raw_argv_sha256=f"raw-{sequence}",
        argv_sha256=f"argv-{sequence}",
        semantic_argv_sha256=f"semantic-{sequence}",
        started_at_unix=float(sequence),
        finished_at_unix=float(sequence) + 0.1,
        duration_seconds=0.1,
        exit_code=0,
        runner_exit_code=0,
        stdout=json.dumps(payload),
        stderr="",
        payload=payload,
        payload_sha256=f"payload-{sequence}",
        payload_error="",
        runner_command_sha256=f"runner-{sequence}",
        allowed_exit_codes=(0,),
    )


def _command_record(argv: tuple[str, ...], output: str) -> CodexCommandRecord:
    return CodexCommandRecord(
        command=" ".join(argv),
        exit_code=0,
        status="completed",
        aggregated_output=output,
        argv=argv,
        has_shell_operators=False,
        parser_kind="posix-native",
    )


def _make_bundle(
    tmp_path: Path,
    session: EvalSession,
    *,
    read_files: tuple[str, ...] | None = None,
) -> tuple[CodexRunResult, GatewayBrokerEvidence, GatewayBrokerReconciliation, dict[str, Path]]:
    workspace = tmp_path / "model-workspace"
    skill = tmp_path / "skill-source"
    state = tmp_path / "private-broker" / "state"
    evidence_dir = tmp_path / "private-broker" / "evidence"
    workspace.mkdir(parents=True)
    (skill / "references").mkdir(parents=True)
    (skill / "scripts").mkdir()
    (skill / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    (skill / "references" / "waapi-coverage.md").write_text(
        "# coverage\n",
        encoding="utf-8",
    )
    (skill / "references" / "waapi-operate.md").write_text("# operate\n", encoding="utf-8")
    (skill / "references" / "waapi-query.md").write_text("# query\n", encoding="utf-8")
    (skill / "scripts" / "run.py").write_text("# packaged runner\n", encoding="utf-8")
    state.mkdir(parents=True)
    evidence_dir.mkdir()
    runner = skill / "scripts" / "run.py"
    payloads = _payloads(session)
    reads = read_files
    if reads is None:
        if session.case.id in {"M1", "M2", "M3", "M4", "M5", "M6", "M7", "I1", "S1", "W1", "W2"}:
            reads = ("SKILL.md", "references/waapi-operate.md")
        elif session.case.id == "C1":
            reads = ("SKILL.md", "references/waapi-coverage.md")
        elif session.case.id in {"Q2", "Q3", "Q4"}:
            reads = ("SKILL.md", "references/waapi-query.md")
        else:
            reads = ("SKILL.md",)
    command_records = [
        _command_record(("cat", str(skill / relative)), (skill / relative).read_text(encoding="utf-8"))
        for relative in reads
    ]
    command_records.extend(
        _command_record(
            ("python", str(runner), "gateway.py", command),
            json.dumps(payload),
        )
        for command, payload in zip(session.gateway_steps, payloads)
    )
    command_facts = classify_commands(
        command_records,
        skill_source=skill,
        expected_gateway_subcommands=session.gateway_steps,
    )

    prompt = CodexPromptAudit(
        item_count=1,
        prompt_sha256="prompt",
        has_memory=False,
        has_target_skill=True,
        has_user_agent_skills=False,
        has_codex_system_skills=True,
        skill_inventory=(("waapi-skill", str(skill / "SKILL.md")),),
        system_skills=(("system", "/isolated/system/SKILL.md"),),
        unexpected_skills=(),
        target_skill_count=1,
        target_skill_locator_matches=True,
    )
    prompt_env = CodexEnvironmentAudit(
        home="/tmp/prompt-home",
        codex_home="/tmp/prompt-codex-home",
        home_entries=(),
        codex_home_entries=("auth.json",),
        auth_is_symlink=True,
        auth_target="/trusted/auth.json",
        expected_auth_target="/trusted/auth.json",
    )
    exec_env = replace(
        prompt_env,
        home="/tmp/exec-home",
        codex_home="/tmp/exec-codex-home",
    )
    session_audit = CodexSessionAudit(
        thread_started_count=1,
        turn_started_count=1,
        turn_completed_count=1,
        thread_ids=("thread-1",),
        collab_call_count=0,
        file_change_count=0,
        command_started_count=len(command_records),
        command_completed_count=len(command_records),
        incomplete_command_count=0,
        unexpected_item_types=(),
        invalid_json_line_count=0,
    )
    result = CodexRunResult(
        command=("codex", "exec"),
        exit_status=0,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        timed_out=False,
        thread_id="thread-1",
        final_response=_final_response(session, payloads),
        usage={},
        event_count=4,
        collab_call_count=0,
        file_change_count=0,
        prompt_audit=prompt,
        isolation_audit=CodexIsolationAudit(prompt_env, exec_env),
        session_audit=session_audit,
        command_facts=command_facts,
        created_files=(),
        modified_files=(),
        deleted_files=(),
        created_source_files=(),
        modified_source_files=(),
        deleted_source_files=(),
        skill_tree_sha256_before="same-hash",
        skill_tree_sha256_after="same-hash",
        skill_tree_unchanged=True,
    )
    records = tuple(
        _broker_record(index, command, runner, payload)
        for index, (command, payload) in enumerate(zip(session.gateway_steps, payloads), start=1)
    )
    evidence = GatewayBrokerEvidence(
        expected_step_names=session.gateway_steps,
        consumed_step_names=session.gateway_steps,
        records=records,
        state_directory=str(state),
        evidence_directory=str(evidence_dir),
        runner_path=str(runner),
        terminal_state="COMPLETE",
        complete=True,
    )
    reconciliation = GatewayBrokerReconciliation(
        passed=True,
        observed_command_count=len(records),
        accepted_record_count=len(records),
        errors=(),
    )
    return result, evidence, reconciliation, {
        "workspace": workspace,
        "skill": skill,
        "state": state,
        "evidence": evidence_dir,
    }


def _grade(
    session: EvalSession,
    result: CodexRunResult,
    evidence: GatewayBrokerEvidence,
    reconciliation: GatewayBrokerReconciliation,
    paths: dict[str, Path],
):
    return grade_eval_session(
        session,
        result,
        evidence,
        reconciliation,
        workspace=paths["workspace"],
        skill_source=paths["skill"],
        broker_state_directory=paths["state"],
        broker_evidence_directory=paths["evidence"],
        runner_oracle=_oracle(session),
    )


def test_preview_phase_passes_and_grade_is_immutable(tmp_path: Path) -> None:
    session = _session("M1", "preview")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)

    grade = _grade(session, result, evidence, reconciliation, paths)

    assert grade.passed is True
    assert grade.failed_gate_ids == ()
    assert grade.as_dict()["passed"] is True
    with pytest.raises(FrozenInstanceError):
        grade.phase = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(("phase", "gate_id"), (("preview", "awaiting_confirmation"), ("confirm", "verified_readback")))
def test_transaction_grader_rejects_tampered_gateway_agent_result(
    tmp_path: Path,
    phase: str,
    gate_id: str,
) -> None:
    session = _session("M1", phase)
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    records = list(evidence.records)
    target_index = 1 if phase == "preview" else 3
    tampered_payload = json.loads(json.dumps(records[target_index].payload, ensure_ascii=False))
    tampered_payload["agent_result"]["artifact_hash"] = "f" * 64
    records[target_index] = replace(
        records[target_index],
        payload=tampered_payload,
        stdout=json.dumps(tampered_payload, ensure_ascii=False),
    )

    grade = _grade(
        session,
        result,
        replace(evidence, records=tuple(records)),
        reconciliation,
        paths,
    )

    assert gate_id in grade.failed_gate_ids


@pytest.mark.parametrize("malformed", ("missing_closing_brace", "tampered_request"))
def test_transaction_grader_rejects_malformed_or_reconstructed_final_json(
    tmp_path: Path,
    malformed: str,
) -> None:
    session = _session("M1", "preview")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    if malformed == "missing_closing_brace":
        final_response = result.final_response[:-1]
    else:
        final = json.loads(result.final_response.split("=", 1)[1])
        final["request"]["arguments"]["fixture"] = "reconstructed"
        final_response = "WAAPI_RESULT_JSON=" + json.dumps(
            final,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    grade = _grade(
        session,
        replace(result, final_response=final_response),
        evidence,
        reconciliation,
        paths,
    )

    assert "awaiting_confirmation" in grade.failed_gate_ids


def test_extra_discovery_command_fails_closed(tmp_path: Path) -> None:
    session = _session("M1", "preview")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    extra = _command_record(("ls", str(paths["workspace"])), "")
    facts = classify_commands(
        (*result.command_facts.command_records, extra),
        skill_source=paths["skill"],
        expected_gateway_subcommands=session.gateway_steps,
    )

    grade = _grade(session, replace(result, command_facts=facts), evidence, reconciliation, paths)

    assert "gateway_only_no_ad_hoc_code" in grade.failed_gate_ids
    assert "no_discovery_before_gateway" in grade.failed_gate_ids


def test_rejected_packaged_gateway_attempt_does_not_imply_discovery(tmp_path: Path) -> None:
    session = _session("M1", "confirm")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    runner = paths["skill"] / "scripts" / "run.py"
    rejected = replace(
        _command_record(
            ("python", str(runner), "gateway.py", "operation-schema", "object.setNotes"),
            "broker rejected out-of-sequence command",
        ),
        exit_code=126,
        status="failed",
    )
    records = (
        *result.command_facts.command_records[:2],
        rejected,
        *result.command_facts.command_records[2:],
    )
    facts = classify_commands(
        records,
        skill_source=paths["skill"],
        expected_gateway_subcommands=session.gateway_steps,
    )
    session_audit = replace(
        result.session_audit,
        command_started_count=len(records),
        command_completed_count=len(records),
    )

    grade = _grade(
        session,
        replace(result, command_facts=facts, session_audit=session_audit),
        evidence,
        reconciliation,
        paths,
    )

    assert facts.discovery_commands == ()
    assert "gateway_only_no_ad_hoc_code" in grade.failed_gate_ids
    assert "no_discovery_before_gateway" not in grade.failed_gate_ids
    gateway_gate = next(gate for gate in grade.gates if gate.id == "gateway_only_no_ad_hoc_code")
    assert "out-of-sequence packaged gateway attempts" in gateway_gate.detail


def test_trusted_broker_evidence_does_not_depend_on_cli_aggregated_output(tmp_path: Path) -> None:
    session = _session("M1", "preview")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    records = tuple(
        replace(record, aggregated_output="")
        if record.argv and Path(record.argv[0]).name in {"python", "python3"}
        else record
        for record in result.command_facts.command_records
    )
    facts = classify_commands(
        records,
        skill_source=paths["skill"],
        expected_gateway_subcommands=session.gateway_steps,
    )

    grade = _grade(session, replace(result, command_facts=facts), evidence, reconciliation, paths)

    assert not facts.inline_python_commands
    assert facts.unexpected_commands
    assert grade.passed is True


def test_duplicate_read_and_missing_operate_reference_fail(tmp_path: Path) -> None:
    session = _session("M1", "preview")
    duplicate = ("SKILL.md", "SKILL.md", "references/waapi-operate.md")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path / "duplicate", session, read_files=duplicate)
    assert _grade(session, result, evidence, reconciliation, paths).failed_gate_ids == (
        "skill_md_read",
    )

    result, evidence, reconciliation, paths = _make_bundle(
        tmp_path / "missing-reference",
        session,
        read_files=("SKILL.md",),
    )
    grade = _grade(session, result, evidence, reconciliation, paths)
    assert grade.failed_gate_ids == ("skill_md_read",)


@pytest.mark.parametrize("case_id", ("Q2", "Q4"))
def test_nonfixed_queries_require_exact_query_reference_read(tmp_path: Path, case_id: str) -> None:
    session = _session(case_id, "single")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path / "valid", session)
    assert _grade(session, result, evidence, reconciliation, paths).passed is True

    result, evidence, reconciliation, paths = _make_bundle(
        tmp_path / "missing",
        session,
        read_files=("SKILL.md",),
    )
    grade = _grade(session, result, evidence, reconciliation, paths)
    assert grade.failed_gate_ids == ("skill_md_read",)

    result, evidence, reconciliation, paths = _make_bundle(
        tmp_path / "extra",
        session,
        read_files=("SKILL.md", "references/waapi-query.md", "references/waapi-operate.md"),
    )
    grade = _grade(session, result, evidence, reconciliation, paths)
    assert grade.failed_gate_ids == ("skill_md_read",)


@pytest.mark.parametrize("case_id", ("Q3", "R5", "R6"))
def test_closed_query_fast_paths_accept_skill_or_query_reference(
    tmp_path: Path,
    case_id: str,
) -> None:
    session = _session(case_id, "single")

    for label, reads in (
        ("skill-only", ("SKILL.md",)),
        ("with-query-reference", ("SKILL.md", "references/waapi-query.md")),
    ):
        result, evidence, reconciliation, paths = _make_bundle(
            tmp_path / label,
            session,
            read_files=reads,
        )
        assert _grade(session, result, evidence, reconciliation, paths).passed is True

    result, evidence, reconciliation, paths = _make_bundle(
        tmp_path / "extra-reference",
        session,
        read_files=("SKILL.md", "references/waapi-query.md", "references/waapi-operate.md"),
    )
    grade = _grade(session, result, evidence, reconciliation, paths)
    assert grade.failed_gate_ids == ("skill_md_read",)


@pytest.mark.parametrize("case_id", ("Q1", "Q5"))
def test_fast_path_queries_remain_skill_only(tmp_path: Path, case_id: str) -> None:
    session = _session(case_id, "single")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path / "valid", session)
    assert _grade(session, result, evidence, reconciliation, paths).passed is True

    result, evidence, reconciliation, paths = _make_bundle(
        tmp_path / "extra-query-reference",
        session,
        read_files=("SKILL.md", "references/waapi-query.md"),
    )
    grade = _grade(session, result, evidence, reconciliation, paths)
    assert grade.failed_gate_ids == ("skill_md_read",)


def test_c1_requires_exact_coverage_reference_read(tmp_path: Path) -> None:
    session = _session("C1", "single")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path / "valid", session)
    assert _grade(session, result, evidence, reconciliation, paths).passed is True

    result, evidence, reconciliation, paths = _make_bundle(
        tmp_path / "missing",
        session,
        read_files=("SKILL.md",),
    )
    grade = _grade(session, result, evidence, reconciliation, paths)
    assert grade.failed_gate_ids == ("skill_md_read",)

    result, evidence, reconciliation, paths = _make_bundle(
        tmp_path / "extra",
        session,
        read_files=(
            "SKILL.md",
            "references/waapi-coverage.md",
            "references/waapi-query.md",
        ),
    )
    grade = _grade(session, result, evidence, reconciliation, paths)
    assert grade.failed_gate_ids == ("skill_md_read",)


def test_screening_read_policy_partitions_all_40_sessions() -> None:
    sessions = SUITE.expand_profile("screening")
    actual = {
        (session.case.id, session.phase): _allowed_read_sequences(session)
        for session in sessions
    }
    skill_only = {
        *((case_id, "single") for case_id in ("Q1", "Q5")),
        *((case_id, "single") for case_id in ("B1", "B2", "B3", "B4", "B5", "B6", "B7")),
        *((case_id, "single") for case_id in ("R1", "R2", "R3", "R4")),
    }
    coverage_required = {("C1", "single")}
    query_required = {("Q2", "single"), ("Q4", "single")}
    query_optional = {(case_id, "single") for case_id in ("Q3", "R5", "R6")}
    operate = {
        (case_id, phase)
        for case_id in ("M1", "M3", "M4", "M5", "M6", "M7", "I1", "S1", "W1", "W2")
        for phase in ("preview", "confirm")
    } | {("M2", "single")}

    assert len(sessions) == len(actual) == 40
    assert set(actual) == skill_only | coverage_required | query_required | query_optional | operate
    assert all(actual[key] == (("SKILL.md",),) for key in skill_only)
    assert all(
        actual[key] == (("SKILL.md", "references/waapi-coverage.md"),)
        for key in coverage_required
    )
    assert all(
        actual[key] == (("SKILL.md", "references/waapi-query.md"),)
        for key in query_required
    )
    assert all(
        actual[key]
        == (("SKILL.md",), ("SKILL.md", "references/waapi-query.md"))
        for key in query_optional
    )
    assert all(
        actual[key] == (("SKILL.md", "references/waapi-operate.md"),)
        for key in operate
    )


def test_memory_and_file_change_events_fail(tmp_path: Path) -> None:
    session = _session("M1", "preview")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    memory_result = replace(result, prompt_audit=replace(result.prompt_audit, has_memory=True))
    assert "fresh_ephemeral_no_memory" in _grade(
        session, memory_result, evidence, reconciliation, paths
    ).failed_gate_ids

    changed_session = replace(result.session_audit, file_change_count=1)
    changed_result = replace(result, session_audit=changed_session, file_change_count=1)
    grade = _grade(session, changed_result, evidence, reconciliation, paths)
    assert "one_thread_one_turn" in grade.failed_gate_ids
    assert "source_workspace_outputs_unchanged" in grade.failed_gate_ids


def test_missing_or_wrongly_typed_runner_oracle_key_fails(tmp_path: Path) -> None:
    session = _session("M1", "preview")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    base = {
        "workspace": paths["workspace"],
        "skill_source": paths["skill"],
        "broker_state_directory": paths["state"],
        "broker_evidence_directory": paths["evidence"],
    }

    missing = grade_eval_session(
        session,
        result,
        evidence,
        reconciliation,
        runner_oracle={"transaction_state": "awaiting_confirmation", "target_unchanged": True},
        **base,
    )
    wrong_type = grade_eval_session(
        session,
        result,
        evidence,
        reconciliation,
        runner_oracle={
            "transaction_state": "awaiting_confirmation",
            "mutation_uri_count": False,
            "target_unchanged": True,
        },
        **base,
    )

    assert "mutation_uri_not_called" in missing.failed_gate_ids
    assert "mutation_uri_not_called" in wrong_type.failed_gate_ids


@pytest.mark.parametrize(
    ("case_id", "phase", "expected_gate"),
    (
        ("Q1", "single", "oracle_matches"),
        ("Q2", "single", "oracle_matches"),
        ("Q3", "single", "oracle_matches"),
        ("Q4", "single", "oracle_matches"),
        ("Q5", "single", "oracle_matches"),
        ("M1", "preview", "awaiting_confirmation"),
        ("M1", "confirm", "verified_readback"),
    ),
)
def test_live_final_response_must_match_runner_oracle(
    tmp_path: Path,
    case_id: str,
    phase: str,
    expected_gate: str,
) -> None:
    session = _session(case_id, phase)
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    oracle = _oracle(session)
    oracle["final_response_matches"] = False

    grade = grade_eval_session(
        session,
        result,
        evidence,
        reconciliation,
        workspace=paths["workspace"],
        skill_source=paths["skill"],
        broker_state_directory=paths["state"],
        broker_evidence_directory=paths["evidence"],
        runner_oracle=oracle,
    )

    assert expected_gate in grade.failed_gate_ids


def test_broker_failure_and_private_path_inside_workspace_fail(tmp_path: Path) -> None:
    session = _session("M1", "preview")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    failed_evidence = replace(evidence, complete=False, terminal_state="FAILED")
    failed_reconciliation = replace(reconciliation, passed=False, errors=("mismatch",))
    assert "gateway_result_v1_parsed" in _grade(
        session,
        result,
        failed_evidence,
        failed_reconciliation,
        paths,
    ).failed_gate_ids

    inside_state = paths["workspace"] / "private-state"
    inside_state.mkdir()
    inside_evidence = replace(evidence, state_directory=str(inside_state))
    inside_paths = {**paths, "state": inside_state}
    assert "runner_oracle_model_unwritable" in _grade(
        session,
        result,
        inside_evidence,
        reconciliation,
        inside_paths,
    ).failed_gate_ids


def test_unknown_gate_fails_closed(tmp_path: Path) -> None:
    original = _session("M1", "preview")
    session = replace(original, hard_gates=(*original.hard_gates, "future_untrusted_gate"))
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)

    grade = _grade(session, result, evidence, reconciliation, paths)

    assert grade.passed is False
    assert grade.unknown_gate_ids == ("future_untrusted_gate",)
    assert grade.gates[-1].known is False


def test_c1_requires_exact_five_version_summary_and_final_metrics(tmp_path: Path) -> None:
    session = _session("C1", "single")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    assert _grade(session, result, evidence, reconciliation, paths).passed is True

    missing_final = replace(result, final_response="五个版本都已比较。")
    grade = _grade(session, missing_final, evidence, reconciliation, paths)
    assert "all_versions_reported" in grade.failed_gate_ids

    payload = evidence.records[0].payload
    summary = payload["summary"]
    by_version = summary["by_version"]
    routes_without_zero = dict(by_version["2025.1"]["preferred_routes"])
    del routes_without_zero["unsupported_boundary"]
    malformed_by_version = {
        **by_version,
        "2025.1": {
            **by_version["2025.1"],
            "preferred_routes": routes_without_zero,
        },
    }
    malformed_payload = {
        **payload,
        "summary": {**summary, "by_version": malformed_by_version},
    }
    malformed_record = replace(evidence.records[0], payload=malformed_payload)
    malformed_evidence = replace(evidence, records=(malformed_record,))
    grade = _grade(session, result, malformed_evidence, reconciliation, paths)
    assert "all_versions_reported" in grade.failed_gate_ids


@pytest.mark.parametrize("case_id", ("B1", "B2", "B3", "B4", "B5", "B6", "B7"))
def test_boundaries_require_schema_only_payload_and_exact_strict_final(
    tmp_path: Path,
    case_id: str,
) -> None:
    session = _session(case_id, "single")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    assert _grade(session, result, evidence, reconciliation, paths).passed is True

    referenced = tmp_path / "with-operate-reference"
    (
        result_with_reference,
        evidence_with_reference,
        reconciliation_with_reference,
        paths_with_reference,
    ) = _make_bundle(
        referenced,
        session,
        read_files=("SKILL.md", "references/waapi-operate.md"),
    )
    assert "skill_md_read" in _grade(
        session,
        result_with_reference,
        evidence_with_reference,
        reconciliation_with_reference,
        paths_with_reference,
    ).failed_gate_ids

    missing_final = replace(result, final_response="我已经检查了这个请求。")
    grade = _grade(session, missing_final, evidence, reconciliation, paths)
    assert "unsupported_boundary_reported" in grade.failed_gate_ids

    bad_payload = {**evidence.records[0].payload, "status": "ok"}
    bad_record = replace(evidence.records[0], payload=bad_payload)
    bad_evidence = replace(evidence, records=(bad_record,))
    grade = _grade(session, result, bad_evidence, reconciliation, paths)
    assert "operation_schema_only" in grade.failed_gate_ids
    assert "unsupported_boundary_reported" in grade.failed_gate_ids


def test_matching_session_version_assignment_reconciles_but_wrong_version_fails(tmp_path: Path) -> None:
    session = _session("B1", "single")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    records = list(result.command_facts.command_records)
    gateway = records[-1]
    prefixed_argv = ("env", "WWISE_VERSION=2022.1", *gateway.argv)
    records[-1] = replace(gateway, command=" ".join(prefixed_argv), argv=prefixed_argv)
    facts = classify_commands(
        records,
        skill_source=paths["skill"],
        expected_gateway_subcommands=session.gateway_steps,
        expected_wwise_version=session.version,
    )

    assert _grade(session, replace(result, command_facts=facts), evidence, reconciliation, paths).passed is True

    wrong_argv = ("WWISE_VERSION=2023.1", *gateway.argv)
    records[-1] = replace(gateway, command=" ".join(wrong_argv), argv=wrong_argv)
    wrong_facts = classify_commands(
        records,
        skill_source=paths["skill"],
        expected_gateway_subcommands=session.gateway_steps,
        expected_wwise_version=session.version,
    )
    grade = _grade(session, replace(result, command_facts=wrong_facts), evidence, reconciliation, paths)
    assert "gateway_only_no_ad_hoc_code" in grade.failed_gate_ids
    assert "gateway_result_v1_parsed" in grade.failed_gate_ids


def test_c1_grader_binds_detached_invocation_to_canonical_skill(
    tmp_path: Path,
) -> None:
    session = _session("C1", "single")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)
    detached_skill = (
        paths["workspace"] / ".agents" / "skills" / "waapi-skill"
    )
    shutil.copytree(paths["skill"], detached_skill)
    detached_runner = detached_skill / "scripts" / "run.py"
    payload = evidence.records[0].payload
    commands = (
        _command_record(
            ("cat", str(detached_skill / "SKILL.md")),
            (detached_skill / "SKILL.md").read_text(encoding="utf-8"),
        ),
        _command_record(
            (
                "cat",
                str(detached_skill / "references" / "waapi-coverage.md"),
            ),
            (detached_skill / "references" / "waapi-coverage.md").read_text(
                encoding="utf-8"
            ),
        ),
        _command_record(
            (
                "python",
                str(detached_runner),
                "gateway.py",
                "capabilities",
                "--all-versions",
                "--summary-only",
            ),
            json.dumps(payload),
        ),
    )
    command_facts = classify_commands(
        commands,
        skill_source=detached_skill,
        expected_gateway_subcommands=session.gateway_steps,
    )
    detached_result = replace(result, command_facts=command_facts)
    normalized = (
        "python",
        str(detached_runner),
        "gateway.py",
        "capabilities",
        "--all-versions",
        "--summary-only",
    )
    detached_record = replace(
        evidence.records[0],
        model_argv=normalized,
        normalized_model_argv=normalized,
        gateway_arguments=(
            "capabilities",
            "--all-versions",
            "--summary-only",
        ),
    )
    detached_evidence = replace(evidence, records=(detached_record,))

    grade = grade_eval_session(
        session,
        detached_result,
        detached_evidence,
        reconciliation,
        workspace=paths["workspace"],
        skill_source=paths["skill"],
        invocation_skill_source=detached_skill,
        broker_state_directory=paths["state"],
        broker_evidence_directory=paths["evidence"],
        runner_oracle=_oracle(session),
    )
    assert grade.passed is True

    third_skill = tmp_path / "untrusted" / "waapi-skill"
    unbound_grade = grade_eval_session(
        session,
        detached_result,
        detached_evidence,
        reconciliation,
        workspace=paths["workspace"],
        skill_source=paths["skill"],
        invocation_skill_source=third_skill,
        broker_state_directory=paths["state"],
        broker_evidence_directory=paths["evidence"],
        runner_oracle=_oracle(session),
    )
    assert "gateway_only_no_ad_hoc_code" in unbound_grade.failed_gate_ids
    assert "gateway_result_v1_parsed" in unbound_grade.failed_gate_ids


@pytest.mark.parametrize("case_id", ("R1", "R2", "R3", "R4", "R5", "R6"))
def test_fixed_read_cases_pass_complete_grader_and_fail_on_oracle_mismatch(
    tmp_path: Path,
    case_id: str,
) -> None:
    session = _session(case_id, "single")
    result, evidence, reconciliation, paths = _make_bundle(tmp_path, session)

    assert _grade(session, result, evidence, reconciliation, paths).passed is True

    bad_oracle = _oracle(session)
    bad_oracle["oracle_matches"] = False
    grade = grade_eval_session(
        session,
        result,
        evidence,
        reconciliation,
        workspace=paths["workspace"],
        skill_source=paths["skill"],
        broker_state_directory=paths["state"],
        broker_evidence_directory=paths["evidence"],
        runner_oracle=bad_oracle,
    )
    assert "oracle_matches" in grade.failed_gate_ids

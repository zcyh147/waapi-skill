"""Fail-closed validation for one child semantic-matrix campaign run.

The matrix runner owns Codex/Wwise execution.  This module never starts either
process; it validates the archived child evidence and turns it into atomic
pair observations for :mod:`tests.semantic.support.codex_campaign`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_campaign import (
    CampaignEvidenceError,
    canonical_json_bytes,
    stable_tree_sha256,
)
from tests.semantic.support.codex_eval_suite import EvalSession
from tests.semantic.support.codex_filesystem_security import binary_file_open_flags
from tests.semantic.support.codex_harness import (
    WORKSPACE_SKILL_EXCLUDED_NAMES,
    assert_detached_workspace_skill_copy,
    is_link_or_junction,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_CONTRACT = "waapi-skill.codex-semantic-matrix-run/v2"
PHASE_CONTRACT = "waapi-skill.codex-semantic-phase-result/v2"
PHASE_ERROR_CONTRACT = "waapi-skill.codex-semantic-phase-error/v2"
RUNTIME_CONTRACT = "waapi-skill.codex-semantic-version-runtime/v2"
LIVE_PREFLIGHT_CONTRACT = "waapi-skill.codex-semantic-live-preflight/v1"
SKILL_LINK_ATTESTATION_CONTRACT = "waapi-skill.codex-campaign-skill-link/v1"
SKILL_COPY_ATTESTATION_CONTRACT = "waapi-skill.codex-campaign-skill-copy/v1"
LIVE_READINESS_RETRY_CATEGORY = "live_readiness_before_agent_action"

AUTO_RETRY_CATEGORIES = frozenset(
    {
        LIVE_READINESS_RETRY_CATEGORY,
        "service_unavailable",
        "timeout_before_agent_action",
        "turn_failed_before_agent_action",
    }
)
PAUSE_RETRY_CATEGORIES = frozenset({"quota_or_rate_limit"})
BLOCKED_INFRASTRUCTURE_CATEGORIES = frozenset({"authentication"})
LIFECYCLE_ERROR_STAGES = frozenset(
    {
        "live-version-run",
        "fixture-cleanup",
        "wwise-shutdown",
        "source-project-proof",
        "sandbox-cleanup",
        "sandbox-lock-release",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WWISE_GET_INFO_DISPLAY_NAME_BY_VERSION = {
    "2021.1": "Wwise",
    "2022.1": "Wwise",
    "2023.1": "WwiseConsole",
    "2024.1": "WwiseConsole",
    "2025.1": "WwiseConsole",
}


@dataclass(frozen=True, slots=True)
class PhaseVerdict:
    session_id: str
    phase: str
    status: str
    reason: str
    retry_category: str | None = None

    def phase_row(self) -> dict[str, str]:
        return {"phase": self.phase, "status": self.status}

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phase": self.phase,
            "status": self.status,
            "reason": self.reason,
            "retry_category": self.retry_category,
        }


@dataclass(frozen=True, slots=True)
class ChildValidation:
    observations: tuple[dict[str, Any], ...]
    phase_verdicts: tuple[PhaseVerdict, ...]
    executed_session_ids: tuple[str, ...]
    pending_session_ids: tuple[str, ...]
    retry_categories: tuple[str, ...]
    summary: Mapping[str, Any]

    @property
    def has_fail(self) -> bool:
        return any(row["status"] == "FAIL" for row in self.observations)

    @property
    def has_blocked(self) -> bool:
        return any(row["status"] == "BLOCKED" for row in self.observations)

    @property
    def has_retryable(self) -> bool:
        return any(row["status"] == "RETRYABLE" for row in self.observations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "observations": list(self.observations),
            "phase_verdicts": [item.as_dict() for item in self.phase_verdicts],
            "executed_session_ids": list(self.executed_session_ids),
            "pending_session_ids": list(self.pending_session_ids),
            "retry_categories": list(self.retry_categories),
        }


def load_strict_regular_json(path: Path) -> Any:
    """Read and parse exactly one non-symlink regular file descriptor."""

    source = Path(path)
    flags = binary_file_open_flags(os.O_RDONLY)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise CampaignEvidenceError(f"cannot open child JSON {source}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise CampaignEvidenceError(f"child JSON must be a regular file: {source}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CampaignEvidenceError(f"child JSON is not UTF-8: {source}") from exc
    return _strict_json_loads(text, source=source)


def replace_expected_skill_symlinks(
    root: Path,
    *,
    skill_source: Path,
    candidate_sha256: str,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    """Replace only exact runner Skill installs with sealed regular attestations.

    This must run before any child-controlled evidence is interpreted.  Every
    other symlink is a hard evidence failure.  POSIX installs remain exact
    links to the frozen candidate.  A native-Windows directory install is
    accepted only when its filtered tree hash equals the frozen candidate and
    no copied file is a hardlink alias to that candidate.
    """

    root_path = Path(root)
    if is_link_or_junction(root_path):
        raise CampaignEvidenceError(f"child evidence root must be a real directory: {root_path}")
    tree = root_path.resolve(strict=True)
    source_path = Path(skill_source)
    if is_link_or_junction(source_path):
        raise CampaignEvidenceError(f"Skill source must be a real directory: {source_path}")
    expected_target = source_path.resolve(strict=True)
    if not expected_target.is_dir():
        raise CampaignEvidenceError(f"Skill source must be a real directory: {expected_target}")
    if _SHA256_RE.fullmatch(candidate_sha256) is None:
        raise CampaignEvidenceError("candidate Skill hash must be lowercase SHA-256")

    links: list[Path] = []
    copies: list[Path] = []
    agent_workspaces: list[Path] = []

    def walk(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise CampaignEvidenceError(f"cannot scan child evidence {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CampaignEvidenceError(f"cannot stat child evidence {path}: {exc}") from exc
            if stat.S_ISLNK(info.st_mode) or is_link_or_junction(path):
                if not _is_expected_skill_link(path, root=tree):
                    raise CampaignEvidenceError(
                        f"unexpected symlink or junction in child evidence: {path}"
                    )
                if not stat.S_ISLNK(info.st_mode):
                    raise CampaignEvidenceError(
                        f"expected Skill install must not be a Windows junction: {path}"
                    )
                try:
                    target = path.resolve(strict=True)
                except OSError as exc:
                    raise CampaignEvidenceError(f"broken Skill symlink in child evidence: {path}") from exc
                if target != expected_target:
                    raise CampaignEvidenceError(
                        f"Skill symlink targets {target}, expected {expected_target}: {path}"
                    )
                links.append(path)
            elif stat.S_ISDIR(info.st_mode):
                if _is_expected_skill_link(path, root=tree):
                    copies.append(path)
                    continue
                if path.name == "agent-workspace" and "sessions" in path.relative_to(tree).parts:
                    agent_workspaces.append(path)
                walk(path)
            elif stat.S_ISREG(info.st_mode):
                if _is_expected_skill_link(path, root=tree):
                    raise CampaignEvidenceError(
                        f"expected installed Skill path is a file, not the runner link: {path}"
                    )
            else:
                raise CampaignEvidenceError(f"unsupported child evidence entry: {path}")

    walk(tree)
    active_platform = os.name if platform_name is None else platform_name
    if copies and active_platform != "nt":
        raise CampaignEvidenceError(
            "runner-created Skill directories are allowed only for native Windows campaigns"
        )
    installed_paths = frozenset((*links, *copies))
    for workspace in agent_workspaces:
        expected_install = workspace / ".agents" / "skills" / "waapi-skill"
        if expected_install not in installed_paths:
            raise CampaignEvidenceError(
                f"agent workspace is missing the exact runner-created Skill install: {workspace}"
            )
    for link in links:
        relative = link.relative_to(tree).as_posix()
        link.unlink()
        _exclusive_write(
            link,
            canonical_json_bytes(
                {
                    "contract": SKILL_LINK_ATTESTATION_CONTRACT,
                    "candidate_sha256": candidate_sha256,
                    "original_link_target": str(expected_target),
                    "path": relative,
                }
            )
            + b"\n",
        )

    expected_copy_sha256 = stable_tree_sha256(
        expected_target,
        exclude_names=tuple(sorted(WORKSPACE_SKILL_EXCLUDED_NAMES)),
    )
    if copies and expected_copy_sha256 != candidate_sha256:
        raise CampaignEvidenceError(
            "Windows Skill-copy exclusions do not match the frozen campaign candidate: "
            f"candidate={candidate_sha256} copy_source={expected_copy_sha256}"
        )
    for copied in copies:
        relative = copied.relative_to(tree).as_posix()
        try:
            observed_sha256 = stable_tree_sha256(copied)
            assert_detached_workspace_skill_copy(expected_target, copied)
        except (CampaignEvidenceError, OSError, RuntimeError) as exc:
            raise CampaignEvidenceError(
                f"cannot attest independent Windows Skill copy {copied}: {exc}"
            ) from exc
        if observed_sha256 != candidate_sha256:
            raise CampaignEvidenceError(
                "Windows Skill copy differs from the frozen candidate: "
                f"expected={candidate_sha256} actual={observed_sha256}: {copied}"
            )
        try:
            shutil.rmtree(copied)
        except OSError as exc:
            raise CampaignEvidenceError(
                f"cannot remove attested Windows Skill copy {copied}: {exc}"
            ) from exc
        _exclusive_write(
            copied,
            canonical_json_bytes(
                {
                    "contract": SKILL_COPY_ATTESTATION_CONTRACT,
                    "candidate_sha256": candidate_sha256,
                    "copied_from": str(expected_target),
                    "path": relative,
                }
            )
            + b"\n",
        )

    # A second complete scan proves replacement did not leave or introduce a
    # link anywhere in the attempt tree.
    _reject_all_symlinks(tree)
    return tuple(path.relative_to(tree).as_posix() for path in (*links, *copies))


def validate_child_run(
    matrix_root: Path,
    *,
    expected_sessions: Sequence[EvalSession],
    expected_pair_ids: Sequence[str],
    profile: str,
    skill_source: Path,
    suite_path: Path,
    live_config: Path,
    model: str,
    reasoning_effort: str,
    service_tier: str,
    version: str | None,
    offline_only: bool,
    returncode: int,
) -> ChildValidation:
    """Validate one complete matrix child and classify its atomic pair units."""

    root = Path(matrix_root).resolve(strict=True)
    sessions = tuple(expected_sessions)
    if not sessions:
        raise CampaignEvidenceError("child validation requires expected sessions")
    expected_ids = tuple(session.session_id for session in sessions)
    _validate_run_config(
        load_strict_regular_json(root / "run-config.json"),
        expected_sessions=sessions,
        expected_pair_ids=expected_pair_ids,
        profile=profile,
        skill_source=skill_source,
        suite_path=suite_path,
        live_config=live_config,
        model=model,
        reasoning_effort=reasoning_effort,
        service_tier=service_tier,
        version=version,
        offline_only=offline_only,
    )
    summary = _validate_summary(
        load_strict_regular_json(root / "summary.json"),
        expected_ids=expected_ids,
        profile=profile,
        returncode=returncode,
    )
    executed = tuple(summary["executed_session_ids"])
    pending = tuple(summary["pending_session_ids"])
    session_by_id = {session.session_id: session for session in sessions}

    actual_session_dirs = _strict_session_directory_names(root)
    expected_executed_dirs = {_safe_session_name(session_id) for session_id in executed}
    missing_session_dirs = expected_executed_dirs - actual_session_dirs
    unexpected_session_dirs = actual_session_dirs - expected_executed_dirs
    pre_codex_failure_session_id = _pre_codex_live_failure_session_id(
        root,
        version=version,
        offline_only=offline_only,
        executed_session_ids=executed,
        failed_session_ids=tuple(summary["failed_session_ids"]),
        run_errors=tuple(summary["run_errors"]),
        missing_session_dirs=missing_session_dirs,
        unexpected_session_dirs=unexpected_session_dirs,
    )
    if (
        unexpected_session_dirs
        or missing_session_dirs
        != (
            {_safe_session_name(pre_codex_failure_session_id)}
            if pre_codex_failure_session_id is not None
            else set()
        )
    ):
        raise CampaignEvidenceError(
            "executed session directories do not match summary: "
            f"expected={sorted(expected_executed_dirs)} actual={sorted(actual_session_dirs)}"
        )

    verdicts: list[PhaseVerdict] = []
    for session_id in executed:
        session = session_by_id[session_id]
        if session_id == pre_codex_failure_session_id:
            verdicts.append(
                PhaseVerdict(
                    session.session_id,
                    session.phase,
                    "BLOCKED",
                    "runner-attributed pre-Codex live phase failure; no Codex session was created",
                )
            )
            continue
        output_dir = root / "sessions" / _safe_session_name(session_id) / "outputs"
        verdicts.append(classify_phase(output_dir, session=session))

    pre_session_live_failure_candidate = (
        version is not None
        and not offline_only
        and not executed
        and tuple(summary["failed_session_ids"]) == ()
        and actual_session_dirs == set()
    )
    pre_session_retry_category: str | None = None
    if version is not None:
        expected_console = _live_config_console_path(live_config, version=version)
        pre_session_retry_category = _validate_live_runtime(
            root,
            version=version,
            expected_console=expected_console,
            expected_session_ids=expected_ids,
            executed_session_ids=executed,
            failed_session_ids=tuple(summary["failed_session_ids"]),
            summary_run_errors=tuple(summary["run_errors"]),
            verdicts=tuple(verdicts),
            pre_codex_failure_session_id=pre_codex_failure_session_id,
            pre_session_live_failure_candidate=pre_session_live_failure_candidate,
        )
    elif (root / "live-preflight.json").exists() or (root / "versions").exists():
        raise CampaignEvidenceError("offline child unexpectedly archived live runtime evidence")

    if pre_session_retry_category is not None:
        first = sessions[0]
        retry_verdict = PhaseVerdict(
            first.session_id,
            first.phase,
            "RETRYABLE",
            "runner-owned Wwise readiness failed before any Codex session or agent action",
            pre_session_retry_category,
        )
        _validate_pre_session_retry_summary(
            summary,
            expected_session_ids=expected_ids,
        )
        return ChildValidation(
            observations=(
                {
                    "unit_id": first.pair_id,
                    "status": "RETRYABLE",
                    "phases": [retry_verdict.phase_row()],
                },
            ),
            phase_verdicts=(retry_verdict,),
            executed_session_ids=(),
            pending_session_ids=pending,
            retry_categories=(pre_session_retry_category,),
            summary=summary,
        )

    observations = _build_unit_observations(sessions, tuple(verdicts), executed)
    _validate_summary_against_verdicts(summary, verdicts=tuple(verdicts), observations=observations)
    retry_categories = tuple(
        dict.fromkeys(item.retry_category for item in verdicts if item.retry_category is not None)
    )
    return ChildValidation(
        observations=observations,
        phase_verdicts=tuple(verdicts),
        executed_session_ids=executed,
        pending_session_ids=pending,
        retry_categories=retry_categories,
        summary=summary,
    )


def _strict_session_directory_names(root: Path) -> set[str]:
    sessions_root = root / "sessions"
    if not sessions_root.exists() and not sessions_root.is_symlink():
        return set()
    if sessions_root.is_symlink() or not sessions_root.is_dir():
        raise CampaignEvidenceError("sessions evidence root must be a real directory")
    names: set[str] = set()
    for path in sessions_root.iterdir():
        if path.is_symlink() or not path.is_dir():
            raise CampaignEvidenceError(f"session evidence entry must be a real directory: {path}")
        names.add(path.name)
    return names


def _validate_pre_session_retry_summary(
    summary: Mapping[str, Any],
    *,
    expected_session_ids: tuple[str, ...],
) -> None:
    if (
        summary.get("executed_session_count") != 0
        or summary.get("executed_session_ids") != []
        or summary.get("failed_session_ids") != []
        or summary.get("passed_session_count") != 0
        or summary.get("pending_session_ids") != list(expected_session_ids)
        or summary.get("all_selected_passed") is not False
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness failure contradicts the child summary"
        )


def _pre_codex_live_failure_session_id(
    root: Path,
    *,
    version: str | None,
    offline_only: bool,
    executed_session_ids: tuple[str, ...],
    failed_session_ids: tuple[str, ...],
    run_errors: tuple[str, ...],
    missing_session_dirs: set[str],
    unexpected_session_dirs: set[str],
) -> str | None:
    """Attribute one runner failure that happened before a Codex session existed.

    The matrix runner records a phase as attempted before it asks the trusted
    fixture for prompt values and a baseline.  A failure in that runner-owned
    preparation therefore has an executed/failed id and a live-phase traceback,
    but deliberately has no session directory.  Accept only that exact final
    attempted phase; successful and earlier failed phases still require their
    complete archived session evidence.
    """

    if not missing_session_dirs and not unexpected_session_dirs:
        return None
    if unexpected_session_dirs:
        return None
    if version is None or offline_only or len(missing_session_dirs) != 1:
        return None
    if not executed_session_ids or failed_session_ids != (executed_session_ids[-1],):
        return None
    session_id = failed_session_ids[0]
    if missing_session_dirs != {_safe_session_name(session_id)}:
        return None
    missing_path = root / "sessions" / _safe_session_name(session_id)
    if missing_path.exists() or missing_path.is_symlink():
        return None
    if len(run_errors) != 1 or not _is_exact_live_phase_traceback(
        run_errors[0],
        session_id=session_id,
    ):
        return None
    return session_id


def _is_exact_live_phase_traceback(error: str, *, session_id: str) -> bool:
    return error.startswith(
        f"[live-phase:{session_id}] Traceback (most recent call last):\n"
    )


def classify_phase(output_dir: Path, *, session: EvalSession) -> PhaseVerdict:
    """Classify one attempted phase without interpreting model prose."""

    try:
        phase = load_strict_regular_json(output_dir / "phase.json")
        _validate_phase_identity(phase, session=session)
        phase_error_path = output_dir / "phase-error.json"
        if phase_error_path.exists():
            phase_error = load_strict_regular_json(phase_error_path)
            return _classify_archived_phase_error(
                output_dir,
                session=session,
                phase=phase,
                phase_error=phase_error,
            )

        grade = load_strict_regular_json(output_dir / "grading.json")
        _validate_grading_identity(grade, session=session)
        error = phase.get("error")
        if error != "":
            return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "phase error is non-empty")
        if phase.get("passed") is True and phase.get("grade_passed") is True:
            if (
                grade.get("passed") is True
                and grade.get("failed_gate_ids") == []
                and grade.get("unknown_gate_ids") == []
            ):
                _validate_completed_phase_integrity(
                    output_dir,
                    session=session,
                    require_success=True,
                )
                return PhaseVerdict(session.session_id, session.phase, "PASS", "all trusted gates passed")
            return PhaseVerdict(
                session.session_id,
                session.phase,
                "BLOCKED",
                "phase PASS contradicts grading evidence",
            )
        if phase.get("passed") is False and phase.get("grade_passed") is False:
            failed = grade.get("failed_gate_ids")
            unknown = grade.get("unknown_gate_ids")
            if grade.get("passed") is False and (
                (isinstance(failed, list) and bool(failed))
                or (isinstance(unknown, list) and bool(unknown))
            ):
                _validate_completed_phase_integrity(
                    output_dir,
                    session=session,
                    require_success=False,
                )
                return PhaseVerdict(
                    session.session_id,
                    session.phase,
                    "FAIL",
                    "trusted semantic grader rejected one or more gates",
                )
        return PhaseVerdict(
            session.session_id,
            session.phase,
            "BLOCKED",
            "phase and grading status are contradictory",
        )
    except (CampaignEvidenceError, OSError, TypeError, ValueError) as exc:
        return PhaseVerdict(
            session.session_id,
            session.phase,
            "BLOCKED",
            f"malformed or missing phase evidence: {type(exc).__name__}: {exc}",
        )


def _classify_archived_phase_error(
    output_dir: Path,
    *,
    session: EvalSession,
    phase: Mapping[str, Any],
    phase_error: Mapping[str, Any],
) -> PhaseVerdict:
    if phase_error.get("contract") != PHASE_ERROR_CONTRACT:
        return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "invalid phase-error contract")
    if phase_error.get("session_id") != session.session_id:
        return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "phase-error session mismatch")
    if phase.get("passed") is not False or phase.get("grade_passed") is not False:
        return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "phase-error contradicts phase status")
    if (output_dir / "grading.json").exists():
        return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "failed phase unexpectedly has grading")
    archive_errors = phase_error.get("archive_errors")
    if archive_errors != []:
        return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "phase evidence archive is incomplete")

    if (
        phase.get("failure_class") == "infrastructure"
        and phase_error.get("failure_class") == "infrastructure"
        and phase_error.get("stage") == "codex-cli-infrastructure"
    ):
        failure = phase_error.get("infrastructure_failure")
        if not isinstance(failure, Mapping) or set(failure) != {
            "category",
            "message",
            "turn_failed",
            "timed_out",
            "agent_item_event_count",
        }:
            return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "invalid infrastructure payload")
        category = failure.get("category")
        if not isinstance(category, str) or failure.get("agent_item_event_count") != 0:
            return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "agent acted before infrastructure failure")
        if phase_error.get("harness_result_available") is not True:
            return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "infrastructure result is unavailable")
        if phase_error.get("reconciliation_available") is not False:
            return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "infrastructure phase reached reconciliation")
        _validate_no_agent_action(output_dir, require_facts=True)
        if category in BLOCKED_INFRASTRUCTURE_CATEGORIES:
            return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "Codex authentication failed", category)
        if category in AUTO_RETRY_CATEGORIES or category in PAUSE_RETRY_CATEGORIES:
            return PhaseVerdict(
                session.session_id,
                session.phase,
                "RETRYABLE",
                "Codex infrastructure failed before agent action",
                category,
            )
        return PhaseVerdict(
            session.session_id,
            session.phase,
            "BLOCKED",
            f"unknown infrastructure category: {category}",
            category,
        )

    legacy_timeout = (
        phase.get("failure_class") == "phase_execution"
        and phase_error.get("failure_class") == "phase_execution"
        and phase_error.get("stage") == "harness-run"
        and phase_error.get("exception_type") == "CodexHarnessError"
        and isinstance(phase_error.get("exception_message"), str)
        and phase_error["exception_message"].startswith("codex debug prompt-input failed with 124:")
        and phase_error.get("harness_result_available") is False
        and phase_error.get("reconciliation_available") is False
        and phase_error.get("infrastructure_failure") is None
    )
    if legacy_timeout:
        _validate_no_agent_action(output_dir, require_facts=False)
        return PhaseVerdict(
            session.session_id,
            session.phase,
            "RETRYABLE",
            "prompt audit timed out before Codex exec",
            "prompt_audit_timeout_before_exec",
        )
    return PhaseVerdict(session.session_id, session.phase, "BLOCKED", "runner-owned phase execution failed")


def _validate_completed_phase_integrity(
    output_dir: Path,
    *,
    session: EvalSession,
    require_success: bool,
) -> None:
    broker = load_strict_regular_json(output_dir / "broker-evidence.json")
    expected_steps = list(session.gateway_steps)
    if not isinstance(broker, Mapping):
        raise CampaignEvidenceError("broker evidence must be an object")
    broker_passed = broker.get("passed")
    broker_complete = broker.get("complete")
    terminal_state = broker.get("terminal_state")
    consumed_steps = broker.get("consumed_step_names")
    records = broker.get("records")
    if (
        type(broker_passed) is not bool
        or type(broker_complete) is not bool
        or not isinstance(terminal_state, str)
        or broker.get("expected_step_names") != expected_steps
        or not isinstance(consumed_steps, list)
        or not all(isinstance(item, str) for item in consumed_steps)
        or consumed_steps != expected_steps[: len(consumed_steps)]
        or not isinstance(records, list)
    ):
        raise CampaignEvidenceError("broker trace is malformed or out of sequence")

    successful_records: list[Mapping[str, Any]] = []
    rejected_seen = False
    for index, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise CampaignEvidenceError("broker record is malformed")
        authenticated = record.get("authenticated")
        accepted = record.get("accepted")
        succeeded = record.get("succeeded")
        allowed = record.get("allowed_exit_codes")
        exit_code = record.get("exit_code")
        model_argv = record.get("model_argv")
        normalized_argv = record.get("normalized_model_argv")
        step_name = record.get("step_name")
        if (
            type(authenticated) is not bool
            or type(accepted) is not bool
            or type(succeeded) is not bool
            or type(exit_code) is not int
            or not isinstance(allowed, list)
            or not all(type(value) is int for value in allowed)
            or not isinstance(model_argv, list)
            or not all(isinstance(value, str) for value in model_argv)
            or not isinstance(normalized_argv, list)
            or not all(isinstance(value, str) for value in normalized_argv)
            or record.get("sequence") != index
            or "step_name" not in record
            or (step_name is not None and not isinstance(step_name, str))
        ):
            raise CampaignEvidenceError("broker record is malformed")
        if authenticated is not True:
            raise CampaignEvidenceError("broker record is unauthenticated")
        if succeeded:
            if (
                rejected_seen
                or accepted is not True
                or exit_code not in allowed
                or not normalized_argv
                or not isinstance(step_name, str)
            ):
                raise CampaignEvidenceError("broker successful record is contradictory")
            successful_records.append(record)
        else:
            successful_prefix = [item["step_name"] for item in successful_records]
            expected_terminal_reason = (
                "broker is terminal FAILED"
                if rejected_seen
                else "broker is terminal COMPLETE"
            )
            valid_post_complete_rejection = (
                step_name is None
                and successful_prefix == expected_steps
                and model_argv != []
                and normalized_argv == []
                and record.get("rejection") == expected_terminal_reason
                and exit_code == 126
                and "runner_exit_code" in record
                and record.get("runner_exit_code") is None
                and "payload" in record
                and record.get("payload") is None
                and record.get("payload_error") == ""
            )
            rejected_seen = True
            if (
                accepted is not False
                or allowed != []
                or not isinstance(record.get("rejection"), str)
                or not record.get("rejection")
                or (step_name is None and not valid_post_complete_rejection)
            ):
                raise CampaignEvidenceError("broker failed record is contradictory")

    successful_steps = [record["step_name"] for record in successful_records]
    if successful_steps != consumed_steps:
        raise CampaignEvidenceError("broker consumed steps disagree with successful records")

    broker_success = (
        broker_passed is True
        and broker_complete is True
        and terminal_state == "COMPLETE"
        and consumed_steps == expected_steps
        and len(records) == len(expected_steps)
        and len(successful_records) == len(records)
    )
    if not broker_success:
        coherent_failure = (
            broker_passed is False
            and broker_complete is False
            and (
                (terminal_state == "FAILED" and rejected_seen)
                or (terminal_state == "RUNNING" and not rejected_seen)
            )
        )
        if not coherent_failure:
            raise CampaignEvidenceError("broker terminal state is contradictory")
    if require_success and not broker_success:
        raise CampaignEvidenceError("broker trace did not complete successfully")

    accepted_count = sum(record.get("accepted") is True for record in records)
    if accepted_count != len(successful_records):
        raise CampaignEvidenceError("broker accepted records are not all successful")
    for record in successful_records:
        allowed = record.get("allowed_exit_codes")
        if record.get("exit_code") not in allowed:
            raise CampaignEvidenceError("broker record exit status is not allowed")

    reconciliation = load_strict_regular_json(output_dir / "broker-reconciliation.json")
    reconciliation_passed = reconciliation.get("passed") if isinstance(reconciliation, Mapping) else None
    reconciliation_errors = reconciliation.get("errors") if isinstance(reconciliation, Mapping) else None
    observed_count = (
        reconciliation.get("observed_command_count") if isinstance(reconciliation, Mapping) else None
    )
    reconciled_accepted_count = (
        reconciliation.get("accepted_record_count") if isinstance(reconciliation, Mapping) else None
    )
    if (
        not isinstance(reconciliation, Mapping)
        or type(reconciliation_passed) is not bool
        or not isinstance(reconciliation_errors, list)
        or not all(isinstance(item, str) for item in reconciliation_errors)
        or type(observed_count) is not int
        or observed_count < 0
        or type(reconciled_accepted_count) is not int
        or reconciled_accepted_count < 0
        or observed_count != len(records)
        or reconciled_accepted_count != accepted_count
    ):
        raise CampaignEvidenceError("broker reconciliation is malformed or misbound")
    if broker_success:
        if reconciliation_passed is not True or reconciliation_errors != []:
            raise CampaignEvidenceError("successful broker trace did not reconcile")
    elif reconciliation_passed is not False or not reconciliation_errors:
        raise CampaignEvidenceError("failed broker trace has contradictory reconciliation")

    oracle = load_strict_regular_json(output_dir / "runner-oracle.json")
    if not isinstance(oracle, Mapping) or not oracle:
        raise CampaignEvidenceError("runner oracle is missing or empty")

    facts = load_strict_regular_json(output_dir / "codex-facts.json")
    if not isinstance(facts, Mapping):
        raise CampaignEvidenceError("Codex facts must be an object")
    if facts.get("exit_status") != 0 or facts.get("timed_out") is not False:
        raise CampaignEvidenceError("Codex did not complete with exit status zero")
    for audit_name in ("prompt_audit", "isolation_audit", "session_audit"):
        audit = facts.get(audit_name)
        if not isinstance(audit, Mapping) or audit.get("passed") is not True:
            raise CampaignEvidenceError(f"{audit_name} did not pass")
    if facts["prompt_audit"].get("has_memory") is not False:
        raise CampaignEvidenceError("Codex prompt contained memory")
    if facts.get("skill_tree_unchanged") is not True:
        raise CampaignEvidenceError("Skill tree changed during the phase")
    before = facts.get("skill_tree_sha256_before")
    after = facts.get("skill_tree_sha256_after")
    if before != after or not isinstance(before, str) or _SHA256_RE.fullmatch(before) is None:
        raise CampaignEvidenceError("Skill tree hashes are absent or changed")
    if facts.get("file_change_count") != 0 or facts.get("collab_call_count") != 0:
        raise CampaignEvidenceError("agent changed files or used collaboration")
    for key in (
        "created_files",
        "modified_files",
        "deleted_files",
        "created_source_files",
        "modified_source_files",
        "deleted_source_files",
    ):
        if facts.get(key) != []:
            raise CampaignEvidenceError(f"Codex facts contain unexpected {key}")
    command_facts = facts.get("command_facts")
    if not isinstance(command_facts, Mapping):
        raise CampaignEvidenceError("command facts are missing")
    gateway_attempts = command_facts.get("gateway_attempt_commands")
    if (
        not isinstance(gateway_attempts, list)
        or not all(isinstance(item, str) for item in gateway_attempts)
        or len(gateway_attempts) != observed_count
    ):
        raise CampaignEvidenceError("gateway attempt evidence does not match reconciliation")
    null_step_rejections = [record for record in records if record.get("step_name") is None]
    if null_step_rejections:
        command_records = command_facts.get("command_records")
        if not isinstance(command_records, list) or not all(
            isinstance(item, Mapping) for item in command_records
        ):
            raise CampaignEvidenceError("post-completion broker rejection lacks command evidence")
        command_cursor = 0
        remaining_gateway_attempts = list(gateway_attempts)
        for rejected_record in null_step_rejections:
            match_index = next(
                (
                    index
                    for index in range(command_cursor, len(command_records))
                    if command_records[index].get("argv")
                    == rejected_record.get("model_argv")
                    and type(command_records[index].get("exit_code")) is int
                    and command_records[index].get("exit_code") != 0
                    and command_records[index].get("status") == "failed"
                    and command_records[index].get("parse_error") == ""
                    and command_records[index].get("has_shell_operators") is False
                    and command_records[index].get("aggregated_output")
                    == (
                        "Gateway broker rejected command: "
                        f"{rejected_record.get('rejection')}\n"
                    )
                ),
                None,
            )
            if match_index is None:
                raise CampaignEvidenceError(
                    "post-completion broker rejection is not bound to exact Codex command evidence"
                )
            command_cursor = match_index + 1
            command = command_records[match_index].get("command")
            if not isinstance(command, str) or command not in remaining_gateway_attempts:
                raise CampaignEvidenceError(
                    "post-completion broker rejection is not bound to exact Codex command evidence"
                )
            remaining_gateway_attempts.remove(command)
    if require_success:
        _validate_success_command_facts(
            command_facts,
            expected_steps=expected_steps,
            broker_records=records,
        )


def _validate_success_command_facts(
    command_facts: Mapping[str, Any],
    *,
    expected_steps: list[str],
    broker_records: list[Any],
) -> None:
    for key in (
        "direct_waapi_client_commands",
        "discovery_commands",
        "inline_python_commands",
        "write_like_commands",
    ):
        if command_facts.get(key) != []:
            raise CampaignEvidenceError(f"Codex used forbidden commands: {key}")

    command_records = command_facts.get("command_records")
    gateway_attempts = command_facts.get("gateway_attempt_commands")
    gateway_subcommands = command_facts.get("gateway_subcommands")
    unexpected = command_facts.get("unexpected_commands")
    if (
        not isinstance(command_records, list)
        or not all(isinstance(item, Mapping) for item in command_records)
        or not isinstance(gateway_attempts, list)
        or not all(isinstance(item, str) for item in gateway_attempts)
        or not isinstance(gateway_subcommands, list)
        or not all(isinstance(item, str) for item in gateway_subcommands)
        or not isinstance(unexpected, list)
        or not all(isinstance(item, str) for item in unexpected)
    ):
        raise CampaignEvidenceError("successful command facts are malformed")

    unmatched_command_indexes = set(range(len(command_records)))
    broker_command_records: list[Mapping[str, Any]] = []
    for broker_record in broker_records:
        normalized = broker_record.get("normalized_model_argv")
        matches = [
            index
            for index in unmatched_command_indexes
            if command_records[index].get("argv") == normalized
        ]
        if len(matches) != 1:
            raise CampaignEvidenceError("trusted broker command is not uniquely present in Codex facts")
        index = matches[0]
        unmatched_command_indexes.remove(index)
        broker_command_records.append(command_records[index])

    broker_commands = [record.get("command") for record in broker_command_records]
    if (
        not all(isinstance(command, str) for command in broker_commands)
        or gateway_attempts != broker_commands
    ):
        raise CampaignEvidenceError("gateway attempts do not exactly match trusted broker commands")

    unexpected_indexes: set[int] = set()
    for unexpected_command in unexpected:
        matches = [
            index
            for index, record in enumerate(broker_command_records)
            if index not in unexpected_indexes and record.get("command") == unexpected_command
        ]
        if len(matches) != 1:
            raise CampaignEvidenceError("unexpected command is not an exact trusted broker command")
        index = matches[0]
        record = broker_command_records[index]
        if (
            record.get("exit_code") != 0
            or record.get("status") != "completed"
            or record.get("parse_error") != ""
            or record.get("has_shell_operators") is not False
            or not isinstance(record.get("aggregated_output"), str)
            or record["aggregated_output"].strip() != ""
        ):
            raise CampaignEvidenceError(
                "unexpected trusted broker command was not caused only by missing CLI output"
            )
        unexpected_indexes.add(index)

    visible_steps = [
        broker_record.get("step_name")
        for index, broker_record in enumerate(broker_records)
        if index not in unexpected_indexes
    ]
    if gateway_subcommands != visible_steps:
        raise CampaignEvidenceError("gateway subcommands do not match trusted visible broker output")
    if len(visible_steps) + len(unexpected_indexes) != len(expected_steps):
        raise CampaignEvidenceError("trusted broker output bridge is incomplete")


def _validate_no_agent_action(output_dir: Path, *, require_facts: bool) -> None:
    broker = load_strict_regular_json(output_dir / "broker-evidence.json")
    if not isinstance(broker, Mapping):
        raise CampaignEvidenceError("broker evidence must be an object")
    if broker.get("records") != [] or broker.get("consumed_step_names") != []:
        raise CampaignEvidenceError("broker observed a gateway action before the failure")
    if (output_dir / "broker-reconciliation.json").exists():
        raise CampaignEvidenceError("pre-action failure unexpectedly has reconciliation")
    facts_path = output_dir / "codex-facts.json"
    if not facts_path.exists():
        if require_facts:
            raise CampaignEvidenceError("structured infrastructure failure lacks Codex facts")
        return
    facts = load_strict_regular_json(facts_path)
    if not isinstance(facts, Mapping):
        raise CampaignEvidenceError("Codex facts must be an object")
    commands = facts.get("command_facts")
    if not isinstance(commands, Mapping) or commands.get("gateway_attempt_commands") != []:
        raise CampaignEvidenceError("Codex attempted the gateway before infrastructure failure")
    if facts.get("file_change_count") != 0 or facts.get("collab_call_count") != 0:
        raise CampaignEvidenceError("Codex acted before infrastructure failure")
    for key in (
        "created_files",
        "modified_files",
        "deleted_files",
        "created_source_files",
        "modified_source_files",
        "deleted_source_files",
    ):
        if facts.get(key) != []:
            raise CampaignEvidenceError(f"Codex changed files before infrastructure failure: {key}")


def _validate_live_runtime(
    root: Path,
    *,
    version: str,
    expected_console: Path,
    expected_session_ids: tuple[str, ...],
    executed_session_ids: tuple[str, ...],
    failed_session_ids: tuple[str, ...],
    summary_run_errors: tuple[str, ...],
    verdicts: tuple[PhaseVerdict, ...],
    pre_codex_failure_session_id: str | None,
    pre_session_live_failure_candidate: bool,
) -> str | None:
    preflight = load_strict_regular_json(root / "live-preflight.json")
    if (
        not isinstance(preflight, Mapping)
        or preflight.get("contract") != LIVE_PREFLIGHT_CONTRACT
        or preflight.get("ok") is not True
        or preflight.get("automatic_install_attempted") is not False
    ):
        raise CampaignEvidenceError("live dependency preflight did not pass without mutation")
    runtime = load_strict_regular_json(root / "versions" / version / "runtime.json")
    if not isinstance(runtime, Mapping) or runtime.get("contract") != RUNTIME_CONTRACT:
        raise CampaignEvidenceError("invalid live runtime contract")
    if (
        runtime.get("version") != version
        or runtime.get("session_ids") != list(expected_session_ids)
        or runtime.get("executed_session_ids") != list(executed_session_ids)
        or runtime.get("failed_session_ids") != list(failed_session_ids)
    ):
        raise CampaignEvidenceError("live runtime session/version binding mismatch")
    runtime_errors = runtime.get("errors")
    if not isinstance(runtime_errors, list) or not all(isinstance(item, str) for item in runtime_errors):
        raise CampaignEvidenceError("live runtime errors must be a string array")
    expected_summary_errors = (
        tuple(runtime_errors) if len(runtime_errors) <= 1 else ("\n\n".join(runtime_errors),)
    )
    if summary_run_errors != expected_summary_errors:
        raise CampaignEvidenceError("summary and runtime errors disagree")
    before = runtime.get("source_hash_before")
    after = runtime.get("source_hash_after")
    if not _valid_project_hash(before) or before != after:
        raise CampaignEvidenceError("SampleProject source hash is absent or changed")
    metadata = runtime.get("sandbox_metadata")
    if not isinstance(metadata, Mapping):
        raise CampaignEvidenceError("sandbox metadata is unavailable")
    if metadata.get("source_hash") != before or metadata.get("sandbox_hash") != before:
        raise CampaignEvidenceError("sandbox/source hash binding mismatch")
    if metadata.get("source_mtime_before") != metadata.get("source_mtime_after"):
        raise CampaignEvidenceError("SampleProject source mtime changed")
    expected_display_name = _WWISE_GET_INFO_DISPLAY_NAME_BY_VERSION.get(version)
    if expected_display_name is None:
        raise CampaignEvidenceError(
            f"Wwise getInfo displayName contract is unavailable for version {version}"
        )
    if (
        pre_session_live_failure_candidate
        and len(runtime_errors) == 1
        and _is_exact_live_readiness_before_agent_error(runtime_errors[0])
    ):
        _validate_pre_session_live_readiness_runtime(
            root,
            version=version,
            expected_console=expected_console,
            runtime=runtime,
            metadata=metadata,
            error=runtime_errors[0],
        )
        return LIVE_READINESS_RETRY_CATEGORY
    if (
        metadata.get("wwise_version") != version
        or metadata.get("identity_verified") is not True
        or metadata.get("expected_project_identity") != "SampleProject"
    ):
        raise CampaignEvidenceError("Wwise identity/version was not proven")
    if metadata.get("get_info_display_name") != expected_display_name:
        raise CampaignEvidenceError(
            "Wwise getInfo displayName does not match the exact version contract: "
            f"version={version} expected={expected_display_name!r} "
            f"actual={metadata.get('get_info_display_name')!r}"
        )
    info_version = metadata.get("get_info_version")
    expected_year, expected_major = (int(part) for part in version.split(".", 1))
    if (
        not isinstance(info_version, Mapping)
        or info_version.get("year") != expected_year
        or info_version.get("major") != expected_major
    ):
        raise CampaignEvidenceError("Wwise getInfo version does not match the requested version")
    launch_project = metadata.get("launch_project_path")
    sandbox_project = metadata.get("sandbox_project_path")
    sandbox_path = metadata.get("sandbox_path")
    source_project = metadata.get("source_path")
    source_root = metadata.get("source_root")
    iteration_sandbox_root = runtime.get("iteration_sandbox_root")
    command = metadata.get("command")
    if (
        not isinstance(launch_project, str)
        or not isinstance(sandbox_project, str)
        or not isinstance(sandbox_path, str)
        or not isinstance(source_project, str)
        or not isinstance(source_root, str)
        or not isinstance(iteration_sandbox_root, str)
        or not isinstance(command, list)
        or not all(isinstance(item, str) for item in command)
        or len(command) < 3
        or command[1] != "waapi-server"
    ):
        raise CampaignEvidenceError("Wwise launch was not bound to the private sandbox project")

    expected_sandbox_root = (root / "versions" / version / "sandbox-root").resolve(strict=False)
    recorded_sandbox_root = Path(iteration_sandbox_root).expanduser().resolve(strict=False)
    recorded_sandbox = Path(sandbox_path).expanduser().resolve(strict=False)
    recorded_sandbox_project = Path(sandbox_project).expanduser().resolve(strict=False)
    recorded_launch_project = Path(launch_project).expanduser().resolve(strict=False)
    recorded_source_root = Path(source_root).expanduser().resolve(strict=False)
    recorded_source_project = Path(source_project).expanduser().resolve(strict=False)
    recorded_console = Path(command[0]).expanduser().resolve(strict=False)
    if (
        recorded_console != expected_console.resolve(strict=False)
        or recorded_sandbox_root != expected_sandbox_root
        or not expected_sandbox_root.is_dir()
        or expected_sandbox_root.is_symlink()
        or recorded_sandbox.parent != expected_sandbox_root
        or recorded_launch_project != recorded_sandbox_project
        or recorded_sandbox_project == recorded_sandbox
        or not _path_is_within(recorded_sandbox_project, recorded_sandbox)
        or recorded_sandbox_project.suffix != ".wproj"
        or recorded_sandbox_project.stem != metadata.get("expected_project_identity")
        or command[2] != sandbox_project
        or Path(command[2]).expanduser().resolve(strict=False) != recorded_sandbox_project
    ):
        raise CampaignEvidenceError("Wwise launch project is not inside the exact campaign sandbox")
    if (
        Path(source_root).is_symlink()
        or Path(source_project).is_symlink()
        or not recorded_source_root.is_dir()
        or not recorded_source_project.is_file()
        or recorded_source_project == recorded_source_root
        or not _path_is_within(recorded_source_project, recorded_source_root)
        or recorded_source_project == recorded_sandbox_project
        or _path_is_within(recorded_sandbox, recorded_source_root)
        or _path_is_within(recorded_source_root, recorded_sandbox)
    ):
        raise CampaignEvidenceError("immutable source project and campaign sandbox are not separated")

    selected_port = metadata.get("selected_port")
    if type(selected_port) is not int or not 1 <= selected_port <= 65535:
        raise CampaignEvidenceError("Wwise selected WAMP port is invalid")
    if _command_option(command, "--wamp-port") != str(selected_port):
        raise CampaignEvidenceError("Wwise command WAMP port does not match sandbox metadata")
    if _command_option(command, "--http-port") != "0":
        raise CampaignEvidenceError("Wwise command must disable the HTTP transport")
    process_pid = metadata.get("process_pid")
    details = metadata.get("process_cleanup_details")
    if (
        metadata.get("process_cleanup_result") != "cleaned"
        or type(process_pid) is not int
        or process_pid <= 0
        or not isinstance(details, Mapping)
        or details.get("process_exited") is not True
        or details.get("residual_processes") != []
        or details.get("launch_pid") != process_pid
    ):
        raise CampaignEvidenceError("Wwise process cleanup is incomplete or unproven")

    statuses = [item.status for item in verdicts]
    all_pass = bool(statuses) and all(status == "PASS" for status in statuses)
    if all_pass and len(executed_session_ids) == len(expected_session_ids):
        if runtime.get("sandbox_retained") is not False or metadata.get("keep_decision") != "deleted":
            raise CampaignEvidenceError("passing live child did not delete its sandbox")
        if recorded_sandbox.exists() or recorded_sandbox.is_symlink():
            raise CampaignEvidenceError("passing live child left its sandbox on disk")
    else:
        if runtime.get("sandbox_retained") is not True or metadata.get("keep_decision") != (
            "retained-in-iteration-root-for-semantic-failure"
        ):
            raise CampaignEvidenceError("failed/retryable live child did not retain evidence as declared")
        if (
            recorded_sandbox.is_symlink()
            or not recorded_sandbox.is_dir()
            or recorded_sandbox_project.is_symlink()
            or not recorded_sandbox_project.is_file()
        ):
            raise CampaignEvidenceError("failed/retryable live child did not retain its real sandbox")

    for error in runtime_errors:
        match = re.match(r"^\[([^\]]+)\]", error)
        stage = match.group(1) if match else ""
        if stage in LIFECYCLE_ERROR_STAGES or stage.startswith("preview-seal-"):
            raise CampaignEvidenceError(f"live lifecycle/postprocess failed: {stage}")
    retryable = [item for item in verdicts if item.status == "RETRYABLE"]
    if retryable:
        expected_prefix = f"[live-phase:{retryable[-1].session_id}] Traceback"
        if len(runtime_errors) != 1 or not runtime_errors[0].startswith(expected_prefix):
            raise CampaignEvidenceError("retryable live phase has unexpected runtime errors")
    elif pre_codex_failure_session_id is not None:
        if failed_session_ids != (pre_codex_failure_session_id,):
            raise CampaignEvidenceError(
                "pre-Codex live failure does not match the runtime failed session"
            )
        if len(runtime_errors) != 1 or not _is_exact_live_phase_traceback(
            runtime_errors[0],
            session_id=pre_codex_failure_session_id,
        ):
            raise CampaignEvidenceError(
                "pre-Codex live failure has unexpected runtime errors"
            )
    elif runtime_errors:
        raise CampaignEvidenceError("semantic PASS/FAIL child has unexpected runtime errors")
    return None


def _is_exact_live_readiness_before_agent_error(error: str) -> bool:
    """Recognize only the runner-owned WAMP-start readiness failure."""

    prefix = "[live-version-run] Traceback (most recent call last):\n"
    if not error.startswith(prefix) or error.count("Traceback (most recent call last):") != 1:
        return False
    expected_call_chain = (
        "in run_live_version_sessions",
        "in launch_sandboxed_wwise",
        "in run_until_ready",
        "in wait_ready",
    )
    observed_call_chain = tuple(
        f"in {match}"
        for match in re.findall(
            r'^\s+File "[^"]+", line \d+, in ([A-Za-z_][A-Za-z0-9_]*)$',
            error,
            flags=re.MULTILINE,
        )
    )
    if observed_call_chain != expected_call_chain:
        return False
    terminal_lines = [
        line
        for line in error.splitlines()
        if line.startswith("wwise_waapi.headless.ReadinessTimeout:")
    ]
    if len(terminal_lines) != 1 or terminal_lines[0] != error.splitlines()[-1]:
        return False
    terminal = terminal_lines[0]
    return (
        terminal.startswith(
            "wwise_waapi.headless.ReadinessTimeout: WAAPI readiness timed out; port="
        )
        and "; last_exception_type=ConnectionRefusedError;" in terminal
        and "WAAPI\\tFatal Error\\tWampFailedStartingServer\\t"
        "WAMP server failed to start (port " in terminal
    )


def _validate_pre_session_live_readiness_runtime(
    root: Path,
    *,
    version: str,
    expected_console: Path,
    runtime: Mapping[str, Any],
    metadata: Mapping[str, Any],
    error: str,
) -> None:
    """Prove a live readiness failure happened before any Codex agent action."""

    if runtime.get("fixture_transactions") != []:
        raise CampaignEvidenceError(
            "pre-session live readiness failure unexpectedly has fixture transactions"
        )
    source_mtime_before = metadata.get("source_mtime_before")
    source_mtime_after = metadata.get("source_mtime_after")
    if (
        type(source_mtime_before) not in {int, float}
        or type(source_mtime_after) not in {int, float}
        or source_mtime_before != source_mtime_after
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness failure lacks unchanged source mtime proof"
        )
    copy_duration = metadata.get("copy_duration_seconds")
    if type(copy_duration) not in {int, float} or copy_duration < 0:
        raise CampaignEvidenceError(
            "pre-session live readiness failure lacks sandbox copy evidence"
        )
    if (
        metadata.get("wwise_version") != version
        or metadata.get("expected_project_identity") != "SampleProject"
        or metadata.get("identity_verified") is not None
        or metadata.get("get_info_display_name") is not None
        or metadata.get("get_info_version") is not None
        or metadata.get("ready_duration_seconds") is not None
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness evidence contains established or drifted identity"
        )
    notes = metadata.get("notes")
    if not isinstance(notes, list) or not all(isinstance(item, str) for item in notes):
        raise CampaignEvidenceError("pre-session live readiness notes are malformed")

    iteration_sandbox_root = _strict_absolute_path(
        runtime.get("iteration_sandbox_root"),
        label="iteration sandbox root",
        kind="directory",
    )
    expected_sandbox_root = (root / "versions" / version / "sandbox-root").resolve(
        strict=True
    )
    if iteration_sandbox_root != expected_sandbox_root or expected_sandbox_root.is_symlink():
        raise CampaignEvidenceError(
            "pre-session live readiness sandbox root is not the exact campaign root"
        )

    sandbox = _strict_absolute_path(
        metadata.get("sandbox_path"),
        label="sandbox",
        kind="directory",
    )
    sandbox_project = _strict_absolute_path(
        metadata.get("sandbox_project_path"),
        label="sandbox project",
        kind="file",
    )
    launch_project = _strict_absolute_path(
        metadata.get("launch_project_path"),
        label="launch project",
        kind="file",
    )
    source_root = _strict_absolute_path(
        metadata.get("source_root"),
        label="source root",
        kind="directory",
    )
    source_project = _strict_absolute_path(
        metadata.get("source_path"),
        label="source project",
        kind="file",
    )
    metadata_path = _strict_absolute_path(
        metadata.get("metadata_path"),
        label="sandbox metadata",
        kind="file",
    )
    if (
        sandbox.parent != expected_sandbox_root
        or launch_project != sandbox_project
        or sandbox_project.parent != sandbox
        or sandbox_project.name != "SampleProject.wproj"
        or metadata_path != sandbox / "sandbox-metadata.json"
        or source_project.parent != source_root
        or source_project.name != "SampleProject.wproj"
        or source_project == sandbox_project
        or _path_is_within(sandbox, source_root)
        or _path_is_within(source_root, sandbox)
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness paths are not bound to separated SampleProject roots"
        )
    persisted_metadata = load_strict_regular_json(metadata_path)
    if not isinstance(persisted_metadata, Mapping) or persisted_metadata != metadata:
        raise CampaignEvidenceError(
            "pre-session live readiness runtime and sandbox metadata disagree"
        )
    if (
        runtime.get("sandbox_retained") is not True
        or metadata.get("keep_decision")
        != "retained-in-iteration-root-for-semantic-failure"
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness failure did not retain its real sandbox"
        )

    selected_port = metadata.get("selected_port")
    command = metadata.get("command")
    exact_command = [
        str(expected_console.resolve(strict=False)),
        "waapi-server",
        str(sandbox_project),
        "--wamp-port",
        str(selected_port),
        "--http-port",
        "0",
    ]
    if (
        type(selected_port) is not int
        or not 1 <= selected_port <= 65535
        or command != exact_command
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness launch command or port is not exact"
        )

    process_pid = metadata.get("process_pid")
    wine_prefix = _strict_absolute_path(
        metadata.get("wine_prefix_path"),
        label="Wwise Wine prefix",
        kind=None,
    )
    cleanup = metadata.get("process_cleanup_details")
    if (
        type(process_pid) is not int
        or process_pid <= 0
        or metadata.get("process_cleanup_result") != "cleaned"
        or not isinstance(cleanup, Mapping)
        or cleanup.get("launch_pid") != process_pid
        or cleanup.get("wine_prefix") != str(wine_prefix)
        or cleanup.get("process_exited") is not True
        or cleanup.get("residual_processes") != []
        or wine_prefix != sandbox / ".wine-prefix"
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness process cleanup is incomplete or unproven"
        )
    detached_pids = cleanup.get("detached_cleanup_pids")
    wineserver_commands = cleanup.get("wineserver_commands")
    if (
        not isinstance(detached_pids, list)
        or not all(type(pid) is int and pid > 0 for pid in detached_pids)
        or len(detached_pids) != len(set(detached_pids))
        or not isinstance(wineserver_commands, list)
        or not all(
            isinstance(row, list)
            and bool(row)
            and all(isinstance(argument, str) and argument for argument in row)
            for row in wineserver_commands
        )
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness cleanup detail arrays are malformed"
        )

    terminal = error.splitlines()[-1]
    if (
        f"; port={selected_port};" not in terminal
        or f"argv={exact_command!r}" not in terminal
        or f"cwd={str(sandbox)!r}" not in terminal
        or f"WAMP server failed to start (port {selected_port})" not in terminal
    ):
        raise CampaignEvidenceError(
            "pre-session live readiness traceback is not bound to launch evidence"
        )


def _strict_absolute_path(
    value: Any,
    *,
    label: str,
    kind: str | None,
) -> Path:
    if not isinstance(value, str) or not value:
        raise CampaignEvidenceError(f"{label} path is absent")
    raw = Path(value).expanduser()
    if not raw.is_absolute() or raw.is_symlink():
        raise CampaignEvidenceError(f"{label} must be an absolute non-symlink path")
    try:
        resolved = raw.resolve(strict=True) if kind is not None else raw.resolve(strict=False)
    except OSError as exc:
        raise CampaignEvidenceError(f"{label} path cannot be resolved: {exc}") from exc
    if raw != resolved:
        raise CampaignEvidenceError(f"{label} path is not canonical")
    if kind == "directory" and not resolved.is_dir():
        raise CampaignEvidenceError(f"{label} is not a real directory")
    if kind == "file" and not resolved.is_file():
        raise CampaignEvidenceError(f"{label} is not a real file")
    return resolved


def _live_config_console_path(live_config: Path, *, version: str) -> Path:
    payload = load_strict_regular_json(live_config)
    versions = payload.get("versions") if isinstance(payload, Mapping) else None
    entry = versions.get(version) if isinstance(versions, Mapping) else None
    raw = entry.get("wwise_console") if isinstance(entry, Mapping) else None
    if not isinstance(raw, str) or not raw:
        raise CampaignEvidenceError(
            f"live config has no exact WwiseConsole binding for version {version}"
        )
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate.resolve(strict=False)


def _validate_run_config(
    value: Any,
    *,
    expected_sessions: Sequence[EvalSession],
    expected_pair_ids: Sequence[str],
    profile: str,
    skill_source: Path,
    suite_path: Path,
    live_config: Path,
    model: str,
    reasoning_effort: str,
    service_tier: str,
    version: str | None,
    offline_only: bool,
) -> None:
    if not isinstance(value, Mapping) or value.get("contract") != RUN_CONTRACT:
        raise CampaignEvidenceError("invalid child run-config contract")
    expected = {
        "profile": profile,
        "expected_session_count": len(expected_sessions),
        "case_ids": [],
        "versions": [version] if version is not None else [],
        "pair_ids": list(expected_pair_ids),
        "offline_only": offline_only,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "service_tier": service_tier,
        "memory": "disabled",
        "fresh_session_per_phase": True,
        "skill_source": str(Path(skill_source).resolve(strict=True)),
        "suite_path": str(Path(suite_path).resolve(strict=True)),
        "live_config": str(Path(live_config).resolve(strict=True)),
    }
    mismatches = {key: (value.get(key), expected_value) for key, expected_value in expected.items() if value.get(key) != expected_value}
    if mismatches:
        raise CampaignEvidenceError(f"child run-config mismatch: {mismatches}")


def _validate_summary(
    value: Any,
    *,
    expected_ids: tuple[str, ...],
    profile: str,
    returncode: int,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("contract") != RUN_CONTRACT:
        raise CampaignEvidenceError("invalid child summary contract")
    if value.get("profile") != profile or value.get("selected_session_count") != len(expected_ids):
        raise CampaignEvidenceError("child summary selection mismatch")
    executed = value.get("executed_session_ids")
    failed = value.get("failed_session_ids")
    pending = value.get("pending_session_ids")
    run_errors = value.get("run_errors")
    if not all(isinstance(item, list) for item in (executed, failed, pending, run_errors)):
        raise CampaignEvidenceError("child summary arrays are malformed")
    if not all(isinstance(item, str) for rows in (executed, failed, pending, run_errors) for item in rows):
        raise CampaignEvidenceError("child summary arrays must contain strings")
    executed_tuple = tuple(executed)
    if executed_tuple != expected_ids[: len(executed_tuple)]:
        raise CampaignEvidenceError("executed sessions are not an ordered selection prefix")
    if tuple(pending) != expected_ids[len(executed_tuple) :]:
        raise CampaignEvidenceError("pending sessions are not the exact ordered suffix")
    if value.get("executed_session_count") != len(executed_tuple):
        raise CampaignEvidenceError("executed session count mismatch")
    if len(failed) > 1 or (failed and (not executed or failed[0] != executed[-1])):
        raise CampaignEvidenceError("failed session must be the final executed session")
    all_pass = value.get("all_selected_passed")
    if returncode == 0 and all_pass is not True:
        raise CampaignEvidenceError("child exited zero without an all-pass summary")
    if returncode == 1 and all_pass is not False:
        raise CampaignEvidenceError("child exited one without a failing summary")
    if returncode not in {0, 1}:
        raise CampaignEvidenceError(f"matrix child exited unexpectedly: {returncode}")
    return value


def _validate_summary_against_verdicts(
    summary: Mapping[str, Any],
    *,
    verdicts: tuple[PhaseVerdict, ...],
    observations: tuple[dict[str, Any], ...],
) -> None:
    passed_count = sum(item.status == "PASS" for item in verdicts)
    if summary.get("passed_session_count") != passed_count:
        raise CampaignEvidenceError("summary passed count disagrees with recomputed verdicts")
    failed_ids = list(summary.get("failed_session_ids", []))
    nonpass = [item for item in verdicts if item.status != "PASS"]
    if nonpass:
        if failed_ids != [nonpass[-1].session_id]:
            raise CampaignEvidenceError("summary failed session disagrees with recomputed verdict")
    elif failed_ids:
        raise CampaignEvidenceError("summary declares failure but every executed phase passed")
    all_pass = (
        bool(verdicts)
        and not nonpass
        and summary.get("pending_session_ids") == []
        and summary.get("run_errors") == []
    )
    if summary.get("all_selected_passed") is not all_pass:
        raise CampaignEvidenceError("summary all-pass flag disagrees with recomputed evidence")
    if any(row["status"] == "PASS" and not row["phases"] for row in observations):
        raise CampaignEvidenceError("empty PASS unit observation")


def _build_unit_observations(
    sessions: tuple[EvalSession, ...],
    verdicts: tuple[PhaseVerdict, ...],
    executed_session_ids: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    verdict_by_id = {item.session_id: item for item in verdicts}
    executed_set = frozenset(executed_session_ids)
    grouped: dict[str, list[EvalSession]] = {}
    for session in sessions:
        grouped.setdefault(session.pair_id, []).append(session)
    observations: list[dict[str, Any]] = []
    for pair_id, pair_sessions in grouped.items():
        attempted = [session for session in pair_sessions if session.session_id in executed_set]
        if not attempted:
            continue
        phases = [verdict_by_id[session.session_id] for session in attempted]
        required_count = len(pair_sessions)
        if any(item.status == "BLOCKED" for item in phases):
            status = "BLOCKED"
        elif phases[-1].status == "FAIL" and all(item.status == "PASS" for item in phases[:-1]):
            status = "FAIL"
        elif phases[-1].status == "RETRYABLE" and all(item.status == "PASS" for item in phases[:-1]):
            status = "RETRYABLE"
        elif len(phases) == required_count and all(item.status == "PASS" for item in phases):
            status = "PASS"
        else:
            status = "BLOCKED"
        observations.append(
            {
                "unit_id": pair_id,
                "status": status,
                "phases": [item.phase_row() for item in phases],
            }
        )
    return tuple(observations)


def _validate_phase_identity(value: Any, *, session: EvalSession) -> None:
    if not isinstance(value, Mapping) or value.get("contract") != PHASE_CONTRACT:
        raise CampaignEvidenceError("invalid phase contract")
    expected = {
        "session_id": session.session_id,
        "pair_id": session.pair_id,
        "profile_id": session.profile_id,
        "case_id": session.case.id,
        "phase": session.phase,
        "version": session.version,
        "repetition": session.repetition,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise CampaignEvidenceError("phase identity does not match the selected suite session")


def _validate_grading_identity(value: Any, *, session: EvalSession) -> None:
    if not isinstance(value, Mapping):
        raise CampaignEvidenceError("grading evidence must be an object")
    expected = {
        "session_id": session.session_id,
        "case_id": session.case.id,
        "phase": session.phase,
        "version": session.version,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise CampaignEvidenceError("grading identity does not match the selected suite session")
    gates = value.get("gates")
    if not isinstance(gates, list) or not gates:
        raise CampaignEvidenceError("grading gate evidence is missing")
    gate_ids: list[str] = []
    failed_gate_ids: list[str] = []
    unknown_gate_ids: list[str] = []
    for gate in gates:
        if not isinstance(gate, Mapping) or not isinstance(gate.get("id"), str):
            raise CampaignEvidenceError("grading gate row is malformed")
        known = gate.get("known")
        passed = gate.get("passed")
        if type(known) is not bool or type(passed) is not bool:
            raise CampaignEvidenceError("grading gate known/passed values must be booleans")
        gate_id = gate["id"]
        gate_ids.append(gate_id)
        if not passed:
            failed_gate_ids.append(gate_id)
        if not known:
            unknown_gate_ids.append(gate_id)
    if gate_ids != list(session.hard_gates):
        raise CampaignEvidenceError("grading gates do not exactly match the declared hard gates")
    if value.get("failed_gate_ids") != failed_gate_ids:
        raise CampaignEvidenceError("grading failed_gate_ids disagree with gate rows")
    if value.get("unknown_gate_ids") != unknown_gate_ids:
        raise CampaignEvidenceError("grading unknown_gate_ids disagree with gate rows")
    aggregate_passed = bool(gates) and all(gate.get("passed") is True for gate in gates)
    if value.get("passed") is not aggregate_passed:
        raise CampaignEvidenceError("grading aggregate passed value disagrees with gate rows")
    if unknown_gate_ids:
        raise CampaignEvidenceError("grading contains an unknown declared hard gate")


def _valid_project_hash(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("algorithm") == "sha256"
        and value.get("strategy") == "full"
        and isinstance(value.get("digest"), str)
        and _SHA256_RE.fullmatch(value["digest"]) is not None
        and type(value.get("bytes_hashed")) is int
        and value["bytes_hashed"] >= 0
        and type(value.get("file_count")) is int
        and value["file_count"] >= 0
    )


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _command_option(command: Sequence[str], option: str) -> str:
    positions = [index for index, value in enumerate(command) if value == option]
    if len(positions) != 1 or positions[0] + 1 >= len(command):
        raise CampaignEvidenceError(f"Wwise command requires exactly one {option}")
    return command[positions[0] + 1]


def _safe_session_name(session_id: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in session_id)
    return safe.strip("-")


def _is_expected_skill_link(path: Path, *, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    suffix = ("agent-workspace", ".agents", "skills", "waapi-skill")
    return len(parts) >= len(suffix) + 2 and tuple(parts[-4:]) == suffix and "sessions" in parts[:-4]


def _reject_all_symlinks(root: Path) -> None:
    def walk(directory: Path) -> None:
        try:
            entries = os.scandir(directory)
        except OSError as exc:
            raise CampaignEvidenceError(f"cannot scan child evidence {directory}: {exc}") from exc
        with entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                path = Path(entry.path)
                if stat.S_ISLNK(info.st_mode) or is_link_or_junction(path):
                    raise CampaignEvidenceError(
                        f"link or junction remained in child evidence: {path}"
                    )
                if stat.S_ISDIR(info.st_mode):
                    walk(path)
                elif not stat.S_ISREG(info.st_mode):
                    raise CampaignEvidenceError(f"unsupported child evidence entry: {path}")

    walk(root)


def _exclusive_write(path: Path, data: bytes) -> None:
    flags = binary_file_open_flags(os.O_WRONLY, os.O_CREAT, os.O_EXCL)
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _strict_json_loads(text: str, *, source: Path) -> Any:
    def reject_constant(value: str) -> Any:
        raise CampaignEvidenceError(f"non-finite JSON constant in {source}: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CampaignEvidenceError(f"duplicate JSON key in {source}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, parse_constant=reject_constant, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise CampaignEvidenceError(f"invalid JSON in {source}: {exc}") from exc


__all__ = [
    "AUTO_RETRY_CATEGORIES",
    "BLOCKED_INFRASTRUCTURE_CATEGORIES",
    "ChildValidation",
    "LIVE_READINESS_RETRY_CATEGORY",
    "PAUSE_RETRY_CATEGORIES",
    "PhaseVerdict",
    "SKILL_COPY_ATTESTATION_CONTRACT",
    "classify_phase",
    "load_strict_regular_json",
    "replace_expected_skill_symlinks",
    "validate_child_run",
]

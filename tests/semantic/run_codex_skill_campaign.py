#!/usr/bin/env python3
"""Run or resume an immutable fresh-Codex WAAPI semantic campaign.

Each child process is the existing v2 semantic matrix runner.  A campaign
groups all currently pending pairs for one live Wwise version into one child,
preserving the matrix runner's one-Wwise-lifecycle-per-version behavior while
adding append-only attempts, strict resume compatibility, evidence sealing,
and narrow pre-agent-action retries.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import os
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
WORKSPACE_ROOT = SKILL_ROOT.parent / "waapi-skill-workspace"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.semantic import run_codex_skill_matrix as matrix  # noqa: E402
from tests.semantic.support.codex_campaign import (  # noqa: E402
    ATTEMPT_MANIFEST_FILE,
    CampaignEvidenceError,
    atomic_write_json_with_digest,
    canonical_json_bytes,
    consolidate_units,
    create_attempt,
    create_immutable_campaign_config,
    list_campaign_attempts,
    load_immutable_campaign_config,
    seal_attempt,
    sha256_file,
    stable_tree_sha256,
    verify_attempt_seal,
)
from tests.semantic.support.codex_campaign_runner import (  # noqa: E402
    AUTO_RETRY_CATEGORIES,
    PAUSE_RETRY_CATEGORIES,
    ChildValidation,
    PhaseVerdict,
    replace_expected_skill_symlinks,
    validate_child_run,
)
from tests.semantic.support.codex_eval_suite import (  # noqa: E402
    CASE_IDS,
    PROFILE_IDS,
    SUPPORTED_VERSIONS,
    EvalSession,
    EvalSuiteError,
    load_eval_suite,
)


CAMPAIGN_MARKER_CONTRACT = "waapi-skill.codex-semantic-campaign-root/v1"
CAMPAIGN_MARKER_FILE = ".waapi-semantic-campaign-root.json"
CAMPAIGN_EFFECTIVE_CONTRACT = "waapi-skill.codex-semantic-campaign-effective/v1"
CHILD_EXECUTION_CONTRACT = "waapi-skill.codex-semantic-campaign-child/v1"
CHILD_CLASSIFICATION_CONTRACT = "waapi-skill.codex-semantic-child-classification/v1"
CONSOLIDATED_SUMMARY_FILE = "consolidated-summary.json"
LOCK_FILE = ".campaign.lock"
LOCK_OWNER_FILE = ".campaign-lock-owner.json"
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2
EXIT_BLOCKED = 3
EXIT_PENDING = 75
EXIT_INTERRUPTED = 130


class CampaignConfigError(RuntimeError):
    """The requested invocation does not match a safe immutable campaign."""


@dataclass(frozen=True, slots=True)
class CampaignOptions:
    campaign_root: Path
    resume: bool
    verify_only: bool
    profile: str
    suite_path: Path
    skill_source: Path
    codex_binary: Path
    auth_json: Path
    live_config: Path
    model: str
    reasoning_effort: str
    service_tier: str
    timeout_seconds: float
    case_ids: tuple[str, ...]
    versions: tuple[str, ...]
    pair_ids: tuple[str, ...]
    offline_only: bool
    lock_timeout_seconds: float
    max_pre_action_retries: int


@dataclass(frozen=True, slots=True)
class ChildGroup:
    group_id: str
    version: str | None
    pair_ids: tuple[str, ...]
    sessions: tuple[EvalSession, ...]

    @property
    def offline_only(self) -> bool:
        return self.version is None


class CampaignLock:
    def __init__(self, root: Path, *, timeout_seconds: float) -> None:
        self.root = Path(root)
        self.timeout_seconds = timeout_seconds
        self._descriptor: int | None = None

    def __enter__(self) -> "CampaignLock":
        lock_path = self.root / LOCK_FILE
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise CampaignConfigError(f"campaign lock is not a regular file: {lock_path}")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise CampaignConfigError(
                        f"campaign writer lock remained busy for {self.timeout_seconds:.1f}s: {lock_path}"
                    )
                time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
        self._descriptor = descriptor
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()} started={utc_now()}\n".encode("utf-8"))
        os.fsync(descriptor)
        atomic_write_json_with_digest(
            self.root / LOCK_OWNER_FILE,
            {
                "pid": os.getpid(),
                "started_at": utc_now(),
                "campaign_root": str(self.root.resolve(strict=True)),
            },
        )
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        if self._descriptor is None:
            return
        try:
            os.ftruncate(self._descriptor, 0)
            os.fsync(self._descriptor)
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._descriptor = None


class InterruptLatch:
    """Defer SIGINT/SIGTERM until the active child reaches an evidence boundary."""

    def __init__(self) -> None:
        self.requested = False
        self.signal_number: int | None = None
        self._previous: dict[int, Any] = {}

    def __enter__(self) -> "InterruptLatch":
        for number in (signal.SIGINT, signal.SIGTERM):
            self._previous[number] = signal.getsignal(number)
            signal.signal(number, self._handle)
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        for number, previous in self._previous.items():
            signal.signal(number, previous)

    def _handle(self, number: int, _frame: object) -> None:
        self.requested = True
        self.signal_number = number
        print(
            f"[campaign] received signal {number}; deferring stop until the current child is sealed",
            flush=True,
        )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        options = parse_args(argv)
        return run_campaign(options)
    except (CampaignConfigError, EvalSuiteError) as exc:
        print(f"[campaign-config] {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except CampaignEvidenceError as exc:
        print(f"[campaign-blocked] {exc}", file=sys.stderr)
        return EXIT_BLOCKED


def run_campaign(options: CampaignOptions) -> int:
    try:
        suite = load_eval_suite(options.suite_path)
        sessions = matrix.select_sessions(
            suite.expand_profile(options.profile),
            case_ids=options.case_ids,
            versions=options.versions,
            pair_ids=options.pair_ids,
            offline_only=options.offline_only,
        )
    except SystemExit as exc:
        raise CampaignConfigError(str(exc)) from exc
    if not sessions:
        raise CampaignConfigError("no semantic sessions matched the requested filters")
    required_units = required_unit_map(sessions)
    try:
        effective = build_effective_config(options, sessions=sessions, required_units=required_units)
    except (CampaignEvidenceError, OSError, subprocess.SubprocessError) as exc:
        raise CampaignConfigError(f"cannot fingerprint campaign inputs: {exc}") from exc

    root = prepare_campaign_root(options)
    with CampaignLock(root, timeout_seconds=options.lock_timeout_seconds):
        if options.resume:
            config = load_immutable_campaign_config(root)
            if config.get("effective") != effective:
                raise CampaignConfigError("resume invocation does not exactly match immutable campaign config")
            expected_effective_hash = hashlib.sha256(canonical_json_bytes(effective)).hexdigest()
            if config.get("effective_sha256") != expected_effective_hash:
                raise CampaignEvidenceError("campaign effective config digest is invalid")
            verify_campaign_marker(root, campaign_id=config.get("campaign_id"))
        else:
            config = create_immutable_campaign_config(
                root,
                {
                    "created_at": utc_now(),
                    "effective": effective,
                    "effective_sha256": hashlib.sha256(canonical_json_bytes(effective)).hexdigest(),
                },
            )
            write_campaign_marker(root, campaign_id=str(config["campaign_id"]))

        manifests = load_verified_attempts(root)
        consolidated = consolidate_units(required_units, manifests)
        write_consolidated(root, consolidated)
        terminal = consolidated_exit(consolidated)
        if terminal is not None:
            return terminal
        if options.verify_only:
            return EXIT_PENDING

        candidate_sha256 = str(effective["candidate"]["tree_sha256"])
        assert_effective_inputs_frozen(options, effective=effective)
        retry_round = 0
        with InterruptLatch() as interrupts:
            while True:
                scheduled = tuple(
                    consolidated["pending_unit_ids"] + consolidated["retryable_unit_ids"]
                )
                if not scheduled:
                    terminal = consolidated_exit(consolidated)
                    return terminal if terminal is not None else EXIT_PENDING
                attempt_id, attempt_root = create_attempt(root)
                print(
                    f"[campaign] {attempt_id} scheduled_units={len(scheduled)}",
                    flush=True,
                )
                observations: list[dict[str, Any]] = []
                current_retry_categories: list[str] = []
                attempt_blocked = False
                groups = build_child_groups(sessions, scheduled_unit_ids=scheduled)
                for group in groups:
                    if interrupts.requested:
                        break
                    try:
                        assert_effective_inputs_frozen(options, effective=effective)
                    except CampaignEvidenceError as exc:
                        attempt_blocked = True
                        validation = blocked_child_validation(group, reason=str(exc))
                        observations.extend(validation.observations)
                        atomic_write_json_with_digest(
                            attempt_root / "candidate-drift.json",
                            {"group_id": group.group_id, "error": str(exc), "recorded_at": utc_now()},
                        )
                        break
                    group_root = attempt_root / "runs" / group.group_id
                    matrix_root = group_root / "matrix"
                    group_root.mkdir(parents=True, exist_ok=False)
                    argv_child = build_child_argv(options, group=group, matrix_root=matrix_root)
                    atomic_write_json_with_digest(
                        group_root / "child-request.json",
                        {
                            "contract": CHILD_EXECUTION_CONTRACT,
                            "group_id": group.group_id,
                            "version": group.version,
                            "pair_ids": list(group.pair_ids),
                            "session_ids": [session.session_id for session in group.sessions],
                            "argv": argv_child,
                            "started_at": utc_now(),
                        },
                    )
                    print(
                        f"[campaign] start group={group.group_id} pairs={len(group.pair_ids)} "
                        f"sessions={len(group.sessions)}",
                        flush=True,
                    )
                    completed = run_child(argv_child, cwd=REPO_ROOT)
                    (group_root / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
                    (group_root / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
                    atomic_write_json_with_digest(
                        group_root / "child-result.json",
                        {
                            "contract": CHILD_EXECUTION_CONTRACT,
                            "group_id": group.group_id,
                            "returncode": completed.returncode,
                            "completed_at": utc_now(),
                        },
                    )
                    print(
                        f"[campaign] end group={group.group_id} returncode={completed.returncode}",
                        flush=True,
                    )
                    replaced_links: tuple[str, ...] = ()
                    try:
                        observed_candidate_sha256 = current_candidate_sha256(
                            options.skill_source,
                            effective=effective,
                        )
                        replaced_links = replace_expected_skill_symlinks(
                            group_root,
                            skill_source=options.skill_source,
                            candidate_sha256=observed_candidate_sha256,
                        )
                        if observed_candidate_sha256 != candidate_sha256:
                            raise CampaignEvidenceError(
                                "candidate Skill changed during child execution: "
                                f"expected={candidate_sha256} actual={observed_candidate_sha256}"
                            )
                        validation = validate_child_run(
                            matrix_root,
                            expected_sessions=group.sessions,
                            expected_pair_ids=group.pair_ids,
                            profile=options.profile,
                            skill_source=options.skill_source,
                            suite_path=options.suite_path,
                            live_config=options.live_config,
                            model=options.model,
                            reasoning_effort=options.reasoning_effort,
                            service_tier=options.service_tier,
                            version=group.version,
                            offline_only=group.offline_only,
                            returncode=completed.returncode,
                        )
                        assert_effective_inputs_frozen(options, effective=effective)
                    except (CampaignEvidenceError, OSError, TypeError, ValueError) as exc:
                        attempt_blocked = True
                        validation = blocked_child_validation(group, reason=str(exc))
                    observations.extend(validation.observations)
                    current_retry_categories.extend(validation.retry_categories)
                    atomic_write_json_with_digest(
                        group_root / "classification.json",
                        {
                            "contract": CHILD_CLASSIFICATION_CONTRACT,
                            "group_id": group.group_id,
                            "skill_link_attestations": list(replaced_links),
                            **validation.as_dict(),
                        },
                    )
                    if attempt_blocked or validation.has_blocked or validation.has_fail or validation.has_retryable:
                        break

                if interrupts.requested and not observations:
                    # No child began after the signal; an empty sealed attempt is
                    # still valid append-only evidence and leaves every unit pending.
                    atomic_write_json_with_digest(
                        attempt_root / "interrupted.json",
                        {"signal": interrupts.signal_number, "recorded_at": utc_now()},
                    )
                try:
                    assert_effective_inputs_frozen(options, effective=effective)
                except CampaignEvidenceError as exc:
                    atomic_write_json_with_digest(
                        attempt_root / "candidate-drift-before-seal.json",
                        {"error": str(exc), "recorded_at": utc_now()},
                    )
                    if observations:
                        observations[-1] = {**observations[-1], "status": "BLOCKED"}
                    else:
                        first = next(session for session in sessions if session.pair_id in scheduled)
                        observations.append(
                            {
                                "unit_id": first.pair_id,
                                "status": "BLOCKED",
                                "phases": [{"phase": first.phase, "status": "BLOCKED"}],
                            }
                        )
                manifest = seal_attempt(attempt_root, observations)
                verified = verify_attempt_seal(attempt_root)
                if verified != manifest:
                    raise CampaignEvidenceError(f"sealed attempt failed immediate verification: {attempt_id}")
                manifests.append(verified)
                consolidated = consolidate_units(required_units, manifests)
                write_consolidated(root, consolidated)
                print_status(consolidated)
                if interrupts.requested:
                    return EXIT_INTERRUPTED
                terminal = consolidated_exit(consolidated)
                if terminal is not None:
                    return terminal
                if not consolidated["retryable_unit_ids"]:
                    return EXIT_PENDING
                if any(category in PAUSE_RETRY_CATEGORIES for category in current_retry_categories):
                    return EXIT_PENDING
                auto_categories = AUTO_RETRY_CATEGORIES | {"prompt_audit_timeout_before_exec"}
                if not current_retry_categories or any(
                    category not in auto_categories for category in current_retry_categories
                ):
                    return EXIT_PENDING
                if retry_round >= options.max_pre_action_retries:
                    return EXIT_PENDING
                retry_round += 1
                print(
                    f"[campaign] retrying pre-action infrastructure units round={retry_round}",
                    flush=True,
                )


def prepare_campaign_root(options: CampaignOptions) -> Path:
    root = options.campaign_root.expanduser().resolve(strict=False)
    allowed = WORKSPACE_ROOT.resolve(strict=False)
    if root == allowed:
        raise CampaignConfigError(f"campaign root must be a named child below {allowed}")
    try:
        relative = root.relative_to(allowed)
    except ValueError as exc:
        raise CampaignConfigError(f"campaign root must be below {allowed}: {root}") from exc
    if not relative.parts:
        raise CampaignConfigError("campaign root must be a named child directory")
    if options.resume:
        if not root.is_dir() or root.is_symlink():
            raise CampaignConfigError(f"resume campaign root is missing or not a real directory: {root}")
    else:
        if root.exists():
            raise CampaignConfigError(f"new campaign root already exists; use --resume: {root}")
        root.mkdir(parents=True, exist_ok=False)
    return root


def build_effective_config(
    options: CampaignOptions,
    *,
    sessions: Sequence[EvalSession],
    required_units: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    skill_excludes = (".venv", "__pycache__", ".pytest_cache", ".DS_Store", ".coverage")
    harness_excludes = ("__pycache__", ".pytest_cache", ".DS_Store", ".coverage")
    interpreter = Path(sys.executable).resolve(strict=True)
    codex_version = subprocess.run(
        [str(options.codex_binary), "--version"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    if codex_version.returncode != 0 or not codex_version.stdout.strip():
        raise CampaignConfigError(
            f"cannot fingerprint Codex binary: {codex_version.stderr.strip() or codex_version.returncode}"
        )
    distributions = sorted(
        {
            (
                str(distribution.metadata.get("Name") or "").casefold(),
                str(distribution.version),
            )
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name")
        }
    )
    session_rows = [
        {
            "session_id": session.session_id,
            "pair_id": session.pair_id,
            "profile_id": session.profile_id,
            "case_id": session.case.id,
            "version": session.version,
            "phase": session.phase,
            "repetition": session.repetition,
            "gateway_steps": list(session.gateway_steps),
            "hard_gates": list(session.hard_gates),
        }
        for session in sessions
    ]
    return {
        "contract": CAMPAIGN_EFFECTIVE_CONTRACT,
        "selection": {
            "profile": options.profile,
            "case_ids": list(options.case_ids),
            "versions": list(options.versions),
            "pair_ids": list(options.pair_ids),
            "offline_only": options.offline_only,
            "sessions": session_rows,
            "required_units": {key: list(value) for key, value in required_units.items()},
        },
        "candidate": {
            "path": str(options.skill_source),
            "tree_sha256": stable_tree_sha256(options.skill_source, exclude_names=skill_excludes),
            "excluded_names": list(skill_excludes),
        },
        "suite": {"path": str(options.suite_path), "sha256": sha256_file(options.suite_path)},
        "harness": {
            "semantic_tree_sha256": stable_tree_sha256(
                REPO_ROOT / "tests" / "semantic", exclude_names=harness_excludes
            ),
            "destructive_support_tree_sha256": stable_tree_sha256(
                REPO_ROOT / "tests" / "destructive" / "support", exclude_names=harness_excludes
            ),
            "excluded_names": list(harness_excludes),
        },
        "live_config": {
            "path": str(options.live_config),
            "sha256": sha256_file(options.live_config),
        },
        "codex": {
            "path": str(options.codex_binary),
            "sha256": sha256_file(options.codex_binary),
            "version": codex_version.stdout.strip(),
            "model": options.model,
            "reasoning_effort": options.reasoning_effort,
            "service_tier": options.service_tier,
            "timeout_seconds": options.timeout_seconds,
            "memory": "disabled",
            "fresh_session_per_phase": True,
        },
        "auth": {
            "mode": "ephemeral-codex-home-auth-link",
            "path": str(options.auth_json),
            "content_hashed": False,
        },
        "runtime": {
            "interpreter": str(interpreter),
            "interpreter_sha256": sha256_file(interpreter),
            "python_version": sys.version,
            "platform": sys.platform,
            "distributions": [[name, version] for name, version in distributions],
        },
        "retry_policy": {
            "max_pre_action_retries_per_invocation": options.max_pre_action_retries,
            "auto_categories": sorted(AUTO_RETRY_CATEGORIES | {"prompt_audit_timeout_before_exec"}),
            "pause_categories": sorted(PAUSE_RETRY_CATEGORIES),
        },
    }


def current_candidate_sha256(skill_source: Path, *, effective: Mapping[str, Any]) -> str:
    candidate = effective.get("candidate")
    if not isinstance(candidate, Mapping):
        raise CampaignEvidenceError("campaign candidate config is malformed")
    excludes = candidate.get("excluded_names")
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise CampaignEvidenceError("campaign candidate exclusions are malformed")
    return stable_tree_sha256(skill_source, exclude_names=tuple(excludes))


def assert_candidate_frozen(skill_source: Path, *, effective: Mapping[str, Any]) -> None:
    candidate = effective.get("candidate")
    if not isinstance(candidate, Mapping) or not isinstance(candidate.get("tree_sha256"), str):
        raise CampaignEvidenceError("campaign candidate config is malformed")
    expected = str(candidate["tree_sha256"])
    actual = current_candidate_sha256(skill_source, effective=effective)
    if actual != expected:
        raise CampaignEvidenceError(
            f"candidate Skill drifted from immutable campaign hash: expected={expected} actual={actual}"
        )


def assert_effective_inputs_frozen(
    options: CampaignOptions,
    *,
    effective: Mapping[str, Any],
) -> None:
    """Re-hash every executable/evidence input at each child boundary."""

    assert_candidate_frozen(options.skill_source, effective=effective)

    def require_section(name: str) -> Mapping[str, Any]:
        section = effective.get(name)
        if not isinstance(section, Mapping):
            raise CampaignEvidenceError(f"campaign {name} fingerprint is malformed")
        return section

    suite = require_section("suite")
    live_config = require_section("live_config")
    codex = require_section("codex")
    runtime = require_section("runtime")
    harness = require_section("harness")
    file_bindings = (
        ("suite", options.suite_path, suite),
        ("live config", options.live_config, live_config),
        ("Codex binary", options.codex_binary, codex),
    )
    for label, path, section in file_bindings:
        if section.get("path") != str(path) or section.get("sha256") != sha256_file(path):
            raise CampaignEvidenceError(f"{label} drifted from the immutable campaign fingerprint")

    interpreter = Path(sys.executable).resolve(strict=True)
    if (
        runtime.get("interpreter") != str(interpreter)
        or runtime.get("interpreter_sha256") != sha256_file(interpreter)
    ):
        raise CampaignEvidenceError("Python interpreter drifted from the immutable campaign fingerprint")
    excludes = harness.get("excluded_names")
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise CampaignEvidenceError("campaign harness exclusions are malformed")
    excluded_names = tuple(excludes)
    semantic_hash = stable_tree_sha256(
        REPO_ROOT / "tests" / "semantic", exclude_names=excluded_names
    )
    destructive_hash = stable_tree_sha256(
        REPO_ROOT / "tests" / "destructive" / "support", exclude_names=excluded_names
    )
    if harness.get("semantic_tree_sha256") != semantic_hash:
        raise CampaignEvidenceError("semantic harness drifted from the immutable campaign fingerprint")
    if harness.get("destructive_support_tree_sha256") != destructive_hash:
        raise CampaignEvidenceError(
            "destructive support harness drifted from the immutable campaign fingerprint"
        )


def required_unit_map(sessions: Sequence[EvalSession]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for session in sessions:
        grouped.setdefault(session.pair_id, []).append(session.phase)
    return {pair_id: tuple(phases) for pair_id, phases in grouped.items()}


def build_child_groups(
    sessions: Sequence[EvalSession],
    *,
    scheduled_unit_ids: Sequence[str],
) -> tuple[ChildGroup, ...]:
    scheduled = frozenset(scheduled_unit_ids)
    selected = tuple(session for session in sessions if session.pair_id in scheduled)
    groups: list[ChildGroup] = []
    offline = tuple(session for session in selected if session.case.id in matrix.OFFLINE_CASE_IDS)
    if offline:
        groups.append(
            ChildGroup(
                group_id="offline",
                version=None,
                pair_ids=ordered_unique(session.pair_id for session in offline),
                sessions=offline,
            )
        )
    for version in SUPPORTED_VERSIONS:
        live = tuple(
            session
            for session in selected
            if session.case.id not in matrix.OFFLINE_CASE_IDS and session.version == version
        )
        if live:
            groups.append(
                ChildGroup(
                    group_id=f"live-{version.replace('.', '-')}",
                    version=version,
                    pair_ids=ordered_unique(session.pair_id for session in live),
                    sessions=live,
                )
            )
    grouped_ids = {session.session_id for group in groups for session in group.sessions}
    if grouped_ids != {session.session_id for session in selected}:
        raise CampaignEvidenceError("scheduled sessions did not map to exactly one child group")
    return tuple(groups)


def build_child_argv(
    options: CampaignOptions,
    *,
    group: ChildGroup,
    matrix_root: Path,
) -> list[str]:
    argv = [
        sys.executable,
        str(REPO_ROOT / "tests" / "semantic" / "run_codex_skill_matrix.py"),
        "--profile",
        options.profile,
        "--suite",
        str(options.suite_path),
        "--iteration-root",
        str(matrix_root),
        "--skill-source",
        str(options.skill_source),
        "--codex-binary",
        str(options.codex_binary),
        "--auth-json",
        str(options.auth_json),
        "--live-config",
        str(options.live_config),
        "--model",
        options.model,
        "--reasoning-effort",
        options.reasoning_effort,
        "--service-tier",
        options.service_tier,
        "--timeout",
        str(options.timeout_seconds),
    ]
    if group.offline_only:
        argv.append("--offline-only")
    else:
        argv.extend(("--version", str(group.version)))
    for pair_id in group.pair_ids:
        argv.extend(("--pair-id", pair_id))
    return argv


def run_child(argv: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        start_new_session=True,
    )


def blocked_child_validation(group: ChildGroup, *, reason: str) -> ChildValidation:
    first = group.sessions[0]
    verdict = {
        "unit_id": first.pair_id,
        "status": "BLOCKED",
        "phases": [{"phase": first.phase, "status": "BLOCKED"}],
    }
    phase_verdict = PhaseVerdict(
        session_id=first.session_id,
        phase=first.phase,
        status="BLOCKED",
        reason=reason,
    )
    return ChildValidation(
        observations=(verdict,),
        phase_verdicts=(phase_verdict,),
        executed_session_ids=(),
        pending_session_ids=tuple(session.session_id for session in group.sessions),
        retry_categories=(),
        summary={"validation_error": reason},
    )


def load_verified_attempts(root: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for attempt in list_campaign_attempts(root):
        if not (attempt / ATTEMPT_MANIFEST_FILE).is_file():
            raise CampaignEvidenceError(f"campaign contains an unsealed attempt: {attempt}")
        manifests.append(verify_attempt_seal(attempt))
    return manifests


def write_campaign_marker(root: Path, *, campaign_id: str) -> None:
    atomic_write_json_with_digest(
        root / CAMPAIGN_MARKER_FILE,
        {
            "contract": CAMPAIGN_MARKER_CONTRACT,
            "campaign_id": campaign_id,
            "campaign_root": str(root.resolve(strict=True)),
            "created_at": utc_now(),
        },
    )


def verify_campaign_marker(root: Path, *, campaign_id: Any) -> None:
    from tests.semantic.support.codex_campaign import load_verified_json

    marker = load_verified_json(root / CAMPAIGN_MARKER_FILE)
    if (
        not isinstance(marker, Mapping)
        or marker.get("contract") != CAMPAIGN_MARKER_CONTRACT
        or marker.get("campaign_id") != campaign_id
        or marker.get("campaign_root") != str(root.resolve(strict=True))
    ):
        raise CampaignEvidenceError("campaign root marker is invalid or misbound")


def write_consolidated(root: Path, consolidated: Mapping[str, Any]) -> None:
    atomic_write_json_with_digest(root / CONSOLIDATED_SUMMARY_FILE, dict(consolidated))


def consolidated_exit(consolidated: Mapping[str, Any]) -> int | None:
    if consolidated.get("blocked_unit_ids"):
        return EXIT_BLOCKED
    if consolidated.get("failed_unit_ids"):
        return EXIT_FAIL
    if consolidated.get("all_selected_passed") is True:
        return EXIT_PASS
    return None


def print_status(consolidated: Mapping[str, Any]) -> None:
    print(
        "[campaign] status "
        f"pass={len(consolidated['passed_unit_ids'])} "
        f"pending={len(consolidated['pending_unit_ids'])} "
        f"retryable={len(consolidated['retryable_unit_ids'])} "
        f"fail={len(consolidated['failed_unit_ids'])} "
        f"blocked={len(consolidated['blocked_unit_ids'])}",
        flush=True,
    )


def ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values))


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args(argv: Sequence[str] | None) -> CampaignOptions:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--profile", choices=PROFILE_IDS, default="screening")
    parser.add_argument("--suite", default=str(matrix.DEFAULT_SUITE))
    parser.add_argument("--skill-source", default=str(matrix.SKILL_ROOT))
    parser.add_argument("--codex-binary", default=str(matrix.DEFAULT_CODEX_BINARY))
    parser.add_argument("--auth-json", default=str(matrix.DEFAULT_AUTH_JSON))
    parser.add_argument("--live-config", default=str(matrix.DEFAULT_LIVE_CONFIG))
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh", "ultra"),
        default="medium",
    )
    parser.add_argument("--service-tier", default="priority")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--case-id", action="append", choices=CASE_IDS, default=[])
    parser.add_argument("--version", action="append", choices=SUPPORTED_VERSIONS, default=[])
    parser.add_argument("--pair-id", action="append", default=[])
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--lock-timeout", type=float, default=10.0)
    parser.add_argument("--max-pre-action-retries", type=int, default=1)
    args = parser.parse_args(argv)
    if args.verify_only and not args.resume:
        parser.error("--verify-only requires --resume")
    if args.timeout <= 0 or args.lock_timeout <= 0:
        parser.error("--timeout and --lock-timeout must be greater than zero")
    if args.max_pre_action_retries < 0:
        parser.error("--max-pre-action-retries must be zero or greater")
    for name, values in (
        ("--case-id", args.case_id),
        ("--version", args.version),
        ("--pair-id", args.pair_id),
    ):
        if len(set(values)) != len(values):
            parser.error(f"{name} values must be unique")
    try:
        suite_path = Path(args.suite).expanduser().resolve(strict=True)
        skill_source = Path(args.skill_source).expanduser().resolve(strict=True)
        codex_binary = Path(args.codex_binary).expanduser().resolve(strict=True)
        auth_json = Path(args.auth_json).expanduser().resolve(strict=True)
        live_config = Path(args.live_config).expanduser().resolve(strict=True)
    except OSError as exc:
        parser.error(str(exc))
    return CampaignOptions(
        campaign_root=Path(args.campaign_root).expanduser().resolve(strict=False),
        resume=bool(args.resume),
        verify_only=bool(args.verify_only),
        profile=str(args.profile),
        suite_path=suite_path,
        skill_source=skill_source,
        codex_binary=codex_binary,
        auth_json=auth_json,
        live_config=live_config,
        model=str(args.model),
        reasoning_effort=str(args.reasoning_effort),
        service_tier=str(args.service_tier),
        timeout_seconds=float(args.timeout),
        case_ids=tuple(str(value) for value in args.case_id),
        versions=tuple(str(value) for value in args.version),
        pair_ids=tuple(str(value) for value in args.pair_id),
        offline_only=bool(args.offline_only),
        lock_timeout_seconds=float(args.lock_timeout),
        max_pre_action_retries=int(args.max_pre_action_retries),
    )


if __name__ == "__main__":
    raise SystemExit(main())

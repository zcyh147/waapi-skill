"""Per-scenario Wwise sandbox lifecycle for executable v3 semantic cases.

Every v3 scenario owns a fresh project copy, Wwise process, asset/output root,
and source-project proof.  Passing cases remove all owned runtime state after
the independent oracle has been archived.  Failed or indeterminate cases are
sealed in place and never reused.  Lifecycle, cleanup, source-integrity, or
residual-process failures are infrastructure blockers rather than ordinary
semantic failures.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from tests.destructive.support.live_environment import require_live_environment
from tests.destructive.support.sandbox_fixture import (
    LiveSandboxLock,
    ProjectHash,
    SandboxProject,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from tests.semantic.support.codex_campaign import (
    stable_tree_manifest,
    stable_tree_sha256,
)
from tests.semantic.support.codex_filesystem_security import (
    path_is_link_or_reparse,
)
from wwise_waapi.headless import HeadlessLifecycle


SCENARIO_LIFECYCLE_CONTRACT = "waapi-skill.codex-semantic-scenario-lifecycle/v3"
SCENARIO_START_FAILURE_CONTRACT = (
    "waapi-skill.codex-semantic-scenario-start-failure/v3"
)
SCENARIO_QUARANTINE_CONTRACT = "waapi-skill.codex-semantic-scenario-quarantine/v3"
SCENARIO_LAUNCH_ENVIRONMENT_ARCHIVE_CONTRACT = (
    "waapi-skill.codex-semantic-launch-environment-archive/v1"
)
SCENARIO_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED", "INDETERMINATE"})
GLOBAL_LIVE_LIFECYCLE_LOCK_ROOT = (
    Path(__file__).resolve().parents[3]
    / ".waapi-skill-state"
    / "runtime"
    / "wwise-live-lifecycle-lock"
)


class ScenarioLifecycleError(RuntimeError):
    """A scenario lifecycle cannot provide trustworthy isolation evidence."""


class ScenarioLifecycleStartError(ScenarioLifecycleError):
    """Start failed after case allocation, with sealed teardown/source proof."""

    def __init__(
        self,
        *,
        stage: str,
        primary_error: str,
        evidence_path: Path | None,
        errors: tuple[str, ...],
        unsafe_to_continue: bool,
    ) -> None:
        self.stage = stage
        self.primary_error = primary_error
        self.evidence_path = evidence_path
        self.errors = errors
        self.unsafe_to_continue = unsafe_to_continue
        suffix = " campaign must abort" if unsafe_to_continue else ""
        super().__init__(
            f"scenario start failed at {stage}: {primary_error}; "
            f"start-proof-errors={errors!r};{suffix}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": SCENARIO_START_FAILURE_CONTRACT,
            "stage": self.stage,
            "primary_error": self.primary_error,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "errors": list(self.errors),
            "unsafe_to_continue": self.unsafe_to_continue,
        }


@dataclass(frozen=True, slots=True)
class ScenarioRuntime:
    scenario_id: str
    version: str
    scenario_root: Path
    evidence_root: Path
    owned_root: Path
    asset_root: Path
    io_root: Path
    sandbox: SandboxProject
    lifecycle: HeadlessLifecycle
    runner_environment: Mapping[str, str]
    source_hash_before: ProjectHash
    source_mtime_before_ns: int

    @property
    def host(self) -> str:
        return self.lifecycle.host

    @property
    def port(self) -> int:
        if self.lifecycle.port is None:
            raise ScenarioLifecycleError("live lifecycle has no WAAPI port")
        return self.lifecycle.port


@dataclass(frozen=True, slots=True)
class ScenarioLifecycleResult:
    scenario_id: str
    version: str
    requested_status: str
    final_status: str
    sandbox_retained: bool
    source_hash_before: ProjectHash | None
    source_hash_after: ProjectHash | None
    source_mtime_before_ns: int | None
    source_mtime_after_ns: int | None
    errors: tuple[str, ...]
    quarantine_path: str | None

    @property
    def blocked(self) -> bool:
        return self.final_status == "BLOCKED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": SCENARIO_LIFECYCLE_CONTRACT,
            "scenario_id": self.scenario_id,
            "version": self.version,
            "requested_status": self.requested_status,
            "final_status": self.final_status,
            "sandbox_retained": self.sandbox_retained,
            "source_hash_before": (
                asdict(self.source_hash_before) if self.source_hash_before else None
            ),
            "source_hash_after": (
                asdict(self.source_hash_after) if self.source_hash_after else None
            ),
            "source_mtime_before_ns": self.source_mtime_before_ns,
            "source_mtime_after_ns": self.source_mtime_after_ns,
            "errors": list(self.errors),
            "quarantine_path": self.quarantine_path,
        }


PrelaunchHook = Callable[[SandboxProject, Path, Path], None]
PostShutdownHook = Callable[[ScenarioRuntime], None]

_ISOLATED_PATH_ENV_KEYS = frozenset(
    {
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)
_RESERVED_LAUNCH_ENV_KEYS = frozenset(
    {
        "WINEPREFIX",
        "WWISE_DESTRUCTIVE",
        "WWISE_FIXTURE_PROJECT",
        "WWISE_LIVE",
        "WWISE_SANDBOX_ROOT",
        "WWISE_VERSION",
    }
)


class ScenarioLifecycle:
    """Single-use controller for exactly one v3 semantic scenario."""

    def __init__(
        self,
        *,
        scenario_id: str,
        version: str,
        scenario_root: Path,
        live_environment: Mapping[str, str],
        prelaunch_hook: PrelaunchHook | None = None,
        launch_environment_overrides: Mapping[str, str] | None = None,
        owned_wine_prefix: Path | None = None,
        lock_root: Path = GLOBAL_LIVE_LIFECYCLE_LOCK_ROOT,
    ) -> None:
        if not scenario_id or not scenario_id.strip():
            raise ValueError("scenario_id must be non-empty")
        if version not in {"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"}:
            raise ValueError(f"unsupported Wwise version: {version}")
        self.scenario_id = scenario_id
        self.version = version
        self.scenario_root = Path(scenario_root).expanduser().resolve(strict=False)
        self.live_environment = {str(key): str(value) for key, value in live_environment.items()}
        self.prelaunch_hook = prelaunch_hook
        self.launch_environment_overrides = _validate_launch_environment_overrides(
            launch_environment_overrides or {},
            scenario_root=self.scenario_root,
        )
        self.owned_wine_prefix = _validate_owned_wine_prefix(
            owned_wine_prefix,
            overrides=self.launch_environment_overrides,
            scenario_root=self.scenario_root,
        )
        self.lock = LiveSandboxLock(Path(lock_root))
        self.runtime: ScenarioRuntime | None = None
        self._lock_acquired = False
        self._finished = False
        self._launch_environment_symlink_baseline: (
            dict[str, tuple[tuple[str, str], ...]] | None
        ) = None

    def start(self) -> ScenarioRuntime:
        if self.runtime is not None or self._finished:
            raise ScenarioLifecycleError("scenario lifecycle is single-use")
        if self.scenario_root.exists():
            raise ScenarioLifecycleError(
                f"scenario root already exists and cannot be reused: {self.scenario_root}"
            )
        self.scenario_root.mkdir(parents=True, exist_ok=False)
        evidence_root = self.scenario_root / "evidence"
        owned_root = self.scenario_root / "owned"
        asset_root = owned_root / "assets"
        io_root = owned_root / "io"
        sandbox_root = owned_root / "sandbox-root"
        for path in (evidence_root, asset_root, io_root):
            path.mkdir(parents=True, exist_ok=False)

        env = dict(self.live_environment)
        env.update(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_VERSION": self.version,
            }
        )
        for path in self.launch_environment_overrides.values():
            Path(path).mkdir(parents=True, exist_ok=False)
        env.update(self.launch_environment_overrides)
        contract = require_live_environment(env)
        if contract.version != self.version or contract.sample_project_source is None:
            raise ScenarioLifecycleError(
                "live environment did not resolve the exact scenario version and SampleProject"
            )

        sandbox: SandboxProject | None = None
        lifecycle: HeadlessLifecycle | None = None
        source_hash_before: ProjectHash | None = None
        source_mtime_before_ns: int | None = None
        stage = "lock-acquire"
        try:
            self.lock.__enter__()
            self._lock_acquired = True
            stage = "sandbox-copy"
            sandbox = prepare_sample_project_sandbox(
                env,
                sandbox_root=sandbox_root,
                hash_strategy="full",
            )
            stage = "source-before-proof"
            source_hash_before = hash_project(
                sandbox.source_root,
                preferred_strategy="full",
            )
            source_mtime_before_ns = sandbox.source_project.stat().st_mtime_ns
            if self.prelaunch_hook is not None:
                stage = "prelaunch"
                self.prelaunch_hook(sandbox, asset_root, io_root)
            stage = "wwise-launch"
            if self.owned_wine_prefix is None:
                lifecycle = launch_sandboxed_wwise(sandbox, env)
            else:
                lifecycle = launch_sandboxed_wwise(
                    sandbox,
                    env,
                    wine_prefix_path=self.owned_wine_prefix,
                    case_owned_root=owned_root,
                )
            stage = "wwise-launch-identity"
            if lifecycle.port is None or str(sandbox.sandbox_project) not in lifecycle.command:
                raise ScenarioLifecycleError(
                    "Wwise launch did not prove the private project path and dynamic WAAPI port"
                )
            stage = "launch-environment-symlink-baseline"
            self._launch_environment_symlink_baseline = (
                _capture_launch_environment_symlink_baseline(
                    self.launch_environment_overrides
                )
            )
            runner_environment = {
                **env,
                **sandbox.env,
                **(
                    {"WINEPREFIX": str(self.owned_wine_prefix)}
                    if self.owned_wine_prefix is not None
                    else {}
                ),
                "WWISE_FIXTURE_PROJECT": str(sandbox.sandbox_project),
                "WWISE_SANDBOX_ROOT": str(sandbox.sandbox_root),
                "WWISE_WAAPI_HOST": lifecycle.host,
                "WWISE_WAAPI_PORT": str(lifecycle.port),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            self.runtime = ScenarioRuntime(
                scenario_id=self.scenario_id,
                version=self.version,
                scenario_root=self.scenario_root,
                evidence_root=evidence_root,
                owned_root=owned_root,
                asset_root=asset_root,
                io_root=io_root,
                sandbox=sandbox,
                lifecycle=lifecycle,
                runner_environment=runner_environment,
                source_hash_before=source_hash_before,
                source_mtime_before_ns=source_mtime_before_ns,
            )
            _write_json(
                evidence_root / "start.json",
                {
                    "contract": SCENARIO_LIFECYCLE_CONTRACT,
                    "scenario_id": self.scenario_id,
                    "version": self.version,
                    "started_at": _utc_now(),
                    "source_hash_before": asdict(source_hash_before),
                    "source_mtime_before_ns": source_mtime_before_ns,
                    "sandbox_project": str(sandbox.sandbox_project),
                    "launch_cwd": str(lifecycle.launch_cwd),
                    "endpoint": {"host": lifecycle.host, "port": lifecycle.port},
                    "isolated_launch_environment": {
                        key: value
                        for key, value in sorted(
                            self.launch_environment_overrides.items()
                        )
                    },
                    "owned_wine_prefix": (
                        str(self.owned_wine_prefix)
                        if self.owned_wine_prefix is not None
                        else None
                    ),
                },
            )
            return self.runtime
        except BaseException as primary_exc:
            proof_errors: list[str] = []
            wwise_stop_status = "not-started"
            if lifecycle is not None and sandbox is not None:
                try:
                    shutdown_sandboxed_wwise(lifecycle, sandbox, suppress_errors=False)
                except BaseException as exc:  # noqa: BLE001 - residuals poison the lane
                    proof_errors.append(_format_error("wwise-start-cleanup", exc))
                    wwise_stop_status = "unproven"
                else:
                    wwise_stop_status = "stopped"
            elif stage == "wwise-launch" and sandbox is not None:
                # launch_sandboxed_wwise owns its internal lifecycle until it
                # returns.  On a failed readiness attempt it records whether
                # that internal process cleanup was complete.
                cleanup_result = getattr(
                    sandbox.metadata,
                    "process_cleanup_result",
                    None,
                )
                if cleanup_result == "cleaned":
                    wwise_stop_status = "stopped-by-launch-helper"
                else:
                    proof_errors.append(
                        "wwise-start-cleanup:unproven launch-helper cleanup:"
                        f"{cleanup_result!r}"
                    )
                    wwise_stop_status = "unproven"

            source_hash_after: ProjectHash | None = None
            source_mtime_after_ns: int | None = None
            if (
                sandbox is not None
                and source_hash_before is not None
                and source_mtime_before_ns is not None
            ):
                try:
                    source_hash_after = hash_project(
                        sandbox.source_root,
                        preferred_strategy="full",
                    )
                    source_mtime_after_ns = sandbox.source_project.stat().st_mtime_ns
                    if source_hash_after != source_hash_before:
                        raise ScenarioLifecycleError(
                            "immutable SampleProject source hash changed during failed start"
                        )
                    if source_mtime_after_ns != source_mtime_before_ns:
                        raise ScenarioLifecycleError(
                            "immutable SampleProject source mtime changed during failed start"
                        )
                except BaseException as exc:  # noqa: BLE001 - source proof is systemic
                    proof_errors.append(_format_error("source-start-proof", exc))

            launch_environment_archive_path: Path | None = None
            if wwise_stop_status in {
                "not-started",
                "stopped",
                "stopped-by-launch-helper",
            }:
                try:
                    launch_environment_archive_path = (
                        self._archive_launch_environment_roots(
                            evidence_root=evidence_root,
                            owned_root=owned_root,
                            phase="start-failure",
                            require_ready_baseline=False,
                        )
                    )
                except BaseException as exc:  # noqa: BLE001 - archive gates sealing
                    proof_errors.append(
                        _format_error("launch-environment-archive", exc)
                    )

            if sandbox is not None:
                sandbox.metadata.keep_decision = "quarantined-after-start-failure"
                try:
                    sandbox.write_metadata()
                except BaseException as exc:  # noqa: BLE001
                    proof_errors.append(_format_error("start-metadata", exc))
            try:
                self._release_lock_best_effort()
            except BaseException as exc:  # noqa: BLE001 - lock uncertainty poisons the lane
                proof_errors.append(_format_error("sandbox-lock-release", exc))

            evidence_path: Path | None = evidence_root / "start-failure.json"
            try:
                _write_json(
                    evidence_path,
                    {
                        "contract": SCENARIO_START_FAILURE_CONTRACT,
                        "scenario_id": self.scenario_id,
                        "version": self.version,
                        "failed_at": _utc_now(),
                        "stage": stage,
                        "primary_error": _format_error("start", primary_exc),
                        "wwise_stop_status": wwise_stop_status,
                        "source_hash_before": (
                            asdict(source_hash_before) if source_hash_before else None
                        ),
                        "source_hash_after": (
                            asdict(source_hash_after) if source_hash_after else None
                        ),
                        "source_mtime_before_ns": source_mtime_before_ns,
                        "source_mtime_after_ns": source_mtime_after_ns,
                        "owned_root": str(owned_root),
                        "owned_tree_sha256": stable_tree_sha256(owned_root),
                        "launch_environment_archive_path": (
                            str(launch_environment_archive_path)
                            if launch_environment_archive_path is not None
                            else None
                        ),
                        "errors": list(proof_errors),
                        "never_reuse": True,
                    },
                )
            except BaseException as exc:  # noqa: BLE001 - retain primary failure
                proof_errors.append(_format_error("start-failure-evidence", exc))
                evidence_path = None
            self._finished = True
            unsafe_to_continue = (
                wwise_stop_status == "unproven"
                or any(
                    row.startswith(
                        (
                            "source-start-proof:",
                            "start-metadata:",
                            "launch-environment-archive:",
                            "sandbox-lock-release:",
                            "start-failure-evidence:",
                        )
                    )
                    for row in proof_errors
                )
            )
            if not isinstance(primary_exc, Exception):
                if unsafe_to_continue:
                    primary_exc.add_note(
                        "scenario start cleanup/source proof is unsafe; campaign must abort"
                    )
                raise
            raise ScenarioLifecycleStartError(
                stage=stage,
                primary_error=f"{type(primary_exc).__name__}: {primary_exc}",
                evidence_path=evidence_path,
                errors=tuple(proof_errors),
                unsafe_to_continue=unsafe_to_continue,
            ) from primary_exc

    def finish(
        self,
        status: str,
        *,
        reason: str = "",
        post_shutdown_hook: PostShutdownHook | None = None,
    ) -> ScenarioLifecycleResult:
        if status not in SCENARIO_STATUSES:
            raise ValueError(f"unsupported scenario status: {status}")
        if self.runtime is None or self._finished:
            raise ScenarioLifecycleError("scenario lifecycle is not active")
        runtime = self.runtime
        errors: list[str] = []
        shutdown_proved = True
        post_shutdown_proved = True
        if reason:
            errors.append(f"scenario:{reason}")

        try:
            shutdown_sandboxed_wwise(
                runtime.lifecycle,
                runtime.sandbox,
                suppress_errors=False,
            )
        except BaseException as exc:  # noqa: BLE001 - cleanup faults block evidence
            errors.append(_format_error("wwise-shutdown", exc))
            shutdown_proved = False

        source_hash_after: ProjectHash | None = None
        source_mtime_after_ns: int | None = None
        try:
            source_hash_after = hash_project(
                runtime.sandbox.source_root,
                preferred_strategy="full",
            )
            source_mtime_after_ns = runtime.sandbox.source_project.stat().st_mtime_ns
            if source_hash_after != runtime.source_hash_before:
                raise ScenarioLifecycleError(
                    "immutable SampleProject source hash changed during the scenario"
                )
            if source_mtime_after_ns != runtime.source_mtime_before_ns:
                raise ScenarioLifecycleError(
                    "immutable SampleProject source project mtime changed during the scenario"
                )
        except BaseException as exc:  # noqa: BLE001 - source drift is systemic
            errors.append(_format_error("source-project-proof", exc))

        if post_shutdown_hook is not None:
            try:
                post_shutdown_hook(runtime)
            except BaseException as exc:  # noqa: BLE001 - post-stop proof gates cleanup
                errors.append(_format_error("post-shutdown-proof", exc))
                post_shutdown_proved = False

        final_status = "BLOCKED" if errors and any(
            row.startswith(
                (
                    "wwise-shutdown:",
                    "source-project-proof:",
                    "post-shutdown-proof:",
                )
            )
            for row in errors
        ) else status
        retained = final_status != "PASS"
        quarantine_path: str | None = None
        if retained and shutdown_proved and post_shutdown_proved:
            try:
                self._archive_launch_environment_roots(
                    evidence_root=runtime.evidence_root,
                    owned_root=runtime.owned_root,
                    phase="finish",
                    require_ready_baseline=True,
                )
            except BaseException as exc:  # noqa: BLE001 - archive gates sealing
                errors.append(_format_error("launch-environment-archive", exc))
                final_status = "BLOCKED"
        try:
            if retained:
                runtime.sandbox.metadata.keep_decision = (
                    f"quarantined:{final_status.lower()}-scenario-never-reuse"
                )
                runtime.sandbox.write_metadata()
                quarantine = self._write_quarantine(final_status, errors)
                quarantine_path = str(quarantine)
            else:
                cleanup_sandbox(runtime.sandbox, keep=False, failed=False)
                if runtime.owned_root.exists():
                    shutil.rmtree(runtime.owned_root, ignore_errors=False)
                if runtime.owned_root.exists():
                    raise ScenarioLifecycleError(
                        "successful scenario retained runner-owned runtime state"
                    )
        except BaseException as exc:  # noqa: BLE001 - cleanup proof is systemic
            errors.append(_format_error("sandbox-cleanup", exc))
            final_status = "BLOCKED"
            retained = True
            if runtime.owned_root.exists() and quarantine_path is None:
                try:
                    quarantine_path = str(self._write_quarantine(final_status, errors))
                except BaseException as quarantine_exc:  # noqa: BLE001
                    errors.append(_format_error("quarantine-seal", quarantine_exc))

        try:
            self.lock.__exit__(None, None, None)
            self._lock_acquired = False
        except BaseException as exc:  # noqa: BLE001 - lock release is systemic
            errors.append(_format_error("sandbox-lock-release", exc))
            final_status = "BLOCKED"
            retained = True

        result = ScenarioLifecycleResult(
            scenario_id=self.scenario_id,
            version=self.version,
            requested_status=status,
            final_status=final_status,
            sandbox_retained=retained,
            source_hash_before=runtime.source_hash_before,
            source_hash_after=source_hash_after,
            source_mtime_before_ns=runtime.source_mtime_before_ns,
            source_mtime_after_ns=source_mtime_after_ns,
            errors=tuple(errors),
            quarantine_path=quarantine_path,
        )
        _write_json(runtime.evidence_root / "lifecycle.json", result.as_dict())
        self._finished = True
        return result

    def _archive_launch_environment_roots(
        self,
        *,
        evidence_root: Path,
        owned_root: Path,
        phase: str,
        require_ready_baseline: bool,
    ) -> Path | None:
        if not self.launch_environment_overrides:
            return None
        if phase not in {"finish", "start-failure"}:
            raise ScenarioLifecycleError(
                f"unsupported launch-environment archive phase: {phase}"
            )

        ready_baseline = self._launch_environment_symlink_baseline
        if require_ready_baseline:
            if ready_baseline is None:
                raise ScenarioLifecycleError(
                    "ready-time launch-environment symlink baseline is missing"
                )
            if set(ready_baseline) != set(self.launch_environment_overrides):
                raise ScenarioLifecycleError(
                    "ready-time launch-environment symlink baseline keys changed"
                )

        prepared: list[tuple[str, Path, list[dict[str, Any]]]] = []
        root_rows: list[dict[str, Any]] = []
        for environment_key, raw_root in sorted(
            self.launch_environment_overrides.items()
        ):
            root = Path(raw_root)
            if not root.is_absolute() or not root.is_relative_to(owned_root):
                raise ScenarioLifecycleError(
                    f"launch-environment root escaped case-owned state: {root}"
                )
            entries = [dict(row) for row in stable_tree_manifest(root)]
            final_symlinks = _symlink_pairs_from_tree_manifest(entries)
            expected_symlinks = (
                ready_baseline[environment_key]
                if require_ready_baseline and ready_baseline is not None
                else None
            )
            if expected_symlinks is not None and final_symlinks != expected_symlinks:
                raise ScenarioLifecycleError(
                    f"launch-environment symlink set changed after Wwise ready: "
                    f"{environment_key}"
                )
            prepared.append((environment_key, root, entries))
            root_rows.append(
                {
                    "environment_key": environment_key,
                    "root": str(root),
                    "ready_symlinks": (
                        _symlink_pairs_as_json(expected_symlinks)
                        if expected_symlinks is not None
                        else None
                    ),
                    "final_symlinks": _symlink_pairs_as_json(final_symlinks),
                    "ready_symlinks_match_final": (
                        final_symlinks == expected_symlinks
                        if expected_symlinks is not None
                        else None
                    ),
                    "entries": entries,
                }
            )

        archive_path = evidence_root / "launch-environment-archive.json"
        payload = {
            "contract": SCENARIO_LAUNCH_ENVIRONMENT_ARCHIVE_CONTRACT,
            "scenario_id": self.scenario_id,
            "version": self.version,
            "phase": phase,
            "captured_at": _utc_now(),
            "roots": root_rows,
        }
        _write_and_verify_json(archive_path, payload)

        # Re-scan every root after the durable archive exists.  Deletion starts
        # only if all archived trees still match, so a mutated root is retained.
        for environment_key, root, entries in prepared:
            if [dict(row) for row in stable_tree_manifest(root)] != entries:
                raise ScenarioLifecycleError(
                    f"launch-environment tree changed after archive: {environment_key}"
                )

        # Overlapping override roots are possible (for example XDG_CACHE_HOME
        # below HOME).  Removing each outermost root once removes every declared
        # descendant without following any symlink contained by the tree.
        deletion_roots: list[Path] = []
        for root in sorted(
            (row[1] for row in prepared),
            key=lambda value: (len(value.parts), str(value)),
        ):
            if any(root.is_relative_to(parent) for parent in deletion_roots):
                continue
            deletion_roots.append(root)
        for root in deletion_roots:
            shutil.rmtree(root, ignore_errors=False)
        remaining = [
            str(root)
            for _key, root, _entries in prepared
            if os.path.lexists(root)
        ]
        if remaining:
            raise ScenarioLifecycleError(
                f"launch-environment roots remain after archive removal: {remaining!r}"
            )
        return archive_path

    def _write_quarantine(self, status: str, errors: list[str]) -> Path:
        assert self.runtime is not None
        runtime = self.runtime
        tree_sha256 = stable_tree_sha256(runtime.owned_root)
        path = runtime.evidence_root / "quarantine.json"
        _write_json(
            path,
            {
                "contract": SCENARIO_QUARANTINE_CONTRACT,
                "scenario_id": self.scenario_id,
                "version": self.version,
                "status": status,
                "sealed_at": _utc_now(),
                "owned_root": str(runtime.owned_root),
                "owned_tree_sha256": tree_sha256,
                "never_reuse": True,
                "errors": list(errors),
            },
        )
        return path

    def _release_lock_best_effort(self) -> None:
        if not self._lock_acquired:
            return
        try:
            self.lock.__exit__(None, None, None)
        finally:
            self._lock_acquired = False


def _format_error(stage: str, exc: BaseException) -> str:
    return f"{stage}:{type(exc).__name__}:{exc}"


def _capture_launch_environment_symlink_baseline(
    overrides: Mapping[str, str],
) -> dict[str, tuple[tuple[str, str], ...]]:
    return {
        environment_key: _collect_symlink_pairs(Path(raw_root))
        for environment_key, raw_root in sorted(overrides.items())
    }


def _collect_symlink_pairs(root: Path) -> tuple[tuple[str, str], ...]:
    tree = Path(root)
    try:
        root_info = tree.lstat()
    except OSError as exc:
        raise ScenarioLifecycleError(
            f"cannot stat launch-environment root {tree}: {exc}"
        ) from exc
    if path_is_link_or_reparse(tree, metadata=root_info) or not stat.S_ISDIR(
        root_info.st_mode
    ):
        raise ScenarioLifecycleError(
            f"launch-environment root must be a real directory: {tree}"
        )

    rows: list[tuple[str, str]] = []

    def walk(directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise ScenarioLifecycleError(
                f"cannot scan launch-environment directory {directory}: {exc}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ScenarioLifecycleError(
                    f"cannot stat launch-environment entry {path}: {exc}"
                ) from exc
            if stat.S_ISLNK(info.st_mode):
                try:
                    target = os.readlink(path)
                except OSError as exc:
                    raise ScenarioLifecycleError(
                        f"cannot read launch-environment symlink {path}: {exc}"
                    ) from exc
                rows.append((path.relative_to(tree).as_posix(), target))
            elif path_is_link_or_reparse(path, metadata=info):
                raise ScenarioLifecycleError(
                    "launch-environment tree may not contain a junction or "
                    f"reparse point: {path}"
                )
            elif stat.S_ISDIR(info.st_mode):
                walk(path)

    walk(tree)
    return tuple(rows)


def _symlink_pairs_from_tree_manifest(
    entries: list[dict[str, Any]],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(row["path"]), str(row["target"]))
        for row in entries
        if row.get("type") == "symlink"
    )


def _symlink_pairs_as_json(
    pairs: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    return [
        {"path": path, "raw_target": raw_target}
        for path, raw_target in pairs
    ]


def _write_and_verify_json(path: Path, payload: Mapping[str, Any]) -> None:
    if os.path.lexists(path):
        raise ScenarioLifecycleError(
            f"launch-environment archive already exists: {path}"
        )
    _write_json(path, payload)
    loaded = _read_regular_json_no_follow(path)
    if loaded != dict(payload):
        raise ScenarioLifecycleError(
            f"launch-environment archive readback mismatch: {path}"
        )


def _read_regular_json_no_follow(path: Path) -> Any:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ScenarioLifecycleError(
            f"cannot open launch-environment archive {path}: {exc}"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ScenarioLifecycleError(
                f"launch-environment archive is not a regular file: {path}"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=True) as handle:
            descriptor = -1
            try:
                return json.load(handle)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ScenarioLifecycleError(
                    f"cannot read launch-environment archive {path}: {exc}"
                ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_owned_wine_prefix(
    value: Path | None,
    *,
    overrides: Mapping[str, str],
    scenario_root: Path,
) -> Path | None:
    if value is None:
        return None
    home_value = overrides.get("HOME")
    if not isinstance(home_value, str) or not home_value:
        raise ValueError("owned_wine_prefix requires a private HOME override")
    owned_root = (scenario_root / "owned").resolve(strict=False)
    home = Path(home_value).resolve(strict=False)
    prefix = Path(value).expanduser()
    if not prefix.is_absolute() or "\x00" in str(prefix):
        raise ValueError("owned_wine_prefix must be an absolute path")
    if os.path.lexists(prefix):
        raise ValueError(f"owned_wine_prefix already exists: {prefix}")
    prefix = prefix.resolve(strict=False)
    if home not in prefix.parents or owned_root not in prefix.parents:
        raise ValueError(
            "owned_wine_prefix must be strictly below the private HOME and owned root"
        )
    return prefix


def _validate_launch_environment_overrides(
    overrides: Mapping[str, str],
    *,
    scenario_root: Path,
) -> dict[str, str]:
    """Accept only case-owned user-state roots; WINEPREFIX stays sandbox-owned."""

    result: dict[str, str] = {}
    owned_root = (scenario_root / "owned").resolve(strict=False)
    for raw_key, raw_value in overrides.items():
        key = str(raw_key)
        if key in _RESERVED_LAUNCH_ENV_KEYS:
            raise ValueError(
                f"launch environment override is runner-owned: {key}"
            )
        if key not in _ISOLATED_PATH_ENV_KEYS:
            raise ValueError(
                f"unsupported launch environment override: {key}"
            )
        value = str(raw_value)
        if not value or "\x00" in value:
            raise ValueError(f"launch environment override {key} is invalid")
        path = Path(value).expanduser().resolve(strict=False)
        if not path.is_relative_to(owned_root) or path == owned_root:
            raise ValueError(
                f"launch environment override {key} must be a private path under "
                f"{owned_root}"
            )
        if path.exists():
            raise ValueError(
                f"launch environment override {key} already exists: {path}"
            )
        result[key] = str(path)
    if len(result.values()) != len(set(result.values())):
        raise ValueError("launch environment override paths must be distinct")
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(serialized.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


__all__ = [
    "GLOBAL_LIVE_LIFECYCLE_LOCK_ROOT",
    "SCENARIO_LIFECYCLE_CONTRACT",
    "SCENARIO_LAUNCH_ENVIRONMENT_ARCHIVE_CONTRACT",
    "SCENARIO_QUARANTINE_CONTRACT",
    "SCENARIO_START_FAILURE_CONTRACT",
    "ScenarioLifecycle",
    "ScenarioLifecycleError",
    "ScenarioLifecycleStartError",
    "ScenarioLifecycleResult",
    "ScenarioRuntime",
]

"""Phase 2 live/destructive environment contract for Wwise tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .headless import WwiseConsolePathResolver


ENV_WWISE_LIVE = "WWISE_LIVE"
ENV_WWISE_DESTRUCTIVE = "WWISE_DESTRUCTIVE"
ENV_WWISE_VERSION = "WWISE_VERSION"
ENV_WWISE_CONSOLE = "WWISE_CONSOLE"
ENV_WWISE_FIXTURE_PROJECT = "WWISE_FIXTURE_PROJECT"
ENV_WWISE_SAMPLE_PROJECT_PATH = "WWISE_SAMPLE_PROJECT_PATH"
ENV_WWISE_SANDBOX_ROOT = "WWISE_SANDBOX_ROOT"

SUPPORTED_WWISE_VERSION = "2022.1"
DEFAULT_SAMPLE_PROJECT_ROOT = Path("/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject")


class LiveEnvironmentError(RuntimeError):
    """Raised when the explicitly enabled live/destructive tier is unsafe to run."""


@dataclass(frozen=True, slots=True)
class LiveEnvironmentContract:
    """Canonicalized Phase 2 test-tier environment."""

    live_enabled: bool
    destructive_enabled: bool
    version: str
    console_path: Path | None
    sample_project_source: Path | None
    fixture_project: Path | None
    sandbox_root: Path | None

    @property
    def active_live_project(self) -> Path | None:
        """Project used by read-only live smoke tests."""

        return self.fixture_project or self.sample_project_source

    @property
    def active_destructive_project(self) -> Path | None:
        """Project allowed for mutation tests; never the immutable sample source."""

        if self.fixture_project is None or self.sandbox_root is None:
            return None
        if path_is_under(self.fixture_project, self.sandbox_root):
            return self.fixture_project
        return None


def parse_live_environment(env: Mapping[str, str] | None = None) -> LiveEnvironmentContract:
    """Parse and canonicalize Phase 2 Wwise test-tier environment variables."""

    env_map = env if env is not None else os.environ
    live_enabled = env_map.get(ENV_WWISE_LIVE) == "1"
    destructive_enabled = live_enabled and env_map.get(ENV_WWISE_DESTRUCTIVE) == "1"
    version = env_map.get(ENV_WWISE_VERSION, SUPPORTED_WWISE_VERSION)
    console_path = WwiseConsolePathResolver(env=dict(env_map)).resolve(env_map.get(ENV_WWISE_CONSOLE))
    sample_source = resolve_sample_project_source(env_map)
    fixture_project = _canonical_optional_path(env_map.get(ENV_WWISE_FIXTURE_PROJECT))
    sandbox_root = _canonical_optional_path(env_map.get(ENV_WWISE_SANDBOX_ROOT))
    return LiveEnvironmentContract(
        live_enabled=live_enabled,
        destructive_enabled=destructive_enabled,
        version=version,
        console_path=console_path,
        sample_project_source=sample_source,
        fixture_project=fixture_project,
        sandbox_root=sandbox_root,
    )


def resolve_sample_project_source(env: Mapping[str, str] | None = None) -> Path | None:
    """Resolve the immutable SampleProject source, defaulting only when it exists."""

    env_map = env if env is not None else os.environ
    configured = env_map.get(ENV_WWISE_SAMPLE_PROJECT_PATH)
    if configured:
        return _canonical_project_path(Path(configured).expanduser())
    if DEFAULT_SAMPLE_PROJECT_ROOT.exists():
        return _canonical_project_path(DEFAULT_SAMPLE_PROJECT_ROOT)
    return None


def require_live_environment(env: Mapping[str, str] | None = None) -> LiveEnvironmentContract:
    """Fail fast when WWISE_LIVE=1 lacks required Wwise/project/version prerequisites."""

    contract = parse_live_environment(env)
    if not contract.live_enabled:
        return contract
    errors: list[str] = []
    if contract.version != SUPPORTED_WWISE_VERSION:
        errors.append(
            f"{ENV_WWISE_VERSION} must be {SUPPORTED_WWISE_VERSION!r} for this Phase 2 contract; got {contract.version!r}"
        )
    if contract.sample_project_source is None and contract.fixture_project is None:
        errors.append(
            f"missing immutable SampleProject source: set {ENV_WWISE_SAMPLE_PROJECT_PATH} or install default source at {DEFAULT_SAMPLE_PROJECT_ROOT}"
        )
    if contract.fixture_project is not None and not contract.fixture_project.exists():
        errors.append(f"{ENV_WWISE_FIXTURE_PROJECT} does not exist: {contract.fixture_project}")
    if contract.sample_project_source is not None and not contract.sample_project_source.exists():
        errors.append(f"{ENV_WWISE_SAMPLE_PROJECT_PATH} does not exist: {contract.sample_project_source}")
    if contract.console_path is None or not contract.console_path.exists():
        errors.append(f"WwiseConsole is unavailable at {contract.console_path}")
    if errors:
        raise LiveEnvironmentError("WWISE_LIVE=1 prerequisite failure: " + "; ".join(errors))
    return contract


def require_destructive_environment(env: Mapping[str, str] | None = None) -> LiveEnvironmentContract:
    """Fail fast unless destructive tests target an active project under WWISE_SANDBOX_ROOT."""

    contract = require_live_environment(env)
    if not contract.live_enabled or not contract.destructive_enabled:
        return contract
    errors: list[str] = []
    if contract.sandbox_root is None:
        errors.append(f"{ENV_WWISE_SANDBOX_ROOT} is required for destructive tests")
    elif not contract.sandbox_root.exists():
        errors.append(f"{ENV_WWISE_SANDBOX_ROOT} does not exist: {contract.sandbox_root}")
    if contract.fixture_project is None:
        errors.append(f"{ENV_WWISE_FIXTURE_PROJECT} must point to the sandbox copy for destructive tests")
    elif contract.sandbox_root is not None and not path_is_under(contract.fixture_project, contract.sandbox_root):
        errors.append(
            f"{ENV_WWISE_FIXTURE_PROJECT} must be under active {ENV_WWISE_SANDBOX_ROOT}; got {contract.fixture_project} outside {contract.sandbox_root}"
        )
    if contract.fixture_project is not None and contract.sample_project_source is not None:
        if _same_path(contract.fixture_project, contract.sample_project_source):
            errors.append("destructive tests must not launch the immutable SampleProject source")
    if errors:
        raise LiveEnvironmentError("WWISE_DESTRUCTIVE=1 guard failure: " + "; ".join(errors))
    return contract


def path_is_under(path: Path, root: Path) -> bool:
    """Return True when path is root or a descendant of root after lexical resolution."""

    resolved_path = path.expanduser().resolve(strict=False)
    resolved_root = root.expanduser().resolve(strict=False)
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _canonical_optional_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    return Path(raw).expanduser().resolve(strict=False)


def _canonical_project_path(path: Path) -> Path:
    candidate = path.expanduser().resolve(strict=False)
    if candidate.suffix == ".wproj":
        return candidate
    projects = sorted(candidate.glob("**/*.wproj")) if candidate.exists() else []
    return projects[0].resolve(strict=False) if projects else candidate


def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)


__all__ = [
    "DEFAULT_SAMPLE_PROJECT_ROOT",
    "ENV_WWISE_DESTRUCTIVE",
    "ENV_WWISE_FIXTURE_PROJECT",
    "ENV_WWISE_LIVE",
    "ENV_WWISE_SAMPLE_PROJECT_PATH",
    "ENV_WWISE_SANDBOX_ROOT",
    "ENV_WWISE_VERSION",
    "LiveEnvironmentContract",
    "LiveEnvironmentError",
    "SUPPORTED_WWISE_VERSION",
    "parse_live_environment",
    "path_is_under",
    "require_destructive_environment",
    "require_live_environment",
    "resolve_sample_project_source",
]

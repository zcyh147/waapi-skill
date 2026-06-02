"""Phase 2 live/destructive environment contract for Wwise tests."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from wwise_waapi.headless import WwiseConsolePathResolver  # pyright: ignore[reportMissingImports]
from wwise_waapi.versions import (  # pyright: ignore[reportMissingImports]
    WWISE_2021_1_BUILD,
    WWISE_2021_1_VERSION_KEY,
    WWISE_2023_1_BUILD,
    WWISE_2023_1_VERSION_KEY,
    WWISE_2024_1_BUILD,
    WWISE_2024_1_VERSION_KEY,
    WWISE_2025_1_BUILD,
    WWISE_2025_1_VERSION_KEY,
)


ENV_WWISE_LIVE = "WWISE_LIVE"
ENV_WWISE_DESTRUCTIVE = "WWISE_DESTRUCTIVE"
ENV_WWISE_VERSION = "WWISE_VERSION"
ENV_WWISE_CONSOLE = "WWISE_CONSOLE"
ENV_WWISE_FIXTURE_PROJECT = "WWISE_FIXTURE_PROJECT"
ENV_WWISE_SAMPLE_PROJECT_PATH = "WWISE_SAMPLE_PROJECT_PATH"
ENV_WWISE_SANDBOX_ROOT = "WWISE_SANDBOX_ROOT"
ENV_WWISE_TEST_CONFIG = "WWISE_TEST_CONFIG"

REPO_ROOT = Path(__file__).resolve().parents[3]
ORG_FIXTURE_SOURCE_ROOT = REPO_ROOT / "tests" / "_org"
DEFAULT_LIVE_ENVIRONMENT_CONFIG = REPO_ROOT / "tests" / "fixtures" / "local" / "live-environment.json"

SUPPORTED_WWISE_VERSION = "2022.1"
WWISE_2022_1_BUILD = "2022.1.19.8584"


def _versioned_console_path(build: str) -> Path:
    if platform.system() == "Windows":
        return Path(fr"C:\Audiokinetic\Wwise{build}\Authoring\x64\Release\bin\WwiseConsole.exe")
    return Path(f"/Applications/Audiokinetic/Wwise{build}/Wwise.app/Contents/Tools/WwiseConsole.sh")


def _versioned_sample_project_path(build: str) -> Path:
    del build
    return Path()


def _repo_fixture_project_path(version: str) -> Path:
    return ORG_FIXTURE_SOURCE_ROOT / version / "SampleProject.wproj"


def _default_sample_project_root(version: str) -> Path:
    return _repo_fixture_project_path(version).parent


def _legacy_installed_sample_project_path(build: str) -> Path:
    if platform.system() == "Windows":
        return Path(fr"C:\Audiokinetic\SampleProject{build}\SampleProject\SampleProject.wproj")
    return Path(f"/Applications/Audiokinetic/SampleProject{build}/SampleProject/SampleProject.wproj")


WWISE_2022_1_CONSOLE_PATH = _versioned_console_path(WWISE_2022_1_BUILD)
WWISE_2021_1_CONSOLE_PATH = _versioned_console_path(WWISE_2021_1_BUILD)
WWISE_2023_1_CONSOLE_PATH = _versioned_console_path(WWISE_2023_1_BUILD)
WWISE_2024_1_CONSOLE_PATH = _versioned_console_path(WWISE_2024_1_BUILD)
WWISE_2025_1_CONSOLE_PATH = _versioned_console_path(WWISE_2025_1_BUILD)
DEFAULT_SAMPLE_PROJECT_ROOT = _default_sample_project_root(SUPPORTED_WWISE_VERSION)
WWISE_2021_1_SAMPLE_PROJECT_PATH = _repo_fixture_project_path(WWISE_2021_1_VERSION_KEY)
WWISE_2023_1_SAMPLE_PROJECT_PATH = _repo_fixture_project_path(WWISE_2023_1_VERSION_KEY)
WWISE_2024_1_SAMPLE_PROJECT_PATH = _repo_fixture_project_path(WWISE_2024_1_VERSION_KEY)
WWISE_2025_1_SAMPLE_PROJECT_PATH = _repo_fixture_project_path(WWISE_2025_1_VERSION_KEY)
INSTALLED_SAMPLE_PROJECT_2023_1_ROOT = _legacy_installed_sample_project_path(WWISE_2023_1_BUILD).parent
INSTALLED_SAMPLE_PROJECT_2021_1_ROOT = _legacy_installed_sample_project_path(WWISE_2021_1_BUILD).parent
INSTALLED_SAMPLE_PROJECT_2024_1_ROOT = _legacy_installed_sample_project_path(WWISE_2024_1_BUILD).parent
INSTALLED_SAMPLE_PROJECT_2025_1_ROOT = _legacy_installed_sample_project_path(WWISE_2025_1_BUILD).parent


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


@dataclass(frozen=True, slots=True)
class _LiveVersionPaths:
    version: str
    console_path: Path
    sample_project_path: Path
    require_exact_paths: bool = False
    sandbox_root: Path | None = None


LIVE_VERSION_PATHS: dict[str, _LiveVersionPaths] = {
    SUPPORTED_WWISE_VERSION: _LiveVersionPaths(
        version=SUPPORTED_WWISE_VERSION,
        console_path=WWISE_2022_1_CONSOLE_PATH,
        sample_project_path=DEFAULT_SAMPLE_PROJECT_ROOT,
    ),
    WWISE_2021_1_VERSION_KEY: _LiveVersionPaths(
        version=WWISE_2021_1_VERSION_KEY,
        console_path=WWISE_2021_1_CONSOLE_PATH,
        sample_project_path=WWISE_2021_1_SAMPLE_PROJECT_PATH,
        require_exact_paths=True,
    ),
    WWISE_2023_1_VERSION_KEY: _LiveVersionPaths(
        version=WWISE_2023_1_VERSION_KEY,
        console_path=WWISE_2023_1_CONSOLE_PATH,
        sample_project_path=WWISE_2023_1_SAMPLE_PROJECT_PATH,
        require_exact_paths=True,
    ),
    WWISE_2024_1_VERSION_KEY: _LiveVersionPaths(
        version=WWISE_2024_1_VERSION_KEY,
        console_path=WWISE_2024_1_CONSOLE_PATH,
        sample_project_path=WWISE_2024_1_SAMPLE_PROJECT_PATH,
        require_exact_paths=True,
    ),
    WWISE_2025_1_VERSION_KEY: _LiveVersionPaths(
        version=WWISE_2025_1_VERSION_KEY,
        console_path=WWISE_2025_1_CONSOLE_PATH,
        sample_project_path=WWISE_2025_1_SAMPLE_PROJECT_PATH,
        require_exact_paths=True,
    ),
}


def _live_version_paths(env: Mapping[str, str], version: str) -> _LiveVersionPaths | None:
    configured = _configured_live_version_paths(env, version)
    if configured is not None:
        return configured
    return LIVE_VERSION_PATHS.get(version)


def _configured_live_version_paths(env: Mapping[str, str], version: str) -> _LiveVersionPaths | None:
    config_path = _live_environment_config_path(env)
    if config_path is None or not config_path.exists():
        return None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise LiveEnvironmentError(f"{config_path} must contain a JSON object")
    versions = payload.get("versions")
    if not isinstance(versions, Mapping):
        return None
    raw_entry = versions.get(version)
    if not isinstance(raw_entry, Mapping):
        return None

    base = LIVE_VERSION_PATHS.get(version)
    console_raw = env.get(ENV_WWISE_CONSOLE) or _first_string(raw_entry, "wwise_console", "console_path")
    project_raw = env.get(ENV_WWISE_SAMPLE_PROJECT_PATH) or _first_string(raw_entry, "sample_project", "sample_project_path")
    sandbox_raw = env.get(ENV_WWISE_SANDBOX_ROOT) or _first_string(raw_entry, "sandbox_root")
    console_path = _config_path(console_raw, config_path) if console_raw is not None else base.console_path if base else None
    sample_project_path = (
        _canonical_project_path(_config_path(project_raw, config_path))
        if project_raw is not None
        else base.sample_project_path if base else None
    )
    if console_path is None or sample_project_path is None:
        raise LiveEnvironmentError(f"{config_path} version {version} must define wwise_console and sample_project")
    sandbox_root = _config_path(sandbox_raw, config_path) if sandbox_raw is not None else None
    return _LiveVersionPaths(
        version=version,
        console_path=console_path,
        sample_project_path=sample_project_path,
        require_exact_paths=base.require_exact_paths if base is not None else False,
        sandbox_root=sandbox_root,
    )


def _live_environment_config_path(env: Mapping[str, str]) -> Path | None:
    configured = env.get(ENV_WWISE_TEST_CONFIG)
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return None


def _first_string(mapping: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _config_path(raw: str, config_path: Path) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    # Keep test configs repo-portable: relative paths are repository-root relative.
    del config_path
    return (REPO_ROOT / candidate).resolve(strict=False)


def parse_live_environment(env: Mapping[str, str] | None = None) -> LiveEnvironmentContract:
    """Parse and canonicalize Phase 2 Wwise test-tier environment variables."""

    env_map = env if env is not None else os.environ
    live_enabled = env_map.get(ENV_WWISE_LIVE) == "1"
    destructive_enabled = live_enabled and env_map.get(ENV_WWISE_DESTRUCTIVE) == "1"
    version = env_map.get(ENV_WWISE_VERSION, SUPPORTED_WWISE_VERSION)
    version_paths = _live_version_paths(env_map, version)
    console_path = resolve_wwise_console_path(env_map, version)
    sample_source = resolve_sample_project_source(env_map)
    fixture_project = _canonical_optional_path(env_map.get(ENV_WWISE_FIXTURE_PROJECT))
    sandbox_root = _canonical_optional_path(env_map.get(ENV_WWISE_SANDBOX_ROOT))
    if sandbox_root is None and version_paths is not None:
        sandbox_root = version_paths.sandbox_root
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
    version = env_map.get(ENV_WWISE_VERSION, SUPPORTED_WWISE_VERSION)
    configured = env_map.get(ENV_WWISE_SAMPLE_PROJECT_PATH)
    if configured:
        return _canonical_project_path(Path(configured).expanduser())
    configured_paths = _configured_live_version_paths(env_map, version)
    if configured_paths is not None:
        return _canonical_project_path(configured_paths.sample_project_path)
    if version == SUPPORTED_WWISE_VERSION:
        if DEFAULT_SAMPLE_PROJECT_ROOT.exists():
            return _canonical_project_path(DEFAULT_SAMPLE_PROJECT_ROOT)
        return None
    version_paths = LIVE_VERSION_PATHS.get(version)
    if version_paths is None:
        return None
    if version_paths.require_exact_paths:
        return version_paths.sample_project_path
    if version_paths.sample_project_path.exists():
        return _canonical_project_path(version_paths.sample_project_path)
    return None


def resolve_wwise_console_path(env: Mapping[str, str] | None = None, version: str | None = None) -> Path | None:
    """Resolve WwiseConsole for the requested supported version without cross-version fallback."""

    env_map = env if env is not None else os.environ
    requested_version = version or env_map.get(ENV_WWISE_VERSION, SUPPORTED_WWISE_VERSION)
    version_paths = _live_version_paths(env_map, requested_version)
    if version_paths is None:
        return None
    resolver = WwiseConsolePathResolver(env=dict(env_map), macos_default=version_paths.console_path)
    return resolver.resolve(env_map.get(ENV_WWISE_CONSOLE))


def require_live_environment(env: Mapping[str, str] | None = None) -> LiveEnvironmentContract:
    """Fail fast when WWISE_LIVE=1 lacks required Wwise/project/version prerequisites."""

    contract = parse_live_environment(env)
    if not contract.live_enabled:
        return contract
    errors: list[str] = []
    version_paths = _live_version_paths(env if env is not None else os.environ, contract.version)
    if version_paths is None:
        errors.append(
            f"{ENV_WWISE_VERSION} must be one of {sorted(LIVE_VERSION_PATHS)!r}; got {contract.version!r}"
        )
    elif version_paths.require_exact_paths:
        if contract.console_path != version_paths.console_path:
            errors.append(
                f"{ENV_WWISE_CONSOLE} must be the exact {contract.version} WwiseConsole path "
                f"{version_paths.console_path}; got {contract.console_path}"
            )
        if contract.sample_project_source != version_paths.sample_project_path:
            errors.append(
                f"{ENV_WWISE_SAMPLE_PROJECT_PATH} must be the exact {contract.version} SampleProject path "
                f"{version_paths.sample_project_path}; got {contract.sample_project_source}"
            )
    if contract.sample_project_source is None and contract.fixture_project is None:
        errors.append(
            f"missing immutable SampleProject source: set {ENV_WWISE_SAMPLE_PROJECT_PATH} or install default source at {_default_sample_project_message_path(contract.version)}"
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
    if contract.sandbox_root is not None and path_is_under_org_fixture(contract.sandbox_root):
        errors.append(f"{ENV_WWISE_SANDBOX_ROOT} must not be under immutable tests/_org fixture sources")
    if contract.fixture_project is not None and path_is_under_org_fixture(contract.fixture_project):
        errors.append(f"{ENV_WWISE_FIXTURE_PROJECT} must not target immutable tests/_org fixture sources")
    if contract.sandbox_root is not None and path_overlaps_immutable_sample_source(contract.sandbox_root):
        errors.append(f"{ENV_WWISE_SANDBOX_ROOT} must not overlap immutable installed SampleProject sources")
    if contract.fixture_project is not None and path_is_under_immutable_sample_source(contract.fixture_project):
        errors.append(f"{ENV_WWISE_FIXTURE_PROJECT} must not target immutable installed SampleProject sources")
    if errors:
        raise LiveEnvironmentError("WWISE_DESTRUCTIVE=1 guard failure: " + "; ".join(errors))
    return contract


def path_is_under(path: Path, root: Path) -> bool:
    """Return True when path is root or a descendant of root after lexical resolution."""

    resolved_path = path.expanduser().resolve(strict=False)
    resolved_root = root.expanduser().resolve(strict=False)
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def path_is_under_org_fixture(path: Path) -> bool:
    """Return True when a path points at the committed immutable tests/_org source fixture tree."""

    return path_is_under(path, ORG_FIXTURE_SOURCE_ROOT)


def path_is_under_immutable_sample_source(path: Path) -> bool:
    """Return True when a path points at a known installed immutable SampleProject source tree."""

    return any(path_is_under(path, root) for root in _immutable_sample_project_roots())


def path_overlaps_immutable_sample_source(path: Path) -> bool:
    """Return True when a path is inside, equal to, or contains a known installed SampleProject source."""

    return any(path_is_under(path, root) or path_is_under(root, path) for root in _immutable_sample_project_roots())


def _immutable_sample_project_roots() -> tuple[Path, ...]:
    return (
        DEFAULT_SAMPLE_PROJECT_ROOT,
        INSTALLED_SAMPLE_PROJECT_2021_1_ROOT,
        INSTALLED_SAMPLE_PROJECT_2023_1_ROOT,
        INSTALLED_SAMPLE_PROJECT_2024_1_ROOT,
        INSTALLED_SAMPLE_PROJECT_2025_1_ROOT,
    )


def _default_sample_project_message_path(version: str) -> Path:
    if version == SUPPORTED_WWISE_VERSION:
        return DEFAULT_SAMPLE_PROJECT_ROOT
    version_paths = _live_version_paths(os.environ, version)
    if version_paths is None:
        return DEFAULT_SAMPLE_PROJECT_ROOT
    return version_paths.sample_project_path


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
    "ENV_WWISE_TEST_CONFIG",
    "ENV_WWISE_VERSION",
    "INSTALLED_SAMPLE_PROJECT_2021_1_ROOT",
    "INSTALLED_SAMPLE_PROJECT_2023_1_ROOT",
    "INSTALLED_SAMPLE_PROJECT_2024_1_ROOT",
    "INSTALLED_SAMPLE_PROJECT_2025_1_ROOT",
    "LIVE_VERSION_PATHS",
    "LiveEnvironmentContract",
    "LiveEnvironmentError",
    "DEFAULT_LIVE_ENVIRONMENT_CONFIG",
    "ORG_FIXTURE_SOURCE_ROOT",
    "SUPPORTED_WWISE_VERSION",
    "WWISE_2022_1_BUILD",
    "WWISE_2022_1_CONSOLE_PATH",
    "WWISE_2021_1_BUILD",
    "WWISE_2021_1_CONSOLE_PATH",
    "WWISE_2021_1_SAMPLE_PROJECT_PATH",
    "WWISE_2023_1_CONSOLE_PATH",
    "WWISE_2023_1_SAMPLE_PROJECT_PATH",
    "WWISE_2024_1_CONSOLE_PATH",
    "WWISE_2024_1_SAMPLE_PROJECT_PATH",
    "WWISE_2025_1_CONSOLE_PATH",
    "WWISE_2025_1_SAMPLE_PROJECT_PATH",
    "parse_live_environment",
    "path_is_under",
    "path_is_under_immutable_sample_source",
    "path_is_under_org_fixture",
    "path_overlaps_immutable_sample_source",
    "require_destructive_environment",
    "require_live_environment",
    "resolve_sample_project_source",
    "resolve_wwise_console_path",
]

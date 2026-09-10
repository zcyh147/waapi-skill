"""Central script configuration for the Wwise WAAPI skill scaffold."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_DIR = SKILL_DIR / ".venv"
ENVIRONMENT_READY_MARKER_NAME = ".waapi-skill-ready-v1"
ENVIRONMENT_READY_CONTRACT = "waapi-skill.environment-ready/v1"
DATA_DIR = SKILL_DIR / "data"
LOGS_DIR = SKILL_DIR / "logs"
FIXTURES_DIR = SKILL_DIR / "fixtures"

# Public and developer-facing wrappers may execute only these packaged entry
# points.  Keeping this list here makes ``run.py`` and ``setup_environment.py``
# share one fail-closed target policy instead of independently accepting any
# Python file that happens to appear under ``scripts/``.
PACKAGED_SCRIPT_ALLOWLIST = frozenset({"gateway.py", "setup_environment.py"})


class PackagedScriptError(ValueError):
    """Raised when a runner target is not one immutable packaged entry point."""


def environment_ready_marker_contents(skill_dir: Path) -> str:
    requirements = Path(skill_dir) / "requirements.txt"
    requirements_digest = (
        hashlib.sha256(requirements.read_bytes()).hexdigest()
        if requirements.is_file()
        else None
    )
    return json.dumps(
        {
            "contract": ENVIRONMENT_READY_CONTRACT,
            "requirements_sha256": requirements_digest,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


def environment_is_ready(venv_dir: Path, skill_dir: Path) -> bool:
    marker = Path(venv_dir) / ENVIRONMENT_READY_MARKER_NAME
    try:
        return (
            not marker.is_symlink()
            and marker.is_file()
            and marker.read_text(encoding="utf-8")
            == environment_ready_marker_contents(skill_dir)
        )
    except (OSError, UnicodeError):
        return False


def write_environment_ready_marker(venv_dir: Path, skill_dir: Path) -> Path:
    root = Path(venv_dir)
    root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{ENVIRONMENT_READY_MARKER_NAME}.",
        suffix=".tmp",
        dir=root,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(environment_ready_marker_contents(skill_dir))
            handle.flush()
            os.fsync(handle.fileno())
        marker = root / ENVIRONMENT_READY_MARKER_NAME
        os.replace(temporary, marker)
        return marker
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def resolve_packaged_script(skill_dir: Path, script_name: str) -> Path:
    """Resolve one allowlisted, regular, non-symlink ``scripts/`` target."""

    candidate = str(script_name)
    if Path(candidate).is_absolute():
        raise PackagedScriptError(f"absolute script paths are not allowed: {script_name}")
    normalized = candidate.removeprefix("scripts/")
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or Path(normalized).name != normalized
    ):
        raise PackagedScriptError(f"script must be one packaged scripts/ basename: {script_name}")
    if not normalized.endswith(".py"):
        normalized = f"{normalized}.py"
    if normalized not in PACKAGED_SCRIPT_ALLOWLIST:
        allowed = ", ".join(sorted(PACKAGED_SCRIPT_ALLOWLIST))
        raise PackagedScriptError(f"script is not in the packaged allowlist ({allowed}): {script_name}")

    script_path = Path(skill_dir) / "scripts" / normalized
    if script_path.is_symlink():
        raise PackagedScriptError(f"packaged script target must not be a symlink: {script_name}")
    if not script_path.is_file():
        raise PackagedScriptError(f"packaged script target is missing: {script_name}")
    skill_root = Path(skill_dir).resolve(strict=True)
    scripts_root = (Path(skill_dir) / "scripts").resolve(strict=True)
    try:
        scripts_root.relative_to(skill_root)
    except ValueError as exc:
        raise PackagedScriptError("packaged scripts directory resolves outside the Skill root") from exc
    if script_path.resolve(strict=True).parent != scripts_root:
        raise PackagedScriptError(f"packaged script target resolves outside scripts/: {script_name}")
    return script_path


ENV_WWISE_LIVE = "WWISE_LIVE"
ENV_WWISE_DESTRUCTIVE = "WWISE_DESTRUCTIVE"
ENV_WWISE_VERSION = "WWISE_VERSION"
ENV_WWISE_CONSOLE = "WWISE_CONSOLE"
ENV_WWISE_ROOT = "WWISEROOT"

DEFAULT_WWISE_CONSOLE_MACOS = Path(
    "/Applications/Audiokinetic/Wwise2022.1.19.8584/Wwise.app/Contents/Tools/WwiseConsole.sh"
)
WINDOWS_WWISE_CONSOLE_RELATIVE = Path("Authoring") / "x64" / "Release" / "bin" / "WwiseConsole.exe"
DEFAULT_WWISE_STARTUP_TIMEOUT = 10.0
DEFAULT_WWISE_READINESS_TIMEOUT = 60.0
DEFAULT_WWISE_SHUTDOWN_TIMEOUT = 10.0

COVERAGE_MINIMUM = 85
CORE_COVERAGE_TARGETS = {
    "headless": 95,
    "manifest": 95,
    "dispatcher": 95,
    "subscriptions": 95,
    "deferred_registry": 95,
}

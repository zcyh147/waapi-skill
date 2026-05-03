"""Central script configuration for the Wwise WAAPI skill scaffold."""

from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_DIR = SKILL_DIR / ".venv"
DATA_DIR = SKILL_DIR / "data"
LOGS_DIR = SKILL_DIR / "logs"
FIXTURES_DIR = SKILL_DIR / "fixtures"

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

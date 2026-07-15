"""Cross-platform WwiseConsole path and command helpers."""

from __future__ import annotations

from pathlib import Path, PurePath, PureWindowsPath
from typing import Iterable, Mapping


WINDOWS_WWISE_CONSOLE_PARTS = ("Authoring", "x64", "Release", "bin", "WwiseConsole.exe")
WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE = r"%WWISEROOT%\Authoring\x64\Release\bin\WwiseConsole.exe"


def windows_wwise_console_path(wwise_root: str) -> PureWindowsPath:
    """Return the Windows WwiseConsole path below a WWISEROOT value."""

    return PureWindowsPath(wwise_root).joinpath(*WINDOWS_WWISE_CONSOLE_PARTS)


def resolve_windows_wwise_console_from_env(env: Mapping[str, str]) -> PureWindowsPath | None:
    """Resolve WwiseConsole from WWISEROOT without shell expansion."""

    wwise_root = env.get("WWISEROOT")
    if not wwise_root:
        return None
    return windows_wwise_console_path(wwise_root)


def build_wwise_console_command(
    console_path: str | Path | PurePath,
    port: int,
    project_path: str | Path | PurePath | None = None,
    extra_args: Iterable[str] = (),
) -> list[str]:
    """Build a shell-safe argv list for a WAMP-only WwiseConsole WAAPI server.

    WwiseConsole otherwise starts the unused HTTP POST endpoint on its fixed
    default port 8090.  Explicitly disabling that endpoint keeps a headless
    WAMP lifecycle independent from an already-running Authoring instance.
    """

    project_args = [str(project_path)] if project_path is not None else []
    return [
        str(console_path),
        "waapi-server",
        *project_args,
        "--wamp-port",
        str(port),
        "--http-port",
        "0",
        *[str(arg) for arg in extra_args],
    ]

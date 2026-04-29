from __future__ import annotations

from pathlib import PureWindowsPath

from wwise_waapi.platform_paths import (  # pyright: ignore[reportMissingImports]
    WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE,
    build_wwise_console_command,
    resolve_windows_wwise_console_from_env,
    windows_wwise_console_path,
)


def test_windows_wwiseroot_template_uses_required_backslash_strategy() -> None:
    assert WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE == r"%WWISEROOT%\Authoring\x64\Release\bin\WwiseConsole.exe"
    assert str(windows_wwise_console_path("%WWISEROOT%")) == WINDOWS_WWISE_CONSOLE_ENV_TEMPLATE


def test_windows_wwiseroot_resolution_preserves_spaces_and_backslashes() -> None:
    resolved = resolve_windows_wwise_console_from_env(
        {"WWISEROOT": r"C:\Program Files\Audiokinetic\Wwise 2022.1"}
    )

    assert resolved == PureWindowsPath(r"C:\Program Files\Audiokinetic\Wwise 2022.1\Authoring\x64\Release\bin\WwiseConsole.exe")
    assert str(resolved) == r"C:\Program Files\Audiokinetic\Wwise 2022.1\Authoring\x64\Release\bin\WwiseConsole.exe"


def test_windows_wwiseroot_resolution_returns_none_without_env() -> None:
    assert resolve_windows_wwise_console_from_env({}) is None


def test_wwise_console_command_is_shell_safe_argument_list_with_spaces() -> None:
    console_path = PureWindowsPath(r"C:\Program Files\Audiokinetic\Wwise 2022.1\Authoring\x64\Release\bin\WwiseConsole.exe")
    project_path = PureWindowsPath(r"D:\Fixture Projects\Wwise Sample\Sample Project.wproj")

    command = build_wwise_console_command(console_path, 26443, project_path=project_path, extra_args=["--verbose"])

    assert command == [
        str(console_path),
        "waapi-server",
        str(project_path),
        "--wamp-port",
        "26443",
        "--verbose",
    ]
    assert isinstance(command, list)
    assert "Program Files" in command[0]
    assert "Fixture Projects" in command[2]

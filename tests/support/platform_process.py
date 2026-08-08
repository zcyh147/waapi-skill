"""Cross-platform subprocess helpers used only by tests.

Windows ``CreateProcess`` resolves a bare executable against the parent
process environment, not the ``PATH`` supplied for the child.  Model-facing
tests deliberately use a bare ``python`` identity so the broker shim owns that
name.  On Windows, launch that shim with its absolute trusted interpreter and
pass the bare identity as data.  This preserves the broker-visible argv without
putting model arguments through ``cmd.exe`` or another shell.

The one native PowerShell transport proof starts an already-attested absolute
``pwsh.exe`` directly through the closed helper below.  It accepts only the
canonical bounded model-command grammar and does not expose a general shell
execution seam.
"""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from wwise_waapi.platform_commands import (
    PlatformCommandError,
    decode_windows_model_argv,
)


class PlatformProcessError(RuntimeError):
    """A model-facing command cannot be launched without changing its argv."""


_WINDOWS_POWERSHELL_MODEL_TIMEOUT_SECONDS = 30


def model_command_launcher_argv(
    model_argv: Sequence[str],
    *,
    platform_name: str | None = None,
    windows_interpreter: Path | None = None,
    windows_command_directory: Path | None = None,
) -> tuple[str, ...]:
    """Return the native launcher while preserving the model-visible argv.

    POSIX can execute the argv directly because ``execvpe`` honors the child
    ``PATH``.  Native Windows starts ``broker_shim.py`` directly with the
    absolute interpreter already attested by the broker.  The shim receives
    the original bare interpreter name as its first data argument.
    """

    command = _model_argv(model_argv)
    active_platform = os.name if platform_name is None else platform_name
    if active_platform == "posix":
        return command
    if active_platform != "nt":
        raise PlatformProcessError(
            f"unsupported model command platform: {active_platform!r}"
        )
    return _closed_windows_command(
        command,
        interpreter=windows_interpreter,
        command_directory=windows_command_directory,
    )


def run_model_argv(
    model_argv: Sequence[str],
    *,
    environment: Mapping[str, str],
    platform_name: str | None = None,
    windows_interpreter: Path | None = None,
    windows_command_directory: Path | None = None,
    **run_options: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run one model command and report the original model-visible argv."""

    forbidden = {"args", "env", "executable", "shell"}.intersection(run_options)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise TypeError(f"launcher owns subprocess option(s): {joined}")
    command = _model_argv(model_argv)
    launcher_argv = model_command_launcher_argv(
        command,
        platform_name=platform_name,
        windows_interpreter=windows_interpreter,
        windows_command_directory=windows_command_directory,
    )
    process_options = dict(run_options)
    text_mode = bool(
        process_options.get("text")
        or process_options.get("universal_newlines")
        or process_options.get("encoding") is not None
        or process_options.get("errors") is not None
    )
    if text_mode and process_options.get("encoding") is None:
        # The broker shim writes protocol output as explicit UTF-8 bytes.  Do
        # not let the Windows ANSI code page reinterpret that byte stream.
        process_options["encoding"] = "utf-8"
    completed = subprocess.run(
        launcher_argv,
        env=dict(environment),
        shell=False,
        **process_options,
    )
    return subprocess.CompletedProcess(
        args=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_windows_powershell_model_command(
    model_command: str,
    *,
    powershell_executable: Path,
    environment: Mapping[str, str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Run one generated model command through an exact attested pwsh path.

    This is the narrow native-Windows test seam for proving Codex's outer
    ``pwsh.exe -NoProfile -Command`` transport.  The caller supplies the
    already-attested executable and complete child environment; this helper
    rechecks the executable and working directory without resolving through
    ``PATH`` or a reparse point and owns every subprocess transport option.
    """

    try:
        decode_windows_model_argv(model_command)
    except PlatformCommandError as exc:
        raise PlatformProcessError(
            f"PowerShell model command is not canonical: {exc}"
        ) from exc
    executable = Path(powershell_executable)
    if executable.name.casefold() != "pwsh.exe":
        raise PlatformProcessError(
            "PowerShell model command requires an exact pwsh.exe executable"
        )
    _require_plain_path(
        executable,
        expect_directory=False,
        label="PowerShell executable",
    )
    working_directory = Path(cwd)
    _require_plain_path(
        working_directory,
        expect_directory=True,
        label="PowerShell working directory",
    )
    return subprocess.run(
        (str(executable), "-NoProfile", "-Command", model_command),
        cwd=working_directory,
        env=dict(environment),
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=_WINDOWS_POWERSHELL_MODEL_TIMEOUT_SECONDS,
        check=False,
    )


def _model_argv(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise PlatformProcessError("model argv must be a sequence of strings")
    command = tuple(value)
    if not command or not command[0]:
        raise PlatformProcessError("model argv must contain an executable")
    if any(type(argument) is not str or "\0" in argument for argument in command):
        raise PlatformProcessError("model argv contains a non-string or NUL argument")
    return command


def _closed_windows_command(
    model_argv: tuple[str, ...],
    *,
    interpreter: Path | None,
    command_directory: Path | None,
) -> tuple[str, ...]:
    if interpreter is None:
        raise PlatformProcessError(
            "native Windows model launch requires its trusted interpreter"
        )
    if command_directory is None:
        raise PlatformProcessError(
            "native Windows model launch requires its closed command directory"
        )
    executable_name = model_argv[0]
    if executable_name not in {"python", "python3"}:
        raise PlatformProcessError(
            "native Windows model launch permits only python or python3"
        )
    trusted_interpreter = Path(interpreter)
    _require_plain_path(
        trusted_interpreter,
        expect_directory=False,
        label="trusted interpreter",
    )
    directory = Path(command_directory)
    _require_plain_path(directory, expect_directory=True, label="command directory")
    shim = directory / "broker_shim.py"
    _require_plain_path(shim, expect_directory=False, label="broker shim")
    return (
        str(trusted_interpreter),
        str(shim),
        executable_name,
        *model_argv[1:],
    )


def _require_plain_path(path: Path, *, expect_directory: bool, label: str) -> None:
    if not path.is_absolute():
        raise PlatformProcessError(f"{label} must be absolute")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PlatformProcessError(f"{label} is unavailable: {path}: {exc}") from exc
    is_junction = getattr(path, "is_junction", None)
    file_attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
    reparse_attribute = int(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if stat.S_ISLNK(metadata.st_mode) or (
        is_junction is not None and is_junction()
    ) or file_attributes & reparse_attribute:
        raise PlatformProcessError(
            f"{label} must not be a link, junction, or reparse point: {path}"
        )
    expected_kind = stat.S_ISDIR if expect_directory else stat.S_ISREG
    if not expected_kind(metadata.st_mode):
        expected = "directory" if expect_directory else "regular file"
        raise PlatformProcessError(f"{label} must be a {expected}: {path}")


__all__ = [
    "PlatformProcessError",
    "model_command_launcher_argv",
    "run_model_argv",
    "run_windows_powershell_model_command",
]

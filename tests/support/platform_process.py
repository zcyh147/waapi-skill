"""Cross-platform subprocess helpers used only by tests.

Windows ``CreateProcess`` resolves a bare executable against the parent
process environment, not the ``PATH`` supplied for the child.  Model-facing
tests deliberately use a bare ``python`` identity so the broker shim owns that
name.  On Windows, launch that shim with its absolute trusted interpreter and
pass the bare identity as data.  This preserves the broker-visible argv without
putting model arguments through ``cmd.exe`` or another shell.
"""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class PlatformProcessError(RuntimeError):
    """A model-facing command cannot be launched without changing its argv."""


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
    """Run one model command without changing what the broker observes."""

    forbidden = {"args", "env", "executable", "shell"}.intersection(run_options)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise TypeError(f"launcher owns subprocess option(s): {joined}")
    launcher_argv = model_command_launcher_argv(
        model_argv,
        platform_name=platform_name,
        windows_interpreter=windows_interpreter,
        windows_command_directory=windows_command_directory,
    )
    return subprocess.run(
        launcher_argv,
        env=dict(environment),
        shell=False,
        **run_options,
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
]

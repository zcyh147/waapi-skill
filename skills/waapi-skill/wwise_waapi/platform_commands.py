"""Deterministic host command envelopes for gateway continuations.

Windows has no standard-library equivalent of POSIX ``shlex.join`` for
``cmd.exe``, and ``subprocess.list2cmdline`` only implements native
CreateProcess/MSVCRT argument quoting.  It does not escape CMD metacharacters.
The gateway therefore places every UTF-8 argv item inside a fixed encoded
PowerShell envelope.  The outer command contains only fixed tokens and Base64;
no path or transaction token is interpolated into shell syntax.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence


WINDOWS_POWERSHELL_ENCODED_FAMILY = "windows-powershell-encoded"
_WINDOWS_COMMAND_PREFIX = (
    "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
)
_SCRIPT_PREFIX = "$ErrorActionPreference='Stop';$waapiArgv=@("
_ARGUMENT_PREFIX = (
    "[System.Text.Encoding]::UTF8.GetString("
    "[System.Convert]::FromBase64String('"
)
_ARGUMENT_SUFFIX = "'))"
_ARGUMENT_SEPARATOR = ","
_SCRIPT_SUFFIX = (
    ");"
    "$waapiExecutable=$waapiArgv[0];"
    "$waapiArgs=@($waapiArgv | Select-Object -Skip 1);"
    "& $waapiExecutable @waapiArgs;"
    "exit $LASTEXITCODE"
)


class PlatformCommandError(ValueError):
    """A platform continuation command is malformed or non-canonical."""


def encode_windows_powershell_argv(argv: Sequence[str]) -> str:
    """Return one shell-safe Windows continuation for an exact argv array."""

    normalized = _validated_argv(argv)
    encoded_arguments = (
        base64.b64encode(argument.encode("utf-8")).decode("ascii")
        for argument in normalized
    )
    inner = _ARGUMENT_SEPARATOR.join(
        f"{_ARGUMENT_PREFIX}{encoded}{_ARGUMENT_SUFFIX}"
        for encoded in encoded_arguments
    )
    script = f"{_SCRIPT_PREFIX}{inner}{_SCRIPT_SUFFIX}"
    encoded_script = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return _WINDOWS_COMMAND_PREFIX + encoded_script


def decode_windows_powershell_argv(command: str) -> tuple[str, ...]:
    """Decode only the exact canonical envelope emitted by the encoder."""

    if not isinstance(command, str) or not command.startswith(_WINDOWS_COMMAND_PREFIX):
        raise PlatformCommandError("not a gateway Windows PowerShell envelope")
    encoded_script = command[len(_WINDOWS_COMMAND_PREFIX) :]
    if not encoded_script or any(character.isspace() for character in encoded_script):
        raise PlatformCommandError("encoded PowerShell payload is malformed")
    script_bytes = _decode_base64(encoded_script, label="PowerShell payload")
    try:
        script = script_bytes.decode("utf-16-le")
    except UnicodeDecodeError as exc:
        raise PlatformCommandError("PowerShell payload is not UTF-16LE") from exc
    if base64.b64encode(script.encode("utf-16-le")).decode("ascii") != encoded_script:
        raise PlatformCommandError("PowerShell payload is not canonical Base64")
    if not script.startswith(_SCRIPT_PREFIX) or not script.endswith(_SCRIPT_SUFFIX):
        raise PlatformCommandError("PowerShell payload uses an unsupported script shape")
    inner = script[len(_SCRIPT_PREFIX) : -len(_SCRIPT_SUFFIX)]
    encoded_arguments = inner.split(_ARGUMENT_SEPARATOR)
    arguments: list[str] = []
    for encoded_argument in encoded_arguments:
        if not (
            encoded_argument.startswith(_ARGUMENT_PREFIX)
            and encoded_argument.endswith(_ARGUMENT_SUFFIX)
        ):
            raise PlatformCommandError(
                "PowerShell payload uses an unsupported argv item shape"
            )
        encoded = encoded_argument[
            len(_ARGUMENT_PREFIX) : -len(_ARGUMENT_SUFFIX)
        ]
        argument_bytes = _decode_base64(encoded, label="argv item")
        try:
            argument = argument_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PlatformCommandError("argv item is not strict UTF-8") from exc
        if base64.b64encode(argument.encode("utf-8")).decode("ascii") != encoded:
            raise PlatformCommandError("argv item is not canonical Base64")
        arguments.append(argument)
    argv = _validated_argv(arguments)
    if encode_windows_powershell_argv(argv) != command:
        raise PlatformCommandError("Windows continuation envelope is not canonical")
    return argv


def _validated_argv(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise PlatformCommandError("argv must be an array of strings")
    argv = tuple(value)
    if not argv or not argv[0]:
        raise PlatformCommandError("argv must contain a nonempty executable")
    for argument in argv:
        if type(argument) is not str:
            raise PlatformCommandError("argv must contain only strings")
        if any(ord(character) < 32 or ord(character) == 127 for character in argument):
            raise PlatformCommandError("argv contains a control character")
    return argv


def _decode_base64(value: str, *, label: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PlatformCommandError(f"{label} is not valid Base64") from exc


__all__ = [
    "PlatformCommandError",
    "WINDOWS_POWERSHELL_ENCODED_FAMILY",
    "decode_windows_powershell_argv",
    "encode_windows_powershell_argv",
]

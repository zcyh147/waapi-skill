"""Deterministic host command envelopes for gateway continuations.

Windows has no standard-library equivalent of POSIX ``shlex.join`` for
``cmd.exe``, and ``subprocess.list2cmdline`` only implements native
CreateProcess/MSVCRT argument quoting.  It does not escape CMD metacharacters.
The gateway therefore places the exact argv JSON inside a fixed encoded
PowerShell envelope.  The outer command contains only fixed tokens and Base64;
no path or transaction token is interpolated into shell syntax.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence


WINDOWS_POWERSHELL_ENCODED_FAMILY = "windows-powershell-encoded"
_WINDOWS_COMMAND_PREFIX = (
    "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
)
_SCRIPT_PREFIX = (
    "$ErrorActionPreference='Stop';"
    "$waapiJson=[System.Text.Encoding]::UTF8.GetString("
    "[System.Convert]::FromBase64String('"
)
_SCRIPT_SUFFIX = (
    "'));"
    "$waapiArgv=@(ConvertFrom-Json -InputObject $waapiJson);"
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
    argv_json = _canonical_argv_json(normalized)
    inner = base64.b64encode(argv_json).decode("ascii")
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
    argv_json = _decode_base64(inner, label="argv payload")
    try:
        value = json.loads(argv_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlatformCommandError("argv payload is not strict UTF-8 JSON") from exc
    argv = _validated_argv(value)
    if _canonical_argv_json(argv) != argv_json:
        raise PlatformCommandError("argv payload is not canonical JSON")
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


def _canonical_argv_json(argv: tuple[str, ...]) -> bytes:
    return json.dumps(
        argv,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


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

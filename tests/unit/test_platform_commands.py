from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wwise_waapi.platform_commands import (
    PlatformCommandError,
    decode_windows_powershell_argv,
    encode_windows_powershell_argv,
)


def test_windows_continuation_round_trips_metacharacters_as_argv_data() -> None:
    argv = (
        "python",
        r"C:\Skill & 100%!\scripts\run.py",
        "gateway.py",
        "confirm",
        "tx1-abc^def|ghi<jkl>",
        "apostrophe-'-$env:TEMP-你好",
    )

    command = encode_windows_powershell_argv(argv)

    assert command.startswith(
        "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
    )
    assert decode_windows_powershell_argv(command) == argv
    outer_payload = command.rsplit(" ", 1)[1]
    assert all(character not in outer_payload for character in "&|<>%^!")


@pytest.mark.parametrize(
    "mutation",
    (
        "powershell.exe -NoProfile -EncodedCommand AAAA",
        "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand not-base64!",
    ),
)
def test_windows_continuation_decoder_rejects_noncanonical_outer_shape(
    mutation: str,
) -> None:
    with pytest.raises(PlatformCommandError):
        decode_windows_powershell_argv(mutation)


def test_windows_continuation_decoder_rejects_modified_script() -> None:
    command = encode_windows_powershell_argv(("python", "run.py", "status"))
    encoded = command.rsplit(" ", 1)[1]
    script = base64.b64decode(encoded).decode("utf-16-le")
    modified = script.replace("exit $LASTEXITCODE", "Write-Output injected")
    tampered = command.rsplit(" ", 1)[0] + " " + base64.b64encode(
        modified.encode("utf-16-le")
    ).decode("ascii")

    with pytest.raises(PlatformCommandError, match="unsupported script shape"):
        decode_windows_powershell_argv(tampered)


@pytest.mark.skipif(os.name != "nt", reason="native Windows shell proof")
def test_windows_continuation_executes_exact_argv_through_cmd_shell(
    tmp_path: Path,
) -> None:
    script = tmp_path / "capture argv.py"
    output = tmp_path / "captured argv.json"
    script.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text(\n"
        "    json.dumps(sys.argv[2:], ensure_ascii=False), encoding='utf-8'\n"
        ")\n",
        encoding="utf-8",
    )
    expected = [
        "%TEMP%",
        "plain&whoami",
        "pipe|redirect<out>",
        "caret^bang!percent%",
        "quoted ' value 你好",
    ]
    command = encode_windows_powershell_argv(
        (sys.executable, str(script), str(output), *expected)
    )

    completed = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == expected

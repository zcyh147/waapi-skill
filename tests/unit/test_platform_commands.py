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
    WINDOWS_MODEL_COMMAND_MAX_BYTES,
    decode_windows_model_argv,
    decode_windows_powershell_argv,
    encode_windows_model_argv,
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


def test_windows_continuation_decodes_each_argv_item_without_json_array_coercion() -> None:
    argv = ("python", "run.py", "", "中文")

    command = encode_windows_powershell_argv(argv)
    encoded_script = command.rsplit(" ", 1)[1]
    script = base64.b64decode(encoded_script).decode("utf-16-le")

    assert "ConvertFrom-Json" not in script
    assert script.count("[System.Convert]::FromBase64String('") == len(argv)
    assert decode_windows_powershell_argv(command) == argv


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


def test_windows_model_command_round_trips_one_closed_literal_grammar() -> None:
    argv = (
        "python",
        r"C:\WAAPI Skill\scripts\run.py",
        "gateway.py",
        "confirm",
        "tx'quoted",
        "",
        "$env:TEMP & whoami | redirect<out> caret^bang!percent%",
        'double " quote and 你好',
    )

    command = encode_windows_model_argv(argv)

    assert command == (
        "python 'C:\\WAAPI Skill\\scripts\\run.py' 'gateway.py' 'confirm' "
        "'tx''quoted' '' '$env:TEMP & whoami | redirect<out> "
        "caret^bang!percent%' 'double \" quote and 你好'"
    )
    assert decode_windows_model_argv(command) == argv


def test_windows_model_command_has_a_stable_short_transaction_show_shape() -> None:
    argv = (
        "python",
        r"C:\Git_Repos\waapi-skills\skills\waapi-skill\scripts\run.py",
        "gateway.py",
        "transaction-show",
        "tx1-04yzrdpe4vgdxprr2kf8",
    )

    model_command = encode_windows_model_argv(argv)
    compatibility_command = encode_windows_powershell_argv(argv)

    assert len(model_command.encode("utf-8")) == 127
    assert len(compatibility_command) == 2006
    assert len(model_command) < len(compatibility_command) // 8


@pytest.mark.parametrize("quote", tuple(chr(value) for value in range(0x2018, 0x2020)))
def test_windows_model_command_rejects_every_powershell_smart_quote(
    quote: str,
) -> None:
    with pytest.raises(PlatformCommandError, match="smart quote"):
        encode_windows_model_argv(("python", f"unsafe{quote}value"))


@pytest.mark.parametrize(
    "argv, message",
    (
        (("python.exe", "run.py"), "fixed bare python"),
        ((r"C:\Python\python.exe", "run.py"), "fixed bare python"),
        (("Python", "run.py"), "fixed bare python"),
        (("python", "line\nbreak"), "control character"),
        (("python", "tab\tvalue"), "control character"),
        (("python", "next-line-\u0085"), "control character"),
        (("python", "surrogate-\ud800"), "strict UTF-8"),
    ),
)
def test_windows_model_command_rejects_unsafe_argv(
    argv: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(PlatformCommandError, match=message):
        encode_windows_model_argv(argv)


def test_windows_model_command_enforces_the_exact_utf8_byte_ceiling() -> None:
    at_limit = encode_windows_model_argv(
        ("python", "x" * (WINDOWS_MODEL_COMMAND_MAX_BYTES - 9))
    )

    assert len(at_limit.encode("utf-8")) == WINDOWS_MODEL_COMMAND_MAX_BYTES
    with pytest.raises(PlatformCommandError, match="bounded UTF-8 size"):
        encode_windows_model_argv(
            ("python", "x" * (WINDOWS_MODEL_COMMAND_MAX_BYTES - 8))
        )
    with pytest.raises(PlatformCommandError, match="bounded UTF-8 size"):
        decode_windows_model_argv(
            "python '" + "x" * WINDOWS_MODEL_COMMAND_MAX_BYTES + "'"
        )


@pytest.mark.parametrize(
    "tampered",
    (
        "Python 'run.py'",
        "python.exe 'run.py'",
        "'python' 'run.py'",
        "python ",
        "python  'run.py'",
        "python run.py",
        "python 'run.py' ",
        "python 'run.py'  'gateway.py'",
        "python 'run.py';whoami",
        "python 'unterminated",
        "python 'smart\u2018quote'",
        "python 'line\nbreak'",
    ),
)
def test_windows_model_command_decoder_rejects_tampering(tampered: str) -> None:
    with pytest.raises(PlatformCommandError):
        decode_windows_model_argv(tampered)


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

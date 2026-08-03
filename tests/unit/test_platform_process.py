from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support import platform_process


def _windows_launcher_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    interpreter = tmp_path / "Python" / "python.exe"
    interpreter.parent.mkdir()
    interpreter.write_bytes(b"python")
    command_directory = tmp_path / "broker bin"
    command_directory.mkdir()
    shim = command_directory / "broker_shim.py"
    shim.write_text("raise SystemExit(0)\n", encoding="utf-8")
    return interpreter, command_directory, shim


def test_posix_model_command_executes_original_argv() -> None:
    command = ("python", "/tmp/skill/scripts/run.py", "gateway.py", "status")

    assert platform_process.model_command_launcher_argv(
        command,
        platform_name="posix",
    ) == command


def test_windows_model_command_uses_closed_python_shim_without_shell(
    tmp_path: Path,
) -> None:
    interpreter, command_directory, shim = _windows_launcher_files(tmp_path)
    command = (
        "python",
        r"C:\Skill Root\scripts\run.py",
        "gateway.py",
        "--version",
        "2022.1",
    )

    assert platform_process.model_command_launcher_argv(
        command,
        platform_name="nt",
        windows_interpreter=interpreter,
        windows_command_directory=command_directory,
    ) == (
        str(interpreter),
        str(shim),
        *command,
    )


def test_windows_model_command_preserves_shell_metacharacters_as_exact_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter, command_directory, shim = _windows_launcher_files(tmp_path)
    observed: dict[str, object] = {}
    model_argv = (
        "python",
        r"C:\Skill Root\scripts\run.py",
        "gateway.py",
        "--request-json",
        '{"path":"%TEMP%","text":"&|<>%^! 你好 \\\"quoted\\\""}',
        "plain&whoami",
    )

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        observed["argv"] = tuple(argv)
        observed.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(platform_process.subprocess, "run", fake_run)
    environment = {"BROKER_TEST": "1"}

    result = platform_process.run_model_argv(
        model_argv,
        environment=environment,
        platform_name="nt",
        windows_interpreter=interpreter,
        windows_command_directory=command_directory,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.args == model_argv
    assert result.stdout == "ok"
    assert observed["argv"] == (str(interpreter), str(shim), *model_argv)
    assert observed["env"] == environment
    assert observed["shell"] is False
    assert observed["encoding"] == "utf-8"


@pytest.mark.parametrize(
    ("interpreter", "command_directory"),
    (
        (None, None),
        (Path("relative-python.exe"), Path("relative-bin")),
    ),
)
def test_windows_model_command_rejects_missing_or_relative_closed_paths(
    interpreter: Path | None,
    command_directory: Path | None,
) -> None:
    with pytest.raises(platform_process.PlatformProcessError):
        platform_process.model_command_launcher_argv(
            ("python", "runner.py"),
            platform_name="nt",
            windows_interpreter=interpreter,
            windows_command_directory=command_directory,
        )


def test_windows_model_command_rejects_missing_or_linked_shim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter, command_directory, shim = _windows_launcher_files(tmp_path)
    shim.unlink()
    with pytest.raises(platform_process.PlatformProcessError, match="broker shim"):
        platform_process.model_command_launcher_argv(
            ("python", "runner.py"),
            platform_name="nt",
            windows_interpreter=interpreter,
            windows_command_directory=command_directory,
        )

    shim.write_text("raise SystemExit(0)\n", encoding="utf-8")
    original_lstat = Path.lstat

    def fake_lstat(path: Path):
        metadata = original_lstat(path)
        if path == shim:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_file_attributes=0x400,
            )
        return metadata

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(platform_process.PlatformProcessError, match="reparse"):
        platform_process.model_command_launcher_argv(
            ("python", "runner.py"),
            platform_name="nt",
            windows_interpreter=interpreter,
            windows_command_directory=command_directory,
        )


def test_run_model_argv_owns_shell_and_environment_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter, command_directory, _shim = _windows_launcher_files(tmp_path)
    monkeypatch.setattr(
        platform_process.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "ok", ""),
    )

    with pytest.raises(TypeError, match="launcher owns"):
        platform_process.run_model_argv(
            ("python", "runner.py"),
            environment={},
            platform_name="nt",
            windows_interpreter=interpreter,
            windows_command_directory=command_directory,
            shell=True,
        )

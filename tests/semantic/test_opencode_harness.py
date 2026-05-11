from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from .support.opencode_harness import (  # pyright: ignore[reportMissingImports]
    OpenCodeHarnessConfig,
    OpenCodeCommandError,
    OpenCodeHarnessError,
    OpenCodeSemanticHarness,
    OpenCodeServeHandle,
    SkillSymlinkRequirement,
    WwiseSandboxMetadata,
    extract_opencode_session_id,
)


def test_task_8_verifies_required_skill_install_is_symlink(tmp_path: Path) -> None:
    source = tmp_path / "repo" / "skills" / "waapi-skill"
    install = tmp_path / "workspace" / ".agents" / "skills" / "waapi-skill"
    source.mkdir(parents=True)
    install.parent.mkdir(parents=True)
    install.symlink_to(source, target_is_directory=True)

    proof = SkillSymlinkRequirement(install_path=install, source_path=source).verify()

    assert proof.resolved_path == source.resolve(strict=True)
    assert str(install) in proof.summary()


def test_task_8_rejects_copied_skill_directory_with_actionable_error(tmp_path: Path) -> None:
    source = tmp_path / "repo" / "skills" / "waapi-skill"
    install = tmp_path / "workspace" / ".agents" / "skills" / "waapi-skill"
    source.mkdir(parents=True)
    install.mkdir(parents=True)

    with pytest.raises(OpenCodeHarnessError, match="must be a symlink.*copied directories are not allowed"):
        SkillSymlinkRequirement(install_path=install, source_path=source).verify()


def test_task_8_models_mocked_serve_lifecycle_without_live_opencode(tmp_path: Path) -> None:
    harness = _mock_harness(tmp_path)

    handle = harness.start_serve()

    assert handle.mocked is True
    assert handle.process is None
    assert handle.command == ["opencode", "serve", "--hostname", "127.0.0.1", "--port", "4096"]
    assert handle.server_url == "http://127.0.0.1:4096"
    assert "mocked" in handle.output
    handle.shutdown()


def test_task_8_shutdown_kills_process_after_subprocess_timeout(tmp_path: Path) -> None:
    process = _TimeoutThenExitProcess()
    handle = OpenCodeServeHandle(command=["opencode", "serve"], cwd=tmp_path, server_url="http://127.0.0.1:4096", process=process)

    handle.shutdown(timeout=0.1)

    assert process.calls == ["terminate", "wait", "kill", "wait"]


def test_task_8_live_serve_invokes_sandbox_launcher_before_opencode_process(tmp_path: Path) -> None:
    events: list[str] = []
    sandbox_metadata = tmp_path / "sandbox" / "sandbox-metadata.json"
    sandbox_metadata.parent.mkdir(parents=True)
    sandbox_metadata.write_text("{}\n", encoding="utf-8")

    def launcher() -> WwiseSandboxMetadata:
        events.append("sandbox")
        return WwiseSandboxMetadata(sandbox_metadata_path=sandbox_metadata)

    def process_factory(command: list[str], **_: Any) -> _ReadyProcess:
        events.append("serve")
        assert command[:2] == ["opencode", "serve"]
        return _ReadyProcess()

    harness = _mock_harness(tmp_path, live=True, sandbox_launcher=launcher, process_factory=process_factory)

    handle = harness.start_serve()

    assert events == ["sandbox", "serve"]
    assert handle.mocked is False
    assert harness.wwise_metadata.sandbox_metadata_path == sandbox_metadata


def test_task_8_live_run_invokes_sandbox_launcher_before_opencode_attach(tmp_path: Path) -> None:
    events: list[str] = []
    sandbox_metadata = tmp_path / "sandbox" / "sandbox-metadata.json"
    sandbox_metadata.parent.mkdir(parents=True)
    sandbox_metadata.write_text("{}\n", encoding="utf-8")

    def launcher() -> WwiseSandboxMetadata:
        events.append("sandbox")
        return WwiseSandboxMetadata(
            wwise_version="2022.1",
            waapi_host="127.0.0.1",
            waapi_port=8080,
            sandbox_metadata_path=sandbox_metadata,
        )

    def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        events.append("run")
        assert command[:8] == [
            "opencode",
            "run",
            "--attach",
            "http://127.0.0.1:4096",
            "--dir",
            str((tmp_path / "workspace").resolve(strict=False)),
            "--format",
            "json",
        ]
        assert command[8:10] == ["--session", "ses_existing"]
        return subprocess.CompletedProcess(command, 0, stdout="Session: ses_live_mock\n", stderr="")

    harness = _mock_harness(tmp_path, live=True, sandbox_launcher=launcher, runner=runner)

    result = harness.run_attached(prompt="List buses.", attach_url="http://127.0.0.1:4096", attach_session_id="ses_existing")

    assert events == ["sandbox", "run"]
    assert result.session_id == "ses_live_mock"
    assert harness.wwise_metadata.sandbox_metadata_path == sandbox_metadata


def test_task_8_live_mode_requires_explicit_sandbox_launcher(tmp_path: Path) -> None:
    harness = _mock_harness(tmp_path, live=True)

    with pytest.raises(OpenCodeHarnessError, match="explicit Wwise sandbox launcher"):
        harness.start_serve()


def test_task_8_runs_attach_and_archives_command_output_status_and_sandbox_metadata(tmp_path: Path) -> None:
    sandbox_metadata = tmp_path / "sandbox" / "sandbox-metadata.json"
    sandbox_metadata.parent.mkdir(parents=True)
    sandbox_metadata.write_text(json.dumps({"wwise_version": "2022.1"}) + "\n", encoding="utf-8")

    def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        assert command[:8] == [
            "opencode",
            "run",
            "--attach",
            "http://127.0.0.1:4096",
            "--dir",
            str((tmp_path / "workspace").resolve(strict=False)),
            "--format",
            "json",
        ]
        assert "--session" not in command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Attached to OpenCode session ses_task8_attach\nListed buses via WAAPI.\n",
            stderr="",
        )

    harness = _mock_harness(
        tmp_path,
        runner=runner,
        wwise=WwiseSandboxMetadata(
            wwise_version="2022.1",
            waapi_host="127.0.0.1",
            waapi_port=8080,
            sandbox_metadata_path=sandbox_metadata,
        ),
    )

    capture = harness.run_attached_and_archive(
        scenario_id="task-8-attach",
        prompt="List all buses in the Wwise project.",
        expected_assertions=["uses attached OpenCode session", "records Wwise sandbox metadata"],
        attach_url="http://127.0.0.1:4096",
        archive_root=tmp_path / "archive",
    )

    payload = json.loads(capture.archive_path.read_text(encoding="utf-8"))
    assert capture.command_result.session_id == "ses_task8_attach"
    assert payload["command_line"] == [
        "opencode",
        "run",
        "--attach",
        "http://127.0.0.1:4096",
        "--dir",
        str((tmp_path / "workspace").resolve(strict=False)),
        "--format",
        "json",
        "List all buses in the Wwise project.",
    ]
    assert payload["prompt"] == "List all buses in the Wwise project."
    assert "Listed buses via WAAPI" in payload["assistant_output"]
    assert payload["command_exit_status"] == 0
    assert payload["opencode_session_id"] == "ses_task8_attach"
    assert payload["wwise_version"] == "2022.1"
    assert payload["waapi_host"] == "127.0.0.1"
    assert payload["waapi_port"] == 8080
    assert payload["sandbox_metadata_path"] == str(sandbox_metadata)
    assert payload["archive_policy"]["references_only"] is True


def test_task_8_uses_explicit_mocked_session_metadata_when_output_has_no_session(tmp_path: Path) -> None:
    def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 2, stdout="OpenCode failed before transcript header\n", stderr="")

    harness = _mock_harness(tmp_path, runner=runner)

    result = harness.run_attached(
        prompt="Read selected object metadata.",
        attach_session_id="ses_parent",
        explicit_session_id="ses_mocked_metadata",
    )

    assert result.exit_status == 2
    assert result.session_id == "ses_mocked_metadata"
    assert "failed before transcript" in result.output


def test_missing_session_error_preserves_attempted_command_output_and_status(tmp_path: Path) -> None:
    def runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            7,
            stdout="ConnectionRefusedError(61, connect failed)\nNo transcript session header\n",
            stderr="stderr context\n",
        )

    harness = _mock_harness(tmp_path, runner=runner)

    with pytest.raises(OpenCodeCommandError) as raised:
        harness.run_attached(prompt="List all buses.")

    error = raised.value
    assert error.command == [
        "opencode",
        "run",
        "--attach",
        "http://127.0.0.1:4096",
        "--dir",
        str((tmp_path / "workspace").resolve(strict=False)),
        "--format",
        "json",
        "List all buses.",
    ]
    assert error.exit_status == 7
    assert "ConnectionRefusedError" in error.output
    assert "stderr context" in error.output
    assert "output_summary=" in str(error)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Session: ses_abc123\n", "ses_abc123"),
        ("session id = semantic-run-42\n", "semantic-run-42"),
        ("Attached to OpenCode session ses_attach_9\n", "ses_attach_9"),
        ('{"type":"session.updated","sessionID":"ses_json_event"}\n', "ses_json_event"),
        ('{"session":{"id":"ses_nested_json"}}\n', "ses_nested_json"),
    ],
)
def test_extract_opencode_session_id_is_behavioral(output: str, expected: str) -> None:
    assert extract_opencode_session_id(output) == expected


def _mock_harness(
    tmp_path: Path,
    *,
    runner: Any | None = None,
    wwise: WwiseSandboxMetadata | None = None,
    live: bool = False,
    sandbox_launcher: Any | None = None,
    process_factory: Any | None = None,
) -> OpenCodeSemanticHarness:
    source = tmp_path / "repo" / "skills" / "waapi-skill"
    install = tmp_path / "workspace" / ".agents" / "skills" / "waapi-skill"
    source.mkdir(parents=True)
    install.parent.mkdir(parents=True)
    install.symlink_to(source, target_is_directory=True)
    config = OpenCodeHarnessConfig(
        workspace=tmp_path / "workspace",
        skill_requirement=SkillSymlinkRequirement(install_path=install, source_path=source),
        wwise=wwise or WwiseSandboxMetadata(),
        live=live,
    )
    return OpenCodeSemanticHarness(
        config,
        runner=runner or _default_runner,
        process_factory=process_factory,
        sandbox_launcher=sandbox_launcher,
    )


def _default_runner(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, stdout="Session: ses_default_mock\n", stderr="")


class _ReadyProcess:
    pid = 1234

    def terminate(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None


class _TimeoutThenExitProcess:
    pid = 5678

    def __init__(self) -> None:
        self.calls: list[str] = []

    def terminate(self) -> None:
        self.calls.append("terminate")

    def wait(self, timeout: float | None = None) -> int:
        self.calls.append("wait")
        if self.calls.count("wait") == 1:
            raise subprocess.TimeoutExpired(cmd=["opencode", "serve"], timeout=timeout or 0.0)
        return 0

    def kill(self) -> None:
        self.calls.append("kill")

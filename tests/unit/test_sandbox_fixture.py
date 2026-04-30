from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

import wwise_waapi.sandbox_fixture as sandbox_fixture  # pyright: ignore[reportMissingImports]
from wwise_waapi.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    ENV_WWISE_SANDBOX_KEEP_ON_FAILURE,
    KEEP_ON_FAILURE_ROOT,
    SandboxFixtureError,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)
from wwise_waapi.live_environment import LiveEnvironmentError, require_destructive_environment  # pyright: ignore[reportMissingImports]


REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_FIXTURE_ROOT = REPO_ROOT / "tests" / "_org" / "2022.1"


def make_console(tmp_path: Path) -> Path:
    console = tmp_path / "WwiseConsole.sh"
    console.write_text("#!/bin/sh\n", encoding="utf-8")
    console.chmod(0o755)
    return console


def make_sample_project(root: Path, name: str = "SampleProject.wproj") -> Path:
    project = root / name
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("<WwiseDocument><ProjectInfo Name='SampleProject'/></WwiseDocument>\n", encoding="utf-8")
    (root / "Actor-Mixer Hierarchy").mkdir(parents=True, exist_ok=True)
    (root / "Actor-Mixer Hierarchy" / "Default Work Unit.wwu").write_text("<WorkUnit/>\n", encoding="utf-8")
    return project


def base_env(console: Path, project: Path, sandbox_root: Path) -> dict[str, str]:
    return {
        "WWISE_LIVE": "1",
        "WWISE_CONSOLE": str(console),
        "WWISE_SAMPLE_PROJECT_PATH": str(project),
        "WWISE_SANDBOX_ROOT": str(sandbox_root),
    }


def test_prepare_and_cleanup_success_preserves_source_immutability(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source SampleProject")
    sandbox_root = tmp_path / "runtime-sandboxes"
    before_mtime = source_project.stat().st_mtime
    before_hash = hash_project(source_project.parent)

    sandbox = prepare_sample_project_sandbox(base_env(console, source_project, sandbox_root))

    assert sandbox.sandbox_project.exists()
    assert sandbox.sandbox_project != source_project
    assert sandbox.sandbox_root == sandbox_root.resolve(strict=False)
    assert sandbox.env["WWISE_FIXTURE_PROJECT"] == str(sandbox.sandbox_project)
    metadata_path = sandbox.sandbox_path / "sandbox-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_path"] == str(source_project.resolve(strict=True))
    assert metadata["sandbox_project_path"] == str(sandbox.sandbox_project)
    assert metadata["source_hash"]["digest"] == before_hash.digest
    assert metadata["sandbox_hash"]["digest"] == before_hash.digest
    assert metadata["source_mtime_before"] == before_mtime

    cleanup_sandbox(sandbox)

    assert not sandbox.sandbox_path.exists()
    assert source_project.stat().st_mtime == before_mtime
    assert hash_project(source_project.parent).digest == before_hash.digest


def test_keep_on_failure_preserves_under_evidence_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    sandbox = prepare_sample_project_sandbox(base_env(console, source_project, tmp_path / "sandbox-root"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ENV_WWISE_SANDBOX_KEEP_ON_FAILURE, "1")

    preserved = cleanup_sandbox(sandbox, failed=True)

    assert preserved is not None
    assert preserved.exists()
    assert preserved.parent == (tmp_path / KEEP_ON_FAILURE_ROOT).resolve(strict=False)
    metadata = json.loads((preserved / "sandbox-metadata.json").read_text(encoding="utf-8"))
    assert metadata["keep_decision"].startswith("kept:")
    shutil.rmtree(preserved)


def test_rejects_sandbox_roots_that_overlap_source(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_root = tmp_path / "source"
    source_project = make_sample_project(source_root)

    with pytest.raises(SandboxFixtureError, match="source root"):
        prepare_sample_project_sandbox(base_env(console, source_project, source_root))
    with pytest.raises(SandboxFixtureError, match="inside"):
        prepare_sample_project_sandbox(base_env(console, source_project, source_root / "child"))
    with pytest.raises(SandboxFixtureError, match="contain"):
        prepare_sample_project_sandbox(base_env(console, source_project, tmp_path))


def test_rejects_sandbox_roots_under_committed_org_fixture_source(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")

    with pytest.raises(SandboxFixtureError, match="tests/_org"):
        prepare_sample_project_sandbox(base_env(console, source_project, ORG_FIXTURE_ROOT / "runtime-sandbox"))


def test_committed_org_fixture_source_is_copied_outside_source(tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = ORG_FIXTURE_ROOT / "SampleProject.wproj"
    sandbox_root = tmp_path / "sandbox-root"

    sandbox = prepare_sample_project_sandbox(base_env(console, source_project, sandbox_root))

    try:
        assert sandbox.source_root == ORG_FIXTURE_ROOT.resolve(strict=True)
        assert sandbox.sandbox_project.exists()
        assert ORG_FIXTURE_ROOT.resolve(strict=True) not in sandbox.sandbox_project.resolve(strict=True).parents
        assert sandbox.sandbox_root == sandbox_root.resolve(strict=False)
        assert sandbox.metadata.sandbox_hash.digest == sandbox.metadata.source_hash.digest
    finally:
        cleanup_sandbox(sandbox)


def test_destructive_environment_rejects_committed_org_fixture_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = make_console(tmp_path)
    source_project = ORG_FIXTURE_ROOT / "SampleProject.wproj"
    sandbox_root = ORG_FIXTURE_ROOT / "runtime-sandbox"
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    monkeypatch.setenv("WWISE_CONSOLE", str(console))
    monkeypatch.setenv("WWISE_SAMPLE_PROJECT_PATH", str(source_project))
    monkeypatch.setenv("WWISE_FIXTURE_PROJECT", str(source_project))
    monkeypatch.setenv("WWISE_SANDBOX_ROOT", str(sandbox_root))

    with pytest.raises(LiveEnvironmentError, match="tests/_org"):
        require_destructive_environment()


def test_launch_uses_sandbox_project_and_records_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")
    env = base_env(console, source_project, tmp_path / "sandbox-root")
    sandbox = prepare_sample_project_sandbox(env)
    seen_project_paths: list[Path] = []

    class FakeLifecycle:
        def __init__(self, **kwargs: Any) -> None:
            self.process = object()
            self.port = 31337
            self.project_path = kwargs["project_path"]
            self.command = [str(kwargs["console_path"]), "waapi-server", str(self.project_path), "--wamp-port", str(self.port)]
            seen_project_paths.append(self.project_path)

        def run_until_ready(self) -> object:
            return {"ok": True}

        def shutdown(self, suppress_errors: bool = True) -> None:
            self.process = None

    monkeypatch.setattr(sandbox_fixture, "HeadlessLifecycle", FakeLifecycle)

    lifecycle = launch_sandboxed_wwise(sandbox, env)
    shutdown_sandboxed_wwise(lifecycle, sandbox)

    assert seen_project_paths == [sandbox.sandbox_project]
    assert str(source_project) not in " ".join(sandbox.metadata.command or [])
    assert sandbox.metadata.selected_port == 31337
    assert sandbox.metadata.identity_verified is True
    assert sandbox.metadata.process_cleanup_result == "cleaned"
    cleanup_sandbox(sandbox)


def test_missing_copied_wproj_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    console = make_console(tmp_path)
    source_project = make_sample_project(tmp_path / "source")

    def broken_copytree(source: Path, destination: Path, symlinks: bool = False) -> None:
        destination.mkdir(parents=True)
        (destination / "not-a-project.txt").write_text("missing wproj", encoding="utf-8")

    monkeypatch.setattr(sandbox_fixture.shutil, "copytree", broken_copytree)

    with pytest.raises(SandboxFixtureError, match="missing expected project file"):
        prepare_sample_project_sandbox(base_env(console, source_project, tmp_path / "sandbox-root"))

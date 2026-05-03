from __future__ import annotations

import json
import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

import tests.destructive.support.destructive_2021_sandbox as destructive_2021_sandbox  # pyright: ignore[reportMissingImports]
import tests.destructive.support.live_environment as live_env  # pyright: ignore[reportMissingImports]
from tests.destructive.support.destructive_2021_sandbox import (  # pyright: ignore[reportMissingImports]
    Destructive2021SandboxRuntime,
    DestructiveSandboxUnavailable,
    cleanup_stale_2021_destructive_sandboxes,
    hash_mutation_bearing_project_files,
    require_2021_live_destructive_prerequisites,
    require_2021_sandbox_copy_target,
)
from tests.destructive.support.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    SUPPORTED_WWISE_VERSION,
    WWISE_2021_1_CONSOLE_PATH,
    WWISE_2021_1_SAMPLE_PROJECT_PATH,
    require_destructive_environment,
)
from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    ProjectHash,
    SandboxFixtureError,
    SandboxMetadata,
    SandboxProject,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_FIXTURE_2021_ROOT = REPO_ROOT / "tests" / "_org" / "2021.1"
EXPECTED_2021_CONSOLE = Path(
    "/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh"
)
EXPECTED_2021_SAMPLE_PROJECT = Path(
    "/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj"
)


def test_2021_destructive_runtime_uses_exact_constants_without_changing_default_version() -> None:
    assert SUPPORTED_WWISE_VERSION == "2022.1"
    assert WWISE_2021_1_CONSOLE_PATH == EXPECTED_2021_CONSOLE
    assert WWISE_2021_1_SAMPLE_PROJECT_PATH == EXPECTED_2021_SAMPLE_PROJECT


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"WWISE_VERSION": "2021.1"}, "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required"),
        ({"WWISE_LIVE": "1", "WWISE_VERSION": "2021.1"}, "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required"),
        ({"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1"}, "WWISE_VERSION=2021.1 is required"),
        (
            {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1", "WWISE_VERSION": "2021"},
            "WWISE_VERSION=2021.1 is required",
        ),
        (
            {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1", "WWISE_VERSION": "2025.1"},
            "WWISE_VERSION=2021.1 is required",
        ),
        (
            {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1", "WWISE_VERSION": "2021.1"},
            "WWISE_SANDBOX_ROOT is required",
        ),
    ],
)
def test_2021_live_destructive_prerequisites_fail_closed_without_required_gates(
    env: dict[str, str], message: str
) -> None:
    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_2021_live_destructive_prerequisites(env)

    assert message in str(exc_info.value)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"WWISE_VERSION": "2021.1"}, "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required"),
        ({"WWISE_LIVE": "1", "WWISE_VERSION": "2021.1"}, "WWISE_LIVE=1 and WWISE_DESTRUCTIVE=1 are required"),
        (
            {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1", "WWISE_VERSION": "2021"},
            "WWISE_VERSION=2021.1 is required",
        ),
        (
            {"WWISE_LIVE": "1", "WWISE_DESTRUCTIVE": "1", "WWISE_VERSION": "2021.1"},
            "WWISE_SANDBOX_ROOT is required",
        ),
    ],
)
def test_2021_runtime_missing_gates_never_locks_prepares_or_launches(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], message: str
) -> None:
    def fail_lock(*_args: object, **_kwargs: object) -> None:
        pytest.fail("missing gates must stop before acquiring the sandbox lock")

    def fail_prepare(*_args: object, **_kwargs: object) -> None:
        pytest.fail("missing gates must stop before sandbox preparation")

    def fail_launch(*_args: object, **_kwargs: object) -> None:
        pytest.fail("missing gates must stop before WwiseConsole launch")

    monkeypatch.setattr(destructive_2021_sandbox, "LiveSandboxLock", fail_lock)
    monkeypatch.setattr(destructive_2021_sandbox, "prepare_sample_project_sandbox", fail_prepare)
    monkeypatch.setattr(destructive_2021_sandbox, "launch_sandboxed_wwise", fail_launch)

    with pytest.raises(DestructiveSandboxUnavailable) as exc_info:
        Destructive2021SandboxRuntime(env).__enter__()

    assert "blocked execution" in str(exc_info.value)
    assert message in str(exc_info.value)


def test_2021_live_destructive_prerequisites_reject_wrong_exact_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exact_console = _make_console(tmp_path / "exact" / "WwiseConsole.sh")
    exact_sample_project = _make_project(tmp_path / "exact" / "SampleProject" / "SampleProject.wproj")
    wrong_console = _make_console(tmp_path / "wrong" / "WwiseConsole.sh")
    wrong_sample_project = _make_project(tmp_path / "wrong" / "SampleProject" / "SampleProject.wproj")
    sandbox_root = tmp_path / "runtime" / "wwise-2021"
    sandbox_root.mkdir(parents=True)
    _configure_2021_paths(monkeypatch, console_path=exact_console, sample_project_path=exact_sample_project)

    with pytest.raises(LiveEnvironmentError) as console_exc_info:
        require_2021_live_destructive_prerequisites(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_VERSION": "2021.1",
                "WWISE_CONSOLE": str(wrong_console),
                "WWISE_SAMPLE_PROJECT_PATH": str(exact_sample_project),
                "WWISE_SANDBOX_ROOT": str(sandbox_root),
            }
        )
    with pytest.raises(LiveEnvironmentError) as sample_exc_info:
        require_2021_live_destructive_prerequisites(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_VERSION": "2021.1",
                "WWISE_CONSOLE": str(exact_console),
                "WWISE_SAMPLE_PROJECT_PATH": str(wrong_sample_project),
                "WWISE_SANDBOX_ROOT": str(sandbox_root),
            }
        )

    assert "WWISE_CONSOLE must be the exact 2021.1 WwiseConsole path" in str(console_exc_info.value)
    assert "WWISE_SAMPLE_PROJECT_PATH must be the exact 2021.1 SampleProject path" in str(sample_exc_info.value)


@pytest.mark.parametrize(
    "sandbox_root, expected_message",
    [
        ("installed", "sandbox lock root must not overlap the immutable SampleProject source"),
        ("org", "sandbox lock root must not be under immutable tests/_org fixture sources"),
    ],
)
def test_2021_runtime_unsafe_sandbox_root_never_prepares_or_launches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sandbox_root: str, expected_message: str
) -> None:
    exact_console = _make_console(tmp_path / "WwiseConsole.sh")
    exact_sample_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    _configure_2021_paths(monkeypatch, console_path=exact_console, sample_project_path=exact_sample_project)
    root = exact_sample_project.parent if sandbox_root == "installed" else ORG_FIXTURE_2021_ROOT

    def fail_lock(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unsafe roots must stop before acquiring the sandbox lock")

    def fail_prepare(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unsafe roots must stop before sandbox preparation")

    def fail_launch(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unsafe roots must stop before WwiseConsole launch")

    monkeypatch.setattr(destructive_2021_sandbox, "LiveSandboxLock", fail_lock)
    monkeypatch.setattr(destructive_2021_sandbox, "prepare_sample_project_sandbox", fail_prepare)
    monkeypatch.setattr(destructive_2021_sandbox, "launch_sandboxed_wwise", fail_launch)

    with pytest.raises(DestructiveSandboxUnavailable) as exc_info:
        Destructive2021SandboxRuntime(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_VERSION": "2021.1",
                "WWISE_CONSOLE": str(exact_console),
                "WWISE_SAMPLE_PROJECT_PATH": str(exact_sample_project),
                "WWISE_SANDBOX_ROOT": str(root),
            }
        ).__enter__()

    assert expected_message in str(exc_info.value)


def test_2021_destructive_environment_rejects_missing_sandbox_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = _make_console(tmp_path / "WwiseConsole.sh")
    sample_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    fixture_project = _make_project(tmp_path / "sandbox" / "copy" / "SampleProject.wproj")
    _configure_2021_paths(monkeypatch, console_path=console, sample_project_path=sample_project)

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_destructive_environment(
            {
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "1",
                "WWISE_VERSION": "2021.1",
                "WWISE_CONSOLE": str(console),
                "WWISE_SAMPLE_PROJECT_PATH": str(sample_project),
                "WWISE_FIXTURE_PROJECT": str(fixture_project),
            }
        )

    assert "WWISE_SANDBOX_ROOT is required for destructive tests" in str(exc_info.value)


def test_2021_sandbox_copy_target_rejects_installed_sample_project_as_active_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = _make_console(tmp_path / "WwiseConsole.sh")
    installed_project = _make_project(
        tmp_path / "Applications" / "Audiokinetic" / "SampleProject2021.1.14.8108" / "SampleProject" / "SampleProject.wproj"
    )
    _configure_2021_paths(monkeypatch, console_path=console, sample_project_path=installed_project)
    sandbox = _sandbox_project(
        source_project=installed_project,
        sandbox_root=installed_project.parent,
        sandbox_project=installed_project,
    )

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_2021_sandbox_copy_target(
            {"WWISE_CONSOLE": str(console), "WWISE_SAMPLE_PROJECT_PATH": str(installed_project)}, sandbox
        )

    message = str(exc_info.value)
    assert "WWISE_DESTRUCTIVE=1 guard failure" in message
    assert "immutable installed SampleProject" in message


def test_2021_sandbox_copy_target_rejects_source_contained_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = _make_console(tmp_path / "WwiseConsole.sh")
    source_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    contained_project = _make_project(source_project.parent / "nested" / "SampleProject.wproj")
    sandbox_root = source_project.parent / "nested"
    _configure_2021_paths(monkeypatch, console_path=console, sample_project_path=source_project)
    sandbox = _sandbox_project(source_project=source_project, sandbox_root=sandbox_root, sandbox_project=contained_project)

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_2021_sandbox_copy_target(
            {"WWISE_CONSOLE": str(console), "WWISE_SAMPLE_PROJECT_PATH": str(source_project)}, sandbox
        )

    assert "immutable installed SampleProject" in str(exc_info.value)


def test_2021_sandbox_copy_target_rejects_symlink_to_installed_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = _make_console(tmp_path / "WwiseConsole.sh")
    source_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    sandbox_root = tmp_path / "runtime" / "safe-sandbox-root"
    sandbox_project = sandbox_root / "sample-project-copy" / "SampleProject.wproj"
    sandbox_project.parent.mkdir(parents=True)
    sandbox_project.symlink_to(source_project)
    _configure_2021_paths(monkeypatch, console_path=console, sample_project_path=source_project)
    sandbox = _sandbox_project(source_project=source_project, sandbox_root=sandbox_root, sandbox_project=sandbox_project)

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_2021_sandbox_copy_target(
            {"WWISE_CONSOLE": str(console), "WWISE_SAMPLE_PROJECT_PATH": str(source_project)}, sandbox
        )

    message = str(exc_info.value)
    assert "WWISE_DESTRUCTIVE=1 guard failure" in message
    assert "immutable SampleProject source" in message


def test_2021_sandbox_copy_target_rejects_hardlink_to_installed_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = _make_console(tmp_path / "WwiseConsole.sh")
    source_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    sandbox_root = tmp_path / "runtime" / "safe-sandbox-root"
    sandbox_project = sandbox_root / "sample-project-copy" / "SampleProject.wproj"
    sandbox_project.parent.mkdir(parents=True)
    os.link(source_project, sandbox_project)
    _configure_2021_paths(monkeypatch, console_path=console, sample_project_path=source_project)
    sandbox = _sandbox_project(source_project=source_project, sandbox_root=sandbox_root, sandbox_project=sandbox_project)

    with pytest.raises(SandboxFixtureError) as exc_info:
        require_2021_sandbox_copy_target(
            {"WWISE_CONSOLE": str(console), "WWISE_SAMPLE_PROJECT_PATH": str(source_project)}, sandbox
        )

    assert "hardlinks" in str(exc_info.value)


def test_2021_sandbox_copy_target_rejects_tests_org_active_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = _make_console(tmp_path / "WwiseConsole.sh")
    sample_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    _configure_2021_paths(monkeypatch, console_path=console, sample_project_path=sample_project)
    unsafe_project = ORG_FIXTURE_2021_ROOT / "SampleProject.wproj"
    _pretend_paths_exist(monkeypatch, {ORG_FIXTURE_2021_ROOT, unsafe_project})
    sandbox = _sandbox_project(source_project=sample_project, sandbox_root=ORG_FIXTURE_2021_ROOT, sandbox_project=unsafe_project)

    with pytest.raises(LiveEnvironmentError) as exc_info:
        require_2021_sandbox_copy_target(
            {"WWISE_CONSOLE": str(console), "WWISE_SAMPLE_PROJECT_PATH": str(sample_project)}, sandbox
        )

    message = str(exc_info.value)
    assert "WWISE_DESTRUCTIVE=1 guard failure" in message
    assert "tests/_org" in message


def test_2021_sandbox_copy_target_rejects_non_exact_source_before_launch_or_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = _make_console(tmp_path / "WwiseConsole.sh")
    exact_source = _make_project(tmp_path / "exact" / "SampleProject" / "SampleProject.wproj")
    wrong_source = _make_project(tmp_path / "wrong" / "SampleProject" / "SampleProject.wproj")
    sandbox_root = tmp_path / "runtime" / "safe-sandbox-root"
    sandbox_project = _make_project(sandbox_root / "sample-project-copy" / "SampleProject.wproj")
    _configure_2021_paths(monkeypatch, console_path=console, sample_project_path=exact_source)
    sandbox = _sandbox_project(source_project=wrong_source, sandbox_root=sandbox_root, sandbox_project=sandbox_project)

    with pytest.raises(SandboxFixtureError) as exc_info:
        require_2021_sandbox_copy_target({"WWISE_CONSOLE": str(console)}, sandbox)

    assert "exact installed 2021.1 SampleProject source" in str(exc_info.value)


def test_2021_sandbox_copy_target_accepts_only_copied_sandbox_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    console = _make_console(tmp_path / "WwiseConsole.sh")
    source_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    sandbox_root = tmp_path / "runtime" / "safe-sandbox-root"
    sandbox_project = _make_project(sandbox_root / "sample-project-copy" / "SampleProject.wproj")
    _configure_2021_paths(monkeypatch, console_path=console, sample_project_path=source_project)
    sandbox = _sandbox_project(source_project=source_project, sandbox_root=sandbox_root, sandbox_project=sandbox_project)

    contract = require_2021_sandbox_copy_target(
        {"WWISE_CONSOLE": str(console), "WWISE_SAMPLE_PROJECT_PATH": str(source_project)}, sandbox
    )

    assert contract.active_destructive_project == sandbox_project.resolve(strict=False)


def test_2021_source_immutability_check_detects_source_project_mutation(tmp_path: Path) -> None:
    source_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    sandbox_project = _make_project(tmp_path / "runtime" / "sample-project-copy" / "SampleProject.wproj")
    sandbox = _sandbox_project(
        source_project=source_project,
        sandbox_root=sandbox_project.parent.parent,
        sandbox_project=sandbox_project,
    )
    runtime = Destructive2021SandboxRuntime({})
    runtime.sandbox = sandbox
    runtime.source_mtime_before = source_project.stat().st_mtime
    runtime.source_project_files_hash_before = hash_mutation_bearing_project_files(source_project.parent)

    source_project.write_text("<WwiseDocument mutated=\"true\" />\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        runtime.assert_source_unchanged()


def test_2021_stale_sandbox_cleanup_only_removes_2021_pending_copies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_project = _make_project(tmp_path / "installed" / "SampleProject" / "SampleProject.wproj")
    monkeypatch.setattr(destructive_2021_sandbox, "WWISE_2021_1_SAMPLE_PROJECT_PATH", source_project)
    root = tmp_path / "runtime"
    stale = root / "sample-project-stale"
    kept = root / "sample-project-kept"
    other_version = root / "sample-project-2025"
    stale.mkdir(parents=True)
    kept.mkdir(parents=True)
    other_version.mkdir(parents=True)
    (stale / "sandbox-metadata.json").write_text(
        json.dumps(
            {
                "keep_decision": "pending",
                "sandbox_path": str(stale),
                "source_path": str(source_project),
            }
        ),
        encoding="utf-8",
    )
    (kept / "sandbox-metadata.json").write_text(
        json.dumps(
            {
                "keep_decision": "kept:/tmp/evidence",
                "sandbox_path": str(kept),
                "source_path": str(source_project),
            }
        ),
        encoding="utf-8",
    )
    (other_version / "sandbox-metadata.json").write_text(
        json.dumps(
            {
                "keep_decision": "pending",
                "sandbox_path": str(other_version),
                "source_path": str(tmp_path / "SampleProject2025.1" / "SampleProject.wproj"),
            }
        ),
        encoding="utf-8",
    )

    cleanup_stale_2021_destructive_sandboxes(root)

    assert not stale.exists()
    assert kept.exists()
    assert other_version.exists()


def _make_console(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _make_project(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<WwiseDocument />\n", encoding="utf-8")
    return path


def _configure_2021_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    console_path: Path,
    sample_project_path: Path,
) -> None:
    monkeypatch.setattr(live_env, "WWISE_2021_1_CONSOLE_PATH", console_path)
    monkeypatch.setattr(live_env, "WWISE_2021_1_SAMPLE_PROJECT_PATH", sample_project_path)
    monkeypatch.setattr(live_env, "INSTALLED_SAMPLE_PROJECT_2021_1_ROOT", sample_project_path.parent)
    monkeypatch.setattr(destructive_2021_sandbox, "WWISE_2021_1_CONSOLE_PATH", console_path)
    monkeypatch.setattr(destructive_2021_sandbox, "WWISE_2021_1_SAMPLE_PROJECT_PATH", sample_project_path)
    version_paths = dict(live_env.LIVE_VERSION_PATHS)
    version_paths["2021.1"] = live_env._LiveVersionPaths(
        version="2021.1",
        console_path=console_path,
        sample_project_path=sample_project_path,
        require_exact_paths=True,
    )
    monkeypatch.setattr(live_env, "LIVE_VERSION_PATHS", version_paths)


def _pretend_paths_exist(monkeypatch: pytest.MonkeyPatch, paths: set[Path]) -> None:
    real_exists = Path.exists
    fake_existing_paths = {path.resolve(strict=False) for path in paths}

    def fake_exists(path: Path) -> bool:
        if path.resolve(strict=False) in fake_existing_paths:
            return True
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)


def _sandbox_project(*, source_project: Path, sandbox_root: Path, sandbox_project: Path) -> SandboxProject:
    source_root = source_project.parent.resolve(strict=True)
    resolved_sandbox_root = sandbox_root.resolve(strict=False)
    resolved_sandbox_project = sandbox_project.resolve(strict=False)
    sandbox_path = resolved_sandbox_project.parent
    project_hash = ProjectHash(
        algorithm="sha256",
        strategy="unit-test-placeholder",
        digest="0" * 64,
        file_count=1,
        bytes_hashed=0,
    )
    return SandboxProject(
        source_project=source_project.resolve(strict=True),
        source_root=source_root,
        sandbox_root=resolved_sandbox_root,
        sandbox_path=sandbox_path,
        sandbox_project=resolved_sandbox_project,
        metadata=SandboxMetadata(
            source_path=str(source_project.resolve(strict=True)),
            source_root=str(source_root),
            sandbox_path=str(sandbox_path),
            sandbox_project_path=str(resolved_sandbox_project),
            wwise_version="2021.1",
            copy_duration_seconds=0.0,
            source_hash=project_hash,
            sandbox_hash=project_hash,
            source_mtime_before=source_project.stat().st_mtime,
            expected_project_identity=source_project.stem,
        ),
    )

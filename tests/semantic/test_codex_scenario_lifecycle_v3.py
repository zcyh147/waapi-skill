from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.platform_filesystem import create_symlink_or_skip
from tests.destructive.support.sandbox_fixture import (
    ProjectHash,
    SandboxMetadata,
    SandboxProject,
)
from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle_v3


class _FakeLock:
    entered = 0
    exited = 0

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "fake.lock"

    def __enter__(self):
        type(self).entered += 1
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        type(self).exited += 1


def _project_hash(value: str = "a" * 64) -> ProjectHash:
    return ProjectHash(
        algorithm="sha256",
        strategy="full",
        digest=value,
        file_count=1,
        bytes_hashed=4,
    )


def _install_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, shutdown_error=False):
    source_root = tmp_path / "immutable-source"
    source_root.mkdir()
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("test", encoding="utf-8")
    fixed_hash = _project_hash()

    def fake_require(_env):
        return SimpleNamespace(version="2022.1", sample_project_source=source_project)

    def fake_prepare(_env, *, sandbox_root: Path, hash_strategy: str):
        assert hash_strategy == "full"
        sandbox_path = sandbox_root / "case-copy"
        sandbox_path.mkdir(parents=True)
        sandbox_project = sandbox_path / "SampleProject.wproj"
        sandbox_project.write_text("copy", encoding="utf-8")
        metadata = SandboxMetadata(
            source_path=str(source_project),
            source_root=str(source_root),
            sandbox_path=str(sandbox_path),
            sandbox_project_path=str(sandbox_project),
            wwise_version="2022.1",
            copy_duration_seconds=0.01,
            source_hash=fixed_hash,
            sandbox_hash=fixed_hash,
            source_mtime_before=source_project.stat().st_mtime,
        )
        return SandboxProject(
            source_project=source_project,
            source_root=source_root,
            sandbox_root=sandbox_root,
            sandbox_path=sandbox_path,
            sandbox_project=sandbox_project,
            metadata=metadata,
        )

    launched_env = {}

    def fake_launch(sandbox, env, **kwargs):
        launched_env.update(env)
        launched_env["__launch_kwargs__"] = kwargs
        return SimpleNamespace(
            host="127.0.0.1",
            port=49152,
            command=("WwiseConsole", str(sandbox.sandbox_project)),
            launch_cwd=sandbox.sandbox_root.resolve(strict=True),
        )

    def fake_shutdown(_lifecycle, _sandbox, *, suppress_errors: bool):
        assert suppress_errors is False
        if shutdown_error:
            raise RuntimeError("residual process")

    def fake_cleanup(sandbox, *, keep: bool, failed: bool):
        assert not keep and not failed
        shutil.rmtree(sandbox.sandbox_path)
        return None

    monkeypatch.setattr(lifecycle_v3, "LiveSandboxLock", _FakeLock)
    monkeypatch.setattr(lifecycle_v3, "require_live_environment", fake_require)
    monkeypatch.setattr(lifecycle_v3, "prepare_sample_project_sandbox", fake_prepare)
    monkeypatch.setattr(lifecycle_v3, "launch_sandboxed_wwise", fake_launch)
    monkeypatch.setattr(lifecycle_v3, "shutdown_sandboxed_wwise", fake_shutdown)
    monkeypatch.setattr(lifecycle_v3, "cleanup_sandbox", fake_cleanup)
    monkeypatch.setattr(lifecycle_v3, "hash_project", lambda *_args, **_kwargs: fixed_hash)
    return source_project, launched_env


def _controller(tmp_path: Path) -> lifecycle_v3.ScenarioLifecycle:
    return lifecycle_v3.ScenarioLifecycle(
        scenario_id="OBJ22-F-CREATE-01",
        version="2022.1",
        scenario_root=tmp_path / "scenario",
        live_environment={"WWISE_TEST_CONFIG": "unused"},
        lock_root=tmp_path / "lock",
    )


def _private_home_controller(
    tmp_path: Path,
    *,
    prelaunch_hook=None,
) -> tuple[lifecycle_v3.ScenarioLifecycle, Path]:
    scenario_root = tmp_path / "scenario"
    private_home = scenario_root / "owned" / "wwise-user-home"
    return (
        lifecycle_v3.ScenarioLifecycle(
            scenario_id="VS25-F-MEDIAPOOL-GET-03",
            version="2022.1",
            scenario_root=scenario_root,
            live_environment={"WWISE_TEST_CONFIG": "unused"},
            prelaunch_hook=prelaunch_hook,
            launch_environment_overrides={"HOME": str(private_home)},
            lock_root=tmp_path / "lock",
        ),
        private_home,
    )


def _install_home_populating_launch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    symlink_target: Path,
) -> None:
    def launch(sandbox, env):
        private_home = Path(env["HOME"])
        preferences = private_home / "preferences"
        preferences.mkdir()
        (preferences / "settings.ini").write_bytes(b"settings")
        create_symlink_or_skip(
            private_home / "BuiltinBottles",
            symlink_target,
            target_is_directory=True,
        )
        return SimpleNamespace(
            host="127.0.0.1",
            port=49152,
            command=("WwiseConsole", str(sandbox.sandbox_project)),
            launch_cwd=sandbox.sandbox_root.resolve(strict=True),
        )

    monkeypatch.setattr(lifecycle_v3, "launch_sandboxed_wwise", launch)


def test_passing_scenario_deletes_all_owned_runtime_state(monkeypatch, tmp_path) -> None:
    _FakeLock.entered = _FakeLock.exited = 0
    _install_fakes(monkeypatch, tmp_path)
    controller = _controller(tmp_path)
    runtime = controller.start()
    (runtime.asset_root / "input.wav").write_bytes(b"audio")
    start = json.loads(
        (runtime.evidence_root / "start.json").read_text(encoding="utf-8")
    )

    assert start["launch_cwd"] == str(runtime.sandbox.sandbox_root.resolve(strict=True))
    assert start["launch_cwd"] != start["sandbox_project"]

    result = controller.finish("PASS")

    assert result.final_status == "PASS"
    assert not result.sandbox_retained
    assert not runtime.owned_root.exists()
    assert (runtime.evidence_root / "lifecycle.json").is_file()
    assert _FakeLock.entered == _FakeLock.exited == 1


def test_launch_environment_uses_only_fresh_case_owned_user_state(
    monkeypatch, tmp_path
) -> None:
    _source, launched_env = _install_fakes(monkeypatch, tmp_path)
    scenario_root = tmp_path / "scenario"
    private_home = scenario_root / "owned" / "wwise-user-home"
    controller = lifecycle_v3.ScenarioLifecycle(
        scenario_id="VS25-F-MEDIAPOOL-GET-02",
        version="2022.1",
        scenario_root=scenario_root,
        live_environment={"WWISE_TEST_CONFIG": "unused"},
        launch_environment_overrides={"HOME": str(private_home)},
        lock_root=tmp_path / "lock",
    )

    runtime = controller.start()

    assert private_home.is_dir()
    assert launched_env["HOME"] == str(private_home.resolve())
    assert runtime.runner_environment["HOME"] == str(private_home.resolve())
    assert runtime.runner_environment["WINEPREFIX"] == str(
        runtime.sandbox.wine_prefix_path
    )
    assert runtime.runner_environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert runtime.sandbox.wine_prefix_path.is_relative_to(runtime.owned_root)
    controller.finish("PASS")


def test_launch_environment_accepts_native_windows_user_state_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _source, launched_env = _install_fakes(monkeypatch, tmp_path)
    scenario_root = tmp_path / "scenario"
    owned = scenario_root / "owned"
    overrides = {
        "USERPROFILE": str(owned / "wwise-user-profile"),
        "APPDATA": str(owned / "wwise-appdata"),
        "LOCALAPPDATA": str(owned / "wwise-localappdata"),
    }
    controller = lifecycle_v3.ScenarioLifecycle(
        scenario_id="VS25-F-MEDIAPOOL-GET-02",
        version="2022.1",
        scenario_root=scenario_root,
        live_environment={"WWISE_TEST_CONFIG": "unused"},
        launch_environment_overrides=overrides,
        lock_root=tmp_path / "lock",
    )

    runtime = controller.start()

    for key, raw_path in overrides.items():
        expected = str(Path(raw_path).resolve())
        assert launched_env[key] == expected
        assert runtime.runner_environment[key] == expected
        assert Path(expected).is_dir()
    controller.finish("PASS")


def test_launch_environment_baseline_rejects_windows_junction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-home"
    junction = root / "redirected"
    junction.mkdir(parents=True)
    (junction / "outside.txt").write_text("outside\n", encoding="utf-8")
    real_is_junction = getattr(Path, "is_junction", lambda _self: False)
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda self: self == junction or real_is_junction(self),
        raising=False,
    )

    with pytest.raises(
        lifecycle_v3.ScenarioLifecycleError,
        match="junction or reparse point",
    ):
        lifecycle_v3._collect_symlink_pairs(root)


def test_lifecycle_binds_explicit_effective_wine_prefix_to_private_home(
    monkeypatch, tmp_path
) -> None:
    _source, launched_env = _install_fakes(monkeypatch, tmp_path)
    scenario_root = tmp_path / "scenario"
    private_home = scenario_root / "owned" / "wwise-user-home"
    wine_prefix = (
        private_home
        / "Library"
        / "Application Support"
        / "Wwise2019"
        / "Bottles"
        / "Wwise2019x64"
    )
    controller = lifecycle_v3.ScenarioLifecycle(
        scenario_id="VS25-F-MEDIAPOOL-GET-02",
        version="2022.1",
        scenario_root=scenario_root,
        live_environment={"WWISE_TEST_CONFIG": "unused"},
        launch_environment_overrides={"HOME": str(private_home)},
        owned_wine_prefix=wine_prefix,
        lock_root=tmp_path / "lock",
    )

    runtime = controller.start()

    assert not wine_prefix.exists()
    assert launched_env["__launch_kwargs__"] == {
        "wine_prefix_path": wine_prefix.resolve(strict=False),
        "case_owned_root": (scenario_root / "owned").resolve(strict=True),
    }
    assert runtime.runner_environment["WINEPREFIX"] == str(
        wine_prefix.resolve(strict=False)
    )
    controller.finish("PASS")


def test_owned_wine_prefix_requires_private_home_and_fresh_owned_descendant(
    tmp_path: Path,
) -> None:
    scenario_root = tmp_path / "scenario"
    with pytest.raises(ValueError, match="requires a private HOME"):
        lifecycle_v3.ScenarioLifecycle(
            scenario_id="VS25-F-MEDIAPOOL-GET-02",
            version="2025.1",
            scenario_root=scenario_root,
            live_environment={"WWISE_TEST_CONFIG": "unused"},
            owned_wine_prefix=scenario_root / "owned" / "wine",
        )

    private_home = scenario_root / "owned" / "home"
    with pytest.raises(ValueError, match="strictly below"):
        lifecycle_v3.ScenarioLifecycle(
            scenario_id="VS25-F-MEDIAPOOL-GET-02",
            version="2025.1",
            scenario_root=scenario_root,
            live_environment={"WWISE_TEST_CONFIG": "unused"},
            launch_environment_overrides={"HOME": str(private_home)},
            owned_wine_prefix=scenario_root / "owned" / "outside-home",
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("WINEPREFIX", "owned/wine"),
        ("WWISE_VERSION", "owned/version"),
        ("PATH", "owned/bin"),
        ("HOME", "/tmp/not-owned-by-the-case"),
    ],
)
def test_launch_environment_refuses_reserved_or_non_owned_overrides(
    tmp_path: Path, key: str, value: str
) -> None:
    scenario_root = tmp_path / "scenario"
    raw_value = (
        str(scenario_root / "owned" / value)
        if not value.startswith("/")
        else value
    )
    with pytest.raises(ValueError, match="launch environment override"):
        lifecycle_v3.ScenarioLifecycle(
            scenario_id="VS25-F-MEDIAPOOL-GET-02",
            version="2025.1",
            scenario_root=scenario_root,
            live_environment={"WWISE_TEST_CONFIG": "unused"},
            launch_environment_overrides={key: raw_value},
            lock_root=tmp_path / "lock",
        )


def test_failed_scenario_is_sealed_and_cannot_be_reused(monkeypatch, tmp_path) -> None:
    _install_fakes(monkeypatch, tmp_path)
    controller = _controller(tmp_path)
    runtime = controller.start()
    (runtime.io_root / "partial.bnk").write_bytes(b"partial")

    result = controller.finish("FAIL", reason="oracle mismatch")

    assert result.final_status == "FAIL"
    assert result.sandbox_retained
    assert runtime.owned_root.exists()
    assert result.quarantine_path is not None
    quarantine_path = Path(result.quarantine_path)
    quarantine = json.loads(quarantine_path.read_text(encoding="utf-8"))
    assert quarantine["owned_tree_sha256"] == lifecycle_v3.stable_tree_sha256(
        runtime.owned_root
    )
    with pytest.raises(lifecycle_v3.ScenarioLifecycleError, match="already exists"):
        _controller(tmp_path).start()


def test_failed_scenario_archives_and_removes_only_launch_environment_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fakes(monkeypatch, tmp_path)
    external_target = tmp_path / "external-bottles"
    external_target.mkdir()
    _install_home_populating_launch(
        monkeypatch,
        symlink_target=external_target,
    )
    controller, private_home = _private_home_controller(tmp_path)
    runtime = controller.start()
    (private_home / "after-ready.log").write_text("codex state", encoding="utf-8")
    outside_link = runtime.io_root / "not-a-launch-environment-link"
    create_symlink_or_skip(
        outside_link,
        external_target,
        target_is_directory=True,
    )

    result = controller.finish("FAIL", reason="oracle mismatch")

    assert result.final_status == "FAIL"
    assert result.sandbox_retained
    assert not os.path.lexists(private_home)
    assert outside_link.is_symlink()
    archive_path = runtime.evidence_root / "launch-environment-archive.json"
    assert archive_path.is_file() and not archive_path.is_symlink()
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["contract"] == (
        lifecycle_v3.SCENARIO_LAUNCH_ENVIRONMENT_ARCHIVE_CONTRACT
    )
    assert archive["phase"] == "finish"
    assert len(archive["roots"]) == 1
    home = archive["roots"][0]
    expected_link = [
        {"path": "BuiltinBottles", "raw_target": str(external_target)}
    ]
    assert home["environment_key"] == "HOME"
    assert home["ready_symlinks"] == expected_link
    assert home["final_symlinks"] == expected_link
    assert home["ready_symlinks_match_final"] is True
    entries = {row["path"]: row for row in home["entries"]}
    assert entries["BuiltinBottles"] == {
        "path": "BuiltinBottles",
        "type": "symlink",
        "target": str(external_target),
    }
    assert entries["preferences"]["type"] == "directory"
    assert entries["preferences/settings.ini"] == {
        "path": "preferences/settings.ini",
        "type": "file",
        "executable": False,
        "size": len(b"settings"),
        "sha256": hashlib.sha256(b"settings").hexdigest(),
    }
    assert entries["after-ready.log"]["size"] == len(b"codex state")
    assert Path(result.quarantine_path).is_file()


def test_changed_ready_symlink_blocks_archive_and_retains_private_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fakes(monkeypatch, tmp_path)
    first_target = tmp_path / "first-target"
    second_target = tmp_path / "second-target"
    first_target.mkdir()
    second_target.mkdir()
    _install_home_populating_launch(
        monkeypatch,
        symlink_target=first_target,
    )
    controller, private_home = _private_home_controller(tmp_path)
    runtime = controller.start()
    link = private_home / "BuiltinBottles"
    link.unlink()
    create_symlink_or_skip(link, second_target, target_is_directory=True)

    result = controller.finish("FAIL")

    assert result.final_status == "BLOCKED"
    assert result.sandbox_retained
    assert private_home.is_dir()
    assert link.is_symlink()
    assert os.readlink(link) == str(second_target)
    assert any(
        error.startswith("launch-environment-archive:")
        and "symlink set changed" in error
        for error in result.errors
    )
    assert not (runtime.evidence_root / "launch-environment-archive.json").exists()


def test_archive_readback_mismatch_blocks_without_removing_private_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fakes(monkeypatch, tmp_path)
    external_target = tmp_path / "external-target"
    external_target.mkdir()
    _install_home_populating_launch(
        monkeypatch,
        symlink_target=external_target,
    )
    controller, private_home = _private_home_controller(tmp_path)
    runtime = controller.start()
    monkeypatch.setattr(
        lifecycle_v3,
        "_read_regular_json_no_follow",
        lambda _path: {"tampered": True},
    )

    result = controller.finish("BLOCKED", reason="infrastructure boundary")

    assert result.final_status == "BLOCKED"
    assert result.sandbox_retained
    assert private_home.is_dir()
    assert any(
        error.startswith("launch-environment-archive:")
        and "readback mismatch" in error
        for error in result.errors
    )
    assert (runtime.evidence_root / "launch-environment-archive.json").is_file()


def test_shutdown_or_residual_process_fault_blocks_campaign(monkeypatch, tmp_path) -> None:
    _install_fakes(monkeypatch, tmp_path, shutdown_error=True)
    controller = _controller(tmp_path)
    runtime = controller.start()

    result = controller.finish("PASS")

    assert result.final_status == "BLOCKED"
    assert result.sandbox_retained
    assert any(error.startswith("wwise-shutdown:") for error in result.errors)
    assert runtime.owned_root.exists()


def test_shutdown_failure_does_not_archive_or_remove_private_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fakes(monkeypatch, tmp_path, shutdown_error=True)
    external_target = tmp_path / "external-target"
    external_target.mkdir()
    _install_home_populating_launch(
        monkeypatch,
        symlink_target=external_target,
    )
    controller, private_home = _private_home_controller(tmp_path)
    runtime = controller.start()

    result = controller.finish("FAIL")

    assert result.final_status == "BLOCKED"
    assert private_home.is_dir()
    assert (private_home / "BuiltinBottles").is_symlink()
    assert not (runtime.evidence_root / "launch-environment-archive.json").exists()
    assert not any(
        error.startswith("launch-environment-archive:")
        for error in result.errors
    )


def test_post_shutdown_proof_runs_before_cleanup_and_blocks_on_failure(
    monkeypatch, tmp_path
) -> None:
    _install_fakes(monkeypatch, tmp_path)
    controller = _controller(tmp_path)
    runtime = controller.start()
    observed = []

    def proof(value):
        observed.append(value.scenario_id)
        assert value.owned_root.exists()
        raise RuntimeError("global user state drift")

    result = controller.finish("PASS", post_shutdown_hook=proof)

    assert observed == [runtime.scenario_id]
    assert result.final_status == "BLOCKED"
    assert result.sandbox_retained
    assert any(error.startswith("post-shutdown-proof:") for error in result.errors)
    assert runtime.owned_root.exists()


def test_post_shutdown_failure_does_not_archive_or_remove_private_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fakes(monkeypatch, tmp_path)
    external_target = tmp_path / "external-target"
    external_target.mkdir()
    _install_home_populating_launch(
        monkeypatch,
        symlink_target=external_target,
    )
    controller, private_home = _private_home_controller(tmp_path)
    runtime = controller.start()

    def failed_proof(_runtime):
        raise RuntimeError("account-state proof failed")

    result = controller.finish("FAIL", post_shutdown_hook=failed_proof)

    assert result.final_status == "BLOCKED"
    assert private_home.is_dir()
    assert (private_home / "BuiltinBottles").is_symlink()
    assert not (runtime.evidence_root / "launch-environment-archive.json").exists()
    assert not any(
        error.startswith("launch-environment-archive:")
        for error in result.errors
    )


def test_not_started_failure_archives_private_home_without_ready_baseline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fakes(monkeypatch, tmp_path)
    external_target = tmp_path / "external-target"
    external_target.mkdir()
    private_home = tmp_path / "scenario" / "owned" / "wwise-user-home"

    def fail_before_launch(_sandbox, _asset_root, _io_root):
        (private_home / "partial").mkdir()
        (private_home / "partial" / "state.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        create_symlink_or_skip(
            private_home / "BuiltinBottles",
            external_target,
            target_is_directory=True,
        )
        raise RuntimeError("prelaunch failed")

    controller, private_home = _private_home_controller(
        tmp_path,
        prelaunch_hook=fail_before_launch,
    )

    with pytest.raises(lifecycle_v3.ScenarioLifecycleStartError) as caught:
        controller.start()

    assert not caught.value.unsafe_to_continue
    assert not os.path.lexists(private_home)
    archive_path = tmp_path / "scenario" / "evidence" / (
        "launch-environment-archive.json"
    )
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["phase"] == "start-failure"
    assert archive["roots"][0]["ready_symlinks"] is None
    assert archive["roots"][0]["final_symlinks"] == [
        {"path": "BuiltinBottles", "raw_target": str(external_target)}
    ]
    evidence = json.loads(caught.value.evidence_path.read_text(encoding="utf-8"))
    assert evidence["wwise_stop_status"] == "not-started"
    assert evidence["launch_environment_archive_path"] == str(archive_path)


def test_unproven_start_failure_leaves_private_home_untouched(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fakes(monkeypatch, tmp_path)
    external_target = tmp_path / "external-target"
    external_target.mkdir()

    def failing_launch(sandbox, env):
        private_home = Path(env["HOME"])
        create_symlink_or_skip(
            private_home / "BuiltinBottles",
            external_target,
            target_is_directory=True,
        )
        sandbox.metadata.process_cleanup_result = None
        raise RuntimeError("readiness failed")

    monkeypatch.setattr(lifecycle_v3, "launch_sandboxed_wwise", failing_launch)
    controller, private_home = _private_home_controller(tmp_path)

    with pytest.raises(lifecycle_v3.ScenarioLifecycleStartError) as caught:
        controller.start()

    assert caught.value.unsafe_to_continue
    assert private_home.is_dir()
    assert (private_home / "BuiltinBottles").is_symlink()
    archive_path = tmp_path / "scenario" / "evidence" / (
        "launch-environment-archive.json"
    )
    assert not archive_path.exists()
    evidence = json.loads(caught.value.evidence_path.read_text(encoding="utf-8"))
    assert evidence["wwise_stop_status"] == "unproven"
    assert evidence["launch_environment_archive_path"] is None

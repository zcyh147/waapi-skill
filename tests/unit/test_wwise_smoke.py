from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ci import wwise_smoke
from tests.destructive.support.sandbox_fixture import SandboxFixtureError


def _get_info(
    *,
    is_command_line: bool = True,
    year: int = 2022,
    major: int = 1,
    minor: int = 19,
    build: int = 8584,
) -> dict[str, Any]:
    return {
        "displayName": "Wwise 2022.1.19.8584",
        "isCommandLine": is_command_line,
        "version": {
            "year": year,
            "major": major,
            "minor": minor,
            "build": build,
        },
    }


def test_smoke_get_info_requires_console_lane_and_exact_build() -> None:
    assert (
        wwise_smoke._validate_console_get_info(  # pyright: ignore[reportPrivateUsage]
            _get_info(),
            expected_version="2022.1",
        )
        == "2022.1.19.8584"
    )

    with pytest.raises(wwise_smoke.WwiseSmokeError, match="isCommandLine=true"):
        wwise_smoke._validate_console_get_info(  # pyright: ignore[reportPrivateUsage]
            _get_info(is_command_line=False),
            expected_version="2022.1",
        )
    with pytest.raises(wwise_smoke.WwiseSmokeError, match="expected 2022.1"):
        wwise_smoke._validate_console_get_info(  # pyright: ignore[reportPrivateUsage]
            _get_info(year=2025, minor=7, build=9143),
            expected_version="2022.1",
        )
    with pytest.raises(wwise_smoke.WwiseSmokeError, match="expected 2022.1.19.8584"):
        wwise_smoke._validate_console_get_info(  # pyright: ignore[reportPrivateUsage]
            _get_info(minor=18, build=9999),
            expected_version="2022.1",
        )


def test_run_smoke_orders_sandbox_get_info_shutdown_source_proof_and_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("<Project />\n", encoding="utf-8")
    sandbox_path = tmp_path / "sandboxes" / "one"
    sandbox_path.mkdir(parents=True)
    sandbox_project = sandbox_path / "SampleProject.wproj"
    sandbox_project.write_text("<Project />\n", encoding="utf-8")
    metadata = SimpleNamespace(
        command=[str(tmp_path / "WwiseConsole.exe"), "waapi-server"],
        get_info_display_name="Wwise 2022.1.19.8584",
        process_cleanup_result=None,
        process_pid=4242,
        ready_duration_seconds=0.25,
        selected_port=17777,
        source_hash=SimpleNamespace(digest="0" * 64),
        wwise_version="2022.1",
    )
    sandbox = SimpleNamespace(
        metadata=metadata,
        sandbox_path=sandbox_path,
        sandbox_project=sandbox_project,
        source_project=source_project,
        source_root=source_root,
    )
    lifecycle = SimpleNamespace()
    order: list[str] = []

    def prepare(environment: dict[str, str], *, hash_strategy: str) -> Any:
        assert environment["WWISE_DESTRUCTIVE"] == "0"
        assert hash_strategy == "full"
        order.append("prepare")
        return sandbox

    def launch(
        prepared: Any,
        environment: dict[str, str],
        *,
        port: int | None,
    ) -> Any:
        assert prepared is sandbox
        assert environment["WWISE_LIVE"] == "1"
        assert environment["WWISE_DESTRUCTIVE"] == "0"
        assert port == 17777
        order.append("launch")
        return lifecycle

    def ready(running: Any) -> dict[str, Any]:
        assert running is lifecycle
        order.append("getInfo")
        return _get_info()

    def shutdown(
        running: Any,
        prepared: Any,
        *,
        suppress_errors: bool,
    ) -> None:
        assert running is lifecycle
        assert prepared is sandbox
        assert suppress_errors is False
        metadata.process_cleanup_result = "cleaned"
        order.append("shutdown")

    def source_proof(
        prepared: Any,
        *,
        source_mtime_ns_before: int,
    ) -> tuple[str, int]:
        assert prepared is sandbox
        assert source_mtime_ns_before == source_project.stat().st_mtime_ns
        assert metadata.process_cleanup_result == "cleaned"
        order.append("source-proof")
        return "a" * 64, source_mtime_ns_before

    def cleanup(prepared: Any, *, failed: bool) -> None:
        assert prepared is sandbox
        assert failed is False
        assert metadata.process_cleanup_result == "cleaned"
        order.append("sandbox-delete")
        shutil.rmtree(sandbox_path)

    monkeypatch.setattr(wwise_smoke, "prepare_sample_project_sandbox", prepare)
    monkeypatch.setattr(wwise_smoke, "launch_sandboxed_wwise", launch)
    monkeypatch.setattr(wwise_smoke, "require_lifecycle_ready_proof", ready)
    monkeypatch.setattr(wwise_smoke, "shutdown_sandboxed_wwise", shutdown)
    monkeypatch.setattr(wwise_smoke, "_require_source_unchanged", source_proof)
    monkeypatch.setattr(wwise_smoke, "cleanup_sandbox", cleanup)

    result = wwise_smoke.run_smoke(
        {
            "WWISE_VERSION": "2022.1",
            "WWISE_SAMPLE_PROJECT_PATH": str(source_project),
            "WWISE_LIVE": "1",
            "WWISE_DESTRUCTIVE": "0",
            "WWISE_SANDBOX_ROOT": str(tmp_path / "sandboxes"),
            "WWISE_WAAPI_PORT": "17777",
        }
    )

    assert order == [
        "prepare",
        "launch",
        "getInfo",
        "shutdown",
        "source-proof",
        "sandbox-delete",
    ]
    assert result == {
        "argv": metadata.command,
        "build": "2022.1.19.8584",
        "cleanup": "cleaned",
        "contract": "waapi-skill.real-smoke/v1",
        "display_name": "Wwise 2022.1.19.8584",
        "isCommandLine": True,
        "pid": 4242,
        "port": 17777,
        "ready_duration_seconds": 0.25,
        "sandbox_deleted": True,
        "sandbox_project": str(sandbox_project),
        "source_mtime_ns": source_project.stat().st_mtime_ns,
        "source_sha256": "a" * 64,
        "version": "2022.1",
    }
    assert source_project.is_file()
    assert not sandbox_path.exists()


def test_wrong_build_and_cleanup_failure_do_not_emit_success_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("<Project />\n", encoding="utf-8")
    sandbox_path = tmp_path / "sandbox"
    sandbox_path.mkdir()
    metadata = SimpleNamespace(source_hash=SimpleNamespace(digest="0" * 64))
    sandbox = SimpleNamespace(
        metadata=metadata,
        sandbox_path=sandbox_path,
        sandbox_project=sandbox_path / "SampleProject.wproj",
        source_project=source_project,
        source_root=source_root,
    )
    lifecycle = SimpleNamespace()
    cleanup_calls: list[str] = []

    monkeypatch.setattr(
        wwise_smoke,
        "prepare_sample_project_sandbox",
        lambda *_args, **_kwargs: sandbox,
    )
    monkeypatch.setattr(
        wwise_smoke,
        "launch_sandboxed_wwise",
        lambda *_args, **_kwargs: lifecycle,
    )
    monkeypatch.setattr(
        wwise_smoke,
        "require_lifecycle_ready_proof",
        lambda _lifecycle: _get_info(minor=18, build=9999),
    )

    def shutdown(*_args: Any, **_kwargs: Any) -> None:
        cleanup_calls.append("shutdown")
        raise RuntimeError("simulated cleanup failure")

    def cleanup(*_args: Any, **_kwargs: Any) -> None:
        cleanup_calls.append("sandbox")
        shutil.rmtree(sandbox_path)

    monkeypatch.setattr(wwise_smoke, "shutdown_sandboxed_wwise", shutdown)
    monkeypatch.setattr(wwise_smoke, "cleanup_sandbox", cleanup)

    with pytest.raises(wwise_smoke.WwiseSmokeError, match="cleanup errors"):
        wwise_smoke.run_smoke(
            {
                "WWISE_VERSION": "2022.1",
                "WWISE_SAMPLE_PROJECT_PATH": str(source_project),
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "0",
                "WWISE_SANDBOX_ROOT": str(tmp_path / "sandbox-root"),
            }
        )

    assert cleanup_calls == ["shutdown", "sandbox"]
    assert not sandbox_path.exists()
    assert "smoke ok:" not in capsys.readouterr().out


@pytest.mark.parametrize("relative_root", (Path("."), Path("nested")))
def test_unsafe_sandbox_root_is_rejected_before_lock_file_is_created(
    tmp_path: Path,
    relative_root: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("<Project />\n", encoding="utf-8")
    console = tmp_path / "WwiseConsole"
    console.write_text("console\n", encoding="utf-8")
    before = tuple(sorted(path.relative_to(source_root) for path in source_root.rglob("*")))

    with pytest.raises(SandboxFixtureError):
        wwise_smoke.run_smoke(
            {
                "WWISE_VERSION": "2022.1",
                "WWISE_CONSOLE": str(console),
                "WWISE_SAMPLE_PROJECT_PATH": str(source_project),
                "WWISE_LIVE": "1",
                "WWISE_DESTRUCTIVE": "0",
                "WWISE_SANDBOX_ROOT": str(source_root / relative_root),
            }
        )

    after = tuple(sorted(path.relative_to(source_root) for path in source_root.rglob("*")))
    assert after == before
    assert not (source_root / ".wwise-live-sandbox.lock").exists()
    assert not (source_root / "nested" / ".wwise-live-sandbox.lock").exists()


def test_failure_cleanup_retries_a_dirty_shutdown_before_deleting_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_path = tmp_path / "sandbox"
    sandbox_path.mkdir()
    lifecycle = SimpleNamespace(cleanup_report=SimpleNamespace(is_clean=False))
    sandbox = SimpleNamespace(sandbox_path=sandbox_path)
    calls: list[str] = []

    def retry_shutdown(*_args: Any, **_kwargs: Any) -> None:
        calls.append("retry-shutdown")
        lifecycle.cleanup_report = SimpleNamespace(is_clean=True)

    def delete_sandbox(*_args: Any, **_kwargs: Any) -> None:
        calls.append("sandbox-delete")
        shutil.rmtree(sandbox_path)

    monkeypatch.setattr(wwise_smoke, "shutdown_sandboxed_wwise", retry_shutdown)
    monkeypatch.setattr(wwise_smoke, "cleanup_sandbox", delete_sandbox)

    assert wwise_smoke._best_effort_failure_cleanup(  # pyright: ignore[reportPrivateUsage]
        lifecycle,
        sandbox,
    ) == []
    assert calls == ["retry-shutdown", "sandbox-delete"]
    assert not sandbox_path.exists()


def test_source_proof_uses_full_tree_hash_and_project_mtime(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_project = source_root / "SampleProject.wproj"
    source_project.write_text("<Project />\n", encoding="utf-8")
    source_hash = wwise_smoke.hash_project(source_root, preferred_strategy="full")
    sandbox = SimpleNamespace(
        metadata=SimpleNamespace(source_hash=source_hash),
        source_project=source_project,
        source_root=source_root,
    )
    before_mtime_ns = source_project.stat().st_mtime_ns

    digest, mtime_ns = wwise_smoke._require_source_unchanged(  # pyright: ignore[reportPrivateUsage]
        sandbox,
        source_mtime_ns_before=before_mtime_ns,
    )
    assert digest == source_hash.digest
    assert mtime_ns == before_mtime_ns

    (source_root / "new-file.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(wwise_smoke.WwiseSmokeError, match="full hash changed"):
        wwise_smoke._require_source_unchanged(  # pyright: ignore[reportPrivateUsage]
            sandbox,
            source_mtime_ns_before=before_mtime_ns,
        )


@pytest.mark.parametrize("value", ("", "zero", "0", "65536"))
def test_smoke_rejects_invalid_fixed_port(value: str) -> None:
    with pytest.raises(wwise_smoke.WwiseSmokeError, match="WWISE_WAAPI_PORT"):
        wwise_smoke._configured_port(  # pyright: ignore[reportPrivateUsage]
            {"WWISE_WAAPI_PORT": value}
        )


def test_main_prints_one_strong_marker_from_completed_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "contract": "waapi-skill.real-smoke/v1",
        "sandbox_deleted": True,
    }
    monkeypatch.setattr(wwise_smoke, "run_smoke", lambda: payload)

    assert wwise_smoke.main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("smoke ok:")
    assert json.loads(lines[0].removeprefix("smoke ok:")) == payload

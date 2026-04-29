from __future__ import annotations

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.headless import (  # pyright: ignore[reportMissingImports]
    HeadlessLifecycle,
    LifecycleTimeouts,
    WwiseConsolePathResolver,
    default_waapi_client_factory,
)
from wwise_waapi.manifest import ManifestStore, audit_manifest, build_manifest_from_caller  # pyright: ignore[reportMissingImports]


SAMPLE_PROJECT_ROOT = Path("/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject")


@pytest.mark.live
def test_live_reflection_inventory_uses_sample_project_when_available(tmp_path: Path) -> None:
    if os.getenv("WWISE_VERSION", "2022.1") != "2022.1":
        pytest.skip("Task 3 live reflection is scoped to Wwise 2022.1")

    console_path = WwiseConsolePathResolver().resolve(os.getenv("WWISE_CONSOLE"))
    if not Path(console_path).exists():
        pytest.fail(f"WwiseConsole is unavailable at {console_path}")

    project_path = _find_sample_project()
    if project_path is None:
        pytest.fail(f"SampleProject .wproj is unavailable under {SAMPLE_PROJECT_ROOT}")

    lifecycle = HeadlessLifecycle(
        console_path=console_path,
        project_path=project_path,
        timeouts=LifecycleTimeouts(
            startup=float(os.getenv("WWISE_STARTUP_TIMEOUT", "10")),
            readiness=float(os.getenv("WWISE_READINESS_TIMEOUT", "60")),
            probe=float(os.getenv("WWISE_PROBE_TIMEOUT", "5")),
            shutdown=float(os.getenv("WWISE_SHUTDOWN_TIMEOUT", "10")),
        ),
    )
    client = None
    try:
        lifecycle.run_until_ready()
        client = default_waapi_client_factory(lifecycle.waapi_url)
        manifest = build_manifest_from_caller(
            client,
            version="2022.1",
            inventory_source="live-reflection",
            wwise_build="2022.1.19.8584",
        )
        store = ManifestStore(root=tmp_path)
        store.write_manifest(manifest)
        loaded = store.load("2022.1")
        audit = audit_manifest(loaded)

        assert audit.counts_match is True
        assert audit.manifest_function_count > 0
        assert audit.manifest_topic_count > 0
        assert audit.schema_count == audit.manifest_function_count + audit.manifest_topic_count
        assert "/Applications/Audiokinetic" not in (tmp_path / "2022.1" / "manifest.json").read_text(encoding="utf-8")
    finally:
        if client is not None:
            client.disconnect()
        lifecycle.shutdown(suppress_errors=True)
        assert lifecycle.process is None or lifecycle.process.poll() is not None


def _find_sample_project() -> Path | None:
    projects = sorted(SAMPLE_PROJECT_ROOT.glob("**/*.wproj"))
    return projects[0] if projects else None

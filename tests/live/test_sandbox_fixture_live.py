from __future__ import annotations

import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from tests.destructive.support.sandbox_fixture import (  # pyright: ignore[reportMissingImports]
    LiveSandboxLock,
    cleanup_sandbox,
    hash_project,
    launch_sandboxed_wwise,
    prepare_sample_project_sandbox,
    shutdown_sandboxed_wwise,
)


@pytest.mark.live
def test_live_sample_project_launches_only_from_sandbox() -> None:
    env = dict(os.environ)
    sandbox = None
    lifecycle = None
    failed = True
    source_hash_before = None
    source_mtime_before = None

    lock_root = Path(env.get("WWISE_SANDBOX_ROOT", ".sisyphus/runtime/wwise-waapi-sandboxes")).expanduser()
    with LiveSandboxLock(lock_root):
        sandbox = prepare_sample_project_sandbox(env, hash_strategy="bounded")
        source_hash_before = hash_project(sandbox.source_root, preferred_strategy="bounded")
        source_mtime_before = sandbox.source_project.stat().st_mtime
        try:
            lifecycle = launch_sandboxed_wwise(sandbox, env)
            assert lifecycle.port is not None and lifecycle.port > 0
            command = lifecycle.command
            assert str(sandbox.sandbox_project) in command
            assert str(sandbox.source_project) not in command
            assert sandbox.metadata.selected_port == lifecycle.port
            assert sandbox.metadata.identity_verified is True
            failed = False
        finally:
            if lifecycle is not None:
                shutdown_sandboxed_wwise(lifecycle, sandbox)
            preserved = cleanup_sandbox(sandbox, failed=failed)

    assert sandbox.source_project.stat().st_mtime == source_mtime_before
    assert hash_project(sandbox.source_root, preferred_strategy="bounded").digest == source_hash_before.digest
    if failed and os.getenv("WWISE_SANDBOX_KEEP_ON_FAILURE") == "1":
        assert preserved is not None
        assert ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage" in str(preserved)
    else:
        assert not sandbox.sandbox_path.exists()

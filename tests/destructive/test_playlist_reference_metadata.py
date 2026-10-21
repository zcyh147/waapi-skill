"""Matching-host PlaylistSlot read using the existing owned sandbox fixture."""
import os

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    workflow_sandbox_runtime,
)
from tests.support.playlist_reference_observation import collect_playlist_slot_reference_metadata


pytestmark = [
    pytest.mark.live,
    pytest.mark.destructive,
    pytest.mark.skipif(
        os.environ.get("WWISE_VERSION") != "2025.1",
        reason="Exact 2025 PlaylistSlot reference observation; older Playlist list semantics remain separate work",
    ),
]


def test_playlist_slot_reference_native_metadata(workflow_sandbox_runtime):
    version = workflow_sandbox_runtime.sandbox.metadata.get_info_version
    assert isinstance(version, dict) and tuple(
        version.get(key) for key in ("year", "major", "minor", "build")
    ) == (2025, 1, 7, 9143), version
    collect_playlist_slot_reference_metadata(workflow_sandbox_runtime)

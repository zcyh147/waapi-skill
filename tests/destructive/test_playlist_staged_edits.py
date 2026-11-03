"""Separately previewed PlaylistSlot edits in one module-owned project copy."""
import os

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime
from tests.destructive.test_playlist_reference_metadata import _observe_existing_playlist_reference_change


pytestmark = [
    pytest.mark.live,
    pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") != "2025.1",
        reason="Exact 2025 PlaylistSlot reference; older list semantics remain separately owned"),
]


def test_existing_playlist_slot_reference_and_notes_use_separate_previews(workflow_sandbox_runtime):
    # Keep this case in its own module: the shared lifecycle is module-scoped,
    # and the standalone reference case changes the same source-selected slot.
    _observe_existing_playlist_reference_change(workflow_sandbox_runtime,
        staged_notes="Verified separately previewed playlist reference update")

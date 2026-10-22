"""Tagged Switch-child source receipts with separately authorized owned history."""
import os

import pytest

from tests.destructive.test_association_continue_play import _exercise_existing_association_continue_play
from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime


pytestmark = [
    pytest.mark.live,
    pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") not in {"2022.1", "2023.1"},
        reason="Owned structural history witnesses: type-absent 2022 undo and type-present 2023 undo/redo"),
]


def test_structural_association_continue_play_owned_history(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    _exercise_existing_association_continue_play(runtime,
        history_actions=("undo",) if runtime.version == "2022.1" else ("undo", "redo"))

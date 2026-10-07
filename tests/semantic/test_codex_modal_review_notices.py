"""Frozen independent owner/scope review controls at the notice seam."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice


_DATA = Path(__file__).parents[1] / "fixtures/semantic"
_FIXTURE = json.loads((_DATA / "expansion-modal-prefix-67279db-fixture.json").read_text())
_REVIEW_PATH = _DATA / "expansion-modal-review-independent-20261007.json"
_REVIEW = json.loads(_REVIEW_PATH.read_text())


@pytest.mark.parametrize("vector", _REVIEW["vectors"], ids=lambda row: row["id"])
def test_all_supplied_owners_and_finite_scope_remain_visible(vector):
    assert hashlib.sha256(_REVIEW_PATH.read_bytes()).hexdigest() == "cbb733a38e562e90f2c6f3ecff9e1847f2a457159ef14f96aed57e4b482d1f8d"
    # Independently attested copied inputs use the exact supplied owner name.
    # No live state, oracle or saved campaign is changed by this developer copy.
    fixture = _FIXTURE
    if "owner_name" in vector:
        fixture = json.loads(json.dumps(fixture).replace(
            "Expansion_EXP25-C09_EffectsOwner", vector["owner_name"]))
    records = [SimpleNamespace(command=phase, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", phase, "x"))
               for phase in ("preview-from-draft", "execute")]
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "preview-from-draft"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": vector["notice"]}},
        {"type": "item.started", "item": {"type": "command_execution", "command": "execute"}},
    ]
    accepted = expansion_preview_notice(
        SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)), records,
        version="2025.1", execute_expected=True, preview_artifact=fixture["preview_artifact"],
        before_snapshot=fixture["before_snapshot"])
    assert accepted is vector["expected"], vector["reason"]

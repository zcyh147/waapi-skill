"""Finite scope-head recognition controls at expansion_preview_notice."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice


_DATA = Path(__file__).parents[1] / "fixtures/semantic"
_FIXTURE = json.loads((_DATA / "expansion-modal-prefix-67279db-fixture.json").read_text())
_DELTA_PATH = _DATA / "expansion-modal-scope-head-delta-20261008.json"
_DELTA = json.loads(_DELTA_PATH.read_text())


@pytest.mark.parametrize("vector", _DELTA["vectors"], ids=lambda row: row["id"])
def test_declared_scope_head_cannot_disappear_on_invalid_composition(vector):
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
    assert accepted is vector["expected"]

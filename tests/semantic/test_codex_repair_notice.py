import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests.semantic.support.codex_repair_cases import repair_notice

RUNNER = Path(__file__).parents[2] / "skills/waapi-skill/scripts/run.py"


def notice(text, *, earlier=None):
    def message(value):
        return {"type": "item.completed", "item": {"type": "agent_message", "text": value}}
    commands = [SimpleNamespace(command=name, argv=("python", str(RUNNER), "gateway.py", command, "id"))
                for name, command in (("preview", "preview-from-draft"), ("execute", "execute"))]
    events = ([message(earlier)] if earlier else []) + [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "preview"}},
        message(text), {"type": "item.completed", "item": {"type": "command_execution", "command": "execute"}}]
    artifact = {"request": {"operation": "object.create", "arguments": {"name": "Repair_WindRange",
        "properties": [{"name": "Min", "value": -12}, {"name": "Max", "value": 36}, {"name": "InitialValue", "value": 7}]}}}
    return repair_notice(SimpleNamespace(stdout="\n".join(json.dumps(row) for row in events)), commands,
                         version="2025.1", execute_expected=True, preview_artifact=artifact, before_snapshot={})


@pytest.mark.parametrize("text", ["Proceeding now.", "I will create Repair_WindRange.",
    "I will create Other with range -12 to 36 and default 7.",
    "I will create Repair_WindRange with range -12 to 36 and default 8."])
def test_notice_rejects_progress_missing_identity_or_wrong_values(text):
    assert not notice(text)


def test_notice_accepts_requested_effect_and_bound_reference_to_earlier_plan():
    effect = "I will create Repair_WindRange with range -12 to 36 and default 7."
    assert notice(effect)
    assert notice("The preview matches the plan above; I will apply those changes now.", earlier=effect)

"""Independent exact-witness/entity contradiction tests for the existing grader."""
import copy
import json
import shlex
from pathlib import Path
import pytest
from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_DATA = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-planned-effect-entity-notices-55df097.json").read_text())

@pytest.mark.parametrize("pair", _DATA["pairs"], ids=lambda pair: pair["id"])
@pytest.mark.parametrize("polarity", ["positive", "negative"])
def test_planned_effect_entity_notice(pair, polarity, tmp_path):
    case = copy.deepcopy(_DATA["case"])
    for event, text in zip(case["events"][1:3], pair[polarity + "_messages"]):
        event["item"]["text"] = text
    # This existing test helper keys command records by phase aliases. Validate
    # each raw shell command against its source-attested Gateway phase, then
    # project only the command field in this private copy; raw fixture stays exact.
    for event, phase in ((case["events"][0], "preview-from-draft"),
                         (case["events"][-1], "execute")):
        outer = shlex.split(event["item"]["command"])
        assert outer[:2] == ["/bin/bash", "-lc"]
        gateway_argv = shlex.split(outer[-1])
        gateway_index = gateway_argv.index("gateway.py")
        assert gateway_argv[gateway_index + 1] == phase
        event["item"]["command"] = phase
    actual = _grammatical_notice(case)
    expected = pair["expected_" + polarity]
    diagnostic = {"id": pair["id"], "polarity": polarity, "actual": actual,
        "expected": expected, "passed": actual is expected, "reason": pair["negative_reason"]}
    (tmp_path / "notice-result.json").write_text(json.dumps(diagnostic) + "\n")
    assert actual is expected, diagnostic

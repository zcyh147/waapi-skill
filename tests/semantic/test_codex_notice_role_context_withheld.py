"""Independent withheld semantic judgments; do not change texts to fit implementation."""
import json
from pathlib import Path
import pytest
from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice, _temporal_notice_case

_FIXTURE = Path(__file__).parents[1] / "fixtures/semantic/expansion-notice-role-context-withheld-r2.json"
_PAIRS = json.loads(_FIXTURE.read_text())["pairs"]

@pytest.mark.parametrize("pair", _PAIRS, ids=lambda pair: pair["id"])
@pytest.mark.parametrize("polarity", ["positive", "negative"])
def test_withheld_role_context_paragraph(pair, polarity):
    case = _temporal_notice_case("002-EXP22-C08" if pair["family"] == "curve" else "003-EXP22-C09")
    post = case["events"][1]
    post["item"]["text"] = pair[polarity]
    # Replace the whole visible notice window, preserving exact Preview/Execute evidence.
    case["events"] = [case["events"][0], post, case["events"][-1]]
    actual = _grammatical_notice(case)
    expected = pair["expected_" + polarity]
    result = {"id": pair["id"], "family": pair["family"], "polarity": polarity,
              "expected": expected, "actual": actual, "passed": actual is expected,
              "reason": pair["negative_reason"], "text": pair[polarity]}
    assert actual is expected, result

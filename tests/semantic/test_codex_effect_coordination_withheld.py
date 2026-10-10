"""Independent paragraph judgments; implementation and corpus stay unchanged."""
import json
from pathlib import Path
import pytest
from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice, _temporal_notice_case

_PAIRS = json.loads((Path(__file__).parents[1] / "fixtures/semantic/expansion-effect-coordination-withheld-r1.json").read_text())["pairs"]

@pytest.mark.parametrize("pair", _PAIRS, ids=lambda pair: pair["id"])
@pytest.mark.parametrize("polarity", ["positive", "negative"])
def test_withheld_effect_coordination(pair, polarity, tmp_path):
    case = _temporal_notice_case("003-EXP22-C09")
    post = case["events"][1]
    post["item"]["text"] = pair[polarity]
    case["events"] = [case["events"][0], post, case["events"][-1]]
    actual = _grammatical_notice(case)
    expected = pair["expected_" + polarity]
    diagnostic = {"id": pair["id"], "polarity": polarity, "expected": expected,
                  "actual": actual, "passed": actual is expected,
                  "reason": pair["negative_reason"], "text": pair[polarity]}
    (tmp_path / "notice-result.json").write_text(json.dumps(diagnostic, ensure_ascii=False) + "\n")
    assert actual is expected, diagnostic

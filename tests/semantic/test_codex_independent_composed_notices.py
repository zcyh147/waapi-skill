"""Independent component contrasts using source-attested immutable contexts."""
import copy
import hashlib
import json
import shlex
from pathlib import Path

import pytest

from tests.semantic.test_codex_expansion_task_runner import _grammatical_notice

_FIXTURES = Path(__file__).parents[1] / "fixtures/semantic"
_DATA = json.loads((_FIXTURES / "expansion-independent-composition-87f9dc8-r2.json").read_text())


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _case(case_id):
    path = _FIXTURES / _DATA["context_fixture"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == _DATA["context_file_sha256"]
    case = copy.deepcopy(next(row for row in json.loads(path.read_text())["cases"] if row["case"] == case_id))
    proof = next(row for row in _DATA["contexts"] if row["case"] == case_id)
    for field in ("artifact", "before", "events"):
        assert _digest(case[field]) == proof[field + "_sha256"]
    assert case["source"] == proof["source"]
    for phase in proof["source"]["phases"]:
        outer = shlex.split(phase["raw_command"])
        assert outer[:2] == ["/bin/bash", "-lc"]
        argv = shlex.split(outer[-1])
        assert argv[argv.index("gateway.py") + 1] == phase["phase"]
        assert sum(event["item"].get("command") == phase["phase"] for event in case["events"]) == 1
    return case


def _post(case):
    preview = next(i for i, event in enumerate(case["events"]) if event["item"].get("command") == "preview-from-draft")
    return next(event for event in case["events"][preview + 1:] if event["item"]["type"] == "agent_message")


def _check(tmp_path, node, case, expected):
    actual = _grammatical_notice(case)
    result = {"id": node, "expected": expected, "actual": actual}
    (tmp_path / "notice-result.json").write_text(json.dumps(result) + "\n")
    assert actual is expected, result


def test_complete_notice_confirms_independent_composition_phase_seam(tmp_path):
    case = _case(_DATA["contexts"][0]["case"])
    _post(case)["item"]["text"] = ('已核对目标声音。即将追加 Wwise Gain 效果器 '
        'Expansion_EXP22-C09_NewGain，备注为“Expansion C09 appended gain”。现在执行这项修改。')
    _check(tmp_path, "supported-phase-control", case, True)


@pytest.mark.parametrize("recipe", _DATA["recipes"], ids=lambda row: row["id"])
def test_independent_composed_role_contrasts(recipe, tmp_path):
    case = _case(recipe["case"])
    post = _post(case)
    for old, new in recipe.get("replace", []):
        assert old in post["item"]["text"]
        post["item"]["text"] = post["item"]["text"].replace(old, new)
    post["item"]["text"] += recipe.get("append", "")
    if recipe.get("phase") == "late_notice":
        case["events"].remove(post)
        case["events"].append(post)
    elif recipe.get("phase") == "artifact_name_changed":
        case["artifact"]["request"]["arguments"]["plugin"]["name"] = "OtherGain"
    _check(tmp_path, recipe["id"], case, recipe["expected"])

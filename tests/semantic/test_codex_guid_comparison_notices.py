"""Frozen independent #147 comparisons at the prospective-notice boundary."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice


_ROOT = Path(__file__).parents[1] / "fixtures/semantic"
_MATRIX = _ROOT / "expansion-guid-comparison-independent-20261007.json"
_CONTEXTS = _ROOT / "expansion-guid-comparison-contexts-20261007.json"
_CASES = json.loads(_MATRIX.read_text(encoding="utf-8"))["cases"]


def _notice(vector):
    fixture = copy.deepcopy(json.loads(_CONTEXTS.read_text(encoding="utf-8"))[vector["family"]])
    if vector.get("context_damage") == "before_owner_id":
        fixture["before"]["owner"]["id"] = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "preview-from-draft"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": vector["notice"]}},
        {"type": "item.started", "item": {"type": "command_execution", "command": "execute"}},
    ]
    records = [SimpleNamespace(command=phase, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", phase, "x"))
               for phase in ("preview-from-draft", "execute")]
    return expansion_preview_notice(
        SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)), records,
        version=fixture["artifact"]["request"]["version"], execute_expected=True,
        preview_artifact=fixture["artifact"], before_snapshot=fixture["before"])


def test_exact_448_byte_comparison_preserves_independently_established_owner():
    assert hashlib.sha256(_MATRIX.read_bytes()).hexdigest() == "527c8243221ac332cff36e31920064fa99690645722d160cc734cd32455eb3bd"
    assert hashlib.sha256(_CONTEXTS.read_bytes()).hexdigest() == "a28eb7501ced6afadf78024a6dbe19d08906d46c589c6e303ffe77dfe9976883"
    witness = _CASES[0]
    assert len(witness["notice"].encode("utf-8")) == 448
    assert hashlib.sha256(witness["notice"].encode("utf-8")).hexdigest() == "0779259641f8c361fb675007bd2520d60e12b3c509fddd1da6a320f4fe0d6b9a"
    assert _notice(witness)


@pytest.mark.parametrize("vector", _CASES, ids=[vector["id"] for vector in _CASES])
def test_frozen_independent_guid_comparison_judgments(vector):
    assert _notice(vector) is vector["expected_gate"], vector["reason"]


@pytest.mark.parametrize("replacement,expected", [
    ("目标关系 GUID 与用户提供的一致", True),
    ("该关联 GUID 与你提供的 GUID 一致", True),
    ("目标关系 GUID {2E835121-0E79-4124-B73C-A69901EECE23} 与用户提供的一致", True),
    ("其他关系 GUID 与用户提供的一致", False),
    ("目标关系和其他关系 GUID 与用户提供的一致", False),
    ("目标关系 GUID 与用户提供的不一致", False),
    ("目标关系 GUID 与用户提供的可能一致", False),
    ("目标关系 GUID 与 OtherAssociation 的 GUID 一致", False),
    ("目标关系 GUID {AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA} 与用户提供的一致", False),
    ("目标关系 GUID {not-a-guid} 与用户提供的一致", False),
    ("目标关系 GUID 与用户提供的一致并修改 Pitch 为12", False),
])
def test_attested_rtpc_association_comparison_remains_separate_from_primary_sound(replacement, expected):
    fixture = json.loads((_ROOT / "expansion-midpoint-notice-919043f.json").read_text(encoding="utf-8"))
    text = fixture["events"][1]["item"]["text"].replace("目标关系 GUID 与用户提供的一致", replacement)
    events = copy.deepcopy(fixture["events"])
    events[1]["item"]["text"] = text
    records = [SimpleNamespace(command=phase, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", phase, "x"))
               for phase in ("preview-from-draft", "execute")]
    result = expansion_preview_notice(SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)), records,
        version=fixture["preview_artifact"]["request"]["version"], execute_expected=True,
        preview_artifact=fixture["preview_artifact"], before_snapshot=fixture["before_snapshot"])
    assert result is expected

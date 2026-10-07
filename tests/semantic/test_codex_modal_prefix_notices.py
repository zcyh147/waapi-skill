"""Local prospective-prefix composition at the agreed notice seam.

Inputs are developer copies; a fixture pass never changes the frozen Fresh FAIL.
"""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.semantic.support.codex_task_runner_v3 import _bound_context_notice, _bound_explicit_owners_agree, expansion_preview_notice

_DATA = Path(__file__).parents[1] / "fixtures/semantic"
_FIXTURE_PATH = _DATA / "expansion-modal-prefix-67279db-fixture.json"
_DESIGN_PATH = _DATA / "expansion-modal-prefix-independent-20261007.json"
_FIXTURE = json.loads(_FIXTURE_PATH.read_text())
_DESIGN = json.loads(_DESIGN_PATH.read_text())


def _notice(text):
    records = [SimpleNamespace(command=phase, argv=("python", "/tmp/skill/scripts/run.py", "gateway.py", phase, "x"))
               for phase in ("preview-from-draft", "execute")]
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "preview-from-draft"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
        {"type": "item.started", "item": {"type": "command_execution", "command": "execute"}},
    ]
    return expansion_preview_notice(
        SimpleNamespace(stdout="\n".join(json.dumps(event) for event in events)), records,
        version="2025.1", execute_expected=True, preview_artifact=_FIXTURE["preview_artifact"],
        before_snapshot=_FIXTURE["before_snapshot"])


def test_exact_current_operation_notice_uses_action_local_attested_owner():
    text = _FIXTURE["notice"]
    assert len(text.encode()) == 393
    assert hashlib.sha256(text.encode()).hexdigest() == "c29a1e84a7d227aeb787891cfe1ce87e72ff9eb6a8420a2c8d88f8e28d358207"
    assert _notice(text)


def test_explicit_primary_recipient_cannot_erase_next_operation_scope():
    vector = next(row for row in _DESIGN["vectors"] if row["id"] == "next-operation-explicit")
    assert not _notice(vector["notice"])


@pytest.mark.parametrize("vector", _DESIGN["vectors"], ids=lambda row: row["id"])
def test_frozen_prospective_prefix_components_keep_local_owner_and_edit_boundaries(vector):
    assert hashlib.sha256(_FIXTURE_PATH.read_bytes()).hexdigest() == "18601391f2abb04bd0d07cc3498a1c885054f007fcc74aab655a1cb93d969bbf"
    assert hashlib.sha256(_DESIGN_PATH.read_bytes()).hexdigest() == "793b49a1f3fcb73f694355a75887abd9d16d7755ba18826118fe6eff5cd20462"
    assert _notice(vector["notice"]) is vector["expected"], vector["reason"]


_REFERENCE_PATH = _DATA / "expansion-modal-prefix-reference-controls-20261007.json"
_REFERENCE = json.loads(_REFERENCE_PATH.read_text())


@pytest.mark.parametrize("vector", _REFERENCE["vectors"], ids=lambda row: row["id"])
def test_shared_recipient_component_keeps_stinger_primary_distinct_from_trigger_destination(vector):
    # Supplementary component controls; the public fixture tests above own the
    # notice seam and no test here grants fresh Agent acceptance credit.
    assert hashlib.sha256(_REFERENCE_PATH.read_bytes()).hexdigest() == "bd5ff3e6f06f42c67916e397e71ddc0b55ec015c7da62e595addc4f25f0eae16"
    context = _bound_context_notice(_REFERENCE["artifact"], _REFERENCE["before"])
    assert context is not None
    assert _bound_explicit_owners_agree(vector["prefix"], "", context, source_referent=True) is vector["recipient_agrees"]


@pytest.mark.parametrize("name", ["下次将向目标声音", "本次第二次将", "已经可能不会"])
def test_scope_words_inside_exact_recipient_names_are_opaque_identity_operands(name):
    context = copy.deepcopy(_bound_context_notice(_FIXTURE["preview_artifact"], _FIXTURE["before_snapshot"]))
    assert context is not None
    context["source_names"] = (name, context["source_names"][-1])
    assert _bound_explicit_owners_agree("本次将向 " + name, "", context, source_referent=False)


@pytest.mark.parametrize("prefix", ["本次将", "此次会"])
@pytest.mark.parametrize("bridge", ["missing-owner", "unknown-bridge"])
def test_current_modal_cannot_fall_back_to_legacy_preview_owner_authority(prefix, bridge):
    text = _FIXTURE["notice"].replace("本次将追加", prefix + "追加")
    if bridge == "missing-owner":
        text = text.split("。", 1)[1]
    else:
        text = text.replace(prefix + "追加", "普通进展说明。" + prefix + "追加")
    assert not _notice(text)


@pytest.mark.parametrize("prefix", ["本次将普通进展向目标声音", "本次普通进展将向目标声音"])
def test_unknown_text_between_prefix_components_remains_unconsumed(prefix):
    text = _FIXTURE["notice"].replace("本次将追加", prefix + "追加")
    assert not _notice(text)

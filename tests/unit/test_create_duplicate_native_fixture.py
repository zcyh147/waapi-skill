"""Non-live controls for the native CREATE result-association oracle."""
from copy import deepcopy
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def collector(monkeypatch):
    # Import live-only definitions, without requesting a sandbox or workflow body.
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    return importlib.import_module("tests.destructive.test_create_duplicate_native")


def test_create_native_witness_collects_one_existing_lifecycle_node(collector, request):
    module = pytest.Module.from_parent(request.session, path=Path(collector.__file__))
    items = list(module.collect())
    assert [item.name for item in items] == ["test_create_duplicate_siblings_bind_actual_guid_reference_2021"]
    assert "workflow_sandbox_runtime" in items[0].fixturenames


def _stage_evidence(collector):
    # Worked example: opaque observed names and GUIDs, independent of requested
    # names and of any predicted native naming convention. This is not Wwise proof.
    root, destination, sender = ("{11111111-1111-1111-1111-111111111111}",
        "{22222222-2222-2222-2222-222222222222}", "{33333333-3333-3333-3333-333333333333}")
    created = {"routing": {"id": root, "name": "Observed parent"},
        "destination": {"id": destination, "name": "Native alpha"},
        "sender": {"id": sender, "name": "Native omega"}}
    stages = []
    for parent, kind, requested, identity, actual in (
            (collector.OWNER, "Bus", "Routing", root, "Observed parent"),
            (root, "AuxBus", "Send", destination, "Native alpha"),
            (root, "AuxBus", "Send", sender, "Native omega")):
        stages.append({"uri": collector.CREATE, "args": {"parent": parent, "type": kind, "name": requested,
            "onNameConflict": "rename", "autoAddToSourceControl": False, "platform": collector.WINDOWS},
            "dispatch_result": {"ok": True, "result": {"id": identity, "name": actual}}})
    stages.append({"uri": collector.REFERENCE, "args": {"object": sender, "reference": "UserAuxSend0",
        "value": destination, "platform": collector.WINDOWS}, "dispatch_result": {"ok": True, "result": {}}})
    return {"stages": stages}, created


def test_create_native_association_accepts_actual_names_without_suffix_inference(collector):
    collector._assert_actual_create_calls(*_stage_evidence(collector))


@pytest.mark.parametrize("fault", ["wrong-parent", "swapped-sibling-guids", "wrong-reference", "synthetic-set-result"])
def test_create_native_association_rejects_misattributed_stage_proof(collector, fault):
    proof, created = deepcopy(_stage_evidence(collector))
    stages = proof["stages"]
    if fault == "wrong-parent":
        stages[2]["args"]["parent"] = collector.OWNER
    elif fault == "swapped-sibling-guids":
        a, b = stages[1]["dispatch_result"]["result"], stages[2]["dispatch_result"]["result"]
        a["id"], b["id"] = b["id"], a["id"]
    elif fault == "wrong-reference":
        stages[-1]["args"]["value"] = created["routing"]["id"]
    else:
        stages[0]["uri"] = "ak.wwise.core.object.set"
        stages[0]["dispatch_result"]["result"] = {"objects": [{"id": created["routing"]["id"]}]}
    with pytest.raises(AssertionError):
        collector._assert_actual_create_calls(proof, created)

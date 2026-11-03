"""Non-live controls for selecting and checking the two native-history witnesses."""
from copy import deepcopy
import importlib
from pathlib import Path

import pytest

@pytest.fixture
def collector(monkeypatch):
    # Match the existing collector-unit seam: import live-only definitions but
    # never request their sandbox fixture or invoke the workflow body.
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    return importlib.import_module("tests.destructive.test_multiple_root_owned_history")


@pytest.mark.parametrize("node,settings", [
    ("test_multiple_colliding_roots_reference_owned_history", {}),
    ("test_duplicate_siblings_below_new_parent_reference_owned_history", {"duplicate_siblings": True}),
])
def test_native_history_node_selects_its_own_fixed_graph(monkeypatch, collector, node, settings):
    runtime, calls = object(), []
    monkeypatch.setattr(collector, "_exercise_owned_creation_history",
        lambda selected, **kwargs: calls.append((selected, kwargs)))
    getattr(collector, node)(runtime)
    assert calls == [(runtime, settings)]


def test_native_history_nodes_collect_without_starting_the_sandbox(collector, request):
    module = pytest.Module.from_parent(request.session, path=Path(collector.__file__))
    items = list(module.collect())
    assert {item.name for item in items} == {
        "test_multiple_colliding_roots_reference_owned_history",
        "test_duplicate_siblings_below_new_parent_reference_owned_history",
    }
    assert all("workflow_sandbox_runtime" in item.fixturenames for item in items)


def _public_occurrences():
    owner = "{ED2BCAC8-D7B6-4448-8900-439B557894F4}"
    root = "{11111111-1111-1111-1111-111111111111}"
    destination = "{22222222-2222-2222-2222-222222222222}"
    sender = "{33333333-3333-3333-3333-333333333333}"
    handles = {"routing": "routing-handle", "destination": "destination-handle", "sender": "sender-handle"}
    specs = {
        "routing": {"request_path": "$.objects[0].children[0]", "requested_name": "Routing"},
        "destination": {"request_path": "$.objects[0].children[0].children[0]", "requested_name": "Send"},
        "sender": {"request_path": "$.objects[0].children[0].children[1]", "requested_name": "Send"},
    }
    independent = {
        "routing": {"id": root, "name": "Observed routing", "type": "Bus", "class_id": 1376272,
            "path": r"\Busses\SFX\Observed routing", "parent": {"id": owner}},
        "destination": {"id": destination, "name": "Native alpha", "type": "AuxBus", "class_id": 3997712,
            "path": r"\Busses\SFX\Observed routing\Native alpha", "parent": {"id": root}},
        "sender": {"id": sender, "name": "Native omega", "type": "AuxBus", "class_id": 3997712,
            "path": r"\Busses\SFX\Observed routing\Native omega", "parent": {"id": root}},
    }
    roster = [
        {"result_handle": handles[role], **specs[role], "compound_child_index": 0,
            "object": {key: independent[role][key] for key in ("id", "name", "type", "path")},
            "class_id": independent[role]["class_id"], "parent_id": independent[role]["parent"]["id"]}
        for role in ("sender", "routing", "destination")
    ]
    verified = {"agent_result": {"business_result": {"configuration_complete": True,
        "identity_source": "independently_verified_creation_occurrences", "created_objects": roster}}}
    return verified, handles, specs, independent


def test_public_occurrence_oracle_uses_compound_result_handles_not_roster_order_or_names(collector):
    collector._assert_public_created_objects(*_public_occurrences())


@pytest.mark.parametrize("fault", ["missing", "swapped-duplicate-handles", "wrong-parent", "aliased-handle"])
def test_public_occurrence_oracle_rejects_incomplete_or_misattributed_objects(collector, fault):
    verified, handles, specs, independent = deepcopy(_public_occurrences())
    roster = verified["agent_result"]["business_result"]["created_objects"]
    if fault == "missing":
        roster.pop()
    elif fault == "swapped-duplicate-handles":
        roster[0]["result_handle"], roster[2]["result_handle"] = roster[2]["result_handle"], roster[0]["result_handle"]
    elif fault == "wrong-parent":
        roster[0]["parent_id"] = independent["routing"]["parent"]["id"]
    else:
        roster[0]["result_handle"] = roster[2]["result_handle"]
    with pytest.raises(AssertionError):
        collector._assert_public_created_objects(verified, handles, specs, independent)

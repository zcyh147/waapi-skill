"""Non-live controls for the bounded existing-EQ native observation oracle."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    return importlib.import_module("tests.destructive.test_eq_gain_condition")


def test_eq_witness_collects_one_existing_lifecycle_node(collector, request):
    module = pytest.Module.from_parent(request.session, path=Path(collector.__file__))
    items = list(module.collect())
    assert [item.name for item in items] == ["test_existing_eq_gain_preserves_condition_controllers_and_context"]
    assert "workflow_sandbox_runtime" in items[0].fixturenames


def _metadata(collector):
    return {"GainBand1": {"name": "GainBand1", "type": "Real32", "supports": {"unlink": False},
            "restriction": {"type": "range", "min": -24.0, "max": 24.0},
            "dependencies": deepcopy([collector.SHOW, collector.ENABLE, collector.FILTER])},
        "OnOffBand1": {"name": "OnOffBand1", "type": "bool", "supports": {"unlink": False},
            "dependencies": deepcopy([collector.SHOW])},
        "FilterTypeBand1": {"name": "FilterTypeBand1", "type": "int32", "supports": {"unlink": False},
            "restriction": {"type": "enum", "values": [{"value": value} for value in (0, 1, 7, 8, 2, 3, 6, 4, 5)]},
            "dependencies": deepcopy([collector.SHOW, collector.ENABLE])},
        "NumBands": {"name": "NumBands", "type": "int32", "supports": {"unlink": False},
            "restriction": {"type": "range", "min": 1, "max": 8}, "dependencies": []}}


def test_eq_metadata_accepts_native_order_and_labels_without_dropping_siblings(collector):
    info = _metadata(collector)
    for dependency in info["GainBand1"]["dependencies"]:
        for choice in dependency["conditions"][0]["restriction"].get("values", []):
            choice["displayName"] = "native label"
    info["FilterTypeBand1"]["restriction"]["values"].reverse()
    collector._assert_metadata(info)


@pytest.mark.parametrize("fault", ["missing-show", "missing-enable", "recursive-show", "boolean-number", "wrong-kind"])
def test_eq_metadata_rejects_incomplete_or_wrongly_typed_closure(collector, fault):
    info = _metadata(collector)
    if fault == "missing-show":
        info["GainBand1"]["dependencies"].pop(0)
    elif fault == "missing-enable":
        info["GainBand1"]["dependencies"].pop(2)
    elif fault == "recursive-show":
        info["FilterTypeBand1"]["dependencies"].pop(0)
    elif fault == "boolean-number":
        info["GainBand1"]["dependencies"][1]["conditions"][0]["restriction"]["values"][0]["value"] = 1
    else:
        info["FilterTypeBand1"]["type"] = "bool"
    with pytest.raises(AssertionError):
        collector._assert_metadata(info)


def _before(collector):
    target = {"id": collector.TARGET, "name": "Voice_EQ", "type": "Effect", "class_id": collector.CLASS_ID,
        "parent": {"id": collector.PARENT}, "properties": {field: 0.0 for field in collector.FIELDS}}
    target["properties"].update(GainBand1=4.0, FilterTypeBand1=4, NumBands=3, OnOffBand1=True)
    peer = {"id": collector.PEER, "name": "Club_Next_Door", "type": "Effect", "class_id": collector.CLASS_ID,
        "parent": {"id": collector.PARENT}, "properties": {"GainBand1": 0.0}}
    return {"target": target, "peer": peer, "members": [{"id": collector.TARGET}, {"id": collector.PEER}]}


@pytest.mark.parametrize("fault", ["wrong-class", "filter-choice", "disabled", "band-count", "duplicate-member"])
def test_eq_fixture_rejects_unproved_identity_or_controller_prestate(collector, fault):
    before = _before(collector)
    collector._assert_before(before)
    if fault == "wrong-class":
        before["target"]["class_id"] += 1
    elif fault == "filter-choice":
        before["target"]["properties"]["FilterTypeBand1"] = 5
    elif fault == "disabled":
        before["target"]["properties"]["OnOffBand1"] = False
    elif fault == "band-count":
        before["target"]["properties"]["NumBands"] = True
    else:
        before["members"].append(deepcopy(before["members"][0]))
    with pytest.raises(AssertionError):
        collector._assert_before(before)


@pytest.mark.parametrize("fault", ["gain-not-changed", "controller", "other-band", "peer", "membership"])
def test_eq_effect_oracle_rejects_missing_effect_and_extra_changes(collector, fault):
    before = _before(collector)
    after = deepcopy(before)
    after["target"]["properties"]["GainBand1"] = 3.0
    collector._assert_preserved(before, after)
    if fault == "gain-not-changed":
        after["target"]["properties"]["GainBand1"] = 4.0
    elif fault == "controller":
        after["target"]["properties"]["NumBands"] = 4
    elif fault == "other-band":
        after["target"]["properties"]["GainBand3"] = 7.0
    elif fault == "peer":
        after["peer"]["properties"]["GainBand1"] = 1.0
    else:
        after["members"].pop()
    with pytest.raises(AssertionError):
        collector._assert_preserved(before, after)


def test_eq_gain_readback_accepts_numeric_representation_without_relaxing_other_fields(collector):
    before = _before(collector)
    before["target"]["properties"]["GainBand1"] = 4
    collector._assert_before(before)
    after = deepcopy(before)
    after["target"]["properties"]["GainBand1"] = 3
    collector._assert_preserved(before, after)
    after["target"]["properties"]["OnOffBand1"] = 1
    with pytest.raises(AssertionError):
        collector._assert_preserved(before, after)


@pytest.mark.parametrize("fault", ["derived-controller", "wrong-property", "wrong-platform"])
def test_eq_preview_oracle_rejects_hidden_controller_or_wrong_dispatch(collector, fault):
    platform = "{11111111-1111-1111-1111-111111111111}"
    preview = {"preview_summary": {}}
    prepared = {"dispatch": {"uri": "ak.wwise.core.object.setProperty", "options": {},
        "args": {"object": collector.TARGET, "property": "GainBand1", "value": 3.0, "platform": platform}}}
    collector._assert_dispatch(preview, prepared, platform)
    if fault == "derived-controller":
        preview["preview_summary"]["derived_changes"] = [{"field": "FilterTypeBand1", "value": 4}]
    elif fault == "wrong-property":
        prepared["dispatch"]["args"]["property"] = "GainBand3"
    else:
        prepared["dispatch"]["args"]["platform"] = "{22222222-2222-2222-2222-222222222222}"
    with pytest.raises(AssertionError):
        collector._assert_dispatch(preview, prepared, platform)


@pytest.mark.parametrize("fault", ["none", "query-result-order", "metadata-result-order", "peer-write"])
def test_eq_full_collector_uses_public_gateway_with_fake_native_transport(tmp_path, collector, fault):
    from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask
    workflow = importlib.import_module("tests.destructive.test_gateway_workflow_transaction_matrix")
    platform = "{9C6217D5-DD11-4795-87C1-6CE02853C541}"

    class EqTask(ScalarPropertyTask):
        def call(self, uri, args=None, options=None):
            args, options = args or {}, options or {}
            if uri.endswith("object.get") and args.get("waql") != "from type Project take 1":
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                if "waql" in args:
                    expression = args["waql"]
                    match = re.fullmatch(r'from object "([^"\n]+)"( select children)? take [0-9]+', expression)
                    assert match is not None, expression
                    identities = [match[1]]
                    children = bool(match[2])
                else:
                    identities = args["from"]["id"]
                    children = args.get("transform") == [{"select": ["children"]}]
                rows = [self.objects[identity] for identity in identities if identity in self.objects]
                if children:
                    assert len(rows) == 1, args
                    rows = [row for row in self.objects.values() if row.get("parent", {}).get("id") == rows[0]["id"]]
                return {"return": [{field: deepcopy(row[field] if field in row else row[field[1:]])
                    for field in options["return"] if field in row or field.startswith("@") and field[1:] in row}
                    for row in rows]}
            result = super().call(uri, args, options)
            if uri.endswith("getInfo"):
                result["version"].update(year=2025, major=1, minor=7, build=9143)
            elif uri.endswith("getProjectInfo"):
                result.update(currentPlatformId=platform, platforms=[{"id": platform, "name": "Mac"}])
            elif uri.endswith("setProperty") and fault == "peer-write":
                self.objects[collector.PEER]["GainBand1"] = 1.0
            return result

    task = EqTask(tmp_path, "2025.1")
    task.metadata = _metadata(collector)
    for field in collector.FIELDS:
        task.metadata.setdefault(field, {"name": field, "type": "Real32"})
    before = _before(collector)
    task.objects = {}
    parent_path = r"\Effects\Factory Effects\Wwise Parametric EQ"
    for role, fields in (("target", collector.FIELDS), ("peer", collector.PEER_FIELDS)):
        row = before[role]
        task.objects[row["id"]] = {key: deepcopy(value) for key, value in row.items() if key not in {"class_id", "properties"}}
        task.objects[row["id"]].update(classId=collector.CLASS_ID, path=parent_path + "\\" + row["name"], notes="preserve",
            **{field: row["properties"].get(field, 0.0) for field in fields})
    task.objects[collector.PARENT] = {"id": collector.PARENT, "name": "Wwise Parametric EQ", "type": "Folder",
        "classId": 1310736, "path": parent_path, "notes": "keep folder"}
    task.types = [{"name": "Wwise Parametric EQ", "classId": collector.CLASS_ID, "type": "Effect"},
        {"name": "Folder", "classId": 1310736, "type": "WObject"}]
    packets = tmp_path / "packets"
    packets.mkdir()
    runtime = SimpleNamespace(version="2025.1", sandbox=SimpleNamespace(metadata=SimpleNamespace(
        get_info_version=dict(year=2025, major=1, minor=7, build=9143))), state_dir=tmp_path / "collector-state",
        lifecycle=SimpleNamespace(host="127.0.0.1", waapi_url="ws://127.0.0.1:31337/waapi"),
        port=31337, env={**task.env, "WWISE_EVIDENCE_DIR": str(packets)}, candidate="program-only", category_results=[])
    commands = []

    def raw(argv):
        commands.append(list(argv))
        code, payload = workflow.waapi_gateway.execute_gateway(
            ["--timeout", "30", "--state-dir", str(runtime.state_dir), *argv],
            env=runtime.env, client_factory=lambda _: task)
        if (fault == "query-result-order" and argv[0] == "query-object"
                or fault == "metadata-result-order" and argv[:2] == ["metadata", "list"]):
            payload["unexpected_tail"] = "must not hide the final exact result"
        return code, payload

    runtime.raw_gateway = raw
    runtime.gateway = lambda argv, live: workflow._WorkflowSandboxRuntime.gateway(runtime, argv, live=live)
    if fault == "none":
        collector.test_existing_eq_gain_preserves_condition_controllers_and_context(runtime)
    else:
        with pytest.raises(AssertionError):
            collector.test_existing_eq_gain_preserves_condition_controllers_and_context(runtime)
    category, = runtime.category_results
    observation = json.loads(Path(category["observation_path"]).read_text())
    assert commands[0] == ["status"]
    status = observation["reads"][0]["payload"]
    assert "agent_result" not in status and list(status)[-1] == "session_context", status
    writes = [(uri, args) for uri, args, _ in task.calls if uri.endswith(("setProperty", "setReference", "object.set", "object.create"))]
    if fault == "none":
        assert category["status"] == "PASS" and observation["business_effect_verified"] is True
        assert len(observation["transactions"]) == 1 and len(writes) == 1
        assert writes[0] == ("ak.wwise.core.object.setProperty", {"object": collector.TARGET,
            "property": "GainBand1", "value": 3.0, "platform": platform})
        assert [argv[0] for argv in commands].count("execute") == 1
        assert [argv[0] for argv in commands].count("verify") == 1
        assert [argv[0] for argv in commands].count("draft-start") == 1
        assert len(observation["reads"]) == 19
        target_queries = [argv for argv in commands if argv[0] == "query-object" and argv[2] == collector.TARGET]
        assert len(target_queries) == 4 and [argv.count("--include-field") for argv in target_queries] == [8, 1, 8, 1]
        for phase in ("before", "after"):
            first, = [row for row in observation["reads"] if row["label"] == phase + "-target-fields-1"]
            second, = [row for row in observation["reads"] if row["label"] == phase + "-target-fields-2"]
            assert set(first["payload"]["agent_result"][0]["properties"]) == set(collector.FIELDS[:8])
            assert set(second["payload"]["agent_result"][0]["properties"]) == set(collector.FIELDS[8:])
            assert set(observation[phase]["target"]["properties"]) == set(collector.FIELDS)
        assert set(observation["metadata_before"]) == set(collector.METADATA_FIELDS)
        assert observation["metadata_after"] == observation["metadata_before"]
    else:
        assert category["status"] == "FAIL" and observation["business_effect_verified"] is False
        assert len(writes) == (1 if fault == "peer-write" else 0)

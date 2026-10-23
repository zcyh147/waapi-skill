"""Meter object projections through the public Gateway and retained observations."""
from __future__ import annotations

from copy import deepcopy

import pytest

from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient

METERS = "ak.wwise.core.profiler.getMeters"
BUS = _RuntimeControlDraftClient.meter_id
BUS_CLASS = 553  # Existing reflected Bus class.


class MeterClient(_RuntimeControlDraftClient):
    def __init__(self, tmp_path, version="2025.1"):
        super().__init__(tmp_path, version=version)
        self.calls = []
        self.rows = [{"object": {"id": BUS, "name": "Master Audio Bus", "type": "Bus",
            "path": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus", "classId": BUS_CLASS,
            "notes": "Bus configuration", "@Volume": -6.0},
            "source": "Bus", "configurationName": name, "configurationMask": 3,
            "configurationType": "Standard", "channels": [{"name": "L", "value": value}]}
            for name, value in [("Stereo", -12.0), ("Mono", -20.0)]]
        self.metadata = {BUS_CLASS: {"Volume": {"name": "Volume", "type": "Real32",
            "display": {"name": "Bus Volume"}, "supports": {}, "restriction": {}, "dependencies": []}}}

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, deepcopy(args), deepcopy(options)))
        if uri == METERS:
            fields = options.get("return", ["id", "name"])
            return {"meters": [{**deepcopy(row), "object": {key: deepcopy(value) for key, value in row["object"].items()
                if key in fields}} for row in self.rows]}
        if uri.endswith("getPropertyAndReferenceNames"):
            return {"return": list(self.metadata[args.get("classId", args.get("object"))])}
        if uri.endswith("getPropertyInfo"):
            return deepcopy(self.metadata[args.get("classId", args.get("object"))][args["property"]])
        return super().call(uri, args, options)


def task(tmp_path, version="2025.1"):
    client = MeterClient(tmp_path, version)
    env = _env(tmp_path, version=version)
    def run(*argv, offline=False):
        return gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv], env=env,
            client_factory=(lambda _url: pytest.fail("offline/page read connected")) if offline else (lambda _url: client))
    return client, run


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_meter_property_projection_reaches_retained_pages_without_new_native_reads(tmp_path, version):
    client, run = task(tmp_path, version)
    code, schema = run("request-schema", METERS, offline=True)
    assert code == 0, schema
    assert "meter_object_fields" in schema["business_adapter"]["declaration"]["optional_fields"]
    assert "notes" in schema["business_adapter"]["declaration"]["meter_object_projection"]["related_outputs"]["outputs"]
    code, result = run("core-call", METERS, "--profiler-position", "123", "--max-results", "1",
        "--meter-object-include", "notes", "--meter-object-include-field", "Bus Volume",
        "--meter-platform", "Mac", "--meter-language", "SFX")
    assert code == 0, result
    assert result["status"] == "partial"
    native = [entry for entry in client.calls if entry[0] == METERS]
    assert native[-1][1] == {"time": 123}
    assert native[-1][2]["platform"] == "Mac" and native[-1][2]["language"] == "SFX"
    assert {"notes", "@Volume"} <= set(native[-1][2]["return"])
    names = [args for uri, args, _ in client.calls if uri.endswith("getPropertyAndReferenceNames")]
    assert names == [{"classId": BUS_CLASS}]
    pages = [result["agent_result"]]
    while pages[-1]["complete"] is False:
        code, result = run(*pages[-1]["next_command"]["gateway_argv"], offline=True)
        assert code == 0, result
        pages.append(result["agent_result"])
    rows = [row for page in pages for row in page["meters"]]
    assert [row["configurationName"] for row in rows] == ["Mono", "Stereo"]
    assert [row["channels"] for row in rows] == [[{"name": "L", "value": -20.0}], [{"name": "L", "value": -12.0}]]
    assert all(row["object"]["notes"] == "Bus configuration" and row["object"]["properties"] == {"Volume": -6.0} for row in rows)
    assert len([entry for entry in client.calls if entry[0] == METERS]) == len(native)
    assert list(result)[-1] == "agent_result"


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
@pytest.mark.parametrize("empty", [False, True], ids=["native-defaults", "explicit-empty"])
def test_meter_native_default_and_empty_object_selection_are_distinct(tmp_path, version, empty):
    client, run = task(tmp_path, version)
    code, result = run("core-call", METERS, "--profiler-position", "123",
        *(["--meter-object-empty-selection"] if empty else []))
    assert code == 0, result
    calls = [entry for entry in client.calls if entry[0] == METERS]
    assert len(calls) == 1
    assert calls[0][2] == ({"return": []} if empty else {})
    assert [row["object"] for row in result["agent_result"]["meters"]] == ([{}, {}] if empty else [
        {"id": BUS, "name": "Master Audio Bus"}, {"id": BUS, "name": "Master Audio Bus"}])


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_meter_property_and_reference_modes_preserve_local_resolved_and_override_values(tmp_path, version):
    client, run = task(tmp_path, version)
    reference = {"id": "{33333333-3333-3333-3333-333333333333}", "name": "Mix Bus"}
    client.metadata[BUS_CLASS]["OutputBus"] = {"name": "OutputBus", "type": "ObjectReference",
        "display": {"name": "Output Bus"}, "restriction": {"type": "reference", "restrictions": []}}
    for row in client.rows:
        row["object"].update({"@@Volume": -3.0, "OutputBus": reference, "@OutputBus": None})
    code, result = run("core-call", METERS, "--profiler-position", "123",
        "--meter-object-include-field", "Bus Volume", "--meter-object-include-field", "Output Bus",
        "--meter-object-include-override-source-value", "Bus Volume",
        "--meter-object-include-local-reference", "Output Bus")
    assert code == 0, result
    for row in result["agent_result"]["meters"]:
        assert row["object"]["properties"] == {"Volume": -6.0}
        assert row["object"]["references"] == {"OutputBus": reference}
        assert row["object"]["override_source_values"] == {"Volume": -3.0}
        assert row["object"]["local_references"] == {"OutputBus": None}
    options = [options for uri, _, options in client.calls if uri == METERS][-1]
    assert {"@Volume", "@@Volume", "OutputBus", "@OutputBus"} <= set(options["return"])


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_meter_related_object_outputs_bind_actual_parent_scope(tmp_path, version):
    client, run = task(tmp_path, version)
    parent = {"id": "{33333333-3333-3333-3333-333333333333}", "name": "Parent Mix"}
    client.metadata[BUS_CLASS]["OutputBus"] = {"name":"OutputBus","type":"ObjectReference",
        "display":{"name":"Output Bus"},"restriction":{"type":"reference","restrictions":[]}}
    for row in client.rows:
        row["object"].update({"parent":parent, "parent.classId":BUS_CLASS,
            "parent.notes":"Parent configuration", "parent.@Volume":-9.0,
            "parent.@@Volume":-3.0,"parent.OutputBus":parent,"parent.@OutputBus":None})
    code, result = run("core-call", METERS, "--profiler-position", "123",
        "--meter-object-include-related", "parent", "notes",
        "--meter-object-include-related-field", "parent", "Bus Volume",
        "--meter-object-include-related-field", "parent", "Output Bus",
        "--meter-object-include-related-override-source-value", "parent", "Bus Volume",
        "--meter-object-include-related-local-reference", "parent", "Output Bus")
    assert code == 0, result
    assert all(row["object"]["related"]["parent"] == {"object":parent,"notes":"Parent configuration",
        "properties":{"Volume":-9.0},"references":{"OutputBus":parent},
        "override_source_values":{"Volume":-3.0},"local_references":{"OutputBus":None}}
        for row in result["agent_result"]["meters"])
    meter_calls = [entry for entry in client.calls if entry[0] == METERS]
    assert "parent.@Volume" in meter_calls[-1][2]["return"]
    assert not any(uri == "ak.wwise.core.object.get" for uri,_,_ in client.calls)


def test_meter_heterogeneous_scopes_keep_inapplicable_field_requests_and_repeated_rows(tmp_path):
    client, run = task(tmp_path)
    device_id = "{44444444-4444-4444-4444-444444444444}"
    device_class = 32768  # A fake native class scope; no installed plug-in claim.
    client.rows[1]["object"].update(id=device_id, name="Device", type="AudioDevice", classId=device_class)
    client.rows[1]["object"].pop("@Volume")
    client.metadata[device_class] = {}
    client.metadata[device_id] = {}
    client.rows.append(deepcopy(client.rows[1]))
    client.rows[-1]["source"] = "DevicePassthrough"
    code, result = run("core-call", METERS, "--profiler-position", "123", "--meter-object-include-field", "Bus Volume")
    assert code == 0 and result["status"] == "ok", result
    rows = result["agent_result"]["meters"]
    assert len(rows) == 3
    assert rows[0]["object"]["properties"] == {"Volume": -6.0}
    for row in rows[1:]:
        assert row["object"]["id"] == device_id
        assert "properties" not in row["object"]
        assert row["object"]["unavailable_field_requests"][0]["meaning"] == "Bus Volume"
    assert [args for uri,args,_ in client.calls if uri.endswith("getPropertyAndReferenceNames")] == [
        {"classId":BUS_CLASS},{"classId":device_class},{"object":device_id}]


@pytest.mark.parametrize("drift", ["object", "class", "channel"])
def test_meter_changed_preparation_scope_cannot_be_reported_as_complete(tmp_path, drift):
    client, run = task(tmp_path)
    original = client.call
    count = 0
    def call(uri, args=None, options=None):
        nonlocal count
        if uri == METERS:
            count += 1
            if count == 2:
                if drift == "object":
                    client.rows[0]["object"]["id"] = "{33333333-3333-3333-3333-333333333333}"
                elif drift == "class":
                    client.rows[0]["object"]["classId"] = 32768
                else:
                    client.rows[0]["channels"][0]["value"] = -99.0
        return original(uri,args,options)
    client.call = call
    code, result = run("core-call", METERS, "--profiler-position", "123", "--meter-object-include-field", "Bus Volume")
    assert code == 2 and result["error_code"] == "METER_OBJECT_SCOPE_CHANGED", result
    assert result.get("agent_result") is None


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1"])
def test_meter_options_keep_the_older_version_boundary_before_connection(tmp_path, version):
    _, run = task(tmp_path,version)
    code,result = run("core-call",METERS,"--profiler-position","123","--meter-object-include","notes",offline=True)
    assert code == 2 and "unavailable" in result["message"], result


@pytest.mark.parametrize("arguments", [
    ["--meter-object-include","@Volume"],
    ["--meter-object-include-field","@@Volume"],
    ["--meter-object-include","notes","--meter-object-include","notes"],
    ["--meter-object-empty-selection","--meter-object-include","notes"],
    ["--meter-platform"," Mac "],
    ["--meter-language","SFX\nOther"],
    ["--meter-object-include-related","parent","native.accessor"],
])
def test_invalid_meter_output_declarations_fail_before_connection(tmp_path,arguments):
    _,run = task(tmp_path)
    code,result = run("core-call",METERS,"--profiler-position","123",*arguments,offline=True)
    assert code == 2, result


def test_meter_wrong_field_kind_returns_a_boundary_instead_of_empty_property(tmp_path):
    client,run = task(tmp_path)
    client.metadata[BUS_CLASS]["OutputBus"] = {"name":"OutputBus","type":"ObjectReference", "restriction":{"type":"reference","restrictions":[]}}
    code,result = run("core-call",METERS,"--profiler-position","123","--meter-object-include-override-source-value","OutputBus")
    assert code == 2 and result["error_code"] == "METER_OBJECT_FIELD_KIND", result
    assert len([entry for entry in client.calls if entry[0] == METERS]) == 1


def test_ambiguous_meter_meaning_keeps_actual_scope_and_does_not_dispatch_data_projection(tmp_path):
    client,run = task(tmp_path)
    client.metadata[BUS_CLASS] = {name:{"name":name,"type":"Real32","display":{"name":"Mix Gain"}}
        for name in ("FirstGain","SecondGain")}
    code,result = run("core-call",METERS,"--profiler-position","123","--meter-object-include-field","Mix Gain")
    assert code == 0 and result["status"] == "needs_clarification", result
    assert result["agent_result"]["unresolved"][0]["candidate_names"] == ["FirstGain","SecondGain"]
    assert result["agent_result"]["unresolved"][0]["scope"] == {"classId":BUS_CLASS}
    assert len([entry for entry in client.calls if entry[0] == METERS]) == 1


def test_meter_preparation_has_an_independent_cumulative_observation_budget(tmp_path, monkeypatch):
    import wwise_waapi.profiler_meter_objects as meter_objects
    monkeypatch.setattr(meter_objects, "MAX_METER_OBSERVATION_BYTES", 1, raising=False)
    client, run = task(tmp_path)
    code, result = run("core-call", METERS, "--profiler-position", "123",
        "--meter-object-include-field", "Bus Volume")
    assert code == 2 and result["error_code"] == "METER_OBJECT_OBSERVATION_LIMIT", result
    assert len([entry for entry in client.calls if entry[0] == METERS]) == 1


def test_meter_projection_provenance_is_retained_with_each_page(tmp_path):
    client, run = task(tmp_path)
    code, result = run("core-call", METERS, "--profiler-position", "123", "--max-results", "1",
        "--meter-object-include-field", "Bus Volume")
    assert code == 0, result
    proof = result["agent_result"]["meter_object_projection"]
    assert proof["root_api"] == METERS and proof["time"] == 123
    assert proof["atomic_snapshot"] is False and proof["mutation_authority"] is False
    assert proof["object_value_semantics"] == "Authoring configuration; not captured runtime mix values"
    assert proof["meter_reads"]["count"] == 2
    assert proof["metadata_reads"]["count"] == 2
    assert len(proof["meter_reads"]["associations_sha256"]) == 64
    code, page = run(*result["agent_result"]["next_command"]["gateway_argv"], offline=True)
    assert code == 0 and page["agent_result"]["meter_object_projection"] == proof, page


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_meter_collection_and_closed_sequence_outputs_retain_distinct_native_provenance(tmp_path, version):
    from tests.unit.test_query_related_lists import ListTask
    import re
    client, run = task(tmp_path, version)
    child_id = "{33333333-3333-3333-3333-333333333333}"
    child = {"id":child_id,"name":"Child Bus","type":"Bus","path":r"\Busses\Child",
        "classId":BUS_CLASS,"notes":"Child configuration","@Volume":-8.0}
    for row in client.rows:
        row["object"]["children"] = [{"id":child_id,"name":"Child Bus"}] * 2
    client.objects = {BUS:client.rows[0]["object"],child_id:child}
    client.comma_fields = ListTask.comma_fields
    client.projection = lambda row, fields: ListTask.projection(client,row,fields)
    original = client.call
    def call(uri, args=None, options=None):
        if uri == METERS:
            client.calls.append((uri,deepcopy(args),deepcopy(options)))
            return {"meters":[{**deepcopy(row),"object":client.projection(row["object"],options["return"])}
                for row in client.rows]}
        if uri == "ak.wwise.core.object.get" and "select children" in args.get("waql", ""):
            client.calls.append((uri,deepcopy(args),deepcopy(options)))
            assert re.search(r"select children(?: take 1)+$", args["waql"]), args
            return {"return":[client.projection(child,options["return"])]}
        if uri == "ak.wwise.core.object.get":
            ids = args.get("from", {}).get("id") or re.findall(r"\{[0-9A-Fa-f-]{36}\}", args.get("waql", ""))
            if ids:
                client.calls.append((uri,deepcopy(args),deepcopy(options)))
                return {"return":[client.projection(client.objects[identity], options["return"]) for identity in ids]}
        return original(uri,args,options)
    client.call = call
    code, result = run("core-call",METERS,"--profiler-position","123",
        "--meter-object-include-related","children","notes",
        "--meter-object-include-related-field","children","Bus Volume",
        "--meter-object-include-related","children","first","notes",
        "--meter-platform","Mac","--meter-language","SFX")
    assert code == 0, result
    for row in result["agent_result"]["meters"]:
        related = row["object"]["related"]
        assert len(related["children"]["items"]) == 2
        assert all(item["notes"] == "Child configuration" and item["properties"] == {"Volume":-8.0}
            for item in related["children"]["items"])
        sequence = related["projections"][0]
        assert sequence["derivation"] == "gateway-business-sequence"
        assert sequence["items"][0]["object"]["id"] == child_id
    proof = result["agent_result"]["meter_object_projection"]["related"]
    assert proof["strategy"] == "native-composed-members"
    assert proof["helper_apis"] == ["ak.wwise.core.object.get"]
    assert "Gateway business derivation" in proof["sequence_semantics"]
    assert any("children.{id,name,type,path,classId,notes,@Volume} as related0" in options["return"]
        for uri,_,options in client.calls if uri == METERS)
    assert all(options.get("platform") == "Mac" and options.get("language") == "SFX"
        for uri,_,options in client.calls if uri == "ak.wwise.core.object.get")


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_meter_named_outputs_disclose_meaningful_versioned_object_configuration(tmp_path, version):
    client, run = task(tmp_path, version)
    code, schema = run("request-schema",METERS,offline=True)
    assert code == 0, schema
    choices = schema["business_adapter"]["declaration"]["meter_object_projection"]["fields"]["meter_object_outputs"]["choices"]
    assert {"notes","volume-db","class-id","short-id","parent","owner","work-unit","state-properties"} <= set(choices)
    assert ("supports-states" in choices) == (version == "2025.1")
    assert "converted-codec" not in choices  # Source-media metadata is not a Bus/device promise.
    code, result = run("core-call",METERS,"--profiler-position","123","--meter-object-include","converted-codec",offline=True)
    assert code == 2, result
    for row in client.rows:
        row["object"].update({"shortId":42,"supportsStates":True})
    code,result = run("core-call",METERS,"--profiler-position","123","--meter-object-include","short-id",
        *(["--meter-object-include","supports-states"] if version == "2025.1" else []))
    assert code == 0, result
    assert all(row["object"]["short_id"] == 42 for row in result["agent_result"]["meters"])
    if version == "2025.1":
        assert all(row["object"]["supports_states"] is True for row in result["agent_result"]["meters"])


def test_meter_metadata_and_clarification_have_separate_bounded_failures(tmp_path, monkeypatch):
    import wwise_waapi.object_query_related_metadata as metadata
    client, run = task(tmp_path)
    monkeypatch.setattr(metadata, "MAX_METADATA_DISCOVERY_RESULT_BYTES", 1)
    code, result = run("core-call",METERS,"--profiler-position","123","--meter-object-include-field","Bus Volume")
    assert code == 2 and result["error_code"] == "LIVE_METADATA_READ_FAILED", result
    assert "aggregate byte budget" in result["details"]["cause"]
    assert len([entry for entry in client.calls if entry[0] == METERS]) == 1


def test_meter_oversized_ambiguity_is_a_bounded_failure_not_a_truncated_answer(tmp_path):
    client, run = task(tmp_path)
    client.rows = [deepcopy(client.rows[0]) for _ in range(200)]
    client.metadata[BUS_CLASS] = {name:{"name":name,"type":"Real32","display":{"name":"Mix Gain"}}
        for name in ("FirstGain","SecondGain")}
    code, result = run("core-call",METERS,"--profiler-position","123","--meter-object-include-field","Mix Gain")
    assert code == 2 and result["error_code"] == "METER_OBJECT_CLARIFICATION_LIMIT", result
    assert result.get("agent_result") is None
    assert 0 < result["details"]["unresolved_count_at_least"] < 200


@pytest.mark.parametrize("platform,language", [("Mac",None), (None,"{55555555-5555-5555-5555-555555555555}"),
    ("{66666666-6666-6666-6666-666666666666}","SFX")])
def test_meter_named_cursor_freezes_once_and_scope_literals_reach_every_meter_read(tmp_path, platform, language):
    client,run = task(tmp_path)
    original = client.call
    cursor_calls = []
    def call(uri,args=None,options=None):
        if uri == "ak.wwise.core.profiler.getCursorTime":
            cursor_calls.append(deepcopy(args))
            return {"return":123 if len(cursor_calls) == 1 else 456}
        return original(uri,args,options)
    client.call = call
    code,result = run("core-call",METERS,"--profiler-position","capture-latest",
        "--meter-object-include-field","Bus Volume",
        *(["--meter-platform",platform] if platform is not None else []),
        *(["--meter-language",language] if language is not None else []))
    assert code == 0, result
    assert cursor_calls == [{"cursor":"capture"}]
    for uri,args,options in client.calls:
        if uri == METERS:
            assert args == {"time":123}
            assert {key:value for key,value in options.items() if key != "return"} == {
                **({"platform":platform} if platform is not None else {}),
                **({"language":language} if language is not None else {})}
    assert result["agent_result"]["meter_object_projection"]["time"] == 123


def test_large_meter_nested_configuration_and_channels_reassemble_without_new_native_reads(tmp_path):
    import json
    client,run = task(tmp_path)
    client.rows = client.rows[:1]
    notes = '界\\"' * 2000
    client.rows[0]["object"]["notes"] = notes
    client.rows[0]["channels"] = [{"name":"L","value":-12.0},{"name":"R","value":-24.0}]
    code,result = run("core-call",METERS,"--profiler-position","123","--meter-object-include","notes")
    assert code == 0, result
    reads = len(client.calls)
    fragments = []
    while True:
        payload = result["agent_result"]
        assert list(result)[-1] == "agent_result"
        assert len(json.dumps(result,ensure_ascii=False).encode()) <= gateway.MAX_GATEWAY_RESULT_JSON_BYTES
        fragments.append(payload["row_fragment"]["value"])
        if payload["complete"]:
            break
        code,result = run(*payload["next_command"]["gateway_argv"],offline=True)
        assert code == 0, result
    row = json.loads("".join(fragments))
    assert row["object"]["notes"] == notes
    assert row["channels"] == [{"name":"L","value":-12.0},{"name":"R","value":-24.0}]
    assert len(client.calls) == reads


def test_meter_field_can_bind_instance_metadata_when_class_metadata_has_no_match(tmp_path):
    client,run = task(tmp_path)
    client.metadata[BUS] = client.metadata[BUS_CLASS]
    client.metadata[BUS_CLASS] = {}
    code,result = run("core-call",METERS,"--profiler-position","123","--meter-object-include-field","Bus Volume")
    assert code == 0, result
    assert all(row["object"]["properties"] == {"Volume":-6.0} for row in result["agent_result"]["meters"])
    assert [args for uri,args,_ in client.calls if uri.endswith("getPropertyAndReferenceNames")] == [
        {"classId":BUS_CLASS},{"object":BUS}]


def test_meter_frame_comparison_uses_canonical_guid_identity_not_native_letter_case(tmp_path):
    client,run = task(tmp_path)
    for row in client.rows:
        row["object"]["id"] = "{ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB}"
    original = client.call
    count = 0
    def call(uri,args=None,options=None):
        nonlocal count
        if uri == METERS:
            count += 1
            if count == 2:
                for row in client.rows:
                    row["object"]["id"] = row["object"]["id"].lower()
        return original(uri,args,options)
    client.call = call
    code,result = run("core-call",METERS,"--profiler-position","123","--meter-object-include-field","Bus Volume")
    assert code == 0, result
    assert all(row["object"]["properties"] == {"Volume":-6.0} for row in result["agent_result"]["meters"])


@pytest.mark.parametrize("change_read", [3, 5], ids=["related-preparation", "final-projection"])
@pytest.mark.parametrize("change", ["case", "identity"])
def test_related_meter_root_identity_comparison_preserves_native_text_and_real_drift(tmp_path, change_read, change):
    client, run = task(tmp_path)
    root_id = "{ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB}"
    name = "Keep MixedCase {aBcDeFaB-cDeF-aBcD-eFaB-cDeFaBcDeFaB}"
    notes = "Parent configuration {aBcDeFaB-cDeF-aBcD-eFaB-cDeFaBcDeFaB}"
    parent = {"id":"{33333333-3333-3333-3333-333333333333}","name":"Parent Mix"}
    for row in client.rows:
        row["object"].update({"id":root_id,"name":name,"parent":parent,
            "parent.classId":BUS_CLASS,"parent.notes":notes})
    original = client.call
    count = 0
    def call(uri, args=None, options=None):
        nonlocal count
        if uri == METERS:
            count += 1
            if count == change_read:
                for row in client.rows:
                    row["object"]["id"] = (root_id.lower() if change == "case" else
                        "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}")
        return original(uri,args,options)
    client.call = call
    code, result = run("core-call",METERS,"--profiler-position","123",
        "--meter-object-include-related","parent","notes")
    assert count >= change_read
    if change == "identity":
        assert code == 2 and result["error_code"] == "METER_OBJECT_SCOPE_CHANGED", result
        assert result.get("agent_result") is None
    else:
        assert code == 0, result
        for row in result["agent_result"]["meters"]:
            assert row["object"]["id"] == root_id.lower()
            assert row["object"]["name"] == name
            assert row["object"]["related"]["parent"] == {"object":parent,"notes":notes}
        assert all(row["object"]["name"] == name and row["object"]["parent.notes"] == notes
            for row in client.rows)

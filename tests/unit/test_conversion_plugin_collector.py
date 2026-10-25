"""Real public collector and existing category finalizer, with only Wwise faked."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.test_conversion_plugin_gateway import ConversionClient, CODEC, OTHER_CODEC, OLD_CODEC, WINDOWS, MAC
from tests.unit.test_gateway_session_context import configured_env, waapi_gateway as gateway
from tests.unit.test_workflow_source_guard import workflow, _fixture_run
from tests.destructive.support.conversion_plugin_acceptance import (
    collect_conversion_plugin_acceptance, collect_conversion_platform_metadata_probe, PCM, PCM_PATH,
)
from tests.destructive.support import exact_real_evidence, category_evidence


def runtime_fixture(tmp_path, *, fault=None):
    client = ConversionClient("2025.1", PCM)
    client.target.update(name="PCM", path=PCM_PATH)
    project = tmp_path / "owned" / "SampleProject.wproj"
    project.parent.mkdir(); project.write_text("<Project />")
    source = tmp_path / "source" / "SampleProject.wproj"
    source.parent.mkdir(); source.write_text("<Project />")
    env = configured_env(tmp_path, version="2025.1", port=31337)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    original = client.call

    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        result = original(uri, args, options)
        if uri == "ak.wwise.core.getInfo":
            result.update(isCommandLine=True, sessionId="{77777777-7777-7777-7777-777777777777}",
                apiVersion=1, branch="release", copyright="Audiokinetic", configuration="release",
                platform="macosx", processId=1234, processPath="/fixture/WwiseConsole",
                directories={key: "/fixture/" + key for key in ("install", "authoring", "bin", "help", "user")})
            result["version"].update(minor=7, build=9143, displayName="2025.1.7.9143", nickname="Fixture", schema=133)
        if uri == "ak.wwise.core.getProjectInfo":
            result.pop("type", None)
            language = "{88888888-8888-8888-8888-888888888888}"
            result.update(path=str(project), currentPlatformId=WINDOWS, displayTitle="SampleProject", isDirty=False,
                currentLanguageId=language, referenceLanguageId=language,
                languages=[{"id": language, "name": "English(US)", "shortId": 1}],
                directories={key: str(project.parent / key) for key in ("root", "cache", "originals", "soundBankOutputRoot", "commands", "properties")},
                defaultConversion={"id": PCM, "name": "PCM"})
            for platform in result["platforms"]:
                platform.update(baseName=platform["name"], baseDisplayName=platform["name"], soundBankPath="/fixture/banks", copiedMediaPath="/fixture/media")
            if fault == "unresolved-default-target":
                result["defaultConversion"] = {"id": OTHER_CODEC, "name": "Unknown Default"}
        if uri == "ak.wwise.core.object.get" and "from type Project" in args.get("waql", ""):
            result["return"][0]["path"] = str(project)
        if fault == "prewrite-shape" and uri == "ak.wwise.core.object.get":
            for row in result["return"]:
                if row.get("id") in {CODEC, OTHER_CODEC, OLD_CODEC} and "type" in row:
                    row["type"] = "UnreviewedAnonymousCodec"
        return result
    client.call = call
    runtime = SimpleNamespace(version="2025.1", candidate="a" * 40, category_results=[],
        state_dir=tmp_path / "state", env=env, port=31337,
        sandbox=SimpleNamespace(source_project=source, sandbox_project=project),
        lifecycle=SimpleNamespace(host="127.0.0.1", port=31337, waapi_url="ws://127.0.0.1:31337/waapi"))
    commands = []

    def raw(argv):
        commands.append(list(argv))
        code, payload = gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
        if fault == "post-verify-field" and argv[0] == "verify" and payload.get("verified") is True and client.quality == 6:
            client.quality = 5
        return code, payload
    runtime.raw_gateway = raw
    return runtime, commands, client


@pytest.mark.parametrize("fault", [None, "post-verify-field", "prewrite-shape", "unresolved-default-target"])
def test_conversion_collector_reaches_persisted_existing_finalizer(tmp_path, workflow, monkeypatch, fault):
    owned = tmp_path / "collector"; owned.mkdir()
    runtime, commands, client = runtime_fixture(owned, fault=fault)
    failure = None
    try:
        category = collect_conversion_plugin_acceptance(runtime)
    except AssertionError as exc:
        failure = exc
        category = runtime.category_results[-1]
    receipt = json.loads(Path(category["observation_path"]).read_text())
    expected_pass = fault in {None, "unresolved-default-target"}
    assert category["status"] == ("PASS" if expected_pass else "FAIL"), json.dumps(receipt.get("failure"), indent=2)
    assert receipt["business_effect_verified"] is expected_pass
    assert (failure is None) is expected_pass
    if fault == "prewrite-shape":
        assert receipt["stage"] == "prewrite-native-shape" and receipt["failure"]
        assert not any(command[0] == "execute" for command in commands)
    else:
        assert len([command for command in commands if command[0] == "execute"]) == 2
        assert len(receipt["transaction_ids"]) == 2
        assert receipt["phases"][-1]["verify"]["state"] == "verified"
        assert receipt["default_conversion_observation"]["status"] == (
            "unresolved" if fault == "unresolved-default-target" else "observed")
        if fault == "post-verify-field":
            assert receipt["phases"][-1]["effect_verified"] is False
            assert receipt["observations"]["after_configuration"][WINDOWS]["fields"]["QualityFactor"] == 5
        else:
            assert receipt["observations"]["after_configuration"][WINDOWS]["fields"]["QualityFactor"] == 6
            assert receipt["observations"]["after_configuration"][MAC] == receipt["observations"]["before"][MAC]

    lifecycle = tmp_path / "lifecycle"; lifecycle.mkdir()
    fixture, events, _ = _fixture_run(lifecycle, workflow, monkeypatch)
    target = tmp_path / "category-final.jsonl"
    monkeypatch.setenv("WWISE_CATEGORY_EVIDENCE_PATH", str(target))
    monkeypatch.setattr(exact_real_evidence, "append_category_evidence", category_evidence.append_category_evidence)
    # The reusable external-lifecycle fake owns a different task folder; read
    # the collector's real durable transactions with the production reader.
    monkeypatch.setattr(exact_real_evidence, "exact_transaction_outcomes",
        lambda _state: category_evidence.exact_transaction_outcomes(runtime.state_dir))
    fixture_runtime = next(fixture)
    fixture_runtime.category_results.extend(runtime.category_results)
    if failure is None:
        with pytest.raises(StopIteration):
            next(fixture)
    else:
        with pytest.raises(AssertionError):
            fixture.throw(failure)
    records = [json.loads(line) for line in target.read_text().splitlines()]
    final = records[-1]
    assert final["invocation"]["phase"] == "final"
    assert final["invocation"]["outcome"] == ("PASS" if expected_pass else "FAIL")
    assert [row for row in final["categories"] if row["category"] == "conversion-plugin-placement"] == runtime.category_results
    assert len(final["transactions"]) == (0 if fault == "prewrite-shape" else 2)
    assert final["residual_state"]["sandbox"] == ("deleted" if expected_pass else "quarantined")
    assert events.index("shutdown") < events.index("release")


@pytest.mark.parametrize("mode", ["scalar", "reference", "missing-detail"])
def test_read_only_codec_platform_probe_preserves_actual_candidates_and_final_report(tmp_path, workflow, monkeypatch, mode):
    missing_detail = mode == "missing-detail"
    owned = tmp_path / "collector"; owned.mkdir()
    runtime, commands, client = runtime_fixture(owned)
    retained = json.loads((Path(__file__).parents[1] / "fixtures/metadata/conversion-plugin-native-2025.json").read_text())["rows"]
    native_rows = [{**{key: row[key] for key in ("id", "name", "type", "path", "owner")},
        "classId": row["class_id"], "pluginName": row["plugin_name"]} for row in retained]
    original = client.call

    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == "ak.wwise.core.object.get" and (
            "conversionplugin" in args.get("waql", "").casefold()
            or any(row["id"] in json.dumps(args) for row in native_rows)
        ):
            selected = list(reversed(native_rows)) if "conversionplugin" in args.get("waql", "").casefold() else [
                row for row in native_rows if row["id"] in json.dumps(args)]
            return {"return": [{**{field: row[field] for field in options["return"] if field in row},
                **({"@Platform": {"id": WINDOWS if row["id"] == native_rows[0]["id"] else MAC}}
                    if "@Platform" in options["return"] else {})} for row in selected]}
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            assert args["object"] in {row["id"] for row in native_rows}
            return {"return": ["Platform" if mode == "reference" else "MaxBitDepth"]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            assert args["object"] in {row["id"] for row in native_rows}
            if mode == "reference":
                assert args["property"] == "Platform"
                return {"name": "Platform", "type": "Reference", "default": None,
                    "restriction": {"type": "reference", "restrictions": [{"type": ["Platform"]}]}}
            assert args["property"] == "MaxBitDepth"
            if missing_detail:
                return {"name": "MaxBitDepth", "type": 42}
            return {"name": "MaxBitDepth", "type": "int32", "default": 16,
                "restriction": {"type": "enum", "values": [{"value": 16}, {"value": 24}]}}
        return original(uri, args, options)
    client.call = call
    failure = None
    try:
        category = collect_conversion_platform_metadata_probe(runtime)
    except AssertionError as exc:
        failure = exc; category = runtime.category_results[-1]
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert receipt["collection_complete"] is (not missing_detail)
    assert receipt["business_effect_verified"] is False and receipt["mutation_allowed"] is False
    assert all(command[0] in {"status", "query-object", "metadata"} for command in commands)
    assert len(commands) <= 64 and receipt["candidates"][0]["object"]["id"] == retained[1]["id"]
    if missing_detail:
        assert category["status"] == "FAIL" and failure is not None and receipt["failure"]
        assert receipt["candidates"][0]["field_lists"][0]["fields"][0]["name"] == "MaxBitDepth"
    else:
        assert category["status"] == "blocked" and failure is None
        assert len(commands) == (10 if mode == "reference" else 8)
        assert {row["object"]["id"] for row in receipt["candidates"]} == {row["id"] for row in retained}
        assert all(row["fields"][0]["pages"][0]["metadata"]["type"] == (
            "Reference" if mode == "reference" else "int32") for row in receipt["candidates"])
        if mode == "reference":
            assert all(row["reference_values"][0]["result"]["objects"][0]["local_references"]["Platform"]["id"] in {WINDOWS, MAC}
                for row in receipt["candidates"])

    lifecycle = tmp_path / "lifecycle"; lifecycle.mkdir()
    fixture, events, _ = _fixture_run(lifecycle, workflow, monkeypatch)
    target = tmp_path / "probe-final.jsonl"
    monkeypatch.setenv("WWISE_CATEGORY_EVIDENCE_PATH", str(target))
    monkeypatch.setattr(exact_real_evidence, "append_category_evidence", category_evidence.append_category_evidence)
    monkeypatch.setattr(exact_real_evidence, "exact_transaction_outcomes",
        lambda _state: category_evidence.exact_transaction_outcomes(runtime.state_dir))
    fixture_runtime = next(fixture); fixture_runtime.category_results.extend(runtime.category_results)
    if failure is None:
        with pytest.raises(StopIteration): next(fixture)
    else:
        with pytest.raises(AssertionError): fixture.throw(failure)
    final = json.loads(target.read_text().splitlines()[-1])
    assert final["invocation"]["phase"] == "final" and final["transactions"] == []
    assert final["invocation"]["outcome"] == ("FAIL" if missing_detail else "PASS")
    assert next(row for row in final["categories"] if row["category"] == category["category"])["status"] == ("FAIL" if missing_detail else "blocked")
    assert final["residual_state"]["sandbox"] == ("quarantined" if missing_detail else "deleted")
    assert events.index("shutdown") < events.index("release")

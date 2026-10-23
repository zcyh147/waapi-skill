"""One existing 2025 EQ gain edit with its complete live condition closure."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import uuid

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object, _complete_business_draft, _discover_business_field,
    _start_business_draft, _update_business_draft, workflow_sandbox_runtime,
)

pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") != "2025.1",
        reason="One matching 2025 EQ composition witness")]
TARGET = "{B035777D-D60E-443B-ABDA-5E6C4679E270}"
PARENT = "{B3505C97-A72E-4CCF-AECF-28B64CB4F662}"
PEER = "{6C9F51BF-8F8D-4817-9908-4067D38961C9}"
CLASS_ID = 6881283
FIELDS = ("NumBands", "OnOffBand1", "FilterTypeBand1", "GainBand1",
    "FrequencyBand1", "QFactorBand1", "GainBand2", "GainBand3", "OutputLevel")
PEER_FIELDS = ("NumBands", "OnOffBand1", "FilterTypeBand1", "GainBand1", "OutputLevel")
METADATA_FIELDS = ("GainBand1", "OnOffBand1", "FilterTypeBand1", "NumBands")


def _same(actual, expected):
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), (actual, expected)


def _dependency(action, controller, restriction):
    return {"type": "property", "action": action, "context": "Self",
        "property": controller, "conditions": [{"restriction": restriction}]}


SHOW = _dependency("Show", "NumBands", {"type": "range", "min": 1, "max": 8})
ENABLE = _dependency("Enable", "OnOffBand1", {"type": "enum", "values": [{"value": True}]})
FILTER = _dependency("Enable", "FilterTypeBand1",
    {"type": "enum", "values": [{"value": value} for value in (4, 5, 6)]})


def _assert_metadata(metadata):
    assert set(metadata) == set(METADATA_FIELDS), metadata
    expected = {"GainBand1": ("Real32", [SHOW, ENABLE, FILTER]),
        "OnOffBand1": ("bool", [SHOW]), "FilterTypeBand1": ("int32", [ENABLE, SHOW]),
        "NumBands": ("int32", [])}
    for field, (kind, dependencies) in expected.items():
        info = metadata[field]
        assert info["name"] == field and info["type"] == kind, info
        # Source order and native order differ. Preserve raw metadata in the
        # receipt; compare complete semantic descriptors without label text.
        actual = deepcopy(info.get("dependencies", []))
        for dependency in actual:
            for condition in dependency.get("conditions", []):
                for choice in condition.get("restriction", {}).get("values", []):
                    choice.pop("displayName", None)
        _same(sorted(actual, key=lambda row: (row["action"], row["property"])),
            sorted(dependencies, key=lambda row: (row["action"], row["property"])))
    _same(metadata["GainBand1"]["restriction"], {"type": "range", "min": -24.0, "max": 24.0})
    _same(metadata["NumBands"]["restriction"], {"type": "range", "min": 1, "max": 8})
    choices = metadata["FilterTypeBand1"]["restriction"]
    assert choices["type"] == "enum", choices
    values = [row["value"] for row in choices["values"]]
    assert all(type(value) is int for value in values) and len(values) == len(set(values)), choices
    assert set(values) == {0, 1, 7, 8, 2, 3, 6, 4, 5}, choices


def _assert_before(before):
    source, peer, members = before["target"], before["peer"], before["members"]
    assert source["id"] == TARGET and source["name"] == "Voice_EQ", source
    assert peer["id"] == PEER and peer["name"] == "Club_Next_Door", peer
    for row in (source, peer):
        assert row["type"] == "Effect" and type(row["class_id"]) is int and row["class_id"] == CLASS_ID, row
        assert row["parent"]["id"] == PARENT, row
    values = source["properties"]
    assert values["OnOffBand1"] is True, source
    assert type(values["FilterTypeBand1"]) is int and values["FilterTypeBand1"] == 4, source
    assert type(values["NumBands"]) is int and 1 <= values["NumBands"] <= 8, source
    assert type(values["GainBand1"]) in (int, float) and values["GainBand1"] == 4.0, source
    ids = [str(uuid.UUID(row["id"])) for row in members]
    assert len(ids) == len(set(ids)) and {str(uuid.UUID(TARGET)), str(uuid.UUID(PEER))} <= set(ids), members


def _assert_preserved(before, after):
    gain = after["target"]["properties"]["GainBand1"]
    assert type(gain) in (int, float) and gain == 3.0, after
    expected = deepcopy(before)
    expected["target"]["properties"]["GainBand1"] = gain
    _same(after, expected)


def _assert_dispatch(preview, prepared, platform):
    assert not preview["preview_summary"].get("derived_changes"), preview
    _same(prepared["dispatch"], {"uri": "ak.wwise.core.object.setProperty",
        "args": {"object": TARGET, "property": "GainBand1", "value": 3.0, "platform": platform}, "options": {}})


def test_existing_eq_gain_preserves_condition_controllers_and_context(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    assert runtime.version == "2025.1"
    build = runtime.sandbox.metadata.get_info_version
    assert tuple(build.get(key) for key in ("year", "major", "minor", "build")) == (2025, 1, 7, 9143)
    output = runtime.state_dir / "eq-gain-condition.json"
    assert not output.exists(), "An earlier observation must not be overwritten"
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    prior_packets = set(evidence_root.glob("*.json"))
    endpoint = {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}
    observation = {"candidate": runtime.candidate, "version": runtime.version, "endpoint": endpoint,
        "operation": "object.setProperty", "reads": [], "transactions": [], "native_evidence": [],
        "setup_transaction_count": 0, "history_executed": False, "business_effect_verified": False}
    category = {"category": "existing-eq-gain-composed-condition", "status": "FAIL",
        "verifier_strength": "independent_gain_controller_observed_band_peer_membership_preservation",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, argv):
        assert len(observation["reads"]) < 32
        record = {"label": label, "argv": list(argv)}
        observation["reads"].append(record)
        code, payload = runtime.raw_gateway(argv)
        record.update(exit_code=code, payload=payload)
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("endpoint") == endpoint and payload.get("detected_version") == runtime.version, payload
        assert payload.get("projection_complete") is not False and payload.get("status") not in {"partial", "needs_clarification"}, payload
        assert payload.get("limit_reached") is not True, payload
        if argv[0] in {"query-object", "metadata"}:
            assert "agent_result" in payload and list(payload)[-1] == "agent_result", payload
        return payload

    def objects(label, identity, platform, fields=(), *, children=False):
        if len(fields) > 8:
            # The public query owns an eight-custom-field ceiling. Keep both
            # exact identity frames equal before joining the bounded results.
            row = objects(label + "-fields-1", identity, platform, fields[:8])
            extra = objects(label + "-fields-2", identity, platform, fields[8:])
            _same({key: value for key, value in row.items() if key != "properties"},
                {key: value for key, value in extra.items() if key != "properties"})
            row["properties"].update(extra["properties"])
            return row
        ceiling = 16 if children else 2
        argv = ["query-object", "--exact-id", identity, "--max-results", str(ceiling), "--detail",
            "--include", "class-id", "--include", "notes", "--include", "parent"]
        if children:
            argv.extend(["--relationship", "children"])
        if fields:
            argv.extend(["--platform", platform])
            for field in fields:
                argv.extend(["--include-field", field])
        payload = read(label, argv)
        rows = payload["agent_result"]
        assert isinstance(rows, list) and payload["count"] == len(rows) and len(rows) < ceiling, payload
        assert len({str(uuid.UUID(row["id"])) for row in rows}) == len(rows), rows
        if children:
            return rows
        row, = rows
        assert row["id"] == identity and set(row["properties"]) == set(fields), row
        return row

    def context(label, platform):
        return {"target": objects(label + "-target", TARGET, platform, FIELDS),
            "peer": objects(label + "-peer", PEER, platform, PEER_FIELDS),
            "members": objects(label + "-members", PARENT, platform, children=True)}

    def metadata(selections=None):
        if selections is None:
            selections, page, seen = {}, None, set()
            for index in range(8):
                listing = read("field-names-" + str(index), ["metadata", "list", "--exact-id", TARGET,
                    "--page-size", "64", *(["--page", page] if page else [])])["agent_result"]
                for row in listing["fields"]:
                    if row["name"] in METADATA_FIELDS:
                        assert row["name"] not in selections, listing
                        selections[row["name"]] = row["selection"]
                if len(selections) == len(METADATA_FIELDS):
                    break
                assert listing.get("complete") is not True, listing
                page = listing["next_page"]
                assert isinstance(page, str) and page not in seen, listing
                seen.add(page)
            assert set(selections) == set(METADATA_FIELDS), selections
        result = {}
        for field in METADATA_FIELDS:
            detail = read(field + "-detail", ["metadata", "detail", "--exact-id", TARGET,
                "--selection", selections[field]])["agent_result"]
            assert detail.get("complete") is True and detail["scope"] == {"kind": "object", "object": TARGET}, detail
            result[field] = detail["metadata"]
        return selections, result

    try:
        host = read("host-before", ["status"])
        assert host["wwise"]["isCommandLine"] is True, host
        platform = host["project"]["currentPlatformId"]
        assert isinstance(platform, str) and uuid.UUID(platform).int != 0, host
        observation["platform"] = platform
        before = observation["before"] = context("before", platform)
        _assert_before(before)
        selections, info = metadata()
        observation["metadata_before"] = info
        _assert_metadata(info)
        draft = _start_business_draft(runtime, "object.setProperty")
        target = _bind_business_object(runtime, draft, object_id=TARGET)
        field = _discover_business_field(runtime, draft, object_handle=target, meaning="GainBand1", platform=platform)
        _update_business_draft(runtime, draft, "draft-declare-field-change", ["--object-handle", target,
            "--field-handle", field, "--business-value", "3.0"], live=False)

        def inspect(preview):
            observation["preview_before_authorization"] = preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_preview_before_authorization"] = shown
            _assert_dispatch(preview, shown["artifact"]["prepared_operation"], platform)

        receipt = _complete_business_draft(runtime, draft, inspect_preview=inspect)
        observation["transactions"].append(receipt)
        after = observation["after"] = context("after", platform)
        _assert_preserved(before, after)
        observation["metadata_after"] = metadata(selections)[1]
        _same(observation["metadata_after"], info)
        assert read("host-after", ["status"])["project"]["currentPlatformId"] == platform
        assert len(observation["transactions"]) == 1
        observation["business_effect_verified"] = True
        status = "PASS"
    except BaseException as exc:
        observation["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        packets = sorted(set(evidence_root.glob("*.json")) - prior_packets)
        assert len(packets) <= 512
        total = 0
        for packet in packets:
            body = packet.read_bytes()
            total += len(body)
            assert total <= 32 * 1024 * 1024
            observation["native_evidence"].append({"path": str(packet), "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest()})
        observation["status"] = status
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest(),
            business_effect_verified=observation["business_effect_verified"])

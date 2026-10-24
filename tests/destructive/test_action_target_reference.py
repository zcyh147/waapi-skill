"""Existing Play Action retargeting; no construction or audio-playback claim."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import uuid

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object,
    _complete_business_draft,
    discovered_business_field_handle,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)

BUILDS = {"2021.1": (2021, 1, 14, 8108), "2022.1": (2022, 1, 19, 8584),
    "2023.1": (2023, 1, 19, 8928), "2024.1": (2024, 1, 13, 9056), "2025.1": (2025, 1, 7, 9143)}
pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") not in BUILDS, reason="Requires a pinned Wwise Console")]
ACTION = "{AFC1119B-9ADF-49EA-9E49-D3A625BB782D}"
EVENT = "{1AF4A3BA-682A-4664-AC31-45C0F0E6F8D1}"
OLD_TARGET = "{B5DB3AFA-044F-441E-BC4A-1397D20E2692}"
NEW_TARGET = "{0030BF58-90C3-428B-B940-44CC1C5A51B5}"
NEW_PARENT = "{D5594A4B-DDB0-47F3-AC2F-08F104C72438}"
PEER = "{81524933-EE47-4F74-8965-472172F06D33}"
PEER_EVENT = "{2B98695B-2238-45B1-89C5-A5B826472425}"


def test_existing_play_action_retargets_without_changing_action_or_audio_context(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "action-target-reference.json"
    assert not output.exists(), "An earlier observation must not be overwritten"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    prior_packets = set(evidence_root.glob("*.json"))
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "operation": "object.setReference", "reads": [], "transactions": [], "native_evidence": [],
        "business_effect_verified": False}
    category = {"category": "existing-action-target-reference", "status": "FAIL",
        "verifier_strength": "independent_action_reference_controller_and_event_audio_peer_preservation",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, argv):
        assert len(observation["reads"]) < 64
        code, payload = runtime.raw_gateway(argv)
        observation["reads"].append({"label": label, "argv": argv, "exit_code": code, "payload": payload})
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") not in {"partial", "needs_clarification"}, payload
        assert list(payload)[-1] == "agent_result"
        return payload["agent_result"]

    def objects(label, identity, *, actions=False, audio=False, children=False):
        argv = ["query-object", "--exact-id", identity, "--max-results", "32" if children else "2",
            "--include", "class-id", "--include", "notes", "--include", "parent", "--include", "owner"]
        if children:
            argv.extend(["--relationship", "children"])
        if actions:
            argv.extend(["--include", "action-type", "--include", "target"])
            if not children:
                for field in ("Delay", "FadeTime", "Scope"):
                    argv.extend(["--include-field", field])
        if audio:
            argv.extend(["--include-field", "Volume", "--include", "output-bus"])
        rows = read(label, argv)
        assert isinstance(rows, list) and len(rows) < (32 if children else 2), rows
        if children:
            assert len({str(uuid.UUID(row["id"])) for row in rows}) == len(rows), rows
            return rows
        row, = rows
        assert row["id"] == identity, row
        return row

    def context(suffix):
        return {"action": objects("action-" + suffix, ACTION, actions=True),
            "event": objects("event-" + suffix, EVENT),
            "event_children": objects("event-children-" + suffix, EVENT, actions=True, children=True),
            "peer": objects("peer-action-" + suffix, PEER, actions=True),
            "peer_event": objects("peer-event-" + suffix, PEER_EVENT),
            "peer_children": objects("peer-children-" + suffix, PEER_EVENT, actions=True, children=True),
            "old_target": objects("old-target-" + suffix, OLD_TARGET, audio=True),
            "new_target": objects("new-target-" + suffix, NEW_TARGET, audio=True),
            "new_parent": objects("new-parent-" + suffix, NEW_PARENT),
            "new_siblings": objects("new-siblings-" + suffix, NEW_PARENT, children=True)}

    def same(actual, expected):
        assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), (actual, expected)

    try:
        before = context("before")
        observation["before"] = before
        source, target = before["action"], before["new_target"]
        assert source["type"] == "Action" and source["class_id"] == 327696 and source["name"] == "", source
        assert type(source["action_type"]) is int and source["action_type"] == 1, source
        assert source["target"]["id"] == OLD_TARGET and source["parent"]["id"] == EVENT, source
        assert before["event"]["type"] == "Event" and before["event"]["name"] == "Play_Footstep", before
        assert source["path"].startswith(before["event"]["path"] + "\\"), source
        assert [row["id"] for row in before["event_children"]].count(ACTION) == 1, before
        assert target["type"] == "Sound" and target["class_id"] == 65552 and target["name"] == "Footstep_Crouching_Concrete_01", target
        assert target["parent"]["id"] == NEW_PARENT and [row["id"] for row in before["new_siblings"]].count(NEW_TARGET) == 1, before
        draft = _start_business_draft(runtime, "object.setReference")
        source_handle = _bind_business_object(runtime, draft, object_id=ACTION)
        target_handle = _bind_business_object(runtime, draft, object_id=NEW_TARGET)
        discovered = _update_business_draft(runtime, draft, "draft-discover-fields",
            ["--object-handle", source_handle, "--meaning", "Target"], live=True)
        observation["field_discovery"] = discovered
        field = discovered_business_field_handle(discovered, "Target")
        candidates = [item for result in discovered["meaning_results"] for item in result["candidates"]
            if item["handle"] == field]
        candidate, = candidates
        assert candidate["field_kind"] == "reference" and candidate["metadata"]["supports"]["unlink"] is False, candidate
        native = candidate["metadata"]
        native_kind = (isinstance(native.get("type"), str) and native["type"].casefold() in {"reference", "objectreference"}) or native.get("restriction", {}).get("type") == "reference"
        if not native_kind:
            proof = candidate["kind_evidence"]
            assert proof["kind"] == "documented-reference-kind" and proof["object_id"] == ACTION and proof["version"] == runtime.version, proof
            assert proof["identity"] == {"id": ACTION, "type": "Action", "classId": 327696, "ActionType": 1}, proof
            assert proof["restrictions_authority"] == "native_getPropertyInfo", proof
        _update_business_draft(runtime, draft, "draft-declare-field-change",
            ["--object-handle", source_handle, "--field-handle", field, "--target-handle", target_handle], live=False)

        def inspect_preview(preview):
            observation["preview_before_authorization"] = preview
            assert not preview["preview_summary"].get("derived_changes"), preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_preview_before_authorization"] = shown
            prepared = shown["artifact"]["prepared_operation"]
            assert prepared["dispatch"] == {"uri": "ak.wwise.core.object.setReference",
                "args": {"object": ACTION, "reference": "Target", "value": NEW_TARGET}, "options": {}}, prepared
            if not native_kind:
                same(prepared["pre_state"]["field_info"]["reference_kind_evidence"], proof)
                notice, = preview["preview_summary"]["reference_kind_evidence"]
                assert notice["object_id"] == ACTION and notice["field"] == "Target" and notice["authority"] == "pinned_sdk_field_kind", notice

        receipt = _complete_business_draft(runtime, draft, inspect_preview=inspect_preview)
        observation["transactions"].append(receipt)
        after = context("after")
        observation["after"] = after
        actual = after["action"]
        assert actual["target"]["id"] == NEW_TARGET, actual
        for key in ("name", "type", "path"):
            if key in actual["target"]:
                assert actual["target"][key] == target[key], (actual, target)
        assert isinstance(actual["path"], str) and actual["path"].startswith(before["event"]["path"] + "\\"), actual
        # The Action's display path may derive from the new target; its actual
        # canonical GUID, intrinsic empty name and owning Event remain fixed.
        expected = deepcopy(source)
        expected.update(target=actual["target"], path=actual["path"])
        same(actual, expected)
        expected_members = deepcopy(before["event_children"])
        selected, = [row for row in expected_members if row["id"] == ACTION]
        selected.update(target=actual["target"], path=actual["path"])
        same(after["event_children"], expected_members)
        for key in ("event", "peer", "peer_event", "peer_children", "old_target", "new_target", "new_parent"):
            same(after[key], before[key])
        same({row["id"]: row for row in after["new_siblings"]},
            {row["id"]: row for row in before["new_siblings"]})
        assert len(observation["transactions"]) == 1
        observation["business_effect_verified"] = True
        status = "PASS"
    finally:
        observation["native_evidence"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(set(evidence_root.glob("*.json")) - prior_packets)]
        observation["status"] = status
        output.write_text(json.dumps(observation, indent=2, sort_keys=True) + "\n")
        category.update(status=status, observation_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            business_effect_verified=observation["business_effect_verified"])

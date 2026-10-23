"""Existing master-bus AudioDevice edits through the closed reference workflow."""
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
    _created_object_id,
    discovered_business_field_handle,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)


BUILDS = {"2024.1": (2024, 1, 13, 9056), "2025.1": (2025, 1, 7, 9143)}
pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") not in BUILDS,
        reason="Requires the pinned 2024.1 or 2025.1 Console")]
BUS = "{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}"
PEER = "{D2E0BC7E-7B3F-4FFE-A670-FAE02761B631}"
SYSTEM = "{ADC920EF-0BEE-483D-B40B-0C2CDF19E1F4}"
NO_OUTPUT = "{5C2A5343-5AB9-44EB-9054-348F70EA38BE}"
BUS_PARENT = "{A74EEB4A-0805-4AFA-969C-53DCB862B550}"
DEVICE_PARENT = "{B231292D-F96D-4EDC-AE14-D62DE1E07EDD}"
# Matching 2024/25 packaged getTypes rows classify these concrete plugins as
# AudioDevice. The base WObject AudioDevice class is not an instance class.
DEVICE_PLUGIN_CLASSES = {"System": 11403271, "No Output": 11862023}
# Both pinned DefaultSink.xml System definitions expose these parameters. Read
# actual values; source defaults are never substituted for missing observations.
SYSTEM_PARAMETERS = ("Allow3DAudio", "MainMixHeadphoneConfiguration", "MainMixSpeakerConfiguration",
    "AllowSystemAudioObjects", "MinSystemAudioObjectsRequired")


def test_existing_master_bus_audio_device_preserves_context(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    build = runtime.sandbox.metadata.get_info_version
    assert tuple(build.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "master-bus-audio-device.json"
    assert not output.exists(), "An earlier observation must not be overwritten"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    prior_packets = set(evidence_root.glob("*.json"))
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "operation": "object.setReference", "reads": [], "transactions": [],
        "native_evidence": [], "business_effect_verified": False}
    category = {"category": "existing-master-bus-audio-device", "status": "FAIL",
        "verifier_strength": "independent_exact_reference_bus_peer_devices_and_topology_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, argv):
        assert len(observation["reads"]) < 64
        code, payload = runtime.raw_gateway(argv)
        observation["reads"].append({"label": label, "argv": argv, "exit_code": code, "payload": payload})
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") not in {"partial", "needs_clarification"}, payload
        if argv[0] != "status":
            assert list(payload)[-1] == "agent_result"
        return payload

    def objects(label, identity, *, reference=False, children=False, parameters=False, platform=None):
        argv = ["query-object", "--exact-id", identity, "--max-results", "16" if children else "2",
            "--detail", "--include", "class-id", "--include", "notes", "--include", "parent", "--include", "owner"]
        if reference:
            argv.extend(["--include-field", "AudioDevice"])
        if children:
            argv.extend(["--relationship", "children"])
        if parameters:
            assert isinstance(platform, str) and uuid.UUID(platform).int != 0
            argv.extend(["--platform", platform])
            for parameter in SYSTEM_PARAMETERS:
                argv.extend(["--include-field", parameter])
        payload = read(label, argv)
        rows = payload["agent_result"]
        assert isinstance(rows, list) and len(rows) < (16 if children else 2), payload
        if children:
            return rows
        assert len(rows) == 1 and rows[0]["id"] == identity, rows
        if parameters:
            assert set(rows[0]["properties"]) == set(SYSTEM_PARAMETERS), rows[0]
        return rows[0]

    def context(suffix, platform):
        # Collect all related context before asserting optional native shapes.
        result = {"bus": objects("bus-" + suffix, BUS, reference=True),
            "peer": objects("peer-" + suffix, PEER, reference=True),
            "system": objects("system-" + suffix, SYSTEM, parameters=True, platform=platform),
            "target": objects("target-" + suffix, NO_OUTPUT),
            "bus_parent": objects("bus-parent-" + suffix, BUS_PARENT),
            "device_parent": objects("device-parent-" + suffix, DEVICE_PARENT),
            "children": objects("bus-children-" + suffix, BUS, children=True),
            "siblings": objects("bus-siblings-" + suffix, BUS_PARENT, children=True),
            "device_children": objects("device-children-" + suffix, DEVICE_PARENT, children=True)}
        # Independently retain the actual hierarchy boundary reached by the
        # parent GUID. No root class/type or absent-parent shape is invented.
        root_id = result["bus_parent"]["parent"]["id"]
        assert isinstance(root_id, str) and uuid.UUID(root_id).int != 0, result["bus_parent"]
        result["bus_hierarchy_root"] = objects("bus-hierarchy-root-" + suffix, root_id)
        return result

    def selected_metadata():
        page, seen = None, set()
        for index in range(8):
            inventory = read("bus-field-names-" + str(index), ["metadata", "list", "--exact-id", BUS,
                "--page-size", "64", *(["--page", page] if page else [])])["agent_result"]
            matches = [row for row in inventory["fields"] if row["name"] == "AudioDevice"]
            if matches:
                selected, = matches
                selection = selected["selection"]
                return selection, metadata_detail("bus-field-before", selection)
            assert inventory.get("complete") is not True, inventory
            page = inventory["next_page"]
            assert isinstance(page, str) and page not in seen, inventory
            seen.add(page)
        raise AssertionError("AudioDevice was not selected within eight bounded metadata pages")

    def metadata_detail(label, selection):
        detail = read(label, ["metadata", "detail", "--exact-id", BUS, "--selection", selection])["agent_result"]
        assert detail.get("complete") is True and detail["scope"] == {"kind": "object", "object": BUS}, detail
        return detail["metadata"]

    def same(actual, expected):
        assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), (actual, expected)

    def device_members(rows):
        # WorkUnit children prove ownership/set membership, not semantic order.
        # Keep every observed row and reject duplicate canonical GUIDs.
        members = {str(uuid.UUID(row["id"])): row for row in rows}
        assert len(members) == len(rows), rows
        return members

    try:
        host = read("host-and-current-platform-before", ["status"])
        platform = host.get("project", {}).get("currentPlatformId")
        assert isinstance(platform, str) and uuid.UUID(platform).int != 0, host
        observation["platform"] = platform
        before = context("before", platform)
        observation["before"] = before
        bus, peer = before["bus"], before["peer"]
        bus_hierarchy = "Busses" if runtime.version == "2025.1" else "Master-Mixer Hierarchy"
        device_hierarchy = "Devices" if runtime.version == "2025.1" else "Audio Devices"
        bus_name = "Main Audio Bus" if runtime.version == "2025.1" else "Master Audio Bus"
        assert bus["type"] == "Bus" and bus["class_id"] == 1376272, bus
        assert bus["name"] == bus_name and bus["path"] == "\\" + bus_hierarchy + "\\Default Work Unit\\" + bus_name, bus
        assert bus["parent"]["id"] == BUS_PARENT and peer["parent"]["id"] == BUS_PARENT, before
        assert bus["references"]["AudioDevice"]["id"] == SYSTEM and peer["references"]["AudioDevice"]["id"] == SYSTEM, before
        for key, name, plugin in (("system", "System", "System"), ("target", "No_Output", "No Output")):
            row = before[key]
            assert row["type"] == "AudioDevice" and row["class_id"] == DEVICE_PLUGIN_CLASSES[plugin] and row["name"] == name, row
            assert row["parent"]["id"] == DEVICE_PARENT, row
            assert row["path"] == "\\" + device_hierarchy + "\\Default Work Unit\\" + name, row
        member, = [row for row in before["siblings"] if row["id"] == BUS]
        assert {key: member[key] for key in ("id", "name", "type", "path")} == {
            key: bus[key] for key in ("id", "name", "type", "path")}, (member, bus)
        assert {row["id"] for row in before["siblings"]} == {BUS, PEER}, before["siblings"]

        selection, metadata = selected_metadata()
        observation["metadata_before"] = metadata
        # A valid reference's raw type may be empty. Its restriction and the
        # selected reference kind certify the actual field; structural Show
        # applicability is proved separately through the public Field/Preview.
        restriction = metadata["restriction"]
        assert restriction["type"] == "reference", metadata
        restrictions = restriction["restrictions"]
        # Source WObjects names AudioDevice; the matching 2024 native packet
        # uses the display label Audio Device. The existing reference matcher
        # accepts these spellings for the same exact native target type.
        assert any(isinstance(row, dict) and isinstance(row.get("type"), list) and row["type"]
            and set(row["type"]) <= {"Audio Device", "AudioDevice"} for row in restrictions), metadata
        master_dependency, = [row for row in metadata.get("dependencies", []) if row.get("type") == "isMasterBus"]
        assert master_dependency == {"type": "isMasterBus", "value": True, "action": "Show", "context": "Self"}, metadata

        # No_Output was a test-owned selection rejected in the retained R3
        # attempt. CanBeMasterSink=false does not establish its complete role
        # semantics. Keep it untouched; do not add a blanket compatibility gate.
        # A separately verified copy of the already assigned System keeps this
        # positive witness on the actual same plugin class and parameter profile.
        setup = _start_business_draft(runtime, "object.copy")
        _bind_business_object(runtime, setup, object_id=SYSTEM, role="object")
        _bind_business_object(runtime, setup, object_id=DEVICE_PARENT, role="parent")
        _update_business_draft(runtime, setup, "draft-declare-object-change", ["--name-conflict", "rename"], live=False)

        def inspect_setup(preview):
            observation["setup_preview_before_authorization"] = preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_setup_preview_before_authorization"] = shown
            dispatch = shown["artifact"]["prepared_operation"]["dispatch"]
            assert dispatch["uri"] == "ak.wwise.core.object.copy", dispatch
            assert dispatch["args"] == {"object": SYSTEM, "parent": DEVICE_PARENT, "onNameConflict": "rename",
                "autoAddToSourceControl": False, "autoCheckOutToSourceControl": False}, dispatch

        setup_receipt = _complete_business_draft(runtime, setup, inspect_preview=inspect_setup)
        observation["transactions"].append(setup_receipt)
        copy_id = _created_object_id(setup_receipt["execute"])
        assert uuid.UUID(copy_id).int != 0 and copy_id not in {SYSTEM, NO_OUTPUT}, copy_id
        observation["owned_copy_id"] = copy_id
        after_setup = context("after-setup", platform)
        observation["after_setup"] = after_setup
        target = objects("owned-system-copy-after-setup", copy_id, parameters=True, platform=platform)
        observation["owned_copy_after_setup"] = target
        original = before["system"]
        assert target["type"] == original["type"] == "AudioDevice", (target, original)
        assert target["class_id"] == original["class_id"] == DEVICE_PLUGIN_CLASSES["System"], (target, original)
        assert target["parent"]["id"] == DEVICE_PARENT, target
        assert isinstance(target["name"], str) and target["name"] and target["name"] != original["name"], target
        assert target["path"] == before["device_parent"]["path"] + "\\" + target["name"], target
        same(target["properties"], original["properties"])
        same(target["notes"], original["notes"])
        for key in before:
            if key != "device_children":
                same(after_setup[key], before[key])
        copied_member, = [row for row in after_setup["device_children"] if row["id"] == copy_id]
        same(copied_member, {key: value for key, value in target.items() if key != "properties"})
        setup_members = device_members(after_setup["device_children"])
        expected_members = device_members(before["device_children"])
        assert str(uuid.UUID(copy_id)) not in expected_members, copy_id
        expected_members[str(uuid.UUID(copy_id))] = copied_member
        same(setup_members, expected_members)
        assert len(after_setup["device_children"]) == len(before["device_children"]) + 1, after_setup
        host_before_reference = read("host-and-current-platform-before-reference", ["status"])
        assert host_before_reference.get("project", {}).get("currentPlatformId") == platform, host_before_reference

        draft = _start_business_draft(runtime, "object.setReference")
        source_handle = _bind_business_object(runtime, draft, object_id=BUS)
        target_handle = _bind_business_object(runtime, draft, object_id=copy_id)
        discovered = _update_business_draft(runtime, draft, "draft-discover-fields", ["--object-handle", source_handle,
            "--meaning", "AudioDevice", "--platform", platform], live=True)
        field = discovered_business_field_handle(discovered, "AudioDevice")
        candidate, = [row for result in discovered["meaning_results"] for row in result["candidates"] if row["handle"] == field]
        applicability = candidate["applicability"]
        observation["field_applicability_before"] = applicability
        assert applicability["kind"] == "structural-reference-visibility", applicability
        assert applicability["condition"] == master_dependency and applicability["native_enabled_state"] == "not_queried", applicability
        assert applicability["object_id"] == BUS and applicability["field"] == "AudioDevice" and applicability["platform"] == platform, applicability
        assert [row["id"] for row in applicability["rows"]] == [BUS, BUS_PARENT, before["bus_hierarchy_root"]["id"]], applicability
        for actual, expected in zip(applicability["rows"], (bus, before["bus_parent"], before["bus_hierarchy_root"])):
            same({("class_id" if key == "classId" else key): value for key, value in actual.items()},
                {("class_id" if key == "classId" else key): expected["class_id" if key == "classId" else key] for key in actual})
        _update_business_draft(runtime, draft, "draft-declare-field-change", ["--object-handle", source_handle,
            "--field-handle", field, "--target-handle", target_handle], live=False)

        def inspect_preview(preview):
            observation["preview_before_authorization"] = preview
            assert not preview["preview_summary"].get("derived_changes"), preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_preview_before_authorization"] = shown
            prepared = shown["artifact"]["prepared_operation"]
            structural, = prepared["pre_state"]["condition_metadata"]["structural_applicability"]
            same(structural, applicability)
            notice, = preview["preview_summary"]["reference_applicability"]
            assert notice["native_enabled_state"] == "not_queried" and notice["condition"] == master_dependency, notice
            assert notice["object_id"] == BUS and notice["field"] == "AudioDevice" and notice["platform"] == platform, notice
            dispatch = prepared["dispatch"]
            assert dispatch["uri"] == "ak.wwise.core.object.setReference", dispatch
            assert dispatch["args"] == {"object": BUS, "reference": "AudioDevice", "value": copy_id, "platform": platform}, dispatch

        receipt = _complete_business_draft(runtime, draft, inspect_preview=inspect_preview)
        observation["transactions"].append(receipt)
        after = context("after", platform)
        observation["after"] = after
        copy_after = objects("owned-system-copy-after-reference", copy_id, parameters=True, platform=platform)
        observation["owned_copy_after_reference"] = copy_after
        same(copy_after, target)
        # Only the declared reference value may differ. Preserve every other
        # observed member, including notes and native omission/null distinctions.
        actual_reference = after["bus"]["references"]["AudioDevice"]
        assert actual_reference["id"] == copy_id, actual_reference
        for key in ("name", "type", "path"):
            if key in actual_reference:
                assert actual_reference[key] == target[key], (actual_reference, target)
        expected_bus = deepcopy(bus)
        expected_bus["references"]["AudioDevice"] = actual_reference
        same(after["bus"], expected_bus)
        for key in ("peer", "system", "target", "bus_parent", "device_parent", "children", "bus_hierarchy_root"):
            same(after[key], before[key])
        same(after["siblings"], before["siblings"])
        same(device_members(after["device_children"]), setup_members)
        same(metadata_detail("bus-field-after", selection), metadata)
        host_after = read("host-and-current-platform-after", ["status"])
        assert host_after.get("project", {}).get("currentPlatformId") == platform, host_after
        assert len(observation["transactions"]) == 2
        assert setup_receipt["preview"]["transaction_id"] != receipt["preview"]["transaction_id"]
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
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest())

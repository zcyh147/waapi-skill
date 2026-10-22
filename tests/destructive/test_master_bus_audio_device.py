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
    _discover_business_field,
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

    def objects(label, identity, *, reference=False, children=False):
        argv = ["query-object", "--exact-id", identity, "--max-results", "16" if children else "2",
            "--detail", "--include", "class-id", "--include", "notes", "--include", "parent", "--include", "owner"]
        if reference:
            argv.extend(["--include-field", "AudioDevice"])
        if children:
            argv.extend(["--relationship", "children"])
        payload = read(label, argv)
        rows = payload["agent_result"]
        assert isinstance(rows, list) and len(rows) < (16 if children else 2), payload
        if children:
            return rows
        assert len(rows) == 1 and rows[0]["id"] == identity, rows
        return rows[0]

    def context(suffix):
        # Collect all related context before asserting optional native shapes.
        return {"bus": objects("bus-" + suffix, BUS, reference=True),
            "peer": objects("peer-" + suffix, PEER, reference=True),
            "system": objects("system-" + suffix, SYSTEM),
            "target": objects("target-" + suffix, NO_OUTPUT),
            "bus_parent": objects("bus-parent-" + suffix, BUS_PARENT),
            "device_parent": objects("device-parent-" + suffix, DEVICE_PARENT),
            "children": objects("bus-children-" + suffix, BUS, children=True),
            "siblings": objects("bus-siblings-" + suffix, BUS_PARENT, children=True)}

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

    def enabled(label, selection, platform):
        result = read(label, ["metadata", "property-state", "--exact-id", BUS,
            "--selection", selection, "--platform", platform])["agent_result"]
        assert result["field"] == "AudioDevice" and result["kind"] == "reference", result
        assert result["scope"] == {"kind": "object", "object": BUS}, result
        assert result["platform"] == platform and result["enabled"] is True and result["mutation_authority"] is False, result
        return result

    def same(actual, expected):
        assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), (actual, expected)

    try:
        host = read("host-and-current-platform-before", ["status"])
        before = context("before")
        observation["before"] = before
        platform = host.get("project", {}).get("currentPlatformId")
        assert isinstance(platform, str) and uuid.UUID(platform).int != 0, host
        observation["platform"] = platform
        bus, peer, target = before["bus"], before["peer"], before["target"]
        bus_hierarchy = "Busses" if runtime.version == "2025.1" else "Master-Mixer Hierarchy"
        device_hierarchy = "Devices" if runtime.version == "2025.1" else "Audio Devices"
        bus_name = "Main Audio Bus" if runtime.version == "2025.1" else "Master Audio Bus"
        assert bus["type"] == "Bus" and bus["class_id"] == 1376272, bus
        assert bus["name"] == bus_name and bus["path"] == "\\" + bus_hierarchy + "\\Default Work Unit\\" + bus_name, bus
        assert bus["parent"]["id"] == BUS_PARENT and peer["parent"]["id"] == BUS_PARENT, before
        assert bus["references"]["AudioDevice"]["id"] == SYSTEM and peer["references"]["AudioDevice"]["id"] == SYSTEM, before
        for key, name in (("system", "System"), ("target", "No_Output")):
            row = before[key]
            assert row["type"] == "AudioDevice" and row["class_id"] == 4653072 and row["name"] == name, row
            assert row["parent"]["id"] == DEVICE_PARENT, row
            assert row["path"] == "\\" + device_hierarchy + "\\Default Work Unit\\" + name, row
        member, = [row for row in before["siblings"] if row["id"] == BUS]
        assert {key: member[key] for key in ("id", "name", "type", "path")} == {
            key: bus[key] for key in ("id", "name", "type", "path")}, (member, bus)
        assert {row["id"] for row in before["siblings"]} == {BUS, PEER}, before["siblings"]

        selection, metadata = selected_metadata()
        observation["metadata_before"] = metadata
        # A valid reference's raw type may be empty. Its restriction and the
        # selected enabled-state result certify the actual reference field.
        restriction = metadata["restriction"]
        assert restriction["type"] == "reference", metadata
        restrictions = restriction["restrictions"]
        assert any(isinstance(row, dict) and "AudioDevice" in row.get("type", []) for row in restrictions), metadata
        master_dependency, = [row for row in metadata.get("dependencies", []) if row.get("type") == "isMasterBus"]
        assert master_dependency == {"type": "isMasterBus", "value": True, "action": "Show", "context": "Self"}, metadata
        enabled("bus-enabled-before", selection, platform)

        draft = _start_business_draft(runtime, "object.setReference")
        source_handle = _bind_business_object(runtime, draft, object_id=BUS)
        target_handle = _bind_business_object(runtime, draft, object_id=NO_OUTPUT)
        field = _discover_business_field(runtime, draft, object_handle=source_handle, meaning="AudioDevice", platform=platform)
        _update_business_draft(runtime, draft, "draft-declare-field-change", ["--object-handle", source_handle,
            "--field-handle", field, "--target-handle", target_handle], live=False)

        def inspect_preview(preview):
            observation["preview_before_authorization"] = preview
            assert not preview["preview_summary"].get("derived_changes"), preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_preview_before_authorization"] = shown
            dispatch = shown["artifact"]["prepared_operation"]["dispatch"]
            assert dispatch["uri"] == "ak.wwise.core.object.setReference", dispatch
            assert dispatch["args"] == {"object": BUS, "reference": "AudioDevice", "value": NO_OUTPUT, "platform": platform}, dispatch

        receipt = _complete_business_draft(runtime, draft, inspect_preview=inspect_preview)
        observation["transactions"].append(receipt)
        after = context("after")
        observation["after"] = after
        # Only the declared reference value may differ. Preserve every other
        # observed member, including notes and native omission/null distinctions.
        actual_reference = after["bus"]["references"]["AudioDevice"]
        assert actual_reference["id"] == NO_OUTPUT, actual_reference
        for key in ("name", "type", "path"):
            if key in actual_reference:
                assert actual_reference[key] == target[key], (actual_reference, target)
        expected_bus = deepcopy(bus)
        expected_bus["references"]["AudioDevice"] = actual_reference
        same(after["bus"], expected_bus)
        for key in ("peer", "system", "target", "bus_parent", "device_parent", "children"):
            same(after[key], before[key])
        same(after["siblings"], before["siblings"])
        same(metadata_detail("bus-field-after", selection), metadata)
        enabled("bus-enabled-after", selection, platform)
        host_after = read("host-and-current-platform-after", ["status"])
        assert host_after.get("project", {}).get("currentPlatformId") == platform, host_after
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
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest())

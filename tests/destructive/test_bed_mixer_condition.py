"""One platform-bound Bed Mixer ShareSet setup and existing conditional edit."""
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
    _discover_business_type,
    discovered_business_field_handle,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)


BUILDS = {"2022.1": (2022, 1, 19, 8584), "2023.1": (2023, 1, 19, 8928),
    "2024.1": (2024, 1, 13, 9056), "2025.1": (2025, 1, 7, 9143)}
pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") not in BUILDS,
        reason="Bed Mixer class is captured on pinned2022–25 hosts; constructor backend is2022–25")]
PARENT = "{2D54A839-DA81-4D75-A684-ABCB4AC6B14E}"
PEER = "{4D11F2B7-6057-4887-A725-F00E1629699E}"
FIELDS = ("SystemAudioObjectsPolicy", "SystemAudioObjectLimit", "MainMixConfiguration", "PassthroughMixPolicy")


def test_existing_bed_mixer_limit_preserves_policy_and_selected_view(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    build = runtime.sandbox.metadata.get_info_version
    assert tuple(build.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "bed-mixer-condition.json"
    assert not output.exists(), "An earlier observation must not be overwritten"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    prior_packets = set(evidence_root.glob("*.json"))
    observation = {"candidate": runtime.candidate, "version": runtime.version, "operation": "object.setProperty",
        "reads": [], "transactions": [], "native_evidence": [], "business_effect_verified": False, "stage": "shareset_setup"}
    category = {"category": "existing-bed-mixer-enum-condition", "status": "FAIL",
        "verifier_strength": "independent_selected_platform_limit_policy_all_plugin_fields_peer_and_membership_readback",
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

    def objects(label, identity, platform, fields=(), *, children=False):
        argv = ["query-object", "--exact-id", identity, "--max-results", "16" if children else "2", "--detail",
            "--include", "class-id", "--include", "notes", "--include", "parent", "--include", "owner"]
        if children:
            argv.extend(["--relationship", "children"])
        if fields:
            # These plugin parameters are platform-linkable. Bind every
            # independent parameter read to the same actually disclosed view.
            argv.extend(["--platform", platform])
            for field in fields:
                argv.extend(["--include-field", field])
        rows = read(label, argv)["agent_result"]
        assert isinstance(rows, list) and len(rows) < (16 if children else 2), rows
        if children:
            return rows
        row, = rows
        assert row["id"] == identity, row
        if fields:
            assert set(row["properties"]) == set(fields), row
        return row

    def context(suffix, platform, peer_parent):
        return {"parent": objects("parent-" + suffix, PARENT, platform),
            "members": objects("members-" + suffix, PARENT, platform, children=True),
            "peer": objects("peer-" + suffix, PEER, platform, ("RoomSize",)),
            "peer_parent": objects("peer-parent-" + suffix, peer_parent, platform)}

    def same(actual, expected):
        assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), (actual, expected)

    def members(rows):
        mapped = {str(uuid.UUID(row["id"])): row for row in rows}
        assert len(mapped) == len(rows), rows
        return mapped

    def metadata(label, identity, field, selection=None):
        if selection is None:
            page, seen = None, set()
            for index in range(8):
                inventory = read(label + "-names-" + str(index), ["metadata", "list", "--exact-id", identity,
                    "--page-size", "64", *(["--page", page] if page else [])])["agent_result"]
                matches = [row for row in inventory["fields"] if row["name"] == field]
                if matches:
                    selected, = matches
                    selection = selected["selection"]
                    break
                assert inventory.get("complete") is not True, inventory
                page = inventory["next_page"]
                assert isinstance(page, str) and page not in seen, inventory
                seen.add(page)
            assert selection is not None, inventory
        detail = read(label + "-detail", ["metadata", "detail", "--exact-id", identity,
            "--selection", selection])["agent_result"]
        assert detail.get("complete") is True and detail["scope"] == {"kind": "object", "object": identity}, detail
        assert detail["metadata"]["name"] == field, detail
        return selection, detail["metadata"]

    def enabled(label, identity, selection, platform):
        result = read(label, ["metadata", "property-state", "--exact-id", identity,
            "--selection", selection, "--platform", platform])["agent_result"]
        assert result["field"] == "SystemAudioObjectLimit" and result["kind"] == "property", result
        assert result["scope"] == {"kind": "object", "object": identity}, result
        assert result["enabled"] is True and result["mutation_authority"] is False, result

    try:
        host = read("host-and-current-platform-before", ["status"])
        platform = host.get("project", {}).get("currentPlatformId")
        assert isinstance(platform, str) and uuid.UUID(platform).int != 0, host
        observation["platform"] = platform
        # Resolve this existing peer's parent from the public row, not a guessed
        # hierarchy token. Collect all before context before format assertions.
        peer = objects("peer-before-setup", PEER, platform, ("RoomSize",))
        peer_parent = peer["parent"]["id"]
        assert uuid.UUID(peer_parent).int != 0, peer
        before = {"peer": peer, "parent": objects("parent-before-setup", PARENT, platform),
            "members": objects("members-before-setup", PARENT, platform, children=True),
            "peer_parent": objects("peer-parent-before-setup", peer_parent, platform)}
        observation["before_setup"] = before
        assert before["parent"]["type"] == "WorkUnit" and before["parent"]["path"] == r"\Effects\Default Work Unit", before
        original_members = members(before["members"])
        setup = _start_business_draft(runtime, "object.createPlugin")
        parent = _bind_business_object(runtime, setup, object_id=PARENT)
        kind = _discover_business_type(runtime, setup, meaning="Wwise 3D Audio Bed Mixer", role="effect", expected_label="Wwise 3D Audio Bed Mixer")
        found = _update_business_draft(runtime, setup, "draft-discover-fields",
            ["--type-handle", kind, "--meaning", "SystemAudioObjectsPolicy", "--platform", platform], live=True)
        policy = discovered_business_field_handle(found, "SystemAudioObjectsPolicy")
        name = "WAAPI_Bed_" + uuid.uuid4().hex[:12]
        _update_business_draft(runtime, setup, "draft-declare-existing", ["--declaration-id", "bed", "--object-handle", parent,
            "--field", "plugin_role", "effect", "--field", "plugin_placement", "shareset", "--field", "plugin_name", name,
            "--field", "plugin_type_handle", kind, "--field", "platform", platform, "--field-value", policy, "1"], live=False)

        def inspect_setup(preview):
            observation["setup_preview_before_authorization"] = preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_setup_preview_before_authorization"] = shown
            prepared = shown["artifact"]["prepared_operation"]
            dispatch = prepared["dispatch"]
            assert dispatch["uri"] == "ak.wwise.core.object.set" and dispatch["options"] == {}, dispatch
            assert dispatch["args"] == {"objects": [{"object": PARENT, "onNameConflict": "fail", "children": [
                {"type": "Effect", "name": name, "classId": 12451843, "platform": platform, "@SystemAudioObjectsPolicy": 1}]}],
                "autoAddToSourceControl": False}, dispatch
            assert prepared["verification_plan"]["readback_view"]["platform"] == platform, prepared

        setup_receipt = _complete_business_draft(runtime, setup, inspect_preview=inspect_setup)
        observation["transactions"].append(setup_receipt)
        observation["stage"] = "existing_object_applicability"
        after_setup = context("after-setup", platform, peer_parent)
        observation["after_setup"] = after_setup
        new_members = members(after_setup["members"])
        added, = set(new_members) - set(original_members)
        assert len(new_members) == len(original_members) + 1, after_setup
        target_id = new_members[added]["id"]
        assert uuid.UUID(target_id).int != 0 and target_id not in {PARENT, PEER, peer_parent}, target_id
        source = objects("bed-before-edit", target_id, platform, FIELDS)
        observation.update(target_id=target_id, source_before=source)
        assert source["type"] in {"Effect", "EffectPlugin"} and source["class_id"] == 12451843, source
        assert source["name"] == name and source["path"] == before["parent"]["path"] + "\\" + name, source
        assert source["parent"]["id"] == PARENT, source
        assert type(source["properties"]["SystemAudioObjectsPolicy"]) is int and source["properties"]["SystemAudioObjectsPolicy"] == 1, source
        assert type(source["properties"]["SystemAudioObjectLimit"]) is int and source["properties"]["SystemAudioObjectLimit"] == 64, source
        for key in ("parent", "peer", "peer_parent"):
            same(after_setup[key], before[key])
        same(new_members, {**original_members, added: {key: value for key, value in source.items() if key != "properties"}})
        limit_selection, limit_info = metadata("limit-before", target_id, "SystemAudioObjectLimit")
        policy_selection, policy_info = metadata("policy-before", target_id, "SystemAudioObjectsPolicy")
        observation["metadata_before"] = {"limit": limit_info, "policy": policy_info}
        assert limit_info["type"] == policy_info["type"] == "Uint16", (limit_info, policy_info)
        assert limit_info["supports"]["unlink"] is True and policy_info["supports"]["unlink"] is True, (limit_info, policy_info)
        dependency, = limit_info["dependencies"]
        assert {key: dependency[key] for key in ("type", "action", "context", "property")} == {
            "type": "property", "action": "Enable", "context": "Self", "property": "SystemAudioObjectsPolicy"}, dependency
        condition, = dependency["conditions"]
        assert condition["restriction"]["type"] == "enum", condition
        values = condition["restriction"]["values"]
        assert all(type(row["value"]) is int for row in values) and {row["value"] for row in values} == {0, 1}, condition
        assert limit_info["restriction"] == {"type": "range", "min": 0, "max": 512}, limit_info
        assert policy_info.get("dependencies", []) == [] and policy_info["restriction"]["type"] == "enum", policy_info
        values = policy_info["restriction"]["values"]
        assert all(type(row["value"]) is int for row in values) and {row["value"] for row in values} == {0, 1, 2}, policy_info
        enabled("limit-enabled-before", target_id, limit_selection, platform)
        assert read("host-and-current-platform-before-edit", ["status"])["project"]["currentPlatformId"] == platform
        draft = _start_business_draft(runtime, "object.setProperty")
        target = _bind_business_object(runtime, draft, object_id=target_id)
        field = _discover_business_field(runtime, draft, object_handle=target, meaning="SystemAudioObjectLimit", platform=platform)
        _update_business_draft(runtime, draft, "draft-declare-field-change", ["--object-handle", target,
            "--field-handle", field, "--business-value", "128"], live=False)

        def inspect_edit(preview):
            observation["preview_before_authorization"] = preview
            assert not preview["preview_summary"].get("derived_changes"), preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_preview_before_authorization"] = shown
            prepared = shown["artifact"]["prepared_operation"]
            assert prepared["dispatch"]["uri"] == "ak.wwise.core.object.setProperty", prepared
            assert prepared["dispatch"]["args"] == {"object": target_id, "property": "SystemAudioObjectLimit", "value": 128, "platform": platform}, prepared
            assert prepared["pre_state"]["field_before"]["activation_requirements"] == {"SystemAudioObjectsPolicy": 1}, prepared
            assert prepared["pre_state"]["field_before"]["observation_platform"] == platform, prepared

        observation["stage"] = "existing_object_edit"
        edit_receipt = _complete_business_draft(runtime, draft, inspect_preview=inspect_edit)
        observation["transactions"].append(edit_receipt)
        after = objects("bed-after-edit", target_id, platform, FIELDS)
        expected = deepcopy(source)
        expected["properties"]["SystemAudioObjectLimit"] = 128
        same(after, expected)
        after_context = context("after-edit", platform, peer_parent)
        observation.update(source_after=after, after=after_context)
        for key in ("parent", "peer", "peer_parent"):
            same(after_context[key], before[key])
        same(members(after_context["members"]), new_members)
        same(metadata("limit-after", target_id, "SystemAudioObjectLimit", limit_selection)[1], limit_info)
        same(metadata("policy-after", target_id, "SystemAudioObjectsPolicy", policy_selection)[1], policy_info)
        enabled("limit-enabled-after", target_id, limit_selection, platform)
        assert read("host-and-current-platform-after", ["status"])["project"]["currentPlatformId"] == platform
        assert len(observation["transactions"]) == 2
        assert setup_receipt["preview"]["transaction_id"] != edit_receipt["preview"]["transaction_id"]
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
            observation["native_evidence"].append({"path": str(packet), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest())

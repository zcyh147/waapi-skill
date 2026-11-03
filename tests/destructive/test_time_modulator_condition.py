"""Owned standalone setup followed by one existing Time Modulator field edit."""
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
    _discover_business_field,
    _discover_business_type,
    discovered_business_field_handle,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)


BUILDS = {"2021.1": (2021, 1, 14, 8108), "2022.1": (2022, 1, 19, 8584),
    "2023.1": (2023, 1, 19, 8928), "2024.1": (2024, 1, 13, 9056), "2025.1": (2025, 1, 7, 9143)}
pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") not in BUILDS, reason="Requires a pinned Wwise Console")]
PARENT = "{F29892F6-1D97-4F5F-8E0A-A82D4CD3D195}"
PEER = "{ABB691DF-7FB4-43C0-A3FB-15B23CE989EB}"
PEER_PARENT = "{409E8F6C-A255-4A94-958B-03E79369113A}"
UNLINKED_PLATFORM = "{00000000-0000-0000-0000-000000000000}"
FIELDS = ("TimeModLoops", "EnvelopeStopPlayback", "TimeModDuration")


def test_existing_time_stop_playback_preserves_loop_count_and_context(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    build = runtime.sandbox.metadata.get_info_version
    assert tuple(build.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "time-modulator-condition.json"
    assert not output.exists(), "An earlier observation must not be overwritten"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    prior_packets = set(evidence_root.glob("*.json"))
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "operation": "object.setProperty", "reads": [], "transactions": [], "native_evidence": [],
        "business_effect_verified": False, "stage": "standalone_setup"}
    category = {"category": "existing-time-modulator-range-condition", "status": "FAIL",
        "verifier_strength": "independent_existing_scalar_effect_loop_duration_peer_and_membership_readback",
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

    def objects(label, identity, fields=(), *, children=False):
        argv = ["query-object", "--exact-id", identity, "--max-results", "16" if children else "2", "--detail",
            "--include", "class-id", "--include", "notes", "--include", "parent", "--include", "owner"]
        if children:
            argv.extend(["--relationship", "children"])
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

    def context(suffix):
        return {"parent": objects("parent-" + suffix, PARENT),
            "members": objects("members-" + suffix, PARENT, children=True),
            "peer": objects("peer-" + suffix, PEER, ("EnvelopeAttackTime", "EnvelopeReleaseTime")),
            "peer_parent": objects("peer-parent-" + suffix, PEER_PARENT)}

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
        assert result["field"] == "EnvelopeStopPlayback" and result["kind"] == "property", result
        assert result["scope"] == {"kind": "object", "object": identity}, result
        assert result["enabled"] is True and result["mutation_authority"] is False, result

    try:
        host = read("host-and-current-platform-before", ["status"])
        project = host.get("project")
        assert isinstance(project, dict), host
        if "currentPlatformId" in project:
            platform = project["currentPlatformId"]
            assert isinstance(platform, str) and uuid.UUID(platform).int != 0, host
            enabled_platform = platform
        else:
            platform, enabled_platform = None, UNLINKED_PLATFORM
        observation.update(platform=platform, enabled_observation_platform=enabled_platform)
        before = context("before-setup")
        observation["before_setup"] = before
        assert before["parent"]["type"] == "WorkUnit" and before["parent"]["path"] == r"\Modulators\Default Work Unit", before
        original_members = members(before["members"])
        # Standalone placement is an owned setup witness, not an assumed native
        # success or a fallback into an RTPC graph if creation is rejected.
        setup = _start_business_draft(runtime, "object.create")
        parent = _bind_business_object(runtime, setup, object_id=PARENT)
        kind = _discover_business_type(runtime, setup, meaning="ModulatorTime", role="object", expected_label="ModulatorTime")
        discovered = _update_business_draft(runtime, setup, "draft-discover-fields",
            ["--type-handle", kind, "--meaning", "TimeModLoops"], live=True)
        loops_field = discovered_business_field_handle(discovered, "TimeModLoops")
        name = "WAAPI_Time_" + uuid.uuid4().hex[:12]
        _update_business_draft(runtime, setup, "draft-declare-new", ["--declaration-id", "time",
            "--parent-handle", parent, "--name", name, "--kind", kind, "--field-value", loops_field, "50"], live=False)

        def inspect_setup(preview):
            observation["setup_preview_before_authorization"] = preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_setup_preview_before_authorization"] = shown
            dispatch = shown["artifact"]["prepared_operation"]["dispatch"]
            assert dispatch["uri"] == "ak.wwise.core.object.create" and dispatch["options"] == {}, dispatch
            assert dispatch["args"] == {"parent": PARENT, "name": name, "type": "ModulatorTime",
                "@TimeModLoops": 50, "onNameConflict": "fail", "autoAddToSourceControl": False}, dispatch

        setup_receipt = _complete_business_draft(runtime, setup, inspect_preview=inspect_setup)
        observation["transactions"].append(setup_receipt)
        target_id = _created_object_id(setup_receipt["execute"])
        assert uuid.UUID(target_id).int != 0 and target_id not in {PARENT, PEER, PEER_PARENT}, target_id
        observation["target_id"] = target_id
        observation["stage"] = "existing_object_applicability"
        after_setup = context("after-setup")
        source = objects("time-before-edit", target_id, FIELDS)
        observation.update(after_setup=after_setup, source_before=source)
        assert source["type"] == "ModulatorTime" and source["class_id"] == 5111824, source
        assert source["name"] == name and source["path"] == before["parent"]["path"] + "\\" + name, source
        assert source["parent"]["id"] == PARENT, source
        assert type(source["properties"]["TimeModLoops"]) is int and source["properties"]["TimeModLoops"] == 50, source
        assert source["properties"]["EnvelopeStopPlayback"] is True, source
        for key in ("parent", "peer", "peer_parent"):
            same(after_setup[key], before[key])
        new_members = members(after_setup["members"])
        target_key = str(uuid.UUID(target_id))
        assert target_key not in original_members and len(new_members) == len(original_members) + 1, after_setup
        same(new_members, {**original_members, target_key: {key: value for key, value in source.items() if key != "properties"}})

        stop_selection, stop_info = metadata("stop-before", target_id, "EnvelopeStopPlayback")
        loops_selection, loops_info = metadata("loops-before", target_id, "TimeModLoops")
        observation["metadata_before"] = {"stop": stop_info, "loops": loops_info}
        assert stop_info["type"] == "bool", stop_info
        dependency, = stop_info["dependencies"]
        assert {key: dependency[key] for key in ("type", "action", "context", "property")} == {
            "type": "property", "action": "Enable", "context": "Self", "property": "TimeModLoops"}, dependency
        condition, = dependency["conditions"]
        assert condition["restriction"] == {"type": "range", "min": 1, "max": 100}, condition
        assert loops_info["type"] == "int32" and loops_info.get("dependencies", []) == [], loops_info
        assert loops_info["restriction"] == {"type": "range", "min": 0, "max": 100}, loops_info
        if platform is None:
            assert stop_info.get("supports", {}).get("unlink") is False, stop_info
            assert loops_info.get("supports", {}).get("unlink") is False, loops_info
        enabled("stop-enabled-before", target_id, stop_selection, enabled_platform)
        host_before_edit = read("host-and-current-platform-before-edit", ["status"])
        same({key: host_before_edit["project"][key] for key in ("currentPlatformId",) if key in host_before_edit["project"]},
            {key: project[key] for key in ("currentPlatformId",) if key in project})
        draft = _start_business_draft(runtime, "object.setProperty")
        target = _bind_business_object(runtime, draft, object_id=target_id)
        field = _discover_business_field(runtime, draft, object_handle=target, meaning="EnvelopeStopPlayback", platform=platform)
        _update_business_draft(runtime, draft, "draft-declare-field-change", ["--object-handle", target,
            "--field-handle", field, "--business-value", "false"], live=False)

        def inspect_edit(preview):
            observation["preview_before_authorization"] = preview
            assert not preview["preview_summary"].get("derived_changes"), preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_preview_before_authorization"] = shown
            prepared = shown["artifact"]["prepared_operation"]
            assert prepared["dispatch"]["uri"] == "ak.wwise.core.object.setProperty", prepared
            assert prepared["dispatch"]["args"] == {"object": target_id, "property": "EnvelopeStopPlayback", "value": False,
                **({"platform": platform} if platform is not None else {})}, prepared
            assert prepared["pre_state"]["field_before"]["activation_requirements"] == {"TimeModLoops": 50}, prepared

        observation["stage"] = "existing_object_edit"
        edit_receipt = _complete_business_draft(runtime, draft, inspect_preview=inspect_edit)
        observation["transactions"].append(edit_receipt)
        after = objects("time-after-edit", target_id, FIELDS)
        expected = deepcopy(source)
        expected["properties"]["EnvelopeStopPlayback"] = False
        same(after, expected)
        after_context = context("after-edit")
        observation.update(source_after=after, after=after_context)
        for key in ("parent", "peer", "peer_parent"):
            same(after_context[key], before[key])
        same(members(after_context["members"]), new_members)
        same(metadata("stop-after", target_id, "EnvelopeStopPlayback", stop_selection)[1], stop_info)
        same(metadata("loops-after", target_id, "TimeModLoops", loops_selection)[1], loops_info)
        enabled("stop-enabled-after", target_id, stop_selection, enabled_platform)
        host_after = read("host-and-current-platform-after", ["status"])
        same({key: host_after["project"][key] for key in ("currentPlatformId",) if key in host_after["project"]},
            {key: project[key] for key in ("currentPlatformId",) if key in project})
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
            observation["native_evidence"].append({"path": str(packet), "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest()})
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest())

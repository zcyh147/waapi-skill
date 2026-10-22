"""One existing Switch association edit through version-pinned Gateway phases."""
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


BUILDS = {
    "2021.1": (2021, 1, 14, 8108),
    "2022.1": (2022, 1, 19, 8584),
    "2023.1": (2023, 1, 19, 8928),
    "2024.1": (2024, 1, 13, 9056),
    "2025.1": (2025, 1, 7, 9143),
}


pytestmark = [
    pytest.mark.live,
    pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") not in BUILDS,
        reason="Requires one of the five pinned Wwise builds"),
]
CHILD = "{0CB83139-F17F-40DB-8221-48AA8A20B807}"
OWNER = "{8A261B8F-89AA-490E-A62A-2551D87F3E56}"
UNLINKED_PLATFORM = "{00000000-0000-0000-0000-000000000000}"


def test_existing_association_continue_play_preserves_owner_and_child(workflow_sandbox_runtime):
    _exercise_existing_association_continue_play(workflow_sandbox_runtime)


def _exercise_existing_association_continue_play(runtime, *, history_actions=()):
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    hierarchy = "Containers" if runtime.version == "2025.1" else "Actor-Mixer Hierarchy"
    owner_path = "\\" + hierarchy + r"\Minigun\Minigun\Shells"
    history = bool(history_actions)
    output = runtime.state_dir / ("association-continue-play-history.json" if history else "association-continue-play.json")
    assert not output.exists(), "An earlier observation must not be overwritten"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    prior_packets = set(evidence_root.glob("*.json"))
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "operation": "object.setProperty", "reads": [], "transactions": [],
        "native_evidence": [], "business_effect_verified": False}
    category = {"category": "structural-association-continue-play-owned-history" if history else "existing-association-continue-play", "status": "FAIL",
        "verifier_strength": ("receipt_bound_structural_history_and_independent_association_owner_child_membership_readback"
            if history else "independent_exact_association_owner_child_and_membership_readback"),
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

    def objects(label, identity, fields=(), *, children=False, context=False):
        argv = ["query-object", "--exact-id", identity, "--max-results", "16" if children else "2",
            "--detail", "--include", "class-id", "--include", "notes",
            "--include", "parent", "--include", "owner"]
        if children:
            argv.extend(["--relationship", "children"])
        if context:
            argv.extend(["--include", "switch-container-child-context"])
        for field in fields:
            argv.extend(["--include-field", field])
        payload = read(label, argv)
        rows = payload["agent_result"]
        assert isinstance(rows, list) and len(rows) < (16 if children else 2), payload
        if children:
            return rows
        assert len(rows) == 1 and rows[0]["id"] == identity, rows
        return rows[0]

    def selected_metadata(label, identity, name):
        page = None
        for index in range(8):
            inventory = read(label + "-names-" + str(index), ["metadata", "list", "--exact-id", identity,
                "--page-size", "64", *(["--page", page] if page else [])])["agent_result"]
            matches = [row for row in inventory["fields"] if row["name"] == name]
            if matches:
                selected, = matches
                selection = selected["selection"]
                detail = read(label + "-detail", ["metadata", "detail", "--exact-id", identity,
                    "--selection", selection])["agent_result"]
                assert detail.get("complete") is True and detail["metadata"]["name"] == name, detail
                return selection, detail["metadata"]
            assert inventory.get("complete") is not True, inventory
            next_page = inventory["next_page"]
            assert isinstance(next_page, str) and next_page != page
            page = next_page
        raise AssertionError("Selected field was not found within eight bounded metadata pages")

    def enabled(label, identity, selection, platform):
        result = read(label, ["metadata", "property-state", "--exact-id", identity,
            "--selection", selection, "--platform", platform])["agent_result"]
        assert result["field"] == "ContinuePlay" and result["kind"] == "property", result
        assert result["scope"] == {"kind": "object", "object": identity}, result
        assert result["enabled"] is True and result["mutation_authority"] is False, result
        return result

    def same(actual, expected):
        # Preserve JSON types as well as every observed field, including notes.
        assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), (actual, expected)

    try:
        host = read("host-and-current-platform", ["status"])
        project = host.get("project")
        assert isinstance(project, dict), host
        if "currentPlatformId" in project:
            platform = project["currentPlatformId"]
            assert isinstance(platform, str) and uuid.UUID(platform).int != 0, host
            enabled_platform = platform
            platform_mode = "observed_current_platform"
        else:
            platform = None
            enabled_platform = UNLINKED_PLATFORM
            platform_mode = "unlinked_enabled_observation_and_default_property_write"
        observation.update(platform=platform, enabled_observation_platform=enabled_platform, platform_mode=platform_mode)
        child = objects("child-before", CHILD, context=True)
        assert child["type"] == "RandomSequenceContainer" and child["name"] == "Shells_Concrete", child
        assert child["path"] == owner_path + r"\Shells_Concrete" and child["parent"]["id"] == OWNER, child
        association = child["switch_container_child_context"]["id"]
        assert isinstance(association, str) and uuid.UUID(association).int != 0, child
        source = objects("association-before", association, ("ContinuePlay", "FadeInTime"))
        owner = objects("owner-before", OWNER, ("SwitchBehavior",))
        members = objects("owner-children-before", OWNER, children=True, context=True)
        assert all(isinstance(source.get(key), str) for key in ("id", "name", "path")), source
        assert source["path"] and source["name"] == "" and source["class_id"] == 1572880, source
        needs_context_binding = "type" not in source
        if history:
            assert runtime.version in {"2022.1", "2023.1"}
            assert needs_context_binding is (runtime.version == "2022.1"), source
        if needs_context_binding:
            # The ordinary query remains an incomplete identity. Only the
            # separate owner/child binding below can authorize a field target.
            assert source["identity_completeness"] == {
                "complete": False, "unavailable_fields": ["type"], "mutation_authority": False}, source
        else:
            assert source["type"] == "ObjectSettingAssociation", source
            assert source.get("identity_completeness", {}).get("complete") is not False, source
        # Keep native omission distinct from explicit null in the saved snapshot.
        if "parent" in source:
            assert source["parent"] is None, source
        else:
            assert "parent" in source["unavailable_fields"], source
        assert source["owner"]["id"] == OWNER, source
        if runtime.version == "2025.1":
            assert source["path"] == owner_path + r"\<Unnamed Object Setting Association>", source
        assert source["properties"]["ContinuePlay"] is False and source["properties"]["FadeInTime"] == 0.0, source
        assert owner["type"] == "SwitchContainer" and owner["name"] == "Shells" and owner["path"] == owner_path, owner
        assert type(owner["properties"]["SwitchBehavior"]) is int and owner["properties"]["SwitchBehavior"] == 1, owner
        member, = [row for row in members if row["id"] == CHILD]
        same(member, child)
        observation["before"] = {"association": source, "owner": owner, "child": child, "children": members}

        selection, source_metadata = selected_metadata("association", association, "ContinuePlay")
        _, owner_metadata = selected_metadata("owner", OWNER, "SwitchBehavior")
        observation["metadata"] = {"association": source_metadata, "owner": owner_metadata}
        assert source_metadata["type"] == "bool" and source_metadata["default"] is False, source_metadata
        dependency, = source_metadata["dependencies"]
        assert {key: dependency[key] for key in ("type", "action", "context", "property")} == {
            "type": "property", "action": "Enable", "context": "AssocParent", "property": "SwitchBehavior"}, dependency
        condition, = dependency["conditions"]
        assert condition["restriction"]["type"] == "enum", condition
        choice, = condition["restriction"]["values"]
        assert type(choice["value"]) is int and choice["value"] == 1, choice
        assert owner_metadata["type"] == "int16" and owner_metadata.get("dependencies", []) == [], owner_metadata
        assert owner_metadata["restriction"]["type"] == "enum", owner_metadata
        choices = owner_metadata["restriction"]["values"]
        assert all(type(row["value"]) is int for row in choices) and {row["value"] for row in choices} == {0, 1}, choices
        if platform is None:
            # The default write is admitted only for these observed fields
            # without per-platform unlink support; no current platform is guessed.
            assert source_metadata.get("supports", {}).get("unlink") is False, source_metadata
            assert owner_metadata.get("supports", {}).get("unlink") is False, owner_metadata
        enabled("association-enabled-before", association, selection, enabled_platform)

        draft = _start_business_draft(runtime, "object.setProperty")
        if needs_context_binding or history:
            owner_handle = _bind_business_object(runtime, draft, object_id=OWNER)
            child_handle = _bind_business_object(runtime, draft, object_id=CHILD)
            binding = _update_business_draft(runtime, draft, "draft-bind-switch-child-context",
                ["--owner-handle", owner_handle, "--child-handle", child_handle], live=True)
            observation["context_binding"] = binding
            context = binding["bound_context"]
            assert context["context_id"] == association and context["business_role"] == "switch_child_context", context
            assert context["native_identity"]["id"] == association, context
            assert ("type" not in context["native_identity"]) is needs_context_binding, context
            if not needs_context_binding:
                assert context["native_identity"]["type"] == source["type"], context
            bound = context["handle"]
            assert isinstance(bound, str) and bound, context
        else:
            bound = _bind_business_object(runtime, draft, object_id=association)
        field = _discover_business_field(runtime, draft, object_handle=bound, meaning="ContinuePlay", platform=platform)
        _update_business_draft(runtime, draft, "draft-declare-field-change",
            ["--object-handle", bound, "--field-handle", field, "--business-value", "true"], live=False)

        def inspect_preview(preview):
            observation["preview_before_authorization"] = preview
            assert not preview["preview_summary"].get("derived_changes"), preview
            shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
            observation["immutable_preview_before_authorization"] = shown
            prepared = shown["artifact"]["prepared_operation"]
            dispatch = prepared["dispatch"]
            assert dispatch["uri"] == "ak.wwise.core.object.setProperty", dispatch
            assert dispatch["args"] == {"object": association, "property": "ContinuePlay", "value": True,
                **({"platform": platform} if platform is not None else {})}, dispatch
            if history:
                proof = prepared["pre_state"]["switch_child_context"]
                assert proof["context_id"] == association and proof["owner_id"] == OWNER and proof["child_id"] == CHILD, proof
                assert ("type" not in proof["rows"]["context"]) is needs_context_binding, proof
                assert prepared["request"]["arguments"]["switch_child_context"] == proof, prepared
                observation["structural_history_source_proof"] = proof
            related, = prepared["pre_state"]["related_conditions"]
            assert related["source_id"] == association and related["owner_id"] == OWNER, related
            assert related["property"] == "SwitchBehavior" and type(related["value"]) is int and related["value"] == 1, related

        receipt = _complete_business_draft(runtime, draft, inspect_preview=inspect_preview)
        observation["transactions"].append(receipt)
        after = objects("association-after", association, ("ContinuePlay", "FadeInTime"))
        same(after, {**source, "properties": {**source["properties"], "ContinuePlay": True}})
        same(objects("owner-after", OWNER, ("SwitchBehavior",)), owner)
        same(objects("child-after", CHILD, context=True), child)
        same(objects("owner-children-after", OWNER, children=True, context=True), members)
        enabled("association-enabled-after", association, selection, enabled_platform)
        assert len(observation["transactions"]) == 1
        if history:
            source_read_count = len(observation["reads"])
            observation["source_observation_read_count"] = source_read_count
            source_receipt = receipt["preview"]["transaction_id"]
            for direction in history_actions:
                history_draft = _start_business_draft(runtime, "ak.wwise.core.undo." + direction)
                _update_business_draft(runtime, history_draft, "draft-declare-core-plan",
                    ["--value", "history_scope", "latest_project_history",
                     "--value", "expectation_receipt", source_receipt], live=True)

                def inspect_history_preview(preview):
                    observation.setdefault("history_previews", {})[direction] = preview
                    action = preview["preview_summary"]["history_action"]
                    assert action["scope"] == "latest_project_history" and action["action"] == direction, action
                    assert action["expectation_receipt"] == source_receipt, action
                    assert action["verification_boundary"] == "owned_receipt_scoped_state_only", action
                    assert action["stack_head_observed"] is False and action["outside_scope_preservation_observed"] is False, action
                    assert action["automatic_retry"] is False and action["automatic_compensation"] is False, action
                    # History detail may be paged out of the compact notice.
                    # Inspect the immutable preparation through the same full
                    # transaction-show read already used for the source Preview.
                    shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
                    observation.setdefault("immutable_history_previews", {})[direction] = shown
                    prepared = shown["artifact"]["prepared_operation"]
                    binding = prepared["pre_state"]["history_binding"]
                    assert binding["source_receipt"]["transaction_id"] == source_receipt, binding
                    assert prepared["verification_plan"]["history_binding"] == binding, prepared
                    expected, = binding["observations"]
                    assert expected["kind"] == "switch_child_property" and expected["field"] == "ContinuePlay", expected
                    assert expected["before"] is False and expected["after"] is True, expected
                    same(expected["guards"]["switch_child_context"], observation["structural_history_source_proof"])
                    assert ("type" not in expected["object_before"]) is needs_context_binding, expected
                    assert ("type" not in expected["object_after"]) is needs_context_binding, expected

                phase = _complete_business_draft(runtime, history_draft, inspect_preview=inspect_history_preview)
                observation["transactions"].append(phase)
                assert phase["verify"]["verification_strength"] == "scoped_history_effect_readback", phase
                expected_source = source if direction == "undo" else after
                same(objects("association-after-" + direction, association, ("ContinuePlay", "FadeInTime")), expected_source)
                same(objects("owner-after-" + direction, OWNER, ("SwitchBehavior",)), owner)
                same(objects("child-after-" + direction, CHILD, context=True), child)
                same(objects("owner-children-after-" + direction, OWNER, children=True, context=True), members)
                enabled("association-enabled-after-" + direction, association, selection, enabled_platform)
            assert len(observation["transactions"]) == 1 + len(history_actions)
            assert len(observation["reads"]) == source_read_count + 5 * len(history_actions)
            observation["history_observation_read_count"] = 5 * len(history_actions)
            observation["history_scope"] = "owned receipt and observed objects only; global stack head and other state are not proven"
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

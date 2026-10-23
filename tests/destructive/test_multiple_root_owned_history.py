"""One real native collision graph with separate receipt-bound undo and redo."""
import hashlib
import json
import os
from pathlib import Path
import uuid

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _BusinessDraft,
    _bind_business_object,
    _complete_business_draft,
    _discover_business_type,
    _start_business_draft,
    _update_business_draft,
    declared_business_object_handle,
    discovered_business_field_handle,
    workflow_sandbox_runtime,
)


pytestmark = [
    pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") != "2025.1",
        reason="One pinned 2025 multiple-root source/history witness; other versions remain separate"),
]
OWNER = "{ED2BCAC8-D7B6-4448-8900-439B557894F4}"
ANCESTOR = "{8CF94195-E210-4967-89DB-CA103B48A267}"
GUNS = "{06362E8D-5A32-497A-B063-3DA95963CE47}"
CARS = "{33329D23-BCDD-4D1A-9734-2403A3428FAE}"
WINDOWS = "{6E0CB257-C6C8-4C5C-8366-2740DFC441EC}"
OWNER_PATH = r"\Busses\Default Work Unit\Main Audio Bus\Environmental\SFX"
GET = "ak.wwise.core.object.get"
SET = "ak.wwise.core.object.set"
IDENTITY_FIELDS = ["id", "name", "type", "path", "parent", "classId", "notes"]


def test_multiple_colliding_roots_reference_owned_history(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    build = runtime.sandbox.metadata.get_info_version
    assert runtime.version == "2025.1"
    assert tuple(build.get(key) for key in ("year", "major", "minor", "build")) == (2025, 1, 7, 9143)
    output = runtime.state_dir / "multiple-root-owned-history.json"
    assert not output.exists(), "Never overwrite an earlier native observation"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    prior_packets = set(evidence_root.glob("*.json"))
    endpoint = {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}
    observation = {"candidate": runtime.candidate, "version": runtime.version, "endpoint": endpoint,
        "calls": [], "reads": [], "transactions": [], "native_evidence": [], "setup_transaction_count": 0,
        "complete": False, "business_effect_verified": False, "stack_head_observed": False,
        "outside_scope_preservation_observed": False,
        "lifecycle_acceptance": "Requires final host-category-evidence/v3 PASS; this receipt alone grants no cleanup/source-integrity credit"}
    category = {"category": "multiple-native-collision-roots-owned-history", "status": "FAIL",
        "observation_path": str(output), "verifier_strength": "actual_separate_stages_and_independent_graph_reference_preservation_history"}
    runtime.category_results.append(category)

    def retain():
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 16 * 1024 * 1024, "Multiple-root observation byte bound exceeded"
        temporary = output.with_suffix(".tmp")
        temporary.write_bytes(body)
        temporary.replace(output)

    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(observation["calls"]) < 128, "Multiple-root public command bound exceeded"
            record = {"argv": list(argv)}
            observation["calls"].append(record)
            try:
                code, payload = runtime.raw_gateway(argv)
                record.update(exit_code=code, payload=payload)
                return code, payload
            except Exception as exc:
                record["exception"] = {"type": type(exc).__name__, "message": str(exc)}
                raise
            finally:
                retain()

        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get("ok") is True, payload
            if live:
                assert payload.get("endpoint") == endpoint and payload.get("detected_version") == runtime.version, payload
            return payload

    gateway = ReceiptGateway()

    def read(label, argv):
        assert len(observation["reads"]) < 20
        observation["reads"].append({"label": label, "call_index": len(observation["calls"])})
        return gateway.gateway(argv, live=True)

    def objects(label, identity, *, descendants=False, reference=False, preservation=True):
        argv = ["query-object", "--exact-id", identity, "--max-results", "9" if descendants else "2", "--detail"]
        if preservation:
            argv.extend(["--include", "class-id", "--include", "parent", "--include", "notes"])
        if descendants:
            argv.extend(["--relationship", "descendants"])
        if reference:
            argv.extend(["--include-field", "UserAuxSend0", "--platform", WINDOWS])
        payload = read(label, argv)
        assert payload.get("status") != "partial" and payload.get("projection_complete") is not False, payload
        assert payload.get("limit_reached") is not True and list(payload)[-1] == "agent_result", payload
        rows = payload["agent_result"]
        assert isinstance(rows, list) and payload.get("count") == len(rows), payload
        assert len(rows) < (9 if descendants else 2), rows
        assert len({row["id"].upper() for row in rows}) == len(rows), rows
        for row in rows:
            assert uuid.UUID(row["id"]).int != 0, row
            if preservation:
                assert type(row["class_id"]) is int and isinstance(row["notes"], str), row
        return {row["id"].upper(): row for row in rows}

    def exact(label, identity, *, reference=False, preservation=True):
        rows = objects(label, identity, reference=reference, preservation=preservation)
        assert set(rows) == {identity.upper()}, rows
        return rows[identity.upper()]

    def preserved(label):
        return {"ancestor": exact(label + "-ancestor", ANCESTOR), "owner": exact(label + "-owner", OWNER),
            "descendants": objects(label + "-descendants", OWNER, descendants=True)}

    def complete(draft, role, inspect):
        phase = {"role": role}
        observation["transactions"].append(phase)
        def preview(preview_payload):
            phase["before_authorization"] = gateway.gateway(["transaction-show", preview_payload["transaction_id"]], live=False)
            inspect(preview_payload, phase["before_authorization"])
        phase.update(_complete_business_draft(gateway, draft, inspect_preview=preview))
        assert phase["execute"]["automatic_retry"] is False and phase["verify"]["verified"] is True, phase
        phase["after_verification"] = gateway.gateway(["transaction-show", phase["preview"]["transaction_id"]], live=False)
        assert phase["after_verification"]["artifact"] == phase["before_authorization"]["artifact"], phase
        return phase

    try:
        host = read("host", ["status"])
        assert host["wwise"]["isCommandLine"] is True, host
        platform = exact("explicit-platform", WINDOWS, preservation=False)
        assert platform["type"] == "Platform" and platform["name"] == "Windows", platform
        before = observation["before"] = preserved("before")
        assert before["owner"]["type"] == before["ancestor"]["type"] == "Bus"
        assert before["owner"]["class_id"] == before["ancestor"]["class_id"] == 1376272
        assert before["owner"]["path"] == OWNER_PATH and before["owner"]["parent"]["id"] == ANCESTOR, before
        assert set(before["descendants"]) == {GUNS, CARS}, before
        for identity, name in ((GUNS, "Guns"), (CARS, "Cars")):
            row = before["descendants"][identity]
            assert row["type"] == "Bus" and row["class_id"] == 1376272 and row["name"] == name, row
            assert row["path"] == OWNER_PATH + "\\" + name and row["parent"]["id"] == OWNER, row

        parent = _start_business_draft(gateway, "waapi.undoGroup")
        child_start = _update_business_draft(gateway, parent, "draft-start-undo-child", ["--operation", "object.set"], live=False)
        child = _BusinessDraft(child_start["draft"]["draft_id"], child_start["task_authority"], int(child_start["draft"]["revision"]))
        owner = _bind_business_object(gateway, child, object_id=OWNER)
        _update_business_draft(gateway, child, "draft-business-configure", ["--name-conflict", "rename", "--platform", WINDOWS], live=False)
        types = {name: _discover_business_type(gateway, child, meaning=name, role="object", expected_label=name) for name in ("Bus", "AuxBus")}
        page, pages, selected = None, set(), None
        for _ in range(4):
            listing = _update_business_draft(gateway, child, "draft-discover-fields",
                ["--type-handle", types["AuxBus"], "--list", "--page-size", "64", *(["--page", page] if page else [])], live=True)["agent_result"]
            matches = [row for row in listing["fields"] if row["name"] == "UserAuxSend0"]
            assert len(matches) <= 1, listing
            if matches:
                selected = matches[0]
                break
            assert listing.get("complete") is not True, listing
            page = listing["next_page"]
            assert isinstance(page, str) and page not in pages, listing
            pages.add(page)
        assert selected is not None, "UserAuxSend0 not disclosed within four pages"
        discovered = _update_business_draft(gateway, child, "draft-discover-fields",
            ["--type-handle", types["AuxBus"], "--selection", selected["selection"]], live=True)
        field = discovered_business_field_handle(discovered, "UserAuxSend0")
        candidates = [row for result in discovered["meaning_results"] for row in result["candidates"] if row["handle"] == field]
        candidate, = candidates
        metadata = observation["live_field"] = candidate["metadata"]
        assert candidate["field_kind"] == "reference" and metadata["restriction"]["type"] == "reference", candidate
        assert metadata["type"] == "" and metadata["default"] is None and metadata["supports"]["unlink"] is False, metadata
        assert candidate["restrictions"]["allowed_target_types"] == ["Auxiliary Bus"], candidate
        dependencies = [{"type": "isMasterBus", "value": False, "action": "Show", "context": "Self"},
            {"type": "override", "action": "Enable", "property": "OverrideUserAuxSends", "context": "Self"}]
        assert sorted(metadata["dependencies"], key=lambda row: row["type"]) == sorted(dependencies, key=lambda row: row["type"]), metadata
        handles = {}
        for declaration, name, parent_handle, kind in (("guns", "Guns", owner, types["Bus"]),
                ("destination", "Destination", "guns", types["AuxBus"]), ("cars", "Cars", owner, types["Bus"]),
                ("sender", "Sender", "cars", types["AuxBus"])):
            declared = _update_business_draft(gateway, child, "draft-declare-new", ["--declaration-id", declaration,
                "--parent-handle", handles.get(parent_handle, parent_handle), "--kind", kind, "--name", name,
                *(["--field-value", field, handles["destination"]] if declaration == "sender" else [])], live=False)
            handles[declaration] = declared_business_object_handle(declared, declaration)
        _update_business_draft(gateway, child, "draft-check", live=True)
        _update_business_draft(gateway, parent, "draft-declare-undo-plan", ["--display-name", "Two native collision roots and owned reference",
            "--child-draft", child.draft_id, child.task_authority], live=False)

        def inspect_source(preview, shown):
            calls = shown["artifact"]["prepared_operation"]["pre_state"]["execution_plan"]["calls"]
            assert len(calls) == 1, calls
            prepared = observation["source_prepared"] = calls[0]["prepared_operation"]
            specs = prepared["verification_plan"]["nodes"]
            names = {node["requested_name"]: node for node in specs if node.get("existing_target") is False}
            assert set(names) == {"Guns", "Cars", "Destination", "Sender"}, names
            assert all(names[name]["class_id"] == (1376272 if name in {"Guns", "Cars"} else 3997712) for name in names)
            plan = prepared["pre_state"]["owned_result_stages"]
            assert [next(node["requested_name"] for node in specs if node["request_path"] == stage["root"]) for stage in plan["creation_stages"]] == ["Guns", "Cars"]
            assert prepared["semantic_preview"]["envelope"]["metadata"]["result_reference_execution"]["stage_count"] == 3
            assert prepared["pre_state"]["field_read_platform"]["platform_id"] == WINDOWS
            evidence, = names["Sender"]["new_object_default_evidence"]
            assert evidence["derived_properties"] == {}, evidence
            applicability, = evidence["override_applicability"]
            assert applicability["kind"] == "not_applicable_on_class" and applicability["class_id"] == 3997712, evidence
            assert applicability["field"] == "UserAuxSend0" and applicability["structural_proof"]["parent"]["type"] == "Bus", evidence
            assert evidence["structural_visibility"][0]["dependency"] == dependencies[0], evidence

        source = complete(parent, "source", inspect_source)
        source_id = source["preview"]["transaction_id"]
        execution = next(event["details"]["dispatch_result"] for event in source["after_verification"]["events"] if event["event_type"] == "execution_completed")
        assert [row["uri"] for row in execution["result"]["phases"]] == ["ak.wwise.core.undo.beginGroup", SET, "ak.wwise.core.undo.endGroup"]
        assert all(row["dispatch_result"]["ok"] is True for row in execution["result"]["phases"])
        phase, = [row["dispatch_result"] for row in execution["result"]["phases"] if "owned_result_execution" in row["dispatch_result"]]
        proof = observation["actual_stage_proof"] = phase["owned_result_execution"]
        prepared = observation["source_prepared"]
        specs = {node["requested_name"]: node for node in prepared["verification_plan"]["nodes"] if not node.get("existing_target")}
        created = {name: proof["identities"][spec["request_path"]] for name, spec in specs.items()}
        ids = {name: row["id"].upper() for name, row in created.items()}
        assert len(set(ids.values())) == 4 and not set(ids.values()) & {OWNER, ANCESTOR, GUNS, CARS}
        stages = proof["stages"]
        assert len(stages) == 3 and phase["result"] == stages[0]["dispatch_result"]["result"]
        for stage, name in zip(stages[:2], ("Guns", "Cars"), strict=True):
            assert stage["uri"] == SET and stage["dispatch_result"]["ok"] is True, stage
            native_parent, = stage["args"]["objects"]
            assert native_parent["object"] == OWNER and "name" not in native_parent
            native_child, = native_parent["children"]
            assert native_child["name"] == name and stage["args"]["onNameConflict"] == "rename", stage
            result_parent, = stage["dispatch_result"]["result"]["objects"]
            result_child, = result_parent["children"]
            assert result_parent["id"] == OWNER and result_child["id"].upper() == ids[name], stage
            assert result_child["name"] == created[name]["name"] and created[name]["name"].casefold() != name.casefold(), stage
        receiver, = stages[2]["args"]["objects"]
        assert stages[2]["uri"] == SET and receiver["object"].upper() == ids["Sender"] and "name" not in receiver
        assert stages[2]["dispatch_result"]["ok"] is True
        assert receiver["@UserAuxSend0"] == created["Destination"]["path"], receiver
        cumulative = proof["creation_bindings"][1]["readbacks"]
        for row in created.values():
            assert any(record["uri"] == GET and record["args"] == {"from": {"id": [row["id"]]}}
                and record["options"] == {"return": IDENTITY_FIELDS} for record in cumulative), row
            assert any(record["uri"] == GET and record["args"] == {"from": {"id": [row["id"]]}, "transform": [{"select": ["children"]}]}
                and record["options"] == {"return": ["id"]} for record in cumulative), row

        def after_state(label):
            state = preserved(label)
            assert state["ancestor"] == before["ancestor"] and state["owner"] == before["owner"], state
            for identity in (GUNS, CARS):
                assert state["descendants"][identity] == before["descendants"][identity], state
            assert set(state["descendants"]) == {GUNS, CARS, *ids.values()}, state
            for name, identity in ids.items():
                row, bound = state["descendants"][identity], created[name]
                assert all(row[key] == bound[key] for key in ("id", "name", "type", "path", "notes")), (row, bound)
                assert row["class_id"] == bound["classId"] and row["parent"]["id"] == bound["parent"]["id"], (row, bound)
                assert (row["type"], row["class_id"]) == (("Bus", 1376272) if name in {"Guns", "Cars"} else ("AuxBus", 3997712)), row
            for name, parent_name in (("Destination", "Guns"), ("Sender", "Cars")):
                row = state["descendants"][ids[name]]
                assert row["parent"]["id"].upper() == ids[parent_name] and row["path"] == created[parent_name]["path"] + "\\" + name, row
            for name in ("Guns", "Cars"):
                assert state["descendants"][ids[name]]["parent"]["id"] == OWNER
            state["sender"] = exact(label + "-sender-reference", ids["Sender"], reference=True)
            target = state["sender"]["references"]["UserAuxSend0"]
            assert isinstance(target, dict) and target["id"].upper() == ids["Destination"], state
            return state

        after = observation["source_state"] = after_state("source")
        for direction in ("undo", "redo"):
            history = _start_business_draft(gateway, "ak.wwise.core.undo." + direction)
            _update_business_draft(gateway, history, "draft-declare-core-plan", ["--value", "history_scope", "latest_project_history",
                "--value", "expectation_receipt", source_id], live=True)
            def inspect_history(preview, shown):
                action = preview["preview_summary"]["history_action"]
                assert action["action"] == direction and action["expectation_receipt"] == source_id
                assert action["verification_boundary"] == "owned_receipt_scoped_state_only"
                assert action["stack_head_observed"] is False and action["outside_scope_preservation_observed"] is False
                assert action["automatic_retry"] is False and action["automatic_compensation"] is False
                prepared_history = shown["artifact"]["prepared_operation"]
                binding = prepared_history["pre_state"]["history_binding"]
                assert binding == prepared_history["verification_plan"]["history_binding"]
                assert binding["source_receipt"]["transaction_id"] == source_id
                presence = [row for row in binding["observations"] if row.get("kind") == "creation_presence"]
                assert {row["object"]["id"].upper() for row in presence} == set(ids.values())
                reference, = [row for row in binding["observations"] if row.get("kind") == "creation_field"]
                assert reference["field"] == "UserAuxSend0" and reference["object_id"].upper() == ids["Sender"]
                assert reference["value"].upper() == reference["internal_reference_target_id"].upper() == ids["Destination"]
                assert reference["field_info"]["raw"]["restriction"]["type"] == "reference", reference
                assert reference["field_kind"] == "reference" and reference["metadata_type"] == "", reference
                retained = {row["object_before"]["id"].upper(): row for row in binding["observations"] if "object_before" in row}
                assert set(retained) == {OWNER, GUNS, CARS}, retained
                for identity in retained:
                    expected = before["owner"] if identity == OWNER else before["descendants"][identity]
                    row = retained[identity]
                    assert row["object_before"] == row["object_after"]
                    assert all(row["object_before"][key] == expected[key] for key in ("id", "name", "type", "path")), row
                    assert row["before"] == row["after"] == expected["notes"] and row["class_id"] == expected["class_id"], row
                    assert row["parent_id"] == expected["parent"]["id"], row
                    assert row["preserved_children_before"] == (sorted([GUNS, CARS]) if identity == OWNER else []), row
                    assert row["preserved_children_after"] == (sorted([GUNS, CARS, ids["Guns"], ids["Cars"]]) if identity == OWNER else []), row
            result = complete(history, direction, inspect_history)
            assert result["verify"]["verification_strength"] == "scoped_history_effect_readback", result
            if direction == "undo":
                state = observation["undo_state"] = preserved("undo")
                assert state == before, state
                for name, identity in ids.items():
                    assert objects("undo-absent-" + name, identity) == {}, identity
            else:
                observation["redo_state"] = after_state("redo")
                assert observation["redo_state"] == after
        assert len(observation["reads"]) == 20 and len(observation["transactions"]) == 3
        observation.update(complete=True, business_effect_verified=True)
        category["status"] = "PASS"
    except BaseException as exc:
        observation["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        try:
            packets = sorted(set(evidence_root.glob("*.json")) - prior_packets)
            assert len(packets) <= 512, "Native evidence packet bound exceeded"
            total = 0
            for packet in packets:
                body = packet.read_bytes()
                total += len(body)
                assert total <= 32 * 1024 * 1024, "Native evidence byte bound exceeded"
                observation["native_evidence"].append({"path": str(packet), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        except BaseException as exc:
            observation.update(complete=False, business_effect_verified=False,
                collection_failure={"type": type(exc).__name__, "message": str(exc)})
            category["status"] = "FAIL"
            raise
        finally:
            try:
                retain()
                category.update(observation_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                    business_effect_verified=observation["complete"] and observation["business_effect_verified"])
            except BaseException:
                category.update(status="FAIL", business_effect_verified=False)
                category.pop("observation_sha256", None)
                raise

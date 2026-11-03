"""One pinned 2021 CREATE duplicate graph, with no history capability assumed."""
import hashlib
import json
import os
from pathlib import Path
import uuid

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object, _complete_business_draft, _discover_business_type,
    _start_business_draft, _update_business_draft, declared_business_object_handle,
    discovered_business_field_handle, workflow_sandbox_runtime,
)

pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") != "2021.1",
        reason="One matching 2021 CREATE staging witness; history is pinned absent")]
OWNER = "{ED2BCAC8-D7B6-4448-8900-439B557894F4}"
ANCESTOR = "{8CF94195-E210-4967-89DB-CA103B48A267}"
MASTER = "{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}"
GUNS = "{06362E8D-5A32-497A-B063-3DA95963CE47}"
CARS = "{33329D23-BCDD-4D1A-9734-2403A3428FAE}"
WINDOWS = "{6E0CB257-C6C8-4C5C-8366-2740DFC441EC}"
OWNER_PATH = r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus\Environmental\SFX"
CREATE = "ak.wwise.core.object.create"
REFERENCE = "ak.wwise.core.object.setReference"
GET = "ak.wwise.core.object.get"
FIELDS = ["id", "name", "type", "path", "parent", "classId", "notes"]
ROLES = ("routing", "destination", "sender")
DEPENDENCY = {"type": "override", "action": "Enable", "property": "OverrideUserAuxSends", "context": "Self"}


def _assert_actual_create_calls(proof, created):
    """Compare each sole native root and addressed parent to the owned roster."""
    ids = {role: row["id"].upper() for role, row in created.items()}
    assert set(ids) == set(ROLES) and len(set(ids.values())) == 3
    assert not set(ids.values()) & {OWNER, ANCESTOR, MASTER, GUNS, CARS}
    stages = proof["stages"]
    assert len(stages) == 4
    for stage, role in zip(stages[:3], ROLES, strict=True):
        assert stage["uri"] == CREATE and stage["dispatch_result"]["ok"] is True, stage
        args, result = stage["args"], stage["dispatch_result"]["result"]
        assert set(args) == {"parent", "type", "name", "onNameConflict", "autoAddToSourceControl", "platform"}, args
        assert args["parent"].upper() == (OWNER if role == "routing" else ids["routing"]), args
        assert args["name"] == ("Routing" if role == "routing" else "Send"), args
        assert args["type"] == ("Bus" if role == "routing" else "AuxBus"), args
        assert args["onNameConflict"] == "rename" and args["platform"] == WINDOWS, args
        assert args["autoAddToSourceControl"] is False, args
        assert result["id"].upper() == ids[role] and result["name"] == created[role]["name"], result
        assert result.get("children", []) == [], result
    reference = stages[-1]
    assert reference["uri"] == REFERENCE and reference["dispatch_result"]["ok"] is True, reference
    assert reference["args"] == {"object": created["sender"]["id"], "reference": "UserAuxSend0",
        "value": created["destination"]["id"], "platform": WINDOWS}, reference
    assert created["destination"]["name"].casefold() != created["sender"]["name"].casefold()


def test_create_duplicate_siblings_bind_actual_guid_reference_2021(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    assert runtime.version == "2021.1"
    build = runtime.sandbox.metadata.get_info_version
    assert tuple(build.get(key) for key in ("year", "major", "minor", "build")) == (2021, 1, 14, 8108)
    output = runtime.state_dir / "create-duplicate-2021.json"
    assert not output.exists(), "Never overwrite an earlier native observation"
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    previous = set(evidence_root.glob("*.json"))
    endpoint = {"host": runtime.lifecycle.host, "port": runtime.port, "url": runtime.lifecycle.waapi_url}
    observation = {"candidate": runtime.candidate, "version": runtime.version, "endpoint": endpoint,
        "calls": [], "reads": [], "transactions": [], "native_evidence": [], "setup_transaction_count": 0,
        "complete": False, "business_effect_verified": False, "history_executed": False,
        "lifecycle_acceptance": "Requires final host-category-evidence/v3 source/cleanup PASS"}
    category = {"category": "create-duplicate-siblings-2021", "status": "FAIL", "observation_path": str(output),
        "verifier_strength": "actual_create_stages_and_independent_graph_guid_reference_preservation"}
    runtime.category_results.append(category)

    def retain():
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 16 * 1024 * 1024, "CREATE observation byte bound exceeded"
        temporary = output.with_suffix(".tmp")
        temporary.write_bytes(body)
        temporary.replace(output)

    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(observation["calls"]) < 128, "CREATE public command bound exceeded"
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
                assert payload.get("endpoint") == endpoint and payload.get("detected_version") == "2021.1", payload
            return payload

    gateway = ReceiptGateway()

    def objects(label, identity, *, descendants=False, reference=False, platform=False):
        assert len(observation["reads"]) < 9
        observation["reads"].append({"label": label, "call_index": len(observation["calls"])})
        argv = ["query-object", "--exact-id", identity, "--max-results", "9" if descendants else "2", "--detail"]
        if not platform:
            argv.extend(["--include", "class-id", "--include", "parent", "--include", "notes"])
        if descendants:
            argv.extend(["--relationship", "descendants"])
        if reference:
            argv.extend(["--include-field", "UserAuxSend0", "--platform", WINDOWS])
        payload = gateway.gateway(argv, live=True)
        assert payload.get("status") != "partial" and payload.get("projection_complete") is not False, payload
        assert payload.get("limit_reached") is not True and list(payload)[-1] == "agent_result", payload
        rows = payload["agent_result"]
        assert isinstance(rows, list) and payload.get("count") == len(rows) and len(rows) < (9 if descendants else 2), payload
        assert len({row["id"].upper() for row in rows}) == len(rows), rows
        for row in rows:
            assert uuid.UUID(row["id"]).int != 0, row
            if not platform:
                assert type(row["class_id"]) is int and isinstance(row["notes"], str), row
        if not descendants:
            assert len(rows) == 1 and rows[0]["id"].upper() == identity.upper(), rows
        return {row["id"].upper(): row for row in rows}

    def preserved(label):
        return {"ancestor": objects(label + "-ancestor", ANCESTOR)[ANCESTOR],
            "owner": objects(label + "-owner", OWNER)[OWNER],
            "descendants": objects(label + "-descendants", OWNER, descendants=True)}

    try:
        observation["reads"].append({"label": "host", "call_index": 0})
        host = gateway.gateway(["status"], live=True)
        assert host["wwise"]["isCommandLine"] is True, host
        platform = objects("platform", WINDOWS, platform=True)[WINDOWS]
        assert platform["type"] == "Platform" and platform["name"] == "Windows", platform
        before = observation["before"] = preserved("before")
        assert before["owner"]["path"] == OWNER_PATH and before["owner"]["parent"]["id"] == ANCESTOR, before
        assert before["ancestor"]["path"] == OWNER_PATH.rsplit("\\", 1)[0] and before["ancestor"]["parent"]["id"] == MASTER, before
        assert all(before[role]["type"] == "Bus" and before[role]["class_id"] == 1376272 for role in ("owner", "ancestor")), before
        assert set(before["descendants"]) == {GUNS, CARS}, before
        for identity, name in ((GUNS, "Guns"), (CARS, "Cars")):
            row = before["descendants"][identity]
            assert row["name"] == name and row["type"] == "Bus" and row["class_id"] == 1376272, row
            assert row["parent"]["id"] == OWNER and row["path"] == OWNER_PATH + "\\" + name, row
        draft = _start_business_draft(gateway, "object.create")
        owner = _bind_business_object(gateway, draft, object_id=OWNER)
        _update_business_draft(gateway, draft, "draft-business-configure", ["--name-conflict", "rename", "--platform", WINDOWS], live=False)
        types = {name: _discover_business_type(gateway, draft, meaning=name, role="object", expected_label=name) for name in ("Bus", "AuxBus")}
        page, pages, selected = None, set(), None
        for _ in range(4):
            listing = _update_business_draft(gateway, draft, "draft-discover-fields", ["--type-handle", types["AuxBus"],
                "--list", "--page-size", "64", *(["--page", page] if page else [])], live=True)["agent_result"]
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
        discovered = _update_business_draft(gateway, draft, "draft-discover-fields",
            ["--type-handle", types["AuxBus"], "--selection", selected["selection"]], live=True)
        field = discovered_business_field_handle(discovered, "UserAuxSend0")
        candidate, = [row for result in discovered["meaning_results"] for row in result["candidates"] if row["handle"] == field]
        metadata = observation["live_field"] = candidate["metadata"]
        assert candidate["field_kind"] == "reference" and metadata["restriction"]["type"] == "reference", candidate
        assert candidate["restrictions"]["allowed_target_types"], candidate
        assert metadata["dependencies"] == [DEPENDENCY], metadata
        handles = {}
        for role in ROLES:
            declared = _update_business_draft(gateway, draft, "draft-declare-new", ["--declaration-id", role,
                "--parent-handle", owner if role == "routing" else handles["routing"],
                "--kind", types["Bus" if role == "routing" else "AuxBus"], "--name", "Routing" if role == "routing" else "Send",
                *(["--field-value", field, handles["destination"]] if role == "sender" else [])], live=False)
            handles[role] = declared_business_object_handle(declared, role)
        observation["declared_handles"] = handles
        phase = {"role": "source"}
        observation["transactions"].append(phase)

        def inspect_preview(preview):
            shown = phase["before_authorization"] = gateway.gateway(["transaction-show", preview["transaction_id"]], live=False)
            prepared = observation["source_prepared"] = shown["artifact"]["prepared_operation"]
            assert prepared["operation"] == "object.create" and prepared["request"]["version"] == "2021.1", prepared
            nodes = prepared["verification_plan"]["nodes"]
            facts = prepared["pre_state"]["planned_reference_context"]["facts"]
            by_handle = {facts[node["request_path"]]["result_handle"]: node for node in nodes}
            assert len(by_handle) == len(nodes) == 3 and set(by_handle) == set(handles.values())
            specs = observation["occurrence_specs"] = {role: by_handle[handles[role]] for role in ROLES}
            assert {role: spec["requested_name"] for role, spec in specs.items()} == {"routing": "Routing", "destination": "Send", "sender": "Send"}
            assert all(specs[role]["class_id"] == (1376272 if role == "routing" else 3997712) for role in ROLES)
            assert specs["destination"]["parent_request_path"] == specs["sender"]["parent_request_path"] == specs["routing"]["request_path"]
            reference, = specs["sender"]["references"]
            assert reference["target_result_handle"] == handles["destination"] and reference["target_request_path"] == specs["destination"]["request_path"]
            plan = prepared["pre_state"]["owned_result_stages"]
            assert plan["uri"] == CREATE and plan["version"] == "2021.1" and len(plan["deferred"]) == 1, plan
            assert [stage["root"] for stage in plan["creation_stages"]] == [specs[role]["request_path"] for role in ROLES]
            assert all(stage["owned_parent"] is True and stage["parent"] == specs["routing"]["request_path"] for stage in plan["creation_stages"][1:])
            assert all(stage["args"]["name"] == ("Routing" if index == 0 else "Send") and "children" not in stage["args"] for index, stage in enumerate(plan["creation_stages"]))
            assert prepared["semantic_preview"]["envelope"]["metadata"]["result_reference_execution"]["stage_count"] == 4
            assert prepared["pre_state"]["field_read_platform"]["platform_id"] == WINDOWS
            evidence, = specs["sender"]["new_object_default_evidence"]
            assert evidence["derived_properties"] == {}, evidence
            applicability, = evidence["override_applicability"]
            assert applicability["kind"] == "not_applicable_on_class" and applicability["version"] == "2021.1", applicability
            assert applicability["class_id"] == 3997712 and applicability["field"] == "UserAuxSend0" and applicability["dependency"] == DEPENDENCY, applicability

        phase.update(_complete_business_draft(gateway, draft, inspect_preview=inspect_preview))
        assert phase["execute"]["automatic_retry"] is False and phase["verify"]["verified"] is True, phase
        phase["after_verification"] = gateway.gateway(["transaction-show", phase["preview"]["transaction_id"]], live=False)
        assert phase["before_authorization"]["artifact"] == phase["after_verification"]["artifact"], phase
        execution = next(event["details"]["dispatch_result"] for event in phase["after_verification"]["events"] if event["event_type"] == "execution_completed")
        proof = observation["actual_stage_proof"] = execution["owned_result_execution"]
        specs = observation["occurrence_specs"]
        created = observation["created_occurrences"] = {role: proof["identities"][specs[role]["request_path"]] for role in ROLES}
        _assert_actual_create_calls(proof, created)
        assert execution["result"] == proof["stages"][0]["dispatch_result"]["result"]
        for index in (1, 2):
            binding = proof["creation_bindings"][index]
            for role in ROLES[:index]:
                identity = created[role]["id"]
                assert any(row["uri"] == GET and row["args"] == {"from": {"id": [identity]}} and row["options"] == {"return": FIELDS} for row in binding["before_readbacks"])
                assert any(row["uri"] == GET and row["args"] == {"from": {"id": [identity]}, "transform": [{"select": ["children"]}]} and row["options"] == {"return": ["id"]} for row in binding["before_readbacks"])
            assert binding["before_preservation"] and all(row["passed"] for row in binding["before_preservation"])
        for role in ROLES:
            identity = created[role]["id"]
            cumulative = proof["creation_bindings"][-1]["readbacks"]
            assert any(row["uri"] == GET and row["args"] == {"from": {"id": [identity]}} and row["options"] == {"return": FIELDS} for row in cumulative)
            assert any(row["uri"] == GET and row["args"] == {"from": {"id": [identity]}, "transform": [{"select": ["children"]}]} and row["options"] == {"return": ["id"]} for row in cumulative)
        for role in ("destination", "sender"):
            assert any(row["uri"] == GET and row["args"] == {"from": {"id": [created[role]["id"]]}} and row["options"] == {"return": FIELDS} for row in proof["readbacks"])
        assert any(row["uri"] == "ak.wwise.core.object.getPropertyInfo" and row["args"] == {"property": "UserAuxSend0", "object": created["sender"]["id"]} for row in proof["readbacks"])
        after = observation["source_state"] = preserved("source")
        assert after["ancestor"] == before["ancestor"] and after["owner"] == before["owner"], after
        ids = {role: row["id"].upper() for role, row in created.items()}
        assert set(after["descendants"]) == {GUNS, CARS, *ids.values()}, after
        for identity in (GUNS, CARS):
            assert after["descendants"][identity] == before["descendants"][identity], after
        for role, identity in ids.items():
            row, bound = after["descendants"][identity], created[role]
            assert all(row[key] == bound[key] for key in ("id", "name", "type", "path", "notes")), (row, bound)
            assert row["class_id"] == bound["classId"] and row["parent"]["id"] == bound["parent"]["id"], (row, bound)
            assert (row["type"], row["class_id"]) == (("Bus", 1376272) if role == "routing" else ("AuxBus", 3997712)), row
            parent_id = OWNER if role == "routing" else ids["routing"]
            parent_path = OWNER_PATH if role == "routing" else created["routing"]["path"]
            assert row["parent"]["id"].upper() == parent_id and row["path"] == parent_path + "\\" + row["name"], row
        sender = objects("source-reference", ids["sender"], reference=True)[ids["sender"]]
        assert sender["references"]["UserAuxSend0"]["id"].upper() == ids["destination"], sender
        observation["independent_sender"] = sender
        business = phase["verify"]["agent_result"]["business_result"]
        assert business["configuration_complete"] is True and business["identity_source"] == "independently_verified_creation_occurrences", business
        roster = {row["result_handle"]: row for row in business["created_objects"]}
        assert len(business["created_objects"]) == len(roster) == 3 and set(roster) == set(handles.values()), roster
        for role, handle in handles.items():
            row, actual = roster[handle], after["descendants"][ids[role]]
            assert row["request_path"] == specs[role]["request_path"] and row["requested_name"] == specs[role]["requested_name"], row
            assert row["object"] == {key: actual[key] for key in ("id", "name", "type", "path")}, row
            assert row["class_id"] == actual["class_id"] and row["parent_id"] == actual["parent"]["id"], row
        assert len(observation["reads"]) == 9 and len(observation["transactions"]) == 1
        observation.update(complete=True, business_effect_verified=True)
        category["status"] = "PASS"
    except BaseException as exc:
        observation["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        try:
            packets = sorted(set(evidence_root.glob("*.json")) - previous)
            assert len(packets) <= 512, "CREATE native packet bound exceeded"
            total = 0
            for packet in packets:
                body = packet.read_bytes()
                total += len(body)
                assert total <= 32 * 1024 * 1024, "CREATE native packet bytes exceeded"
                record = json.loads(body)
                uri = record.get("uri", record.get("api"))
                assert isinstance(uri, str) and uri != "ak.wwise.core.object.set" and not uri.startswith("ak.wwise.core.undo."), record
                observation["native_evidence"].append({"path": str(packet), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        except BaseException as exc:
            observation.update(complete=False, business_effect_verified=False, collection_failure={"type": type(exc).__name__, "message": str(exc)})
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

"""Owned reference-history effects retain actual Action identities and kind proof."""
from copy import deepcopy

import pytest

from tests.unit.test_action_reference_kind_gateway import ActionTask, FIRST, SECOND, OLD, EVENT, confirm

PLATFORM = "{9C6217D5-DD11-4795-87C1-6CE02853C541}"


class ActionHistoryTask(ActionTask):
    def __init__(self, path, version="2025.1", *, native_kind=False):
        super().__init__(path, version)
        if native_kind:
            self.metadata["Target"]["type"] = "Reference"
        self.history_before = self.history_after = None
        self.drop_history = False

    def call(self, uri, args=None, options=None):
        if uri.endswith("getProjectInfo"):
            return {**super().call(uri, args, options), "currentPlatformId": PLATFORM,
                "platforms": [{"id": PLATFORM, "name": "Mac"}]}
        if uri.endswith("object.setReference"):
            self.history_before = deepcopy(self.objects[FIRST])
            result = super().call(uri, args, options)
            self.history_after = deepcopy(self.objects[FIRST])
            return result
        if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
            assert args == {} and options == {}, (uri, args, options)
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if not self.drop_history:
                self.objects[FIRST] = deepcopy(self.history_before if uri.endswith(".undo") else self.history_after)
            return {}
        return super().call(uri, args, options)

    def complete_source(self):
        self.declare()
        tx, shown = self.preview()
        confirm(self, tx, shown)
        code, result = self.run("execute", tx)
        assert code == 0, result
        code, result = self.run("verify", tx)
        assert code == 0 and result["verified"] is True, result
        return tx

    def history(self, direction, source):
        code, started = self.run("draft-start", "ak.wwise.core.undo." + direction)
        assert code == 0, started
        self.draft, self.authority, self.revision = started["draft"]["draft_id"], started["task_authority"], started["draft"]["revision"]
        code, declared = self.step("draft-declare-core-plan", "--value", "history_scope", "latest_project_history",
            "--value", "expectation_receipt", source)
        assert code == 0, declared
        return self.preview()

    def complete_history(self, direction, source):
        tx, shown = self.history(direction, source)
        confirm(self, tx, shown)
        code, result = self.run("execute", tx)
        assert code == 0, result
        code, result = self.run("verify", tx)
        assert code == 0 and result["verified"] is True, result
        assert result["verification_strength"] == "scoped_history_effect_readback"
        return tx, shown


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
@pytest.mark.parametrize("native_kind", [False, True])
def test_owned_action_reference_undo_redo_uses_actual_paths_and_source_kind(tmp_path, version, native_kind):
    task = ActionHistoryTask(tmp_path, version, native_kind=native_kind)
    before = deepcopy(task.objects)
    source = task.complete_source()
    after = deepcopy(task.objects)
    assert before[FIRST]["path"] != after[FIRST]["path"]
    phases = [("undo", before)] + ([] if version == "2022.1" else [("redo", after)])
    for direction, expected in phases:
        _tx, shown = task.complete_history(direction, source)
        assert task.objects == expected
        binding = shown["artifact"]["prepared_operation"]["pre_state"]["history_binding"]
        row, = binding["observations"]
        assert row["object_before"]["path"] == before[FIRST]["path"]
        assert row["object_after"]["path"] == after[FIRST]["path"]
        assert row["field_info"]["type"] == ("Reference" if native_kind else "") and row["field_info"]["restriction"] == {}
        assert ("reference_kind_evidence" in row["field_info"]) is not native_kind
        assert row["controller_values"] == {"ActionType": 1} and row["parent_id"] == EVENT
        assert row["class_id"] == 327696
    assert len([uri for uri, _, _ in task.calls if uri == "ak.wwise.core.undo.undo"]) == 1
    assert len([uri for uri, _, _ in task.calls if uri == "ak.wwise.core.undo.redo"]) == int(version != "2022.1")


@pytest.mark.parametrize("version,direction", [("2021.1", "undo"), ("2021.1", "redo"), ("2022.1", "redo")])
def test_unpinned_history_lane_stays_an_explicit_boundary(tmp_path, version, direction):
    task = ActionHistoryTask(tmp_path, version)
    task.calls.clear()
    code, result = task.run("--version", version, "request-schema", "ak.wwise.core.undo." + direction)
    assert code == 2, result
    assert task.calls == []


@pytest.mark.parametrize("native_kind", [False, True])
@pytest.mark.parametrize("phase", ["prewrite", "postwrite"])
@pytest.mark.parametrize("damage", ["controller", "parent", "class", "metadata", "path", "reference"])
def test_history_rejects_drift_without_weakening_source_kind_or_identity(tmp_path, native_kind, phase, damage):
    task = ActionHistoryTask(tmp_path, native_kind=native_kind)
    source = task.complete_source()
    tx, shown = task.history("undo", source)
    confirm(task, tx, shown)
    if phase == "postwrite":
        code, result = task.run("execute", tx)
        assert code == 0, result
    if damage == "controller":
        task.objects[FIRST]["ActionType"] = True
    elif damage == "parent":
        task.objects[FIRST]["parent"] = {"id": OLD}
    elif damage == "class":
        task.objects[FIRST]["classId"] = True
    elif damage == "metadata":
        task.metadata["Target"]["future"] = {"enabled": False, "count": 0}
    elif damage == "path":
        task.objects[FIRST]["path"] = r"\Events\Default Work Unit\Wrong\[Play - Rain]"
    else:
        task.objects[FIRST]["Target"] = {"id": FIRST}
    code, rejected = task.run("execute" if phase == "prewrite" else "verify", tx)
    assert code == 2, rejected
    assert len([uri for uri, _, _ in task.calls if uri == "ak.wwise.core.undo.undo"]) == (phase == "postwrite")
    assert not any(uri == "ak.wwise.core.undo.redo" for uri, _, _ in task.calls)


@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_history_empty_acknowledgment_does_not_prove_a_dropped_effect(tmp_path, direction):
    task = ActionHistoryTask(tmp_path)
    source = task.complete_source()
    if direction == "redo":
        task.complete_history("undo", source)
    tx, shown = task.history(direction, source)
    confirm(task, tx, shown)
    task.drop_history = True
    before = deepcopy(task.objects)
    code, result = task.run("execute", tx)
    assert code == 0, result
    code, rejected = task.run("verify", tx)
    assert code == 2 and rejected.get("verified") is not True, rejected
    assert task.objects == before


class MissingSourceFrameTask(ActionHistoryTask):
    def call(self, uri, args=None, options=None):
        result = super().call(uri, args, options)
        required = {"name", "type", "classId", "parent", "ActionType"}
        if (uri.endswith("object.get") and self.history_after is not None
                and required <= set(options.get("return", []))):
            for row in result.get("return", []):
                if row.get("id") == FIRST:
                    row.pop(self.missing_frame_member, None)
        return result


@pytest.mark.parametrize("member", ["name", "type", "classId", "parent", "ActionType"])
def test_source_cannot_verify_or_offer_history_from_an_unobserved_after_identity(tmp_path, member):
    task = MissingSourceFrameTask(tmp_path)
    task.missing_frame_member = member
    task.declare()
    source, shown = task.preview()
    confirm(task, source, shown)
    code, result = task.run("execute", source)
    assert code == 0, result
    code, rejected = task.run("verify", source)
    assert code == 2 and rejected.get("verified") is not True, rejected
    code, started = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, started
    task.draft, task.authority, task.revision = started["draft"]["draft_id"], started["task_authority"], started["draft"]["revision"]
    code, rejected = task.step("draft-declare-core-plan", "--value", "history_scope", "latest_project_history",
        "--value", "expectation_receipt", source)
    assert code == 2, rejected
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _, _ in task.calls)


def legacy_or_forged_source(task, source, fault):
    # Build a sealed test-only historical fixture from this test's owned
    # execution. No old real receipt is edited or replayed.
    from wwise_waapi.transactions import TransactionStore, TransactionState
    store = TransactionStore(task.path / "state")
    snapshot = store.load_snapshot(source)
    artifact = deepcopy(snapshot.preview.artifact)
    prepared = artifact["prepared_operation"]
    verification = deepcopy(next(event["details"]["verification"] for event in snapshot.events
        if event["event_type"] == "verification_recorded"))
    execution = deepcopy(next(event["details"]["dispatch_result"] for event in snapshot.events
        if event["event_type"] == "execution_completed"))
    if fault == "legacy":
        prepared["pre_state"].pop("derived_reference_context")
        for field in ("name", "type", "classId", "parent", "ActionType"):
            prepared["pre_state"]["field_before"]["row"].pop(field)
        verification["assertions"] = [item for item in verification["assertions"] if item.get("kind") != "verified-derived-reference-identity"]
    else:
        witness = next(item for item in verification["assertions"] if item.get("kind") == "verified-derived-reference-identity")
        if fault == "missing-witness":
            verification["assertions"].remove(witness)
        elif fault == "row-path":
            witness["evidence"]["row"]["path"] += "forged"
        elif fault == "proof":
            prepared["pre_state"]["field_info"]["reference_kind_evidence"]["sdk"]["raw_member_sha256"] = "0" * 64
        elif fault == "parent":
            witness["evidence"]["after"]["parent_id"] = OLD
        elif fault == "boolean-tag":
            witness["passed"] = 1
        elif fault == "malformed-witness":
            witness["evidence"] = None
        elif fault == "unretained-row":
            read = next(item for item in verification["readbacks"]
                if item["uri"].endswith("object.get") and "ActionType" in item["options"].get("return", []))
            read["result"]["return"] = []
    tx = "legacy-action-reference-" + fault
    created = store.create_preview(tx, artifact)
    store.submit_for_confirmation(tx)
    store.confirm(tx, artifact_hash=created.artifact_hash)
    store.begin_execution(tx, expected_authorization=TransactionState.CONFIRMED)
    store.mark_executed_unverified(tx, details={"dispatch_result": execution})
    store.record_verification(tx, "verified", details={"verification": verification})
    return tx, store.read_events(tx)


@pytest.mark.parametrize("fault", ["legacy", "missing-witness", "row-path", "proof", "parent", "boolean-tag",
    "malformed-witness", "unretained-row"])
def test_history_rejects_legacy_or_resealed_forged_reference_observation_without_enrichment(tmp_path, fault):
    task = ActionHistoryTask(tmp_path)
    source = task.complete_source()
    fixture, original_events = legacy_or_forged_source(task, source, fault)
    objects = deepcopy(task.objects)
    code, started = task.run("draft-start", "ak.wwise.core.undo.undo")
    assert code == 0, started
    task.draft, task.authority, task.revision = started["draft"]["draft_id"], started["task_authority"], started["draft"]["revision"]
    code, rejected = task.step("draft-declare-core-plan", "--value", "history_scope", "latest_project_history",
        "--value", "expectation_receipt", fixture)
    assert code == 2, rejected
    from wwise_waapi.transactions import TransactionStore
    assert rejected["error_code"] == "GatewayInputError", rejected
    assert TransactionStore(task.path / "state").read_events(fixture) == original_events
    assert task.objects == objects
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _, _ in task.calls)


@pytest.mark.parametrize("member", ["metadata", "parent"])
def test_history_keeps_boolean_and_number_extensions_distinct(tmp_path, member):
    task = ActionHistoryTask(tmp_path, native_kind=True)
    if member == "metadata":
        task.metadata["Target"]["future"] = {"enabled": False, "count": 0}
    else:
        task.objects[FIRST]["parent"]["future"] = {"enabled": False, "count": 0}
    source = task.complete_source()
    tx, shown = task.history("undo", source)
    confirm(task, tx, shown)
    if member == "metadata":
        task.metadata["Target"]["future"]["enabled"] = 0
    else:
        task.objects[FIRST]["parent"]["future"]["enabled"] = 0
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert not any(uri.startswith("ak.wwise.core.undo.") for uri, _, _ in task.calls)

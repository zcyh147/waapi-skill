"""Owned structural property receipts use the normal latest-history protocol."""
from copy import deepcopy
import json

import pytest

from tests.unit.test_switch_child_context_gateway import ContextTask, FIRST, SECOND, CHILD
from tests.unit.test_compound_undo_business_gateway import _created_leaf_history_preview

PLATFORM = "{9C6217D5-DD11-4795-87C1-6CE02853C541}"


class ContextHistoryTask(ContextTask):
    def call(self, uri, args=None, options=None):
        if uri.endswith("setProperty"):
            self.history_before = deepcopy(self.objects)
            result = super().call(uri, args, options)
            self.history_after = deepcopy(self.objects)
            return result
        if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}:
            self.calls.append((uri, deepcopy(args), options))
            self.objects = deepcopy(self.history_before if uri.endswith(".undo") else self.history_after)
            return {}
        return super().call(uri, args, options)


def source_receipt(task, field="ContinuePlay", value=True, platform=PLATFORM):
    target = task.bind_context()
    code, discovered = task.step("draft-discover-fields", "--object-handle", target, "--meaning", field,
        *(["--platform", platform] if platform else []))
    assert code == 0, discovered
    handle = discovered["meaning_results"][0]["candidates"][0]["handle"]
    code, result = task.step("draft-declare-field-change", "--object-handle", target,
        "--field-handle", handle, "--business-value", json.dumps(value))
    assert code == 0, result
    for command in ("draft-check", "preview-from-draft"):
        code, result = task.step(command)
        assert code == 0, result
    source = result["transaction_id"]
    code, shown = task.run("transaction-show", source)
    assert code == 0, shown
    for command, argv in (("confirm", ("--confirmation-token", shown["confirmation"]["token"])), ("execute", ()), ("verify", ())):
        code, result = task.run(command, source, *argv)
        assert code == 0, result
    return source


def test_structural_type_absent_receipt_undo_public_flow(tmp_path):
    task = ContextHistoryTask(tmp_path, "2022.1")
    before = deepcopy(task.objects)
    source = source_receipt(task)
    tx = _created_leaf_history_preview(task, source)
    code, result = task.run("execute", tx)
    assert code == 0, result
    code, result = task.run("verify", tx)
    assert code == 0 and result["verified"] is True, result
    assert task.objects == before
    assert "type" not in task.objects[FIRST]


PAIRS = [(v, d) for v in ("2022.1", "2023.1", "2024.1", "2025.1")
    for d in (["undo"] if v == "2022.1" else ["undo", "redo"])]


@pytest.mark.parametrize("version,direction", PAIRS)
@pytest.mark.parametrize("native_type", [False, True])
@pytest.mark.parametrize("field,value,platform", [("ContinuePlay", True, PLATFORM),
    ("ContinuePlay", True, None), ("FadeInTime", 2.5, PLATFORM)])
def test_structural_property_owned_history_all_permitted_lanes(tmp_path, version, direction, native_type, field, value, platform):
    task = ContextHistoryTask(tmp_path, version, native_type)
    source = source_receipt(task, field, value, platform)
    for action in (["undo"] if direction == "undo" else ["undo", "redo"]):
        tx = _created_leaf_history_preview(task, source, action)
        code, shown = task.run("transaction-show", tx)
        assert code == 0, shown
        summary = shown["artifact"]["prepared_operation"]["semantic_preview"]
        assert "owned_receipt" in json.dumps(summary)
        code, result = task.run("execute", tx)
        assert code == 0, result
        code, result = task.run("verify", tx)
        assert code == 0 and result["verified"] is True, result
        assert task.objects == (task.history_before if action == "undo" else task.history_after)
        assert ("type" in task.objects[FIRST]) is native_type
        code, rejected = task.run("execute", tx)
        assert code == 2, rejected
    assert sum(uri == "ak.wwise.core.undo." + direction for uri, _, _ in task.calls) == 1


def history_calls(task):
    return [uri for uri, _, _ in task.calls if uri in {"ak.wwise.core.undo.undo", "ak.wwise.core.undo.redo"}]


@pytest.mark.parametrize("stage", ["prewrite", "postaction"])
@pytest.mark.parametrize("damage", ["child-parent", "child-context", "owner", "class", "type-null", "type-presence",
    "catalog", "owner-value", "owner-metadata", "field-metadata", "bool-number", "missing", "duplicate", "extra"])
def test_history_revalidates_structural_proofs_conditions_and_values_without_retry(tmp_path, stage, damage):
    task = ContextHistoryTask(tmp_path, "2022.1")
    source = source_receipt(task)
    tx = _created_leaf_history_preview(task, source)
    if stage == "postaction":
        code, result = task.run("execute", tx)
        assert code == 0, result
    if damage == "child-parent": task.objects[CHILD]["parent"] = {"id": FIRST}
    if damage == "child-context": task.objects[CHILD]["switchContainerChildContext"] = {"id": SECOND}
    if damage == "owner": task.objects[FIRST]["owner"] = {"id": CHILD}
    if damage == "class": task.objects[FIRST]["classId"] = 655376
    if damage == "type-null": task.objects[FIRST]["type"] = None
    if damage == "type-presence": task.objects[FIRST]["type"] = "ObjectSettingAssociation"
    if damage == "catalog": task.types[0]["name"] = "GuessedAssociation"
    if damage == "owner-value": task.objects[SECOND]["SwitchBehavior"] = 0
    if damage == "owner-metadata": task.metadata["SwitchBehavior"]["default"] = 1
    if damage == "field-metadata": task.metadata["ContinuePlay"]["default"] = True
    if damage == "bool-number": task.objects[FIRST]["ContinuePlay"] = int(task.objects[FIRST]["ContinuePlay"])
    if damage in {"missing", "duplicate", "extra"}:
        original = task.call
        def malformed(uri, args=None, options=None):
            result = original(uri, args, options)
            if uri.endswith("object.get") and "from" in args and FIRST in args["from"].get("id", []):
                if damage == "missing": result["return"] = [r for r in result["return"] if r["id"] != FIRST]
                if damage == "duplicate": result["return"].append(deepcopy(result["return"][0]))
                if damage == "extra": result["return"].append({"id": PLATFORM})
            return result
        task.call = malformed
    code, result = task.run("execute" if stage == "prewrite" else "verify", tx)
    assert code == 2 and result.get("verified") is not True, result
    assert len(history_calls(task)) == (0 if stage == "prewrite" else 1)
    if stage == "postaction":
        code, rejected = task.run("execute", tx)
        assert code == 2, rejected
        assert len(history_calls(task)) == 1


@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_dropped_history_action_fails_verification_and_is_never_replayed(tmp_path, direction):
    task = ContextHistoryTask(tmp_path, "2023.1", True)
    source = source_receipt(task)
    if direction == "redo":
        undo = _created_leaf_history_preview(task, source)
        for command in ("execute", "verify"):
            code, result = task.run(command, undo)
            assert code == 0, result
    tx = _created_leaf_history_preview(task, source, direction)
    original = task.call
    def dropped(uri, args=None, options=None):
        if uri == "ak.wwise.core.undo." + direction:
            task.calls.append((uri, args, options))
            return {}
        return original(uri, args, options)
    task.call = dropped
    code, result = task.run("execute", tx)
    assert code == 0, result
    code, result = task.run("verify", tx)
    assert code == 2 and result.get("verified") is not True, result
    code, result = task.run("execute", tx)
    assert code == 2, result
    assert sum(uri == "ak.wwise.core.undo." + direction for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version,direction", [("2021.1", "undo"), ("2021.1", "redo"), ("2022.1", "redo")])
def test_structural_receipt_does_not_invent_unavailable_history_route(tmp_path, version, direction):
    task = ContextHistoryTask(tmp_path, version)
    source_receipt(task)
    code, result = task.run("draft-start", "ak.wwise.core.undo." + direction)
    assert code == 2, result
    assert not history_calls(task)


@pytest.mark.parametrize("kind", ["linkable", "unknown"])
def test_uncertified_omitted_platform_remains_a_history_boundary(tmp_path, kind):
    from tests.unit.test_compound_undo_business_gateway import _reject_created_graph_receipt
    task = ContextHistoryTask(tmp_path, "2022.1")
    if kind == "unknown":
        task.metadata["FadeInTime"].pop("supports")
    source = source_receipt(task, "FadeInTime", 2.5, None)
    rejected = _reject_created_graph_receipt(task, source)
    assert "read platform is not certified" in rejected["message"], rejected


@pytest.mark.parametrize("platform", [None, "Windows"])
def test_structural_linkable_receipt_keeps_its_certified_original_read_view(tmp_path, platform):
    task = ContextHistoryTask(tmp_path, "2025.1", True)
    original = task.call
    def platforms(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith("getProjectInfo"):
            result.update(currentPlatformId=PLATFORM, platforms=[{"id": PLATFORM, "name": "Windows"}])
        return result
    task.call = platforms
    source = source_receipt(task, "FadeInTime", 2.5, platform)
    tx = _created_leaf_history_preview(task, source)
    start = len(task.calls)
    for command in ("execute", "verify"):
        code, result = task.run(command, tx)
        assert code == 0, result
    field_reads = [options for uri, args, options in task.calls[start:]
        if uri.endswith("object.get") and "FadeInTime" in options.get("return", [])]
    assert field_reads and all(options.get("platform") == PLATFORM for options in field_reads)


def test_structural_history_rechecks_read_only_policy_before_action(tmp_path):
    task = ContextHistoryTask(tmp_path, "2022.1")
    source = source_receipt(task)
    tx = _created_leaf_history_preview(task, source)
    code, result = task.run("config-set", "--project-modification-policy", "read_only")
    assert code == 0, result
    code, result = task.run("execute", tx)
    assert code == 2, result
    assert not history_calls(task)


@pytest.mark.parametrize("fault", ["projection", "expected-type", "request-field", "dispatch-value", "proof-source", "condition-guard", "zero-platform"])
def test_resealed_structural_receipt_must_retain_exact_source_agreement(tmp_path, fault):
    from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256
    from tests.unit.test_compound_undo_business_gateway import _reject_created_graph_receipt
    task = ContextHistoryTask(tmp_path, "2022.1")
    source = source_receipt(task)
    directory = task.path / "state" / "transactions" / source
    document = json.loads((directory / "preview.json").read_text())
    prepared = document["artifact"]["prepared_operation"]
    if fault == "projection": prepared["pre_state"]["field_before"]["row"]["ContinuePlay"] = True
    if fault == "expected-type": prepared["verification_plan"]["expected_value"] = 1
    if fault == "request-field": prepared["request"]["arguments"]["property"] = "FadeInTime"
    if fault == "dispatch-value": prepared["dispatch"]["args"]["value"] = 1
    if fault == "proof-source": prepared["pre_state"]["switch_child_context"]["catalog_sha256"] = "0" * 64
    if fault == "condition-guard": prepared["pre_state"]["related_conditions"] = []
    if fault == "zero-platform": prepared["verification_plan"]["platform"] = "{00000000-0000-0000-0000-000000000000}"
    document["artifact_hash"] = canonical_sha256(document["artifact"])
    (directory / "preview.json").write_bytes(canonical_json_bytes(document))
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    previous = ""
    for event in events:
        event["artifact_hash"] = document["artifact_hash"]
        event["previous_event_hash"] = previous
        event.pop("event_hash")
        event["event_hash"] = previous = canonical_sha256(event)
    (directory / "events.jsonl").write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))
    record = json.loads((directory / "state.json").read_text())
    record.update(artifact_hash=document["artifact_hash"], last_event_hash=previous)
    (directory / "state.json").write_bytes(canonical_json_bytes(record))
    _reject_created_graph_receipt(task, source)


@pytest.mark.parametrize("stage", ["prewrite", "postaction"])
def test_history_preserves_explicit_native_type_presence(tmp_path, stage):
    task = ContextHistoryTask(tmp_path, "2023.1", True)
    source = source_receipt(task)
    tx = _created_leaf_history_preview(task, source)
    if stage == "postaction":
        code, result = task.run("execute", tx)
        assert code == 0, result
    task.objects[FIRST].pop("type")
    code, result = task.run("execute" if stage == "prewrite" else "verify", tx)
    assert code == 2, result
    assert len(history_calls(task)) == (0 if stage == "prewrite" else 1)


def test_lost_history_acknowledgement_is_indeterminate_and_not_replayed(tmp_path):
    task = ContextHistoryTask(tmp_path, "2022.1")
    source = source_receipt(task)
    tx = _created_leaf_history_preview(task, source)
    original = task.call
    def lost(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri == "ak.wwise.core.undo.undo":
            raise ValueError("owned fixture lost history acknowledgement")
        return result
    task.call = lost
    code, result = task.run("execute", tx)
    assert code == 2, result
    assert task.objects[FIRST]["ContinuePlay"] is False
    code, repeated = task.run("execute", tx)
    assert code == 2, repeated
    assert len(history_calls(task)) == 1


@pytest.mark.parametrize("fault", ["schema-only", "unverified"])
def test_structural_receipt_requires_actual_business_verification(tmp_path, fault):
    from tests.unit.test_compound_undo_business_gateway import _reject_created_graph_receipt, _rewrite_created_graph_verification
    task = ContextHistoryTask(tmp_path, "2022.1")
    source = source_receipt(task)
    def mutate(verification):
        verification["business_state_verified"] = False
        if fault == "unverified":
            verification["status"] = "failed"
    _rewrite_created_graph_verification(task, source, mutate)
    _reject_created_graph_receipt(task, source)


def test_actual_zero_guid_unlink_receipt_is_not_a_read_platform_witness(tmp_path):
    from tests.unit.test_compound_undo_business_gateway import _reject_created_graph_receipt
    task = ContextHistoryTask(tmp_path, "2022.1")
    source = source_receipt(task, "FadeInTime", 2.5, "{00000000-0000-0000-0000-000000000000}")
    rejected = _reject_created_graph_receipt(task, source)
    assert "null GUID is an unlink instruction" in rejected["message"], rejected

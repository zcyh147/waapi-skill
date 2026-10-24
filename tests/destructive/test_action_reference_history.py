"""One owned 2025 Action retarget followed by separately authorized undo/redo."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.destructive.test_action_target_reference import (
    test_existing_play_action_retargets_without_changing_action_or_audio_context as _retarget_source,
)
from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _complete_business_draft,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)

pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") != "2025.1", reason="Initial owned Action-history witness is 2025 only")]


def test_owned_action_reference_undo_redo_preserves_actual_identity_and_context(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    output = runtime.state_dir / "action-kind-history.json"
    assert not output.exists(), "An earlier observation must not be overwritten"
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    prior_packets = set(evidence_root.glob("*.json"))
    observation = {"candidate": runtime.candidate, "version": runtime.version, "history": [], "reads": [],
        "native_evidence": [], "business_effect_verified": False,
        "scope": "owned receipt and independently observed objects only; native stack head and outside scope are not proven"}
    category = {"category": "owned-source-kind-action-reference-history", "status": "FAIL",
        "verifier_strength": "owned_source_receipt_and_independent_reference_path_controller_peer_audio_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"
    try:
        # Reuse the already reviewed public producer and its full independent
        # preservation checks; its snapshots are test oracles, not Gateway
        # receipt inputs. History selects only the owned verified transaction.
        _retarget_source(runtime)
        source_path = runtime.state_dir / "action-target-reference.json"
        source = json.loads(source_path.read_text())
        observation.update(source_observation_path=str(source_path),
            source_observation_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest())
        assert source["business_effect_verified"] is True and len(source["transactions"]) == 1, source
        source_id = source["transactions"][0]["preview"]["transaction_id"]
        observation["source_transaction_id"] = source_id
        # Reuse the exact compact public query requests from this same producer.
        # No stale selections/continuations or reconstructed native fields.
        selected = {"action": "action-before", "event_children": "event-children-before",
            "peer": "peer-action-before", "old_target": "old-target-before", "new_target": "new-target-before"}
        queries = {row["label"]: row["argv"] for row in source["reads"]}
        for direction, side in (("undo", "before"), ("redo", "after")):
            history = _start_business_draft(runtime, "ak.wwise.core.undo." + direction)
            declared = _update_business_draft(runtime, history, "draft-declare-core-plan",
                ["--value", "history_scope", "latest_project_history", "--value", "expectation_receipt", source_id], live=True)
            observation.setdefault("history_declarations", {})[direction] = declared

            def inspect(preview):
                observation.setdefault("history_previews", {})[direction] = preview
                shown = runtime.gateway(["transaction-show", preview["transaction_id"]], live=False)
                observation.setdefault("immutable_history_previews", {})[direction] = shown
                prepared = shown["artifact"]["prepared_operation"]
                dispatch = prepared["dispatch"]
                assert dispatch["uri"] == "ak.wwise.core.undo." + direction and dispatch["args"] == {} and dispatch["options"] == {}, dispatch
                row, = prepared["pre_state"]["history_binding"]["observations"]
                assert row["kind"] == "derived_action_reference" and row["controller_values"] == {"ActionType": 1}, row
                assert row["object_before"]["path"] == source["before"]["action"]["path"], row
                assert row["object_after"]["path"] == source["after"]["action"]["path"], row
                info = row["field_info"]
                assert info["type"] == "" and info["restriction"] == {}, info
                assert info["reference_kind_evidence"]["kind"] == "documented-reference-kind", info

            receipt = _complete_business_draft(runtime, history, inspect_preview=inspect)
            observation["history"].append(receipt)
            for key, label in selected.items():
                argv = queries[label]
                assert argv[0] == "query-object" and "--detail" not in argv, argv
                code, payload = runtime.raw_gateway(argv)
                observation["reads"].append({"label": key + "-after-" + direction, "argv": argv,
                    "exit_code": code, "payload": payload})
                assert code == 0 and payload.get("ok") is True and payload.get("projection_complete") is not False, payload
                assert list(payload)[-1] == "agent_result" and payload.get("status") not in {"partial", "needs_clarification"}, payload
                expected = source[side][key]
                actual = payload["agent_result"]
                assert isinstance(actual, list), actual
                if key != "event_children":
                    actual, = actual
                assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), (actual, expected)
        assert len(observation["history"]) == 2 and len(observation["reads"]) == 10
        assert len({source_id, *(item["preview"]["transaction_id"] for item in observation["history"])}) == 3
        observation["business_effect_verified"] = True
        status = "PASS"
    finally:
        observation["native_evidence"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(set(evidence_root.glob("*.json")) - prior_packets)]
        observation["status"] = status
        output.write_text(json.dumps(observation, indent=2, sort_keys=True) + "\n")
        category.update(status=status, observation_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            business_effect_verified=observation["business_effect_verified"])

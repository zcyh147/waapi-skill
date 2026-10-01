"""Explicit 2025 existing-entry maintenance; no Fresh Agent or new Skill route."""

import pytest

from tests.destructive.test_expansion_case_preflight import expansion_runtime
from tests.semantic.support.codex_expansion_cases import ExpansionCaseContext
from tests.semantic.support.codex_music_oracle_probes import xml_music_witness
from tests.semantic.support.codex_music_switch_reference_goal import (
    MEDIA_PREPARATION_REPORT_BYTES, append_bounded_goal_receipt, music_switch_reference_snapshot, prepare_music_switch_reference_media,
    run_music_switch_reference_goal,
)


pytestmark = [pytest.mark.live, pytest.mark.destructive]


def test_existing_music_switch_audio_node_reference_goal(expansion_runtime):
    runtime = expansion_runtime
    assert runtime.version == "2025.1", "this goal has one reviewed version lane"
    owned = runtime.sandbox.sandbox_path / "Containers" / "Music" / "Music.wwu"
    owned.resolve(strict=True).relative_to(runtime.sandbox.sandbox_path.resolve(strict=True))
    witness = xml_music_witness(owned, runtime.version)
    receipts = []
    report = {"category": "music-switch-existing-audio-node-goal", "status": "FAIL",
        "verifier_strength": "public_single_reference_with_complete_mapping_and_protected_media_readback",
        "agent_pass": False, "business_effect_verified": False, "complete_workflow_verified": False,
        "gateway_receipts": receipts, "transaction_ids": []}
    runtime.category_results.append(report)
    def gateway(argv):
        if len(receipts) >= 180:
            raise AssertionError("music reference goal exceeded its total public call ceiling")
        code, payload = runtime.raw_gateway(argv)
        append_bounded_goal_receipt(receipts, argv, code, payload,
            max_total_bytes=8 * 1_048_576 - MEDIA_PREPARATION_REPORT_BYTES)
        assert code == 0 and payload.get("ok") is True, payload
        if payload.get("endpoint") is not None:
            assert payload["endpoint"] == {"host": runtime.lifecycle.host, "port": runtime.port,
                                          "url": runtime.lifecycle.waapi_url}
        if payload.get("detected_version") is not None:
            assert payload["detected_version"] == runtime.version
        return payload
    ctx = ExpansionCaseContext(runtime.version, "MUSIC_REFERENCE_GOAL", runtime.sandbox.sandbox_project,
                               runtime.sandbox.sandbox_path / "ReferenceGoalAssets", gateway)
    report["media_preparation"] = {}
    prepare_music_switch_reference_media(ctx, owned, runtime.sandbox.source_project,
                                       evidence=report["media_preparation"])
    result = run_music_switch_reference_goal(ctx, witness,
        lambda: music_switch_reference_snapshot(ctx, witness, lambda: xml_music_witness(owned, runtime.version)))
    report.update(result)
    report["transaction_ids"] = [result["transaction_id"]]
    report["status"] = "PASS"  # selected-reference proof, explicitly not complete music authoring

"""Explicit developer public-read investigations; no mutations or Agent credit."""

from pathlib import Path

import pytest

from tests.destructive.test_expansion_case_preflight import expansion_runtime
from tests.semantic.support.codex_music_oracle_probes import (
    compare_music_read_receipts, music_read_plan, run_music_read_plan, xml_music_witness,
)


pytestmark = [pytest.mark.live, pytest.mark.destructive]


@pytest.mark.parametrize("family", ("playlist", "transition", "music-switch"))
def test_music_complete_oracle_public_read_investigation(expansion_runtime, family):
    runtime = expansion_runtime
    relative = (Path("Interactive Music Hierarchy") / "Music.wwu" if runtime.version == "2022.1"
                else Path("Containers") / "Music" / "Music.wwu")
    owned = runtime.sandbox.sandbox_path / relative
    owned.resolve(strict=True).relative_to(runtime.sandbox.sandbox_path.resolve(strict=True))
    witness = xml_music_witness(owned, runtime.version)
    report = {"category": "music-complete-oracle-read-" + family, "status": "FAIL",
        "verifier_strength": "bounded_public_read_findings_not_music_configuration_acceptance",
        "version": runtime.version, "xml_witness": witness, "transaction_ids": [],
        "agent_pass": False, "business_effect_verified": False}
    runtime.category_results.append(report)
    plan = music_read_plan(family, witness, runtime.version)
    def gateway(argv):
        code, payload = runtime.raw_gateway(argv)
        if payload.get("endpoint") is not None:
            assert payload["endpoint"] == {"host": runtime.lifecycle.host,
                "port": runtime.port, "url": runtime.lifecycle.waapi_url}
        if payload.get("detected_version") is not None:
            assert payload["detected_version"] == runtime.version
        return code, payload
    report.update(run_music_read_plan(plan, gateway))
    report["baseline_comparisons"] = compare_music_read_receipts(witness, report["receipts"])
    assert xml_music_witness(owned, runtime.version) == witness, "read-only probe changed its owned WWU"
    report["status"] = "PASS"  # the bounded investigation ran; its findings retain failed reads
    report["scope"] = "read_transport_and_retained_findings_only_not_complete_oracle_or_mutation_pass"

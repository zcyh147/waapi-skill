"""Read-only repair fixture attestation in the standard owned Wwise lifecycle."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import pytest
from tests.semantic.support.codex_expansion_runtime import fixture_gateway
from tests.semantic.support.codex_repair_cases import attest_predelay
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def test_repair_roomverb_predelay_metadata_preflight():
    root_text = os.environ.get("WAAPI_REPAIR_PREFLIGHT_ROOT")
    if not root_text:
        pytest.skip("requires a new explicit WAAPI_REPAIR_PREFLIGHT_ROOT")
    assert os.environ["WWISE_VERSION"] == "2025.1"
    root = Path(root_text)
    assert root.is_absolute() and not root.exists()
    home = root / "owned/wwise-user-home" if sys.platform == "darwin" else None
    prefix = home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64" if home else None
    lifecycle = ScenarioLifecycle(scenario_id="repair-f1-metadata-preflight", version="2025.1",
        scenario_root=root, live_environment=dict(os.environ),
        launch_environment_overrides={"HOME": str(home)} if home else None, owned_wine_prefix=prefix)
    runtime = None
    status, reason = "FAIL", "metadata attestation did not complete"
    receipts = []
    evidence = {"agent_started": False, "project_mutation_count": 0, "receipts": receipts}
    try:
        runtime = lifecycle.start()
        skill = Path(__file__).resolve().parents[2] / "skills/waapi-skill"
        gateway = fixture_gateway(skill_source=skill, runtime=runtime, version="2025.1", receipts=receipts)
        gateway(["config-set", "--wwise-version", "2025.1", "--waapi-host", runtime.host,
                 "--waapi-port", str(runtime.port), "--project-modification-policy", "read_only"])
        evidence["attestation"] = attest_predelay(gateway)
        status, reason = "PASS", "exact PreDelay metadata attested"
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        evidence["error"] = reason
        raise
    finally:
        if runtime is not None:
            (runtime.evidence_root / "repair-metadata-preflight.json").write_text(json.dumps(evidence, indent=2) + "\n")
            result = lifecycle.finish(status, reason="" if status == "PASS" else reason)
            assert result.final_status == status, result.as_dict()


@pytest.mark.parametrize("case_id", ["F1", "F2", "F3", "F4"])
def test_repair_formal_fixture_preparation_without_agent(case_id, monkeypatch):
    """Exercise formal setup and teardown; the task seam never starts Codex."""
    from tests.semantic.support import codex_expansion_runtime as runner
    from tests.semantic.support.codex_repair_profile import load_repair_profile

    root_text = os.environ.get("WAAPI_REPAIR_PREFLIGHT_ROOT")
    if not root_text:
        pytest.skip("requires a new explicit WAAPI_REPAIR_PREFLIGHT_ROOT")
    assert sys.platform == "darwin" and os.environ["WWISE_VERSION"] == "2025.1"
    root = Path(root_text) / case_id
    assert root.is_absolute() and not root.exists()
    repo = Path(__file__).resolve().parents[2]
    profile = load_repair_profile(repo / "tests/semantic/data/waapi-v11-repairs/profile.json")
    unit = next(unit for unit in profile.units if unit.case_id == case_id)
    observed = []

    def inspect_fixture(*, prepared, scoped_paths, **kwargs):
        before = prepared.before
        assert before["complete"] is True
        assert prepared.snapshot() == before
        assert prepared.policy == unit.policy
        assert set(scoped_paths) == set(before["objects"])
        expected = prepared.archive_oracle_parameters["expected"]
        targets = [row for row in before["objects"].values() if row.get("path") == expected["path"]]
        if case_id in {"F1", "F2"}:
            assert len(targets) == 1
            target = targets[0]
            assert (target["name"], target["type"]) == (expected["name"], expected["type"])
            if case_id == "F1":
                assert target["properties"]["PreDelay"] == 25
                assert target["class_id"] > 0
            else:
                assert target["properties"] == {"Min": -12, "Max": 36, "InitialValue": 7}
        else:
            assert targets == []
        observed.append(case_id)
        return {"status": "PASS", "evidence_kind": "native_fixture_preparation_only",
                "agent_started": False, "semantic_acceptance": False}

    monkeypatch.setattr(runner, "run_expansion_codex_task", inspect_fixture)
    options = runner.ExpansionRunnerOptions(skill_source=repo / "skills/waapi-skill",
        codex_binary=root / "never-launch-codex", auth_json=root / "no-agent-auth",
        model="gpt-5.6-terra", reasoning_effort="medium", service_tier="default",
        timeout_seconds=600, live_environment=dict(os.environ), campaign_inputs_sha256="0" * 64)
    outcome = runner.run_expansion_unit(unit, scenario_root=root, options=options)
    assert outcome.status == "PASS", outcome.as_dict()
    assert observed == [case_id]
    assert outcome.thread_id is None
    assert outcome.checks["task"]["agent_started"] is False
    assert outcome.checks["task"]["semantic_acceptance"] is False
    proof = outcome.lifecycle
    assert proof["source_hash_before"] == proof["source_hash_after"]
    assert proof["source_mtime_before_ns"] == proof["source_mtime_after_ns"]
    assert outcome.checks["trusted_oracle_closed"] is True

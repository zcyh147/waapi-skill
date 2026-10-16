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

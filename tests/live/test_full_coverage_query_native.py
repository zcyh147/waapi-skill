"""Bounded public read observations for #181, using the existing owned lifecycle.

A native rejection is preserved as an observation, not counted as acceptance of
that weight/filter. This fixture records native semantics before review.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
from tests.semantic.support.codex_expansion_runtime import fixture_gateway
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle


@pytest.mark.live
def test_media_pool_empty_and_weight_native_observations() -> None:
    root_text = os.environ.get("WAAPI_QUERY_NATIVE_ROOT")
    if not root_text:
        pytest.skip("requires a new explicit WAAPI_QUERY_NATIVE_ROOT")
    assert os.environ.get("WWISE_VERSION") == "2025.1"
    root = Path(root_text)
    assert root.is_absolute() and not root.exists()
    home = root / "owned/wwise-user-home" if sys.platform == "darwin" else None
    prefix = home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64" if home else None
    lifecycle = ScenarioLifecycle(
        scenario_id="full-coverage-181-media-observations", version="2025.1",
        scenario_root=root, live_environment=dict(os.environ),
        launch_environment_overrides={"HOME": str(home)} if home else None,
        owned_wine_prefix=prefix,
    )
    runtime = None
    status, reason = "FAIL", "native observation collection did not finish"
    receipts: list[dict] = []
    observations: list[dict] = []
    evidence = {"agent_started": False, "project_mutation_count": 0,
                "functional_acceptance": False,
                "scope": "bounded native read observations; native errors retain their original verdict",
                "receipts": receipts, "observations": observations}
    try:
        runtime = lifecycle.start()
        skill = Path(__file__).resolve().parents[2] / "skills/waapi-skill"
        gateway = fixture_gateway(skill_source=skill, runtime=runtime, version="2025.1", receipts=receipts)
        gateway(["config-set", "--wwise-version", "2025.1", "--waapi-host", runtime.host,
                 "--waapi-port", str(runtime.port), "--project-modification-policy", "read_only"])
        evidence["status"] = gateway(["status"])
        disclosed = gateway(["request-schema", "ak.wwise.core.mediaPool.getFields"])
        continuation = disclosed["continuation"]
        fields = gateway([continuation["subcommand"], *continuation["arguments"], "--meaning", "Filename"])["agent_result"]["fields"]
        fields = [field["name"] for field in fields if field.get("name_complete") is True]
        assert "Filename" in fields
        base = ["core-call", "ak.wwise.core.mediaPool.get", "--max-results", "5", "--database-scope", "project-originals"]
        cases = [
            ("empty-search", ["--search-text", ""]),
            ("empty-text-filter", ["--text-filter", "filename", "equals", ""]),
            ("description-control-weight", ["--weighted-audio-description", "rain", "0.5"]),
            ("description-negative-weight", ["--weighted-audio-description", "rain", "-0.25"]),
            ("description-above-one-weight", ["--weighted-audio-description", "rain", "1.25"]),
        ]
        audio_files = sorted(runtime.sandbox.sandbox_project.parent.rglob("*.wav"))
        if audio_files:
            selected = next((path for path in audio_files if path.is_file() and not path.is_symlink()), None)
            if selected is not None:
                cases.extend([
                    ("similarity-control-weight", ["--weighted-audio-similarity-file", str(selected), "0.5"]),
                    ("similarity-negative-weight", ["--weighted-audio-similarity-file", str(selected), "-0.25"]),
                    ("similarity-above-one-weight", ["--weighted-audio-similarity-file", str(selected), "1.25"]),
                ])
        else:
            observations.append({"case": "audio-similarity", "outcome": "BLOCKED", "reason": "no owned sandbox WAV file available"})
        for case_id, arguments in cases:
            start = len(receipts)
            try:
                payload = gateway([*base, *arguments])
            except CaseBoundaryError:
                assert len(receipts) == start + 1
                payload = receipts[-1]["payload"]
                assert payload.get("call", {}).get("api") == "ak.wwise.core.mediaPool.get", payload
                assert payload["call"].get("waapi_error_uri"), payload
                observations.append({"case": case_id, "outcome": "NATIVE_ERROR", "receipt_index": len(receipts) - 1,
                                     "waapi_error_uri": payload["call"]["waapi_error_uri"]})
            else:
                assert payload["call"]["api"] == "ak.wwise.core.mediaPool.get"
                assert payload["agent_result"]["candidate_count"] <= 5
                observations.append({"case": case_id, "outcome": "NATIVE_SUCCESS", "receipt_index": len(receipts) - 1,
                                     "returned_count": payload["agent_result"]["returned_count"]})
        status, reason = "PASS", "native read observations captured; semantic acceptance requires separate review"
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        evidence["error"] = reason
        raise
    finally:
        if runtime is not None:
            (runtime.evidence_root / "query-native-observations.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = lifecycle.finish(status, reason="" if status == "PASS" else reason)
            assert result.final_status == status, result.as_dict()

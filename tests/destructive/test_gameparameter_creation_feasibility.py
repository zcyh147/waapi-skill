"""Native feasibility only: registry-owned create request in an owned sandbox.

This deterministic developer test does not grant public Gateway or Fresh credit.
It uses the existing single-scenario lifecycle, including private HOME and Wine
prefix attestation, source hashes, and failure quarantine.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle
from wwise_waapi.operation_registry import parse_operation_request, prepare_operation, verify_prepared_operation

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def test_gameparameter_same_call_creation_native_feasibility():
    version = os.environ["WWISE_VERSION"]
    root = Path(os.environ["WAAPI_GAMEPARAMETER_PROBE_ROOT"]).resolve()
    private_home = root / "owned" / "wwise-user-home" if sys.platform == "darwin" else None
    prefix = private_home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64" if private_home else None
    lifecycle = ScenarioLifecycle(
        scenario_id=f"gameparameter-native-{version}", version=version,
        scenario_root=root, live_environment=dict(os.environ),
        launch_environment_overrides={"HOME": str(private_home)} if private_home else None,
        owned_wine_prefix=prefix,
    )
    runtime = actor = None
    status, reason = "FAIL", "probe did not complete"
    evidence = {"kind": "native-registry-feasibility", "public_gateway_pass": False,
                "agent_semantic_pass": False, "version": version}
    try:
        runtime = lifecycle.start()
        actor = OwnedDirectWaapiCall(host=runtime.host, port=runtime.port)
        catalog = actor("ak.wwise.core.object.getTypes", {}, {})["return"]
        matches = [row for row in catalog if row["name"] == "GameParameter"]
        assert len(matches) == 1
        class_id = matches[0]["classId"]
        names = actor("ak.wwise.core.object.getPropertyAndReferenceNames", {"classId": class_id}, {})["return"]
        assert {"Min", "Max", "InitialValue"} <= set(names)
        metadata = {name: actor("ak.wwise.core.object.getPropertyInfo", {"classId": class_id, "property": name}, {})
                    for name in ("Min", "Max", "InitialValue")}
        dependency_names = {row["property"] for info in metadata.values() for row in info.get("dependencies", []) if "property" in row}
        metadata.update({name: actor("ak.wwise.core.object.getPropertyInfo", {"classId": class_id, "property": name}, {})
                         for name in sorted(dependency_names) if name not in metadata})
        evidence["class_metadata"] = metadata
        request = parse_operation_request({
            "contract": "waapi-skill.operation-request/v1", "version": version,
            "operation": "object.create", "arguments": {
                "parent": {"kind": "path", "value": r"\Game Parameters\Default Work Unit"},
                "type": "GameParameter", "name": "WAAPI_SameCall_Feasibility",
                "properties": [{"name": "Min", "value": -12.0}, {"name": "Max", "value": 36.0}, {"name": "InitialValue", "value": 7.0}],
            },
        })
        prepared = prepare_operation(request, read_call=actor).as_dict()
        evidence["prepared"] = prepared
        dispatch = prepared["dispatch"]
        result = actor(dispatch["uri"], dispatch["args"], dispatch["options"])
        evidence["execution_result"] = result
        verified = verify_prepared_operation(prepared, execution_result={"ok": True, "result": result}, read_call=actor).as_dict()
        evidence["verification"] = verified
        created_id = result["id"]
        rows = actor("ak.wwise.core.object.get", {"from": {"id": [created_id]}}, {"return": ["id", "name", "type", "path", "Min", "Max", "InitialValue"]})["return"]
        evidence["independent_readback"] = rows
        assert len(rows) == 1 and rows[0]["Min"] == -12 and rows[0]["Max"] == 36 and rows[0]["InitialValue"] == 7
        assert verified["status"] == "verified", verified
        status, reason = "PASS", "same-call native create and independent range/default readback succeeded"
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        evidence["error"] = reason
        raise
    finally:
        actor_closed = True
        if actor is not None:
            evidence["native_calls"] = actor.calls
            try:
                actor_closed = actor.close() and actor.fully_closed
            except BaseException as exc:
                actor_closed = False
                evidence["actor_close_error"] = str(exc)
            if not actor_closed:
                status, reason = "BLOCKED", "owned direct actor did not close"
        if runtime is not None:
            (runtime.evidence_root / "gameparameter-native.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
            result = lifecycle.finish(status, reason="" if status == "PASS" else reason)
            assert result.final_status == status and actor_closed, result.as_dict()

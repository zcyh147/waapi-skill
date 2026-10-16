"""Public ShareSet lifecycle in an owned, private-HOME Wwise sandbox.

Run one configured version at a time with a new WAAPI_SHARESET_PROBE_ROOT.
The existing readiness gate and ScenarioLifecycle remain authoritative.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle

pytestmark = [pytest.mark.live, pytest.mark.destructive]


def test_standalone_shareset_public_gateway_lifecycle():
    version = os.environ["WWISE_VERSION"]
    root_text = os.environ.get("WAAPI_SHARESET_PROBE_ROOT")
    if not root_text:
        pytest.skip("requires a new explicit WAAPI_SHARESET_PROBE_ROOT")
    root = Path(root_text)
    assert root.is_absolute(), "probe root must be absolute"
    assert version in {"2022.1", "2023.1", "2024.1", "2025.1"}
    private_home = root / "owned" / "wwise-user-home" if sys.platform == "darwin" else None
    prefix = private_home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64" if private_home else None
    lifecycle = ScenarioLifecycle(
        scenario_id=f"shareset-gateway-{version}", version=version,
        scenario_root=root, live_environment=dict(os.environ),
        launch_environment_overrides={"HOME": str(private_home)} if private_home else None,
        owned_wine_prefix=prefix,
    )
    script = Path(__file__).resolve().parents[2] / "skills/waapi-skill/scripts/gateway.py"
    spec = importlib.util.spec_from_file_location("shareset_native_gateway", script)
    assert spec is not None and spec.loader is not None
    gateway = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gateway
    spec.loader.exec_module(gateway)
    runtime = actor = None
    status, reason = "FAIL", "ShareSet Gateway lifecycle did not complete"
    evidence = {"kind": "public-gateway-native-shareset", "version": version, "agent_semantic_pass": False, "receipts": []}
    try:
        runtime = lifecycle.start()
        env = {**os.environ, "WAAPI_SKILL_CONFIG_PATH": str(root / "owned/gateway/config.json"),
               "WAAPI_SKILL_STATE_DIR": str(root / "owned/gateway/state")}
        def run(*argv):
            code, result = gateway.execute_gateway(list(argv), env=env)
            evidence["receipts"].append({"argv": list(argv), "exit_code": code, "result": result})
            assert code == 0, result
            return result
        run("config-set", "--wwise-version", version, "--waapi-host", runtime.host,
            "--waapi-port", str(runtime.port), "--project-modification-policy", "ask_before_changes")
        result = run("draft-start", "object.createPlugin")
        draft_id, authority = result["draft"]["draft_id"], result["task_authority"]
        def step(command, *fields):
            nonlocal result
            result = run(command, draft_id, "--task-authority", authority,
                         "--expected-revision", str(result["draft"]["revision"]), *fields)
            return result
        bound = step("draft-bind-object", "--object-path-segment", "Effects", "--object-path-segment", "Default Work Unit")
        types = step("draft-discover-types", "--role", "effect", "--meaning", "Wwise RoomVerb")
        assert len(types["type_candidates"]) == 1, types
        candidate = types["type_candidates"][0]
        name = "WAAPI_Standalone_ShareSet"
        step("draft-declare-existing", "--declaration-id", "shareset", "--object-handle", bound["bound_object"]["handle"],
             "--field", "plugin_role", "effect", "--field", "plugin_placement", "shareset", "--field", "plugin_name", name,
             "--field", "plugin_type_handle", candidate["handle"])
        step("draft-check")
        preview = step("preview-from-draft")
        transaction_id = preview["transaction_id"]
        shown = run("transaction-show", transaction_id)
        run("confirm", transaction_id, "--confirmation-token", shown["confirmation"]["token"])
        run("execute", transaction_id)
        verified = run("verify", transaction_id)
        assert verified["state"] == "verified", verified
        actor = OwnedDirectWaapiCall(host=runtime.host, port=runtime.port)
        catalog = actor("ak.wwise.core.object.getTypes", {}, {})["return"]
        matches = [row for row in catalog if row["name"] == candidate["label"] and row["type"].casefold() == "effect"]
        assert len(matches) == 1, matches
        parent = actor("ak.wwise.core.object.get", {"from": {"path": [r"\Effects\Default Work Unit"]}}, {"return": ["id", "type", "path"]})["return"]
        rows = actor("ak.wwise.core.object.get", {"from": {"path": [rf"\Effects\Default Work Unit\{name}"]}}, {"return": ["id", "name", "type", "classId", "parent", "path"]})["return"]
        evidence["independent_readback"] = {"parent": parent, "shareset": rows, "plugin_type": matches}
        assert len(parent) == len(rows) == 1
        assert parent[0]["type"] == "WorkUnit"
        assert rows[0]["name"] == name and rows[0]["type"] in {"Effect", "EffectPlugin"}
        assert rows[0]["classId"] == matches[0]["classId"]
        actual_parent = rows[0]["parent"]
        assert (actual_parent["id"] if isinstance(actual_parent, dict) else actual_parent) == parent[0]["id"]
        status, reason = "PASS", "public ShareSet lifecycle and independent parent/plugin readback succeeded"
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        evidence["error"] = reason
        raise
    finally:
        actor_closed = True
        if actor is not None:
            evidence["independent_calls"] = actor.calls
            try:
                actor_closed = actor.close() and actor.fully_closed
            except BaseException as exc:
                actor_closed = False
                evidence["actor_close_error"] = str(exc)
            if not actor_closed:
                status, reason = "BLOCKED", "owned readback actor did not close"
        if runtime is not None:
            (runtime.evidence_root / "shareset-gateway-native.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
            result = lifecycle.finish(status, reason="" if status == "PASS" else reason)
            assert result.final_status == status and actor_closed, result.as_dict()

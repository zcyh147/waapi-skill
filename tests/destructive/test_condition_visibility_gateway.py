"""Native Show semantics through owned, separately previewed Gateway edits."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tests.destructive.test_attenuation_activation_gateway import PublicDraft, create_object, set_property
from tests.destructive.support.category_evidence import exact_transaction_outcomes
from tests.destructive.support.condition_finalization import prepare_condition_finalization
from tests.support.condition_branch_evidence import prepare_condition_native_capture
from tests.semantic.support.codex_expansion_runtime import fixture_gateway
from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle

pytestmark = [pytest.mark.live, pytest.mark.destructive]
UNLINKED = "{00000000-0000-0000-0000-000000000000}"


def _create_child(gateway, parent, kind, name):
    draft = PublicDraft(gateway, "object.create")
    parent_handle = draft.bind(parent)
    type_handle = draft.step("draft-discover-types", "--role", "object", "--meaning", kind)["type_candidates"][0]["handle"]
    draft.step("draft-declare-new", "--declaration-id", "owned", "--parent-handle", parent_handle,
               "--name", name, "--kind", type_handle)
    _, verified = draft.finish()
    return verified["agent_result"]["business_result"]["verified_root"]["id"]


def _row(actor, object_id, fields):
    rows = actor("ak.wwise.core.object.get", {"from": {"id": [object_id]}}, {"return": ["id", "name", "type", "path", "notes", *fields]})["return"]
    assert len(rows) == 1 and rows[0]["id"] == object_id
    return rows[0]


@pytest.mark.parametrize("relation", ["Self", "Parent"])
def test_show_visibility_does_not_change_native_prerequisite(relation, request):
    started_at_unix_ns = time.time_ns()
    version = os.environ["WWISE_VERSION"]
    root = Path(os.environ["WAAPI_CONDITION_PROBE_ROOT"]).resolve() / relation.lower()
    capture = prepare_condition_native_capture(root / "evidence" / "branch-evidence", request.node.nodeid, version, relation)
    private_home = root / "owned" / "wwise-user-home" if sys.platform == "darwin" else None
    prefix = private_home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64" if private_home else None
    lifecycle = ScenarioLifecycle(
        scenario_id=f"condition-show-{relation.lower()}-{version}", version=version,
        scenario_root=root, live_environment=dict(os.environ),
        launch_environment_overrides={"HOME": str(private_home)} if private_home else None,
        owned_wine_prefix=prefix,
        lock_root=Path(os.environ.get("WAAPI_CONDITION_LOCK_ROOT",
                       "/Users/xiye/Documents/Git/waapi-skills/.waapi-skill-state/runtime/wwise-live-lifecycle-lock")),
    )
    runtime = actor = None
    status, reason = "FAIL", "native visibility probe did not complete"
    evidence = {"kind": "public-gateway-condition-visibility", "version": version,
                "relation": relation, "agent_semantic_pass": False,
                "gateway_receipts": [], "observations": []}
    source = controller = prerequisite = field = None
    try:
        runtime = lifecycle.start()
        actor = OwnedDirectWaapiCall(host=runtime.host, port=runtime.port)
        evidence["host"] = actor("ak.wwise.core.getInfo", {}, {})
        evidence["candidate"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parents[2], text=True).strip()
        gateway = fixture_gateway(skill_source=Path(__file__).parents[2] / "skills/waapi-skill",
                                  runtime=runtime, version=version, receipts=evidence["gateway_receipts"])
        gateway(["config-set", "--wwise-version", version, "--waapi-host", runtime.host,
                 "--waapi-port", str(runtime.port), "--project-modification-policy", "ask_before_changes"])
        if relation == "Self":
            source = controller = create_object(gateway, "GameParameter", "WAAPI_Show_Ramping", "Game Parameters")
            prerequisite, field = "RTPCRamping", "SlewRateUp"
        else:
            controller = create_object(gateway, "RandomSequenceContainer", "WAAPI_Show_Parent",
                                       "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy")
            source = _create_child(gateway, controller, "Sound", "WAAPI_Show_Weight")
            prerequisite, field = "RandomOrSequence", "Weight"
        evidence.update(source_id=source, controller_id=controller, field=field, prerequisite=prerequisite)
        evidence["metadata"] = actor("ak.wwise.core.object.getPropertyInfo", {"object": source, "property": field}, {})
        dependencies = evidence["metadata"]["dependencies"]
        assert any(row.get("action") == "Show" and row.get("context") == relation
                   and row.get("property") == prerequisite for row in dependencies), dependencies
        for index, mode in enumerate((0, 1)):
            controller_before = _row(actor, controller, [prerequisite])
            if controller_before[prerequisite] != mode:
                set_property(gateway, controller, prerequisite, mode)
            before = _row(actor, source, [field])
            controller_before = _row(actor, controller, [prerequisite])
            enabled = actor("ak.wwise.core.object.isPropertyEnabled", {
                "object": source, "property": field, "platform": UNLINKED}, {})
            observation = {"mode": mode, "before": before, "controller_before": controller_before,
                           "is_property_enabled": enabled,
                           "metadata_before": actor("ak.wwise.core.object.getPropertyInfo", {"object": source, "property": field}, {}),
                           "controller_metadata_before": actor("ak.wwise.core.object.getPropertyInfo", {"object": controller, "property": prerequisite}, {})}
            evidence["observations"].append(observation)
            value = 37 + index
            set_property(gateway, source, field, value)
            after = _row(actor, source, [field])
            controller_after = _row(actor, controller, [prerequisite])
            observation.update(after=after, controller_after=controller_after, requested_value=value)
            observation["metadata_after"] = actor("ak.wwise.core.object.getPropertyInfo", {"object": source, "property": field}, {})
            observation["controller_metadata_after"] = actor("ak.wwise.core.object.getPropertyInfo", {"object": controller, "property": prerequisite}, {})
            assert after[field] == value
            assert controller_after == controller_before
            assert all(after[key] == before[key] for key in ("id", "name", "type", "path", "notes"))
        status, reason = "PASS", "Show-off and Show-on writes preserved the explicit prerequisite state"
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        evidence["error"] = reason
        raise
    finally:
        closed = True
        if actor is not None:
            # A native rejection is an observation too. Preserve bounded final
            # state without replaying a failed or uncertain mutation.
            if source is not None and controller is not None and field is not None and prerequisite is not None:
                try:
                    evidence["final_state"] = {
                        "source": _row(actor, source, [field]),
                        "controller": _row(actor, controller, [prerequisite]),
                        "metadata": actor("ak.wwise.core.object.getPropertyInfo", {"object": source, "property": field}, {}),
                        "controller_metadata": actor("ak.wwise.core.object.getPropertyInfo", {"object": controller, "property": prerequisite}, {}),
                    }
                except BaseException as exc:
                    evidence["final_state_error"] = f"{type(exc).__name__}: {exc}"
            evidence["oracle_calls"] = actor.calls
            closed = actor.close() and actor.fully_closed
            if not closed:
                status, reason = "BLOCKED", "owned oracle did not close"
        if runtime is not None:
            transactions = []
            observation_path = runtime.evidence_root / "condition-visibility.json"
            try:
                transactions = exact_transaction_outcomes(runtime.owned_root / "setup-state")
                observation_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
            except BaseException as exc:
                status, reason = "BLOCKED", f"evidence finalization: {type(exc).__name__}: {exc}"
            finally:
                if "host" in evidence and "candidate" in evidence:
                    result = prepare_condition_finalization(
                        item=request.node, owner=lifecycle, status=status, reason=reason,
                        repo_root=Path(__file__).parents[2], candidate=evidence["candidate"], version=version,
                        started_at_unix_ns=started_at_unix_ns, host=evidence["host"],
                        observation_path=observation_path, transactions=transactions, capture=capture)
                else:
                    result = lifecycle.finish(status, reason=reason)
            expected = "PREPARED" if status == "PASS" else status
            assert result.final_status == expected and closed, result.as_dict()
            assert status == "PASS", reason

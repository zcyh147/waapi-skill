"""Public attenuation association in an owned, source-preserving Wwise sandbox."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from tests.semantic.support.codex_expansion_runtime import fixture_gateway
from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
from tests.semantic.support.codex_scenario_lifecycle_v3 import ScenarioLifecycle

pytestmark = [pytest.mark.live, pytest.mark.destructive]


class PublicDraft:
    def __init__(self, gateway, operation):
        self.gateway = gateway
        started = gateway(["draft-start", operation])
        self.draft, self.authority = started["draft"], started["task_authority"]

    def step(self, command, *arguments):
        reply = self.gateway([command, self.draft["draft_id"], "--task-authority", self.authority,
                              "--expected-revision", str(self.draft["revision"]), *arguments])
        self.draft = reply.get("draft", self.draft)
        return reply

    def bind(self, object_id):
        return self.step("draft-bind-object", "--object-id", object_id)["bound_object"]["handle"]

    def field(self, target, meaning):
        return self.step("draft-discover-fields", "--object-handle", target,
                         "--meaning", meaning)["meaning_results"][0]["candidates"][0]["handle"]

    def finish(self):
        self.step("draft-check")
        preview = self.step("preview-from-draft")
        tx = preview["transaction_id"]
        shown = self.gateway(["transaction-show", tx])
        self.gateway(["confirm", tx, "--confirmation-token", shown["confirmation"]["token"]])
        self.gateway(["execute", tx])
        verified = self.gateway(["verify", tx])
        assert verified["verified"] is True
        assert list(preview)[-1] == list(verified)[-1] == "agent_result"
        return preview, verified


def create_object(gateway, kind, name, hierarchy):
    draft = PublicDraft(gateway, "object.create")
    parent = draft.step("draft-bind-object", "--object-path-segment", hierarchy,
                        "--object-path-segment", "Default Work Unit")["bound_object"]["handle"]
    type_handle = draft.step("draft-discover-types", "--role", "object", "--meaning", kind)["type_candidates"][0]["handle"]
    draft.step("draft-declare-new", "--declaration-id", "owned", "--parent-handle", parent,
               "--name", name, "--kind", type_handle)
    _, verified = draft.finish()
    return verified["agent_result"]["business_result"]["verified_root"]["id"]


def test_attenuation_activation_public_gateway_native():
    _run_attenuation_native(false_routing=False)


def test_attenuation_activation_false_routing_public_gateway_native():
    assert os.environ["WWISE_VERSION"] == "2025.1"
    _run_attenuation_native(false_routing=True)


def set_property(gateway, source, name, value):
    draft = PublicDraft(gateway, "object.setProperty")
    target = draft.bind(source)
    field = draft.field(target, name)
    draft.step("draft-declare-field-change", "--object-handle", target,
               "--field-handle", field, "--business-value", json.dumps(value))
    draft.finish()


def _run_attenuation_native(*, false_routing):
    version = os.environ["WWISE_VERSION"]
    root = Path(os.environ["WAAPI_ATTENUATION_PROBE_ROOT"]).resolve()
    private_home = root / "owned" / "wwise-user-home" if sys.platform == "darwin" else None
    prefix = private_home / "Library/Application Support/Wwise2019/Bottles/Wwise2019x64" if private_home else None
    lifecycle = ScenarioLifecycle(
        scenario_id=f"attenuation-public-{version}", version=version, scenario_root=root,
        live_environment=dict(os.environ),
        launch_environment_overrides={"HOME": str(private_home)} if private_home else None,
        owned_wine_prefix=prefix,
    )
    runtime = actor = None
    status, reason = "FAIL", "public attenuation test did not complete"
    evidence = {"kind": "public-gateway-attenuation", "version": version,
                "agent_semantic_pass": False, "false_routing_variant": false_routing,
                "gateway_receipts": [], "objects": []}
    try:
        runtime = lifecycle.start()
        actor = OwnedDirectWaapiCall(host=runtime.host, port=runtime.port)
        gateway = fixture_gateway(skill_source=Path(__file__).parents[2] / "skills/waapi-skill",
                                  runtime=runtime, version=version, receipts=evidence["gateway_receipts"])
        gateway(["config-set", "--wwise-version", version, "--waapi-host", runtime.host,
                 "--waapi-port", str(runtime.port), "--project-modification-policy", "ask_before_changes"])
        attenuation = create_object(gateway, "Attenuation", "WAAPI_Near", "Attenuations")
        fields = ["id", "name", "type", "path", "Attenuation", "ListenerRelativeRouting", "OverridePositioning", "Volume", "notes"]
        for kind in ("Sound", "RandomSequenceContainer"):
            source = create_object(gateway, kind, "WAAPI_" + kind,
                                   "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy")
            if false_routing and kind == "Sound":
                # Three explicit, separately verified fixture transactions make
                # both activation requirements missing before the tested call.
                set_property(gateway, source, "OverridePositioning", True)
                set_property(gateway, source, "ListenerRelativeRouting", False)
                set_property(gateway, source, "OverridePositioning", False)
            before = actor("ak.wwise.core.object.get", {"from": {"id": [source]}}, {"return": fields})["return"][0]
            if false_routing and kind == "Sound":
                assert before["ListenerRelativeRouting"] is False
                assert before["OverridePositioning"] is False
            metadata = {field: actor("ak.wwise.core.object.getPropertyInfo", {"object": source, "property": field}, {})
                        for field in ("Attenuation", "ListenerRelativeRouting", "OverridePositioning")}
            record = {"kind": kind, "before": before, "metadata": metadata}
            evidence["objects"].append(record)
            if version == "2021.1":
                for name in ("OverridePositioning", "ListenerRelativeRouting"):
                    if before[name] is True:
                        continue
                    set_property(gateway, source, name, True)
            draft = PublicDraft(gateway, "object.setReference" if version == "2021.1" else "object.set")
            target, reference = draft.bind(source), draft.bind(attenuation)
            field = draft.field(target, "Attenuation")
            if version == "2021.1":
                draft.step("draft-declare-field-change", "--object-handle", target,
                           "--field-handle", field, "--target-handle", reference)
            else:
                draft.step("draft-declare-existing", "--declaration-id", "association",
                           "--object-handle", target, "--field-value", field, reference)
            preview, verified = draft.finish()
            after = actor("ak.wwise.core.object.get", {"from": {"id": [source]}}, {"return": fields})["return"][0]
            record.update({"preview": preview, "after": after})
            assert after["Attenuation"]["id"] == attenuation
            assert after["ListenerRelativeRouting"] is True and after["OverridePositioning"] is True
            assert all(after[name] == before[name] for name in ("id", "name", "type", "path", "Volume", "notes"))
            if version != "2021.1":
                expected = {name for name in ("ListenerRelativeRouting", "OverridePositioning") if before[name] is not True}
                changes = preview["preview_summary"].get("derived_changes", [])
                assert {row["field"] for row in changes} == expected
                assert all(row["value"] is True for row in changes)
        status, reason = "PASS", "public association and independent positioning/preservation readback succeeded"
    except BaseException as exc:
        reason = f"{type(exc).__name__}: {exc}"
        evidence["error"] = reason
        raise
    finally:
        closed = True
        if actor is not None:
            evidence["oracle_calls"] = actor.calls
            closed = actor.close() and actor.fully_closed
            if not closed:
                status, reason = "BLOCKED", "owned oracle did not close"
        if runtime is not None:
            (runtime.evidence_root / "attenuation-public.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
            result = lifecycle.finish(status, reason="" if status == "PASS" else reason)
            assert result.final_status == status and closed, result.as_dict()

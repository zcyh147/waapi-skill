"""Clear one dormant stored reference while retaining its inherited value."""
import hashlib
import json
import os

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object,
    _complete_business_draft,
    _discover_business_field,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)


pytestmark = [
    pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get("WWISE_VERSION") != "2025.1",
        reason="Targeted inactive-clear effect; reference read modes have separate five-version acceptance"),
]
SOUND = "{0030BF58-90C3-428B-B940-44CC1C5A51B5}"
ANCESTOR = "{B5DB3AFA-044F-441E-BC4A-1397D20E2692}"
PEER = "{63715E20-32E0-4D02-B0D7-B510915A8A01}"
LOCAL_ATTENUATION = "{C8288DEA-9716-4647-A5DE-6FFB5FD78D75}"
RESOLVED_ATTENUATION = "{DD088B98-4DAD-4C54-B1EE-CA3427643E93}"
ZERO_GUID = "{00000000-0000-0000-0000-000000000000}"


def test_clear_dormant_attenuation_preserves_inheritance_and_peer(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == (2025, 1, 7, 9143)
    output = runtime.state_dir / "inherited-reference-clear.json"
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "operation": "object.setReference", "reads": [], "transactions": [],
        "business_effect_verified": False}
    category = {"category": "clear-dormant-reference", "status": "FAIL",
        "verifier_strength": "stored_clear_with_inherited_reference_and_peer_preservation",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, identity):
        assert len(observation["reads"]) < 6
        argv = ["query-object", "--exact-id", identity, "--max-results", "2", "--detail",
            "--include", "notes", "--include", "parent"]
        for meaning in ("Attenuation", "OutputBus"):
            argv.extend(["--include-field", meaning, "--include-local-reference", meaning])
        for meaning in ("OverridePositioning", "ListenerRelativeRouting"):
            argv.extend(["--include-field", meaning])
        code, payload = runtime.raw_gateway(argv)
        observation["reads"].append({"label": label, "argv": argv, "exit_code": code, "payload": payload})
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") != "partial", payload
        assert list(payload)[-1] == "agent_result"
        rows = payload["agent_result"]
        assert isinstance(rows, list) and len(rows) == 1 and rows[0]["id"] == identity, rows
        return rows[0]

    try:
        before = read("source-before", SOUND)
        ancestor = read("ancestor-before", ANCESTOR)
        peer = read("peer-before", PEER)
        assert before["type"] == "Sound" and before["name"] == "Footstep_Crouching_Concrete_01"
        assert before["properties"]["OverridePositioning"] is False
        assert before["local_references"]["Attenuation"]["id"] == LOCAL_ATTENUATION
        assert before["references"]["Attenuation"]["id"] == RESOLVED_ATTENUATION
        assert ancestor["references"]["Attenuation"]["id"] == RESOLVED_ATTENUATION

        draft = _start_business_draft(runtime, "object.setReference")
        owner = _bind_business_object(runtime, draft, object_id=SOUND)
        field = _discover_business_field(runtime, draft, object_handle=owner, meaning="Attenuation")
        _update_business_draft(runtime, draft, "draft-declare-field-change",
            ["--object-handle", owner, "--field-handle", field, "--clear-reference"], live=False)
        receipt = _complete_business_draft(runtime, draft,
            inspect_preview=lambda preview: observation.update(preview_before_authorization=preview))
        observation["transactions"].append(receipt)

        after = read("source-after", SOUND)
        cleared = after["local_references"]["Attenuation"]
        cleared_id = cleared.get("id") if isinstance(cleared, dict) else cleared
        assert cleared is None or cleared_id == ZERO_GUID, cleared
        assert after == {**before, "local_references": {**before["local_references"], "Attenuation": cleared}}
        assert read("ancestor-after", ANCESTOR) == ancestor
        assert read("peer-after", PEER) == peer
        assert len(observation["transactions"]) == 1
        observation["business_effect_verified"] = True
        status = "PASS"
    except BaseException as exc:
        observation["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest())

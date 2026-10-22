"""Read persisted and override-resolved references without changing the project."""
import hashlib
import json
from pathlib import Path

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime


pytestmark = [pytest.mark.live, pytest.mark.destructive]
BUILDS = {
    "2021.1": (2021, 1, 14, 8108), "2022.1": (2022, 1, 19, 8584),
    "2023.1": (2023, 1, 19, 8928), "2024.1": (2024, 1, 13, 9056),
    "2025.1": (2025, 1, 7, 9143),
}
SOUND = "{0030BF58-90C3-428B-B940-44CC1C5A51B5}"
ANCESTOR = "{B5DB3AFA-044F-441E-BC4A-1397D20E2692}"
LOCAL_BUS = "{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}"
RESOLVED_BUS = "{ED2BCAC8-D7B6-4448-8900-439B557894F4}"
LOCAL_ATTENUATION = "{C8288DEA-9716-4647-A5DE-6FFB5FD78D75}"
RESOLVED_ATTENUATION = "{DD088B98-4DAD-4C54-B1EE-CA3427643E93}"


def test_local_and_resolved_output_bus_references_remain_distinct(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "query-local-reference.json"
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "read_only": True, "reads": [], "business_effect_verified": False}
    category = {"category": "query-local-and-resolved-reference", "status": "FAIL",
        "verifier_strength": "distinct_native_public_references_and_exact_bus_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, identity, *, references=False):
        assert len(observation["reads"]) < 5
        argv = ["query-object", "--exact-id", identity, "--max-results", "2", "--detail"]
        if references:
            for meaning in ("OutputBus", "Attenuation"):
                argv.extend(["--include-field", meaning, "--include-local-reference", meaning])
            argv.extend(["--include-field", "OverridePositioning"])
        code, payload = runtime.raw_gateway(argv)
        record = {"label": label, "argv": argv, "exit_code": code, "payload": payload}
        observation["reads"].append(record)
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") != "partial", payload
        assert list(payload)[-1] == "agent_result"
        rows = payload["agent_result"]
        assert isinstance(rows, list) and len(rows) == 1 and rows[0]["id"] == identity, rows
        evidence = Path(payload["call"]["evidence_path"]).resolve(strict=True)
        assert evidence.is_relative_to(runtime.state_dir.parent.resolve())
        raw = evidence.read_bytes()
        assert len(raw) < 1024 * 1024
        packet = json.loads(raw)
        assert packet["ok"] is True and packet["api"] == "ak.wwise.core.object.get"
        native = packet["result"]["return"]
        assert len(native) == 1 and native[0]["id"] == identity, native
        record["native"] = {"path": str(evidence), "sha256": hashlib.sha256(raw).hexdigest(), "row": native[0]}
        if references:
            assert rows[0]["local_references"] == {
                field: native[0]["@" + field] for field in ("OutputBus", "Attenuation")}
            assert rows[0]["references"] == {
                field: native[0][field] for field in ("OutputBus", "Attenuation")}
            assert rows[0]["properties"]["OverridePositioning"] is native[0]["@OverridePositioning"]
        return rows[0]

    try:
        sound = read("sound-before", SOUND, references=True)
        assert sound["type"] == "Sound" and sound["name"] == "Footstep_Crouching_Concrete_01"
        assert sound["local_references"]["OutputBus"]["id"] == LOCAL_BUS
        assert sound["references"]["OutputBus"]["id"] == RESOLVED_BUS
        assert sound["local_references"]["Attenuation"]["id"] == LOCAL_ATTENUATION
        assert sound["references"]["Attenuation"]["id"] == RESOLVED_ATTENUATION
        assert sound["properties"]["OverridePositioning"] is False
        ancestor = read("override-source", ANCESTOR, references=True)
        assert ancestor["type"] == "SwitchContainer" and ancestor["name"] == "Footstep_Types"
        assert ancestor["local_references"]["OutputBus"]["id"] == RESOLVED_BUS
        assert ancestor["references"]["OutputBus"]["id"] == RESOLVED_BUS
        assert ancestor["local_references"]["Attenuation"]["id"] == RESOLVED_ATTENUATION
        assert ancestor["references"]["Attenuation"]["id"] == RESOLVED_ATTENUATION
        local_bus = read("local-bus-identity", LOCAL_BUS)
        assert local_bus["type"] == "Bus"
        assert local_bus["name"] == ("Main Audio Bus" if runtime.version == "2025.1" else "Master Audio Bus")
        resolved_bus = read("resolved-bus-identity", RESOLVED_BUS)
        assert resolved_bus["type"] == "Bus" and resolved_bus["name"] == "SFX"
        assert read("sound-after", SOUND, references=True) == sound
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

"""Read both property value sources in the existing owned five-version fixture."""
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
SOUND = "{55BB4B28-88A8-4EA6-AFE1-1B1F63776E31}"
PARENT = "{69B63CDA-3CCD-4246-982E-C1104DE15720}"


def test_property_object_and_override_source_values_remain_distinct(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "query-override-source-values.json"
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "read_only": True, "reads": [], "business_effect_verified": False}
    category = {"category": "query-property-override-source-values", "status": "FAIL",
        "verifier_strength": "distinct_native_and_public_values_with_parent_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, identity):
        assert len(observation["reads"]) < 3
        argv = ["query-object", "--exact-id", identity, "--max-results", "2", "--detail",
            "--include", "parent", "--include-field", "3DSpatialization",
            "--include-field", "OverridePositioning", "--include-override-source-value", "3DSpatialization"]
        code, payload = runtime.raw_gateway(argv)
        record = {"label": label, "argv": argv, "exit_code": code, "payload": payload}
        observation["reads"].append(record)
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") != "partial", payload
        assert list(payload)[-1] == "agent_result", payload
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
        row = rows[0]
        assert row["properties"]["3DSpatialization"] == native[0]["@3DSpatialization"]
        assert row["properties"]["OverridePositioning"] is native[0]["@OverridePositioning"]
        assert row["override_source_values"]["3DSpatialization"] == native[0]["@@3DSpatialization"]
        return row

    try:
        child = read("child-before", SOUND)
        parent = read("parent", PARENT)
        assert child["type"] == "Sound" and child["name"] == "SLS_CAR_PassBy_DirtGravelRoad_01"
        assert child["parent"]["id"] == PARENT
        assert parent["type"] == "RandomSequenceContainer" and parent["name"] == "City Traffic"
        assert child["properties"] == {"3DSpatialization": 0, "OverridePositioning": False}
        assert child["override_source_values"] == {"3DSpatialization": 2}
        assert parent["properties"] == {"3DSpatialization": 2, "OverridePositioning": True}
        assert parent["override_source_values"] == {"3DSpatialization": 2}
        assert read("child-after", SOUND) == child
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

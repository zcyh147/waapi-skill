"""Read local and parent values in one projection without changing root identity."""
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
PARENT = "{D5594A4B-DDB0-47F3-AC2F-08F104C72438}"


def test_related_parent_values_preserve_root_identity(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "query-related-outputs.json"
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "read_only": True, "reads": [], "business_effect_verified": False}
    category = {"category": "query-related-parent-outputs", "status": "FAIL",
        "verifier_strength": "native_public_parent_values_and_independent_parent_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, identity, *, related=False):
        assert len(observation["reads"]) < 3
        argv = ["query-object", "--exact-id", identity, "--max-results", "2", "--detail",
            "--include", "volume-db", "--include", "pitch-cents"]
        if related:
            for meaning in ("volume-db", "pitch-cents"):
                argv.extend(["--include-related", "parent", meaning])
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
        for field, token in (("volume_db", "@Volume"), ("pitch_cents", "@Pitch")):
            assert rows[0][field] == native[0][token]
            if related:
                assert rows[0]["related"]["parent"][field] == native[0]["parent." + token]
        if related:
            assert rows[0]["related"]["parent"]["object"] == native[0]["parent"]
        return rows[0]

    try:
        sound = read("sound-before", SOUND, related=True)
        assert sound["type"] == "Sound" and sound["name"] == "Footstep_Crouching_Concrete_01"
        parent = sound["related"]["parent"]
        assert parent["object"]["id"] == PARENT and parent["object"]["name"] == "FS_Concrete"
        assert parent["volume_db"] == -12 and parent["pitch_cents"] == -560
        assert sound["volume_db"] != parent["volume_db"] and sound["pitch_cents"] != parent["pitch_cents"]
        exact_parent = read("parent-independent", PARENT)
        assert exact_parent["name"] == "FS_Concrete"
        assert exact_parent["volume_db"] == parent["volume_db"]
        assert exact_parent["pitch_cents"] == parent["pitch_cents"]
        assert read("sound-after", SOUND, related=True) == sound
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

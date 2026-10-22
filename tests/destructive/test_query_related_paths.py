"""One read-only witness for fixed paths, scoped fields and a reference hop."""
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
AUDIO_SOURCE = "{806D447C-2AC4-4A6C-89DB-9D6DAFA7B5CF}"
SOUND = "{0030BF58-90C3-428B-B940-44CC1C5A51B5}"
CONTAINER = "{D5594A4B-DDB0-47F3-AC2F-08F104C72438}"
LOCAL_BUS = "{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}"
RESOLVED_BUS = "{ED2BCAC8-D7B6-4448-8900-439B557894F4}"


def test_scoped_related_paths_match_independent_objects(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "query-related-paths.json"
    assert not output.exists()
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "read_only": True, "reads": [], "business_effect_verified": False}
    category = {"category": "query-related-paths-and-scoped-fields", "status": "FAIL",
        "verifier_strength": "native_public_paths_and_actual_class_scope_with_independent_object_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, identity, projection):
        assert len(observation["reads"]) < 4
        argv = ["query-object", "--exact-id", identity, "--max-results", "2", "--detail", *projection]
        code, payload = runtime.raw_gateway(argv)
        record = {"label": label, "argv": argv, "exit_code": code, "payload": payload}
        observation["reads"].append(record)
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") not in {"partial", "needs_clarification"}, payload
        assert list(payload)[-1] == "agent_result"
        rows = payload["agent_result"]
        assert isinstance(rows, list) and len(rows) == 1 and rows[0]["id"] == identity, rows
        evidence = Path(payload["call"]["evidence_path"]).resolve(strict=True)
        assert evidence.is_relative_to(runtime.state_dir.parent.resolve())
        body = evidence.read_bytes()
        assert len(body) < 1024 * 1024
        packet = json.loads(body)
        assert packet["ok"] is True and packet["api"] == "ak.wwise.core.object.get"
        native, = packet["result"]["return"]
        assert native["id"] == identity
        record["native"] = {"path": str(evidence), "sha256": hashlib.sha256(body).hexdigest(), "row": native}
        return rows[0], native, payload

    source_projection = [
        "--include-related", "parent", "parent", "volume-db",
        "--include-related-field", "parent", "Pitch",
        "--include-related-field", "parent", "OutputBus",
        "--include-related-local-reference", "parent", "OutputBus",
        "--include-related", "parent", "reference", "OutputBus", "volume-db",
    ]
    try:
        source, native, payload = read("source-before", AUDIO_SOURCE, source_projection)
        assert source["type"] == "AudioFileSource"
        parent = source["related"]["parent"]
        container = parent["related"]["parent"]
        bus = parent["related"]["references"]["OutputBus"]
        assert parent["object"]["id"] == SOUND and parent["object"] == native["parent"]
        assert container["object"]["id"] == CONTAINER and container["object"] == native["parent.parent"]
        assert container["volume_db"] == native["parent.parent.@Volume"] == -12
        assert parent["properties"]["Pitch"] == native["parent.@Pitch"]
        assert parent["references"]["OutputBus"] == native["parent.OutputBus"]
        assert parent["local_references"]["OutputBus"] == native["parent.@OutputBus"]
        assert parent["references"]["OutputBus"]["id"] == RESOLVED_BUS
        assert parent["local_references"]["OutputBus"]["id"] == LOCAL_BUS
        assert bus["object"] == native["parent.OutputBus"] and bus["object"]["id"] == RESOLVED_BUS
        assert bus["volume_db"] == native["parent.OutputBus.@Volume"]

        sound, _, _ = read("sound-independent", SOUND, [
            "--include", "class-id", "--include-field", "Pitch", "--include-field", "OutputBus",
            "--include-local-reference", "OutputBus", "--include-related", "parent", "volume-db"])
        assert sound["properties"]["Pitch"] == parent["properties"]["Pitch"]
        assert sound["references"]["OutputBus"] == parent["references"]["OutputBus"]
        assert sound["local_references"]["OutputBus"] == parent["local_references"]["OutputBus"]
        assert sound["related"]["parent"] == container
        proof = payload["related_scope_binding"]
        assert proof["observed_rows"][0]["parent.classId"] == native["parent.classId"] == sound["class_id"]
        selected = [row for row in proof["scopes"] if row.get("path") == "parent" and row.get("selected")]
        assert {row["selected"]["name"] for row in selected} == {"Pitch", "OutputBus"}, selected
        for row in selected:
            assert row["scope"] == {"classId": sound["class_id"]}, row
            assert row["selected"]["kind"] == ("property" if row["selected"]["name"] == "Pitch" else "reference"), row

        exact_bus, bus_native, _ = read("bus-independent", RESOLVED_BUS, ["--include", "volume-db"])
        assert exact_bus["type"] == "Bus" and exact_bus["name"] == "SFX"
        assert exact_bus["volume_db"] == bus_native["@Volume"] == bus["volume_db"]
        repeated, _, _ = read("source-after", AUDIO_SOURCE, source_projection)
        assert repeated == source
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

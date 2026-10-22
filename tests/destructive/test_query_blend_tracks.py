"""Read existing Blend Tracks through the closed, versioned public projection."""
import hashlib
import json
from pathlib import Path

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime


pytestmark = [pytest.mark.live, pytest.mark.destructive]
BUILDS = {"2024.1": (2024, 1, 13, 9056), "2025.1": (2025, 1, 7, 9143)}
OWNER = "{97A58685-6231-4227-9BAB-451E089615A8}"
TRACKS = {
    "{8D76C40F-1C73-42C7-9A26-8C0E56E6898F}": "On-Load",
    "{8650F5F9-E62B-4394-8729-1FF0C63A0681}": "Off-Load",
}


def test_existing_blend_tracks_are_disclosed_and_resolve(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    assert runtime.version in BUILDS, "Select the documented 2024.1/2025.1 native lanes"
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "query-blend-tracks.json"
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "read_only": True, "reads": [], "business_effect_verified": False}
    category = {"category": "query-blend-tracks", "status": "FAIL",
        "verifier_strength": "native_public_list_and_exact_track_identity_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, identity, *, tracks=False):
        assert len(observation["reads"]) < 4
        argv = ["query-object", "--exact-id", identity, "--max-results", "2", "--detail"]
        if tracks:
            argv.extend(["--include", "blend-tracks"])
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
        if tracks:
            assert rows[0]["blend_tracks"] == native[0]["blendTracks"]
        return rows[0]

    try:
        owner = read("owner-before", OWNER, tracks=True)
        assert owner["type"] == "BlendContainer" and owner["name"] == "Porsche 911 - Blend Container"
        tracks = owner["blend_tracks"]
        assert isinstance(tracks, list) and len(tracks) == 2, tracks
        assert {track["id"]: track["name"] for track in tracks} == TRACKS
        for identity, name in TRACKS.items():
            track = read("track-identity", identity)
            assert track["name"] == name and track["type"] == "BlendTrack", track
        assert read("owner-after", OWNER, tracks=True) == owner
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

"""Matching-host PlaylistSlot read using the existing owned sandbox fixture."""
import hashlib
import json
import os

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _complete_object_metadata_business_transaction,
    workflow_sandbox_runtime,
)
from tests.support.playlist_reference_observation import (
    collect_playlist_instance_identities,
    collect_playlist_slot_reference_metadata,
)


pytestmark = [
    pytest.mark.live,
    pytest.mark.destructive,
    pytest.mark.skipif(
        os.environ.get("WWISE_VERSION") != "2025.1",
        reason="Exact 2025 PlaylistSlot reference observation; older Playlist list semantics remain separate work",
    ),
]


def test_playlist_slot_reference_native_metadata(workflow_sandbox_runtime):
    version = workflow_sandbox_runtime.sandbox.metadata.get_info_version
    assert isinstance(version, dict) and tuple(
        version.get(key) for key in ("year", "major", "minor", "build")
    ) == (2025, 1, 7, 9143), version
    collect_playlist_slot_reference_metadata(workflow_sandbox_runtime)


def test_playlist_slot_native_identity(workflow_sandbox_runtime):
    version = workflow_sandbox_runtime.sandbox.metadata.get_info_version
    assert isinstance(version, dict) and tuple(
        version.get(key) for key in ("year", "major", "minor", "build")
    ) == (2025, 1, 7, 9143), version
    collect_playlist_instance_identities(workflow_sandbox_runtime)


def test_existing_playlist_slot_reference_change_preserves_peer_and_order(workflow_sandbox_runtime):
    """One reference change on existing objects in the copied SampleProject."""
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert isinstance(version, dict) and tuple(
        version.get(key) for key in ("year", "major", "minor", "build")
    ) == (2025, 1, 7, 9143), version
    slot = "{7571D6B0-D614-40B5-B02D-0012FE3743A7}"
    peer = "{6298C41E-F7C6-40B6-BFFE-E0B02EE7DC72}"
    owner = "{8C0FD1AD-E45D-408D-9BF3-874970CCC123}"
    old_target = "{0DD1BBE3-BB1E-424A-9648-BEBFBB212426}"
    target = "{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}"
    output = runtime.state_dir / "playlist-reference-effect.json"
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "reads": [], "transactions": [], "business_effect_verified": False}
    category = {"category": "existing-playlist-reference-change", "status": "FAIL",
        "verifier_strength": "independent_reference_membership_and_peer_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, selector):
        assert len(observation["reads"]) < 14
        argv = ["query-object", *selector, "--max-results", "4", "--include", "class-id",
                "--include", "owner", "--include", "parent"]
        code, payload = runtime.raw_gateway(argv)
        observation["reads"].append({"label": label, "argv": argv, "exit_code": code, "payload": payload})
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") != "partial", payload
        rows = payload.get("objects", payload.get("agent_result"))
        assert isinstance(rows, list) and len(rows) < 4, payload
        return rows

    def exact(label, identity):
        rows = read(label, ["--exact-id", identity])
        assert len(rows) == 1 and rows[0]["id"] == identity, rows
        return rows[0]

    def reference(label, identity):
        rows = read(label, ["--advanced-waql", f'from object "{identity}" select @PlaylistObject'])
        assert len(rows) == 1, rows
        return rows[0]["id"]

    def members(label):
        return read(label, ["--advanced-waql", f'from object "{owner}" select @Playlist'])

    try:
        before = {"slot": exact("before-slot", slot), "peer": exact("before-peer", peer),
                  "owner": exact("before-owner", owner), "target": exact("before-target", target)}
        observation["before"] = before
        for key in ("slot", "peer"):
            assert before[key]["name"] == "" and before[key]["type"] == "PluginInnerObject", before[key]
            assert before[key]["class_id"] == 5636096 and before[key]["owner"]["id"] == owner, before[key]
        assert before["owner"]["type"] == "RandomSequenceContainer" and before["owner"]["class_id"] == 589840
        assert before["target"]["type"] == "Sound" and before["target"]["class_id"] == 65552
        assert before["target"]["parent"]["id"] == owner
        assert reference("before-slot-target", slot) == old_target
        assert reference("before-peer-target", peer) == target
        before_members = members("before-playlist")
        assert [row["id"] for row in before_members] == [slot, peer], before_members

        receipt = _complete_object_metadata_business_transaction(
            runtime, operation="object.setReference", object_id=slot,
            field_name="PlaylistObject", target_id=target,
        )
        observation["transactions"].append(receipt)
        assert reference("after-slot-target", slot) == target
        assert reference("after-peer-target", peer) == target
        after_members = members("after-playlist")
        # Native slot display paths depend on their selected target. Material
        # identity, membership and class/owner must remain stable independently.
        stable = lambda row: {key: row[key] for key in ("id", "name", "type", "class_id", "owner")}
        assert [stable(row) for row in after_members] == [stable(row) for row in before_members]
        for key, identity in (("peer", peer), ("owner", owner), ("target", target)):
            assert exact("after-" + key, identity) == before[key]
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

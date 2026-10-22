"""Keep a container and its child values together through the public query."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime
from tests.destructive.test_query_related_paths import BUILDS


pytestmark = [pytest.mark.live, pytest.mark.destructive]
CONTAINER = "{D5594A4B-DDB0-47F3-AC2F-08F104C72438}"
CHILDREN = {
    "{0030BF58-90C3-428B-B940-44CC1C5A51B5}",
    "{63715E20-32E0-4D02-B0D7-B510915A8A01}",
    "{2098FAF4-52C6-4F61-A37C-4A53B97F7F68}",
    "{3A8D10D7-BACE-46C7-AB62-17B47EAF4DCB}",
    "{CDCCBB41-E427-4269-99C7-66FC34B49F2A}",
}


def test_related_child_records_match_independent_children(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert tuple(version.get(key) for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    output = runtime.state_dir / "query-related-lists.json"
    assert not output.exists()
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "read_only": True, "reads": [], "business_effect_verified": False}
    category = {"category": "query-related-child-records", "status": "FAIL",
        "verifier_strength": "native_member_records_and_independent_guid_value_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, projection):
        assert len(observation["reads"]) < 3
        before = set(evidence_root.glob("*.json"))
        argv = ["query-object", "--exact-id", CONTAINER, "--max-results", "16", "--detail", *projection]
        code, payload = runtime.raw_gateway(argv)
        record = {"label": label, "argv": argv, "exit_code": code, "payload": payload, "native_packets": []}
        observation["reads"].append(record)
        packets = sorted(set(evidence_root.glob("*.json")) - before)
        assert len(packets) <= 128
        native_results = []
        total = 0
        for path in packets:
            body = path.read_bytes()
            total += len(body)
            assert total <= 8 * 1024 * 1024
            record["native_packets"].append({"path": str(path), "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest()})
            packet = json.loads(body)
            if packet.get("api") == "ak.wwise.core.object.get" and packet.get("ok") is True:
                native_results.append(packet["result"]["return"])
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") not in {"partial", "needs_clarification"}, payload
        assert list(payload)[-1] == "agent_result"
        assert isinstance(payload["agent_result"], list), payload
        return payload["agent_result"], payload, native_results

    projection = ["--include-related", "children", "volume-db",
        "--include-related-field", "children", "Pitch"]
    try:
        roots, payload, native_results = read("container-before", projection)
        root, = roots
        assert root["id"] == CONTAINER and root["name"] == "FS_Concrete" and root["type"] == "RandomSequenceContainer", root
        items = root["related"]["children"]["items"]
        assert len(items) == 5 and {item["object"]["id"] for item in items} == CHILDREN, items
        by_id = {item["object"]["id"]: item for item in items}
        strategy = payload["related_scope_binding"]["strategy"]
        expected_strategy = "gateway-guid-grouped-reads" if runtime.version in {"2021.1", "2022.1"} else "native-composed-members"
        assert strategy == expected_strategy, payload

        # Inspect actual transport records independently of Gateway projections.
        # A native composition must carry identity and values in each member;
        # a grouped read must supply member rows selected by those same GUIDs.
        witnesses = []
        membership_lists = []
        for rows in native_results:
            root_lists = [
                value for row in rows if row.get("id") == CONTAINER
                for value in row.values() if isinstance(value, list)]
            membership_lists.extend(members for members in root_lists
                if len(members) == 5 and all(isinstance(member, dict) for member in members)
                and {member.get("id") for member in members} == CHILDREN)
            candidates = [rows] if strategy == "gateway-guid-grouped-reads" else root_lists
            for members in candidates:
                if (len(members) == 5 and all(isinstance(member, dict) for member in members)
                        and {member.get("id") for member in members} == CHILDREN
                        and all("@Volume" in member and "@Pitch" in member for member in members)):
                    witnesses.append(members)
        if strategy == "gateway-guid-grouped-reads":
            from wwise_waapi.canonical import canonical_sha256
            # Old versions establish membership with query SELECT, not a bare
            # list return accessor. Trace each owner-specific request association
            # to its independently sealed native packet and actual ordered rows.
            captured_paths = {packet["path"] for packet in observation["reads"][0]["native_packets"]}
            for association in payload["related_read_evidence"]:
                waql = association["args"].get("waql", "")
                if not re.fullmatch(r'from object "' + re.escape(CONTAINER) + r'" select children take [1-9][0-9]*', waql):
                    continue
                path = association["call"]["evidence_path"]
                assert path in captured_paths, association
                packet = json.loads(Path(path).read_text())
                assert packet["api"] == "ak.wwise.core.object.get" and packet["ok"] is True, packet
                assert canonical_sha256(packet["result"]) == association["result_sha256"], association
                members = packet["result"]["return"]
                assert len(members) == 5 and {member["id"] for member in members} == CHILDREN, members
                membership_lists.append(members)
        assert witnesses, native_results
        assert membership_lists, native_results
        for members in membership_lists:
            assert [member["id"] for member in members] == [item["object"]["id"] for item in items]
        for members in witnesses:
            for member in members:
                actual = by_id[member["id"]]
                assert actual["volume_db"] == member["@Volume"]
                assert actual["properties"]["Pitch"] == member["@Pitch"]
            if strategy == "native-composed-members":
                assert [member["id"] for member in members] == [item["object"]["id"] for item in items]

        children, _, _ = read("children-independent", ["--relationship", "children",
            "--include", "volume-db", "--include-field", "Pitch"])
        assert len(children) == 5 and {child["id"] for child in children} == CHILDREN, children
        for child in children:
            item = by_id[child["id"]]
            assert all(item["object"][field] == child[field] for field in ("id", "name", "type", "path")), item
            assert item["volume_db"] == child["volume_db"]
            assert item["properties"]["Pitch"] == child["properties"]["Pitch"]
        repeated, _, _ = read("container-after", projection)
        assert json.dumps(repeated, sort_keys=True) == json.dumps(roots, sort_keys=True)
        observation["business_effect_verified"] = True
        status = "PASS"
    except BaseException as exc:
        observation["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 24 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest())

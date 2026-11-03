"""Read-only acceptance of closed, Gateway-derived related sequences."""
import hashlib
import json
from pathlib import Path

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime
from tests.destructive.test_query_related_lists import CHILDREN, CONTAINER
from tests.destructive.test_query_related_paths import BUILDS
from wwise_waapi.canonical import canonical_json_bytes, canonical_sha256


pytestmark = [pytest.mark.live, pytest.mark.destructive]
REPO = Path(__file__).resolve().parents[2]
PINS = {
    "2021.1": ("1e23d3f4d2d9a654c4fd90655c955c20a43aadbccea4f393158cc4925e3139b4", "973fde161bbba33fc05fa76f0ae7aa6a77fed67763474fc53808132f5e6db37a"),
    "2022.1": ("947aa8dc8a714ad5173290394f84b5f4739b2edb5d9d7a6b2884caf03e501d20", "4fd96cfd17eb8aabe45d5dd7a52c929092cf3224076636d5a08219b5153ec9c0"),
    "2023.1": ("39abb2ec5b02bb2758b1cf0bdce21ef6bfda7424b6b15d2b64ffbe018f8712e4", "9685e4a1b023edcf3f55091fed4c43a946a155b4278bff71255daa9651233683"),
    "2024.1": ("23a2bfa118702c4d03d24412239847d5c97fb3e3ed7c9bedef14e58970103a40", "30493a7b054c49ab11e40f7abc242c7475198fa0d59a5881f63f3ed75cf706c7"),
    "2025.1": ("39a04186fa2686278fe2df42479350e77f4670923f0e999d421dd76482ec8f96", "0b5c0a9c8b195d4c2c95d5ace81836711b3978533f7c2ec17cb17a7782700270"),
}
READ_APIS = {
    "ak.wwise.core.getInfo", "ak.wwise.core.getProjectInfo", "ak.wwise.core.object.get",
    "ak.wwise.core.object.getPropertyAndReferenceNames", "ak.wwise.core.object.getPropertyInfo",
}


def _wwu(version):
    return Path("Containers" if version == "2025.1" else "Actor-Mixer Hierarchy") / "Footsteps.wwu"


def _definition_evidence():
    """Check all matching lanes before the fixture can launch Wwise."""
    evidence = {}
    for version, (definition_sha, wwu_sha) in PINS.items():
        root = REPO / "skills/waapi-skill/resources/manifest" / version
        body = (root / "definitions.json").read_bytes()
        assert hashlib.sha256(body).hexdigest() == definition_sha
        graph = json.loads(body)
        assert graph["wwise_build"] == ".".join(map(str, BUILDS[version]))
        definitions = graph["documents"]["waapi_definitions.json"]["definitions"]
        schemas = json.loads((root / "schemas.json").read_text())
        schema = next(row["schema"] for row in schemas["schemas"] if row["uri"] == "ak.wwise.core.object.get")
        assert schema["argsSchema"]["properties"]["waql"]["type"] == "string"
        assert schema["optionsSchema"]["$ref"].endswith("#/definitions/objectReturnOptions")
        assert definitions["objectReturnOptions"]["properties"]["return"]["$ref"] == "#/definitions/returnExpression"
        assert definitions["returnExpression"]["type"] == "array"
        assert schema["resultSchema"]["properties"]["return"]["items"]["$ref"].endswith("#/definitions/objectReturn")
        assert hashlib.sha256((REPO / "tests/_org" / version / _wwu(version)).read_bytes()).hexdigest() == wwu_sha
        source = json.loads((REPO / "skills/waapi-skill/references/semantic" / version / "query-list-output-sources.json").read_text())
        assert source["version"] == version and source["wwise_build"] == graph["wwise_build"]
        assert source["sequence_sources"]["query_transforms"]["domain"] == "query-selection"
        evidence[version] = {"build": graph["wwise_build"], "definitions_sha256": definition_sha,
            "wwu_sha256": wwu_sha, "sequence_source": {
                **{key: source[key] for key in ("version", "wwise_build", "archive", "archive_sha256", "page", "page_sha256")},
                "sections_sha256": canonical_sha256(source["sequence_sources"])}}
    return evidence


DEFINITION_EVIDENCE = _definition_evidence()


def _page_value(entries, encoding):
    # Reuse the established query document-fragment join and the pointer/string
    # reconstruction in unit._collect_history_pages, not a new wire format.
    if encoding == "json-document-fragments":
        text = ""
        for row in entries:
            assert row["pointer"] == "" and row["kind"] == "string-fragment"
            assert row["offset"] == len(text)
            text += row["value"]
            assert len(text) <= row["total_characters"]
        assert entries and len(text) == entries[-1]["total_characters"]
        return json.loads(text)
    assert encoding == "json-pointer-entries", f"Unsupported query page encoding: {encoding}"
    root = None
    for row in entries:
        parts = [part.replace("~1", "/").replace("~0", "~") for part in row["pointer"].split("/")[1:]]
        parent = root
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = (int(parts[-1]) if isinstance(parent, list) else parts[-1]) if parts else None
        if row["kind"] == "object": value = {}
        elif row["kind"] == "array": value = [None] * row["length"]
        elif row["kind"] == "string-fragment":
            previous = parent[key] if row["offset"] else ""
            assert len(previous) == row["offset"]
            value = previous + row["value"]
        else:
            assert row["kind"] == "value", f"Unsupported query entry kind: {row['kind']}"
            value = row["value"]
        if parts: parent[key] = value
        else: root = value
    return root


def _spec(source="children", stages=(), reducer=None, arms=None):
    value = {"source": source, "stages": list(stages)}
    if reducer is not None: value["reducer"] = reducer
    if arms is not None: value["arms"] = arms
    return value


def _projection(root, spec):
    matches = [record for record in root["related"]["projections"]
        if canonical_json_bytes(record["spec"]) == canonical_json_bytes(spec)]
    assert len(matches) == 1, (spec, root)
    assert matches[0]["derivation"] == "gateway-business-sequence"
    return matches[0]


def test_closed_sequences_match_existing_child_order_and_values(workflow_sandbox_runtime):
    runtime = workflow_sandbox_runtime
    live = runtime.sandbox.metadata.get_info_version
    assert tuple(live[key] for key in ("year", "major", "minor", "build")) == BUILDS[runtime.version]
    assert hashlib.sha256((runtime.sandbox.source_root / _wwu(runtime.version)).read_bytes()).hexdigest() == PINS[runtime.version][1]
    output = runtime.state_dir / "query-list-sequences.json"
    assert not output.exists()
    evidence_root = Path(runtime.env["WWISE_EVIDENCE_DIR"])
    observation = {"candidate": runtime.candidate, "version": runtime.version, "read_only": True,
        "definitions": DEFINITION_EVIDENCE, "reads": [], "business_effect_verified": False}
    category = {"category": "query-list-sequences", "status": "FAIL",
        "verifier_strength": "business_derived_sequences_with_independent_native_order_guid_values_and_packets",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status, continuation_count = "FAIL", 0

    def read(label, flags, *, detail=True):
        nonlocal continuation_count
        assert len(observation["reads"]) < 7
        argv = ["query-object", "--exact-id", CONTAINER, "--max-results", "16", *(["--detail"] if detail else []), *flags]
        record = {"label": label, "invocations": []}
        observation["reads"].append(record)
        entries, offset, encoding, initial, packets = [], 0, None, None, {}
        while True:
            before = set(evidence_root.glob("*.json"))
            code, payload = runtime.raw_gateway(argv)
            invocation = {"argv": argv, "exit_code": code, "payload": payload, "native_packets": []}
            record["invocations"].append(invocation)
            paths = sorted(set(evidence_root.glob("*.json")) - before)
            assert len(paths) <= 128
            total = 0
            for path in paths:
                body = path.read_bytes(); total += len(body)
                assert total <= 8 * 1024 * 1024
                invocation["native_packets"].append({"path": str(path), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
                packet = json.loads(body)
                assert packet["api"] in READ_APIS, packet
                packets[str(path)] = packet
            assert code == 0 and payload.get("ok") is True, payload
            assert list(payload)[-1] == "agent_result"
            if initial is None: initial = payload
            value = payload["agent_result"]
            if isinstance(value, list):
                assert not entries and payload.get("projection_complete") is not False
                return value, initial, packets
            assert isinstance(value, dict) and value["entries_encoding"] in {"json-document-fragments", "json-pointer-entries"}, payload
            if encoding is None: encoding = value["entries_encoding"]
            assert encoding == value["entries_encoding"] and value["page"]["offset"] == offset
            entries.extend(value["entries"]); offset += len(value["entries"])
            assert value["page"]["next_offset"] == offset
            if value["projection_complete"]: break
            assert continuation_count < 4, "Unexpected query delivery cost; retain evidence for Main to adjust grouping"
            continuation_count += 1
            argv = value["next_command"]["gateway_argv"]
            assert "query-object" in argv and "--result-query" in argv and "--result-page" in argv
        restored = _page_value(entries, encoding)
        # Preserve original page payloads above; these are the exact reconstructed
        # business objects and optional origin diagnostics delivered by that protocol.
        diagnostics = {**initial, **{key: restored[key] for key in ("related_scope_binding", "related_read_evidence") if key in restored}}
        return restored["objects"], diagnostics, packets

    def trace(detail, packets):
        proof = detail["related_scope_binding"]
        assert proof["sequence_source"] == DEFINITION_EVIDENCE[runtime.version]["sequence_source"]
        assert "no native function-return equality" in proof["sequence_semantics"]
        records = detail["related_read_evidence"]
        first_paths = {row["path"] for row in observation["reads"][-1]["invocations"][0]["native_packets"]}
        assert records
        assert [{key: row[key] for key in ("api", "args", "options", "result_sha256")} for row in records] == proof["read_associations"]
        for row in records:
            path = row["call"]["evidence_path"]
            assert path in first_paths, "Paged origin evidence must not name a later invocation"
            packet = packets[path]
            assert packet["ok"] is True and packet["api"] == row["api"]
            assert canonical_sha256(packet["result"]) == row["result_sha256"]
            assert "skip 0" not in row["args"].get("waql", "")
        return records

    def root_result(rows, detail, packets):
        root, = rows
        # Compact scalar replies deliberately omit call diagnostics. Their
        # independent native root facts still exist in this invocation's packets.
        native_roots = [row for packet in packets.values()
            if packet.get("api") == "ak.wwise.core.object.get" and packet.get("ok") is True
            for row in packet["result"]["return"] if row.get("id") == CONTAINER]
        assert native_roots
        assert root["id"] == CONTAINER and root["name"] == "FS_Concrete" and root["type"] == "RandomSequenceContainer"
        assert isinstance(root["path"], str) and root["path"]
        assert all(all(root[key] == native[key] for key in ("id", "name", "type", "path")) for native in native_roots)
        return root

    try:
        baseline, detail, packets = read("independent-children", ["--relationship", "children", "--include", "volume-db",
            "--include", "pitch-cents", "--include", "class-id"])
        native = packets[detail["call"]["evidence_path"]]["result"]["return"]
        assert len(baseline) == len(native) == 5
        order = [row["id"] for row in native]
        assert set(order) == CHILDREN and [row["id"] for row in baseline] == order
        by_id = {row["id"]: row for row in baseline}
        assert {row["name"] for row in baseline} == {f"Footstep_Crouching_Concrete_{number:02d}" for number in range(1, 6)}
        for row, raw in zip(baseline, native):
            assert row["type"] == raw["type"] == "Sound"
            assert all(row[key] == raw[key] for key in ("id", "name", "type", "path"))
            for business, field in (("volume_db", "@Volume"), ("pitch_cents", "@Pitch"), ("class_id", "classId")):
                assert canonical_json_bytes(row[business]) == canonical_json_bytes(raw[field])
        observation["independent_order"] = order

        def check_members(record, expected, *, pitch=False):
            assert [member["object"]["id"] for member in record["items"]] == expected
            for member in record["items"]:
                known = by_id[member["object"]["id"]]
                assert all(member["object"][key] == known[key] for key in ("id", "name", "type", "path"))
                assert canonical_json_bytes(member["volume_db"]) == canonical_json_bytes(known["volume_db"])
                if pitch: assert canonical_json_bytes(member["properties"]["Pitch"]) == canonical_json_bytes(known["pitch_cents"])

        rows, detail, packets = read("endpoints-and-pitch", ["--include-related", "children", "first", "volume-db",
            "--include-related-field", "children", "first", "Pitch", "--include-related", "children", "last", "volume-db"])
        root = root_result(rows, detail, packets); trace(detail, packets)
        check_members(_projection(root, _spec(stages=[{"selection": "first"}])), order[:1], pitch=True)
        check_members(_projection(root, _spec(stages=[{"selection": "last"}])), order[-1:])
        scopes = [row for row in detail["related_scope_binding"]["scopes"] if (row.get("selected") or {}).get("name") == "Pitch"]
        assert scopes
        assert all(row["selected"]["kind"] == "property" and row["scope"] in ({"classId": by_id[order[0]]["class_id"]}, {"object": order[0]}) for row in scopes)

        rows, detail, packets = read("index-and-range", ["--include-related", "children", "at", "2", "volume-db",
            "--include-related", "children", "skip", "1", "take", "2", "volume-db"])
        root = root_result(rows, detail, packets); trace(detail, packets)
        check_members(_projection(root, _spec(stages=[{"selection": "at", "count": 2}])), order[2:3])
        check_members(_projection(root, _spec(stages=[{"selection": "skip", "count": 1}, {"selection": "take", "count": 2}])), order[1:3])

        condition = {"condition": "kind-is", "value": "sound"}
        rows, detail, packets = read("derived-count-existence-and-all", ["--include-related", "children", "count",
            "--include-related", "children", "any-match", "kind-is", "sound", "--include-related", "children", "all-match", "kind-is", "sound",
            "--include-related", "children", "take", "0", "all-match", "kind-is", "sound",
            "--include-related", "children", "matching", "name-is", "FS_Concrete", "count"], detail=False)
        root = root_result(rows, detail, packets)
        cases = [(_spec(reducer={"operation": "count"}), 5),
            (_spec(reducer={"operation": "any-match", "condition": condition}), True),
            (_spec(reducer={"operation": "all-match", "condition": condition}), True),
            (_spec(stages=[{"selection": "take", "count": 0}], reducer={"operation": "all-match", "condition": condition}), False),
            (_spec(stages=[{"selection": "matching", "condition": "name-is", "value": "FS_Concrete"}], reducer={"operation": "count"}), 0)]
        for spec, expected in cases:
            actual = _projection(root, spec)["value"]
            assert type(actual) is type(expected) and actual == expected

        staged = ["--include-related", "combine", "self", "and", "children", "end", "take", "2", "matching", "kind-is", "sound", "volume-db"]
        staged_spec = _spec("combine", [{"selection": "take", "count": 2}, {"selection": "matching", **condition}], arms=[["self"], ["children"]])
        first_concat, detail, packets = read("concat-then-take-then-filter", staged)
        root = root_result(first_concat, detail, packets); trace(detail, packets)
        selected = _projection(root, staged_spec)
        check_members(selected, order[:1])
        assert selected["items"][0]["origin"] == {"arm": 1, "occurrence": 0}

        rows, detail, packets = read("concat-independent-occurrences", ["--include-related", "combine", "children", "and", "children", "end", "skip", "4", "take", "2", "volume-db"])
        root = root_result(rows, detail, packets); trace(detail, packets)
        combined = _projection(root, _spec("combine", [{"selection": "skip", "count": 4}, {"selection": "take", "count": 2}], arms=[["children"], ["children"]]))
        check_members(combined, [order[4], order[0]])
        assert [row["origin"] for row in combined["items"]] == [{"arm": 0, "occurrence": 4}, {"arm": 1, "occurrence": 0}]

        repeated, detail, packets = read("concat-repeat", staged)
        root_result(repeated, detail, packets); trace(detail, packets)
        assert canonical_json_bytes(repeated) == canonical_json_bytes(first_concat)  # Exact agent_result, not volatile diagnostics.
        assert len(observation["reads"]) == 7
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

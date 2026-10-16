"""Runner-owned repair fixtures and business checks, outside the installed Skill."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_expansion_case_helpers import BusinessDraft, CaseBoundaryError, query_path
from tests.semantic.support.codex_expansion_cases import PreparedExpansionCase
from tests.semantic.support.codex_repair_oracle import assess_repair_state
from tests.destructive.support.sandbox_fixture import hash_project

STATE_ASSERTIONS = frozenset({"complete_snapshots", "source_unchanged", "media_unchanged",
    "other_objects_unchanged", "target_identity", "target_values", "target_cardinality"})
F1_ASSERTIONS = STATE_ASSERTIONS | {"metadata_list_page_detail"}
F2_ASSERTIONS = STATE_ASSERTIONS | {"read_refinement"}
F3_ASSERTIONS = F4_ASSERTIONS = STATE_ASSERTIONS


def require_predelay_metadata(detail):
    metadata = detail.get("agent_result", {}).get("metadata", {})
    restriction = metadata.get("restriction", {})
    unit = metadata.get("unit", {})
    if (metadata.get("name") != "PreDelay" or metadata.get("type") not in {"Real32", "Real64"}
            or type(metadata.get("default")) not in {int, float} or not math.isfinite(metadata["default"])
            or any(type(restriction.get(key)) not in {int, float} or not math.isfinite(restriction[key]) for key in ("min", "max"))
            or not restriction["min"] <= 24 <= restriction["max"]
            or not (unit == {"status": "unknown", "value": None}
                    or unit.get("status") == "known" and isinstance(unit.get("value"), str) and bool(unit["value"]))):
        raise CaseBoundaryError("PreDelay=24 requires exact live numeric range/default and explicit unit availability")
    return dict(metadata)


def attest_predelay(gateway):
    """Bounded public class metadata read; no project writes or Fresh calls."""
    pages, fields = [], []
    token = None
    for _ in range(16):
        args = ["metadata", "list", "--custom-kind", "Wwise RoomVerb", "--page-size", "16"]
        if token:
            args += ["--page", token]
        receipt = gateway(args)
        page = receipt["agent_result"]
        pages.append(receipt)
        fields.extend(page["fields"])
        token = page.get("next_page")
        if not token:
            break
    if token or len(fields) != pages[-1]["agent_result"]["total_count"]:
        raise CaseBoundaryError("RoomVerb metadata inventory is incomplete")
    matches = [row for row in fields if row["name"] == "PreDelay"]
    if len(matches) != 1:
        raise CaseBoundaryError("RoomVerb has no unique exact PreDelay field")
    detail = gateway(["metadata", "detail", "--custom-kind", "Wwise RoomVerb", "--selection", matches[0]["selection"]])
    metadata = require_predelay_metadata(detail)
    return {"pages": pages, "detail": detail, "metadata": metadata}


def read_refinement_proven(receipts, *, target_id, expected):
    """Prove Agent-visible identity/values from a bounded authenticated read chain.

    Callers supply only Broker-authenticated receipts. A unique refinement may
    carry the values itself; later projections must select that same exact GUID.
    Runner snapshots are deliberately not an input to this receipt proof.
    """
    required = expected.get("properties", {})
    if (set(required) != {"Min", "Max", "InitialValue"} or len(receipts) > 96
            or any(not isinstance(expected.get(key), str) or not expected[key] for key in ("name", "type", "path"))):
        return False
    miss = selected = False
    observed = {}
    for row in receipts:
        if row.get("command") != "query-object":
            continue
        result = row.get("payload", {})
        objects = result.get("objects")
        bound = result.get("query_bound", {})
        if (result.get("ok") is not True or result.get("limit_reached") is True or not isinstance(objects, list)
                or type(result.get("count")) is not int or result["count"] != len(objects)
                or bound.get("mode") not in {"take", "exact-object"}
                or bound.get("mode") == "take" and (type(bound.get("value")) is not int or len(objects) >= bound["value"])):
            continue
        if not objects:
            miss = True
            continue
        if not miss or len(objects) != 1 or objects[0].get("id") != target_id:
            continue
        target = objects[0]
        if any(target.get(key) != expected[key] for key in ("name", "type", "path")):
            return False
        if selected:
            args = row.get("arguments", [])
            exact_ids = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "--exact-id"]
            exact_ids += [value.partition("=")[2] for value in args if value.startswith("--exact-id=")]
            if exact_ids != [target_id]:
                continue
        selected = True
        properties = target.get("properties", {})
        if not isinstance(properties, Mapping):
            return False
        for field in required.keys() & properties.keys():
            value = properties[field]
            if type(value) not in {int, float} or not math.isfinite(value) or value != required[field]:
                return False
            observed[field] = value
    return selected and observed == required


def metadata_chain_proven(receipts):
    previous = None
    seen = set()
    continued = False
    for row in receipts:
        if row.get("command") != "metadata":
            continue
        args = row.get("arguments", [])
        result = row.get("payload", {}).get("agent_result", {})
        if args[:1] == ["list"]:
            if "--page" in args and previous and args[args.index("--page") + 1] == previous:
                continued = True
            previous = result.get("next_page")
            for field in result.get("fields", []):
                if field.get("name") == "PreDelay":
                    seen.add(field.get("selection"))
        elif args[:1] == ["detail"] and continued and result.get("selection") in seen:
            try:
                require_predelay_metadata(row["payload"])
                return True
            except CaseBoundaryError:
                pass
    return False


def verify_state(before, after, *, case_id, expected, target_id=None):
    matches = [key for key, value in after.get("objects", {}).items() if value.get("path") == expected["path"]]
    selected = target_id or (matches[0] if len(matches) == 1 else "")
    return assess_repair_state(case_id, before, after, target_id=selected, expected=expected)


def verify_f1(before, after, **kwargs):
    checks = verify_state(before, after, case_id="F1", **kwargs)
    # Authenticated metadata receipts are checked separately by Broker/archive.
    return checks


def verify_f2(before, after, **kwargs):
    return verify_state(before, after, case_id="F2", **kwargs)


def verify_f3(before, after, **kwargs):
    return verify_state(before, after, case_id="F3", **kwargs)


def verify_f4(before, after, **kwargs):
    return verify_state(before, after, case_id="F4", **kwargs)


def approve_repair_preview(artifact, *, case_id, parent_id, expected, target_id=None):
    request = artifact.get("request", {})
    prepared = artifact.get("prepared_operation", {})
    dispatch = prepared.get("dispatch", {})
    args = dispatch.get("args", {})
    if request.get("version") != "2025.1" or dispatch.get("options") != {}:
        return False
    if case_id == "F1":
        return (request.get("operation") == "object.setProperty"
            and dispatch.get("uri") == "ak.wwise.core.object.setProperty"
            and args == {"object": target_id, "property": "PreDelay", "value": 24})
    if case_id == "F3":
        return (request.get("operation") == "object.create"
            and dispatch.get("uri") == "ak.wwise.core.object.create"
            and args == {"parent": parent_id, "type": "GameParameter", "name": expected["name"],
                         "onNameConflict": "fail", "autoAddToSourceControl": False, "@Min": -12, "@Max": 36, "@InitialValue": 7})
    if case_id == "F4":
        return (request.get("operation") == "object.createPlugin"
            and dispatch.get("uri") == "ak.wwise.core.object.set"
            and args == {"autoAddToSourceControl": False, "objects": [{"object": parent_id, "onNameConflict": "fail", "children": [
                {"type": "Effect", "name": expected["name"], "classId": expected["class_id"]}]}]})
    return False


def approve_f1_preview(artifact, **kwargs):
    return approve_repair_preview(artifact, case_id="F1", **kwargs)


def approve_f3_preview(artifact, **kwargs):
    return approve_repair_preview(artifact, case_id="F3", **kwargs)


def approve_f4_preview(artifact, **kwargs):
    return approve_repair_preview(artifact, case_id="F4", **kwargs)


def repair_notice(result, command_records, *, version, execute_expected, preview_artifact, before_snapshot):
    from tests.semantic.support.codex_task_runner_v3 import normalized_gateway_command_argv
    commands = {}
    for record in command_records:
        argv = normalized_gateway_command_argv(record.argv, expected_wwise_version=version)
        if len(argv) >= 4:
            commands[record.command] = argv[3]
    request = preview_artifact.get("request", {})
    arguments = request.get("arguments", {})
    operation = request.get("operation")
    numbers = set()
    if operation == "object.create":
        groups = [(arguments.get("name", ""),)]
        numbers = {float(row["value"]) for row in arguments.get("properties", [])
                   if row.get("name") in {"Min", "Max", "InitialValue"} and type(row.get("value")) in {int, float}}
        if numbers != {-12.0, 36.0, 7.0}:
            return False
    elif operation == "object.setProperty":
        target = arguments.get("object", {}).get("value")
        row = before_snapshot.get("objects", {}).get(target, {})
        groups = [(row.get("name", ""), target or ""), ("predelay", "pre-delay", "pre delay")]
        numbers = {24.0}
    elif operation == "object.createPlugin":
        plugin = arguments.get("plugin", {})
        groups = [(plugin.get("name", ""),), ("roomverb", str(plugin.get("class_id", ""))), ("shareset", "share set")]
    else:
        return False
    if any(not any(value for value in group) for group in groups):
        return False

    def numeric_values(text):
        return {float(value) for value in re.findall(r"(?<![\w.\-])-?\d+(?:\.\d+)?(?!\d|\.\d)", text.replace("−", "-"))}

    def concrete_effect(text):
        folded = text.casefold()
        return (all(any(value and value.casefold() in folded for value in group) for group in groups)
                and numbers.issubset(numeric_values(text)))

    preview_seen = False
    text, earlier = "", ""
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {})
        if event.get("type") != "item.completed":
            continue
        command = commands.get(item.get("command"))
        if command == "preview-from-draft":
            preview_seen, text = True, ""
        elif command == "execute":
            reference = any(term in text.casefold() for term in
                ("plan above", "as described", "as planned", "changes above", "previewed changes"))
            return preview_seen and (concrete_effect(text) or
                reference and concrete_effect(earlier) and numeric_values(text).issubset(numbers))
        elif item.get("type") == "agent_message":
            if preview_seen:
                text += "\n" + item.get("text", "")
            else:
                earlier += "\n" + item.get("text", "")
    return preview_seen and concrete_effect(text) and not execute_expected


def prepare_repair_case(ctx, *, unit, direct, runtime):
    """Seed through public Drafts; collect independent fixed native read views."""
    if ctx.version != "2025.1" or unit.case_id not in {"F1", "F2", "F3", "F4"}:
        raise CaseBoundaryError("repair fixture has no reviewed version/case")
    fixture = unit.fixture
    parent = query_path(ctx, unit.parent_segments)
    parent_id = parent["id"]
    target_id = None
    class_id = None
    plugin_fields = []
    if unit.case_id in {"F1", "F4"}:
        types = direct("ak.wwise.core.object.getTypes", {}, {})
        matches = [row for row in types.get("return", []) if row.get("name") == "Wwise RoomVerb" and row.get("type") == "Effect"]
        if len(matches) != 1 or type(matches[0].get("classId")) is not int:
            raise CaseBoundaryError("live Wwise RoomVerb Effect is unavailable or ambiguous")
        class_id = matches[0]["classId"]
    if unit.case_id == "F1":
        attestation = attest_predelay(ctx.gateway)
        plugin_fields = [row["name"] for page in attestation["pages"] for row in page["agent_result"]["fields"]]
        (runtime.evidence_root / "repair-predelay-attestation.json").write_text(json.dumps(attestation, indent=2) + "\n")
        draft = BusinessDraft(ctx, "object.createPlugin")
        handle = draft.bind(object_id=parent_id)
        kind = draft.discover_type("Wwise RoomVerb", role="effect")
        draft.step("draft-declare-existing", "--declaration-id", "fixture", "--object-handle", handle,
            "--field", "plugin_role", "effect", "--field", "plugin_placement", "shareset",
            "--field", "plugin_name", fixture["plugin_name"], "--field", "plugin_type_handle", kind)
        draft.finish()
        target_id = query_path(ctx, (*unit.parent_segments, fixture["plugin_name"]))["id"]
    if unit.case_id == "F2":
        draft = BusinessDraft(ctx, "object.create")
        handle = draft.bind(object_id=parent_id)
        kind = draft.discover_type("GameParameter")
        fields = []
        for meaning, value in (("Min", -12), ("Max", 36), ("InitialValue", 7)):
            found = draft.step("draft-discover-fields", "--type-handle", kind, "--meaning", meaning)
            candidates = found.get("field_candidates", [])
            if len(candidates) != 1:
                raise CaseBoundaryError("fixture GameParameter field is unavailable or ambiguous")
            fields += ["--field-value", candidates[0]["handle"], str(value)]
        draft.step("draft-declare-new", "--declaration-id", "fixture", "--parent-handle", handle,
            "--kind", kind, "--name", fixture["name"], *fields)
        draft.finish()
        target_id = query_path(ctx, (*unit.parent_segments, fixture["name"]))["id"]
    name = fixture.get("name", fixture.get("plugin_name"))
    expected = {"name": name, "path": fixture["parent_path"] + "\\" + name,
                "type": "Effect" if unit.case_id in {"F1", "F4"} else "GameParameter", "parent": parent_id}
    if unit.case_id in {"F2", "F3"}:
        expected["properties"] = {"Min": -12, "Max": 36, "InitialValue": 7}
    elif unit.case_id == "F1":
        expected["properties"] = {"PreDelay": 24}
    else:
        expected["class_id"] = class_id

    def read(args, projection):
        payload = direct("ak.wwise.core.object.get", args, {"return": projection})
        rows = payload.get("return") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list) or len(rows) > 128 or len(json.dumps(payload).encode()) > 131072:
            raise CaseBoundaryError("repair oracle returned unbounded or malformed state")
        return rows

    def snapshot():
        rows = read({"from": {"id": [parent_id]}, "transform": [{"select": ["children"]}]},
                    ["id", "name", "type", "path", "parent"])
        objects = {parent_id: {"id": parent_id, "name": parent["name"], "type": parent["type"], "path": parent["path"]}}
        for original in rows:
            row = dict(original)
            if row.get("type") == "EffectPlugin":
                row["type"] = "Effect"
            row["parent"] = row.get("parent", {}).get("id")
            if row["id"] in objects or row["parent"] != parent_id:
                raise CaseBoundaryError("repair child set duplicates or escapes parent")
            if row["path"] == expected["path"]:
                properties = ["Min", "Max", "InitialValue"] if row["type"] == "GameParameter" else plugin_fields if unit.case_id == "F1" else []
                projection = ["id", "classId", "owner"] if row["type"] == "Effect" else ["id"]
                details = read({"from": {"id": [row["id"]]}}, projection + ["@" + key for key in properties])
                if len(details) != 1 or details[0].get("id") != row["id"]:
                    raise CaseBoundaryError("repair exact target readback is missing")
                if any("@" + key not in details[0] for key in properties):
                    raise CaseBoundaryError("independent target property projection is incomplete")
                if properties:
                    row["properties"] = {key: details[0].get("@" + key) for key in properties}
                if row["type"] == "Effect":
                    row["class_id"] = details[0].get("classId")
                    row["owner"] = details[0].get("owner")
            objects[row["id"]] = row
        source = runtime.sandbox.source_project
        digest = hash_project(source.parent, preferred_strategy="full")
        originals = runtime.sandbox.sandbox_project.parent / "Originals"
        media = {str(path.relative_to(originals)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(originals.rglob("*")) if path.is_file()}
        return {"objects": objects, "source_integrity": {"sha256": digest.digest,
                "mtime_ns": source.stat().st_mtime_ns}, "media": media, "complete": True}

    before = snapshot()
    if unit.case_id in {"F3", "F4"} and any(row.get("path") == expected["path"] for row in before["objects"].values()):
        raise CaseBoundaryError("repair creation target already exists")
    oracle_parameters = {"expected": expected, "target_id": target_id}
    preview_parameters = {**oracle_parameters, "parent_id": parent_id}
    prompt = unit.prompt.format(plugin_path=expected["path"], parent_path=fixture["parent_path"], pre_delay=24)
    return PreparedExpansionCase(prompt=prompt, operation=unit.operation, policy=unit.policy,
        before=before, read_object_ids=frozenset(before["objects"]), relationship_sources=frozenset({parent_id}),
        read_includes=frozenset({"parent", "owner", "notes", "plugin-name"}),
        read_fields=frozenset({"Min", "Max", "InitialValue", "PreDelay"}),
        required_assertions=globals()[unit.case_id + "_ASSERTIONS"],
        approve_preview=lambda artifact: approve_repair_preview(artifact, case_id=unit.case_id, **preview_parameters),
        snapshot=snapshot, verify=lambda old, new: verify_state(old, new, case_id=unit.case_id, **oracle_parameters),
        archive_oracle_parameters=oracle_parameters, archive_preview_parameters=preview_parameters)

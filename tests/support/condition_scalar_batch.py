"""Predeclared exact source models for original scalar-condition program evidence.

Installed XML establishes a predicate, not effective instance/class metadata.
No cross-member PASS inheritance or native applicability is inferred here.
"""
from __future__ import annotations

from collections import defaultdict
import base64
from copy import deepcopy
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import installed_obligations


def _scalar(text, kind):
    if kind == "string":
        return text or ""
    value = text.strip()
    if kind == "bool":
        if value.lower() not in {"true", "false"}:
            raise ValueError("unrecognized installed Boolean predicate")
        return value.lower() == "true"
    if kind in {"Real32", "Real64"}:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("nonfinite installed scalar")
        return result
    if kind not in {"int16", "int32", "Uint16", "Uint32"}:
        raise ValueError("unreviewed installed scalar predicate type")
    return int(value)


def scalar_manifest(root: Path) -> dict:
    """Declare exact alternatives without claiming native type or applicability."""
    source = audit.load(root / "docs/branch-coverage-condition-sources.json")
    parent_bytes = (root / "tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz").read_bytes()
    parent_document = json.loads(gzip.decompress(parent_bytes))
    parents = parent_document["parents"]
    source_roots = {}
    for key, file in parent_document["files"].items():
        raw = base64.b64decode(file["bytes_base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != file["sha256"]:
            raise ValueError("complete installed source snapshot seal mismatch")
        source_roots[key] = ET.fromstring(raw)
    by_occurrence = defaultdict(list)
    for branch in installed_obligations(root, digest=audit.digest, load=audit.load):
        if branch["owner_issue"] == 177 and branch["kind"] == "metadata_condition":
            alternative = branch["business_dimensions"]["alternative"]
            by_occurrence[branch["id"][:-len(alternative)]].append(branch)
    cases = []
    for corpus in source["corpora"]:
        for lane in corpus["lanes"]:
            build = lane["build"]
            version = ".".join(build.split(".")[:2])
            sibling_positions = defaultdict(int)
            for index, row in enumerate(lane["rows"]):
                sibling_key = (row["file"], row["path"])
                sibling_position = sibling_positions[sibling_key]
                sibling_positions[sibling_key] += 1
                attrs = row["attributes"]
                if (row["tag"] != "PropertyDependency" or attrs.get("Action", "Enable") != "Enable"
                        or attrs.get("Context", "Self") != "Self"):
                    continue
                xml = ET.fromstring(row["xml"])
                predicates = [n for n in xml.iter() if n.tag in {"Enumeration", "Range"}]
                if not predicates:
                    continue
                if len(predicates) != 1:
                    raise ValueError("compound installed scalar predicate requires separate review")
                node = predicates[0]
                kind = node.attrib["Type"]
                if node.tag == "Enumeration":
                    predicate = {"kind": "enum", "type": kind,
                                 "values": [_scalar(v.text, kind) for v in node if v.tag == "Value"]}
                else:
                    predicate = {"kind": "range", "type": kind,
                                 "min": _scalar(node.findtext("Min"), kind),
                                 "max": _scalar(node.findtext("Max"), kind)}
                match = re.search(r"/Properties/(Property|Reference)\[([^\]]+)\]/Dependencies$", row["path"])
                receiver = ({"kind": match[1], "field": match[2]} if match else
                            {"kind": "inherited-base", "field": None})
                receiver["native_type"] = None
                receiver["source_scope_kind"] = ("inner-type-property" if "/InnerTypes/" in row["path"] else
                    "object-base-property" if match and row["path"].split("/")[1].startswith("ObjectBase[") else
                    "source-property" if match else "inherited-base")
                parent_key = "|".join((build, corpus["name"], row["file"], row["path"]))
                parent = parents[parent_key]
                if (hashlib.sha256(parent["xml"].encode()).hexdigest() != parent["parent_xml_sha256"]
                        or parent["source_file_sha256"] != next(f["sha256"] for f in lane["files"] if f["path"] == row["file"])):
                    raise ValueError("installed parent declaration seal mismatch")
                parent_xml = ET.fromstring(parent["xml"])
                if parent_xml.attrib != parent["attributes"]:
                    raise ValueError("installed parent declaration attributes mismatch")
                declared_type = parent["attributes"].get("Type")
                receiver["source_declared_type"] = declared_type
                receiver["source_parent_key"] = parent_key
                receiver["source_parent_xml_sha256"] = parent["parent_xml_sha256"]
                default = parent_xml.find("DefaultValue")
                if declared_type is not None and default is not None:
                    receiver["source_default"] = _scalar(default.text, declared_type)
                restrictions = parent_xml.findall("./Restrictions/ValueRestriction/*")
                if len(restrictions) > 1:
                    raise ValueError("multiple parent field restrictions require explicit review")
                if restrictions:
                    restriction = restrictions[0]
                    if restriction.tag == "Range":
                        receiver["source_restriction"] = {"type": "range",
                            "min": _scalar(restriction.findtext("Min"), restriction.get("Type")),
                            "max": _scalar(restriction.findtext("Max"), restriction.get("Type"))}
                    elif restriction.tag == "Enumeration":
                        receiver["source_restriction"] = {"type": "enum", "values": [
                            {"value": _scalar(v.text, restriction.get("Type"))} for v in restriction if v.tag == "Value"]}
                    else:
                        raise ValueError("unreviewed installed parent restriction")
                prefix = (f'{version}|installed|{build}|{corpus["name"]}|existing-object|'
                          f'{row["file"]}|{row["path"]}/{index}/')
                branches = by_occurrence[prefix]
                if not branches:
                    raise ValueError("installed scalar member was not assigned an exact obligation")
                members = [{"id": branch["id"], "shape_sha256": branch["shape_sha256"],
                            "source_file_sha256": branch["source_file_sha256"],
                            "alternative": branch["business_dimensions"]["alternative"],
                            "value": deepcopy(branch["business_dimensions"]["condition_value"])}
                           for branch in branches]
                cases.append({"id": prefix + "condition", "version": version, "build": build,
                              "corpus": corpus["name"], "file": row["file"], "pointer": row["path"],
                              "class": deepcopy(row.get("class")), "xml": row["xml"],
                              "source_parent_xml": parent["xml"],
                              "source_dependency_index": sibling_position,
                              **_source_scope(source_roots["|".join((build, corpus["name"], row["file"]))], row["path"]),
                              "attributes": deepcopy(attrs), "controller": attrs["Name"],
                              "predicate": predicate, "receiver": receiver, "members": members,
                              "native_applicability": "unverified"})
    return {"contract": "waapi-skill.condition-scalar-members/v1",
            "source_sha256": audit.digest(source), "parent_artifact_sha256": hashlib.sha256(parent_bytes).hexdigest(),
            "evidence_kind": "installed_definition_only",
            "occurrences": cases}


def _source_scope(root, pointer):
    """Resolve only explicit source ObjectBaseRef edges, with no native alias."""
    scopes = {(n.tag, n.get("Name")): n for n in root}
    fields, visited = {}, set()
    def visit(node, active):
        key = id(node)
        if key in active:
            raise ValueError("cyclic installed source base composition")
        if key in visited:
            return
        for base in node.findall("./ObjectBaseRef"):
            visit(scopes[("ObjectBase", base.attrib["Name"])], active | {key})
        for field in node.findall("./Properties/Property"):
            name = field.attrib["Name"]
            raw = ET.tostring(field, encoding="unicode").strip()
            if name in fields and fields[name] != raw:
                raise ValueError("ambiguous installed source field composition")
            fields[name] = raw
        visited.add(key)
    try:
        scope = root
        for component in pointer.rsplit("/Properties/", 1)[0].split("/")[1:]:
            if component == "Dependencies":
                continue
            match = re.fullmatch(r"([^\[]+)(?:\[(.*)\])?", component)
            candidates = [n for n in scope if n.tag == match[1] and (match[2] is None or n.get("Name") == match[2])]
            if len(candidates) != 1:
                raise ValueError("source parent scope is not exact")
            scope = candidates[0]
        visit(scope, set())
    except (KeyError, ValueError) as exc:
        return {"source_scope_fields": {}, "source_scope_error": str(exc)}
    field_match = re.search(r"/Properties/Property\[([^\]]+)\]/Dependencies$", pointer)
    if field_match is None:
        return {"source_scope_fields": {}, "source_scope_error": "receiver_requires_separate_applicability"}
    selected, pending = {}, [field_match[1]]
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in fields:
            return {"source_scope_fields": selected, "source_scope_error": "source_controller_declaration_unresolved:" + name}
        selected[name] = fields[name]
        pending.extend(n.attrib["Name"] for n in ET.fromstring(fields[name]).findall("./Dependencies/*")
                       if n.tag in {"PropertyDependency", "OverrideDependency"} and n.get("Context", "Self") == "Self")
    return {"source_scope_fields": selected, "source_scope_error": None}


def _source_metadata(raw):
    source = ET.fromstring(raw)
    field, kind = source.attrib["Name"], source.attrib["Type"]
    result = {"name": field, "type": kind}
    default = source.find("DefaultValue")
    if default is not None:
        result["default"] = _scalar(default.text, kind)
    restrictions = source.findall("./Restrictions/ValueRestriction/*")
    if len(restrictions) > 1:
        raise ValueError("multiple source restrictions need explicit review")
    if restrictions:
        restriction = restrictions[0]
        if restriction.tag == "Range":
            result["restriction"] = {"type": "range", "min": _scalar(restriction.findtext("Min"), restriction.get("Type")),
                                     "max": _scalar(restriction.findtext("Max"), restriction.get("Type"))}
        elif restriction.tag == "Enumeration":
            result["restriction"] = {"type": "enum", "values": [{"value": _scalar(v.text, restriction.get("Type")),
                **({"displayName": v.attrib["DisplayName"]} if "DisplayName" in v.attrib else {})}
                for v in restriction if v.tag == "Value"]}
        else:
            raise ValueError("unreviewed source restriction")
    dependencies = []
    for node in source.findall("./Dependencies/*"):
        if (node.tag != "PropertyDependency" or node.get("Context", "Self") != "Self"
                or node.get("Action", "Enable") not in {"Enable", "Show"}):
            raise ValueError("parent predicate requires a distinct context/grammar witness")
        conditions = list(node.findall("./Condition/*"))
        if len(conditions) != 1:
            raise ValueError("compound parent predicate requires explicit review")
        condition = conditions[0]
        condition_kind = condition.attrib["Type"]
        if condition.tag == "Enumeration":
            restriction = {"type": "enum", "values": [{"value": _scalar(v.text, condition_kind)}
                                                      for v in condition if v.tag == "Value"]}
        elif condition.tag == "Range":
            restriction = {"type": "range", "min": _scalar(condition.findtext("Min"), condition_kind),
                           "max": _scalar(condition.findtext("Max"), condition_kind)}
        else:
            raise ValueError("unreviewed parent predicate")
        name = node.attrib["Name"]
        dependencies.append({"type": "property", "action": node.get("Action", "Enable"), "context": "Self",
                             "property": name, "conditions": [{"restriction": restriction}]})
    if dependencies:
        result["dependencies"] = dependencies
    return result


def scalar_model(case: dict) -> dict:
    """Model complete scoped source declarations, never live effective facts."""
    if case["receiver"]["kind"] != "Property":
        raise ValueError("receiver needs separate exact field applicability proof")
    if case["receiver"]["source_scope_kind"] == "inner-type-property":
        raise ValueError("inner-type public field applicability requires exact native scope proof")
    if case["source_scope_error"]:
        raise ValueError(case["source_scope_error"])
    field, controller = case["receiver"]["field"], case["controller"]
    if field == controller:
        raise ValueError("self-referential scalar predicate needs separate review")
    metadata = {name: _source_metadata(raw) for name, raw in case["source_scope_fields"].items()}
    active = _active_fields(metadata, field)
    dependencies = [d for name, info in metadata.items() if name in active for d in info.get("dependencies", [])]
    controller_before = {}
    for name, info in metadata.items():
        if name == field:
            continue
        restrictions = [d["conditions"][0]["restriction"] for d in dependencies
                        if d["property"] == name and d["action"] == "Enable"]
        if "restriction" in info:
            restrictions.append(info["restriction"])
        candidates = [info["default"]] if "default" in info else []
        candidates.extend(v["value"] for r in restrictions if r["type"] == "enum" for v in r["values"])
        candidates.extend(r["min"] for r in restrictions if r["type"] == "range")
        def allowed(value):
            return all(any(type(v["value"]) is type(value) and v["value"] == value for v in r["values"])
                       if r["type"] == "enum" else r["min"] <= value <= r["max"] for r in restrictions)
        satisfied = next((v for v in candidates if allowed(v)), None)
        if satisfied is None:
            raise ValueError("source prerequisite intersection has no modeled satisfying value")
        controller_before[name] = satisfied
    receiver = case["receiver"]
    field_type = receiver["source_declared_type"]
    if field_type is None:
        raise ValueError("source dependent type unavailable; controlled model cannot grant product evidence")
    before = receiver.get("source_default", False if field_type == "bool" else "" if field_type == "string" else 0)
    if field_type == "bool":
        requested = not before
    elif field_type == "string":
        requested = "Owned source condition witness" if before != "Owned source condition witness" else "Changed witness"
    else:
        limits = receiver.get("source_restriction", {})
        if limits.get("type") == "enum":
            requested = next((v["value"] for v in limits["values"] if v["value"] != before), before)
        elif limits.get("type") == "range":
            minimum, maximum = limits["min"], limits["max"]
            # A source restriction may use Real64 bounds on an int16 field.
            # Keep the original restriction and choose an actual field value.
            if field_type.lower().startswith(("int", "uint")):
                bits = int(re.search(r"[0-9]+$", field_type)[0])
                unsigned = field_type.lower().startswith("uint")
                domain_min, domain_max = (0, 2 ** bits - 1) if unsigned else (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1)
                minimum, maximum = max(domain_min, math.ceil(minimum)), min(domain_max, math.floor(maximum))
                if minimum > maximum:
                    raise ValueError("source field restriction has no representable integer witness")
            requested = minimum if before != minimum else maximum
        else:
            requested = 1 if before != 1 else 0
    return {"field": field, "controller": controller,
            "metadata": metadata,
            "before": {field: before, **controller_before}, "requested": requested,
            "provenance": {"predicate": "exact_installed_definition_model", "isolated_predicate_only": False,
                           "dependent_type": "exact_installed_parent_Property_Type",
                           "controller_recursive_metadata": "exact_scoped_installed_declarations",
                           "source_inheritance": "source_ObjectBaseRef_composition_only_not_live_applicability",
                           "instance_identity": "explicit_program_model_native_class_applicability_unavailable",
                           "effective_native_metadata": "unobserved", "native_effect": "unverified"}}


def scalar_plan(manifest: dict) -> dict:
    """Assign exact members to original same-field observations before execution.

    This is a source-model plan. It neither borrows a different field's PASS nor
    declares any requirements reviewed. Native facts stay explicitly unresolved.
    """
    parents = defaultdict(list)
    for case in manifest["occurrences"]:
        parents[case["receiver"]["source_parent_key"]].append(case)
    groups, unresolved = [], []
    for key, cases in parents.items():
        first = cases[0]
        try:
            model = scalar_model(first)
        except ValueError as exc:
            unresolved.extend({"id": member["id"], "shape_sha256": member["shape_sha256"], "reason": str(exc)}
                              for case in cases for member in case["members"])
            continue
        group = {"id": audit.digest(key), "source_parent_key": key, "version": first["version"],
                 "build": first["build"], "class": deepcopy(first["class"]),
                 "receiver": deepcopy(first["receiver"]), "field": model["field"], "model": model, "members": []}
        for case in cases:
            index = case["source_dependency_index"]
            source_node = ET.fromstring(case["source_parent_xml"]).findall("./Dependencies/*")[index]
            if source_node.attrib != case["attributes"] or source_node.tag != "PropertyDependency":
                raise ValueError("source occurrence does not match its exact parent dependency slot")
            dependency = model["metadata"][model["field"]]["dependencies"][index]
            if dependency["property"] != case["controller"]:
                raise ValueError("modeled dependency does not match the source controller")
            predicate = case["predicate"]
            source_restriction = ({"type": "enum", "values": [{"value": v} for v in predicate["values"]]}
                                  if predicate["kind"] == "enum" else
                                  {"type": "range", "min": predicate["min"], "max": predicate["max"]})
            if dependency["conditions"] != [{"restriction": source_restriction}]:
                raise ValueError("source predicate differs from the exact modeled metadata observation")
            prefix = f"/observations/metadata/dependencies/{index}"
            for member in case["members"]:
                alternative = member["alternative"]
                expected, pointer = dependency, prefix
                if alternative != "condition":
                    expected = dependency["conditions"][0]["restriction"]
                    pointer += "/conditions/0/restriction"
                    if "/value/" in alternative:
                        value_index = int(alternative.rsplit("/", 1)[1])
                        expected = expected["values"][value_index]["value"]
                        pointer += f"/values/{value_index}/value"
                group["members"].append({"id": member["id"], "shape_sha256": member["shape_sha256"],
                    "source_file_sha256": member["source_file_sha256"], "alternative": alternative,
                    "source_predicate_type": case["predicate"]["type"], "source_occurrence_id": case["id"],
                    "source_attributes": deepcopy(case["attributes"]), "source_value": deepcopy(member["value"]),
                    "observation_pointer": pointer, "expected": deepcopy(expected)})
        _plan_behaviors(group, unresolved)
        groups.append(group)
    return {"contract": "waapi-skill.condition-scalar-program-plan/v1",
            "credit": "none_before_original_observation_and_reviewed_requirements",
            "requirements_state": "pending_review", "source_manifest_sha256": audit.digest(manifest),
            "groups": groups, "unresolved": unresolved}


def _active_fields(metadata, field):
    active, pending = set(), [field]
    while pending:
        name = pending.pop()
        if name in active:
            continue
        active.add(name)
        pending.extend(d["property"] for d in metadata[name].get("dependencies", []) if d["action"] == "Enable")
    return active


def _allows(restriction, value):
    def equal(expected):
        if isinstance(value, bool) or isinstance(expected, bool):
            return type(value) is type(expected) and value == expected
        return value == expected
    if restriction["type"] == "enum":
        return any(equal(v["value"]) for v in restriction["values"])
    return not isinstance(value, bool) and restriction["min"] <= value <= restriction["max"]


def _valid_field_value(info, value):
    kind = info["type"].lower()
    if kind == "bool":
        valid = type(value) is bool
    elif kind == "string":
        valid = type(value) is str
    elif kind.startswith(("int", "uint")):
        bits = int(re.search(r"[0-9]+$", kind)[0])
        minimum, maximum = (0, 2 ** bits - 1) if kind.startswith("uint") else (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1)
        valid = type(value) is int and minimum <= value <= maximum
    else:
        valid = type(value) in {int, float} and math.isfinite(value)
    return valid and ("restriction" not in info or _allows(info["restriction"], value))


def _satisfies(model, before):
    metadata, field = model["metadata"], model["field"]
    if any(not _valid_field_value(info, before[name]) for name, info in metadata.items() if name != field):
        return False
    after = {**before, field: model["requested"]}
    if not _valid_field_value(metadata[field], after[field]):
        return False
    for name in _active_fields(metadata, field):
        for dependency in metadata[name].get("dependencies", []):
            if dependency["action"] == "Enable" and not all(
                    _allows(c["restriction"], state[dependency["property"]])
                    for c in dependency["conditions"] for state in (before, after)):
                return False
    return True


def _plan_behaviors(group, unresolved):
    model, field = group["model"], group["field"]
    workflows, controls = {}, {}
    def add(before):
        if not _satisfies(model, before):
            return None
        identity = audit.digest({"before": before, "requested": model["requested"]})
        workflows.setdefault(identity, {"id": identity, "before": deepcopy(before), "requested": model["requested"]})
        return identity
    representative = add(model["before"])
    if representative is None:
        unresolved.extend({"id": m["id"], "shape_sha256": m["shape_sha256"],
            "reason": "source model representative does not satisfy complete active sibling/recursive constraints"} for m in group["members"])
        group.update(members=[], workflows=[], negative_controls=[])
        return
    pending_members, shape_values = [], {}
    for member in group["members"]:
        controller = member["source_attributes"]["Name"]
        alternative = member["alternative"]
        required = [representative]
        if "/value/" in alternative:
            before = {**model["before"], controller: deepcopy(member["expected"])}
            flow = add(before)
            shape_values.setdefault(member["source_occurrence_id"], []).append(flow)
            required = [flow]
        elif alternative.startswith("Range/"):
            minimum, maximum = member["expected"]["min"], member["expected"]["max"]
            middle = (minimum + maximum) // 2 if type(minimum) is int and type(maximum) is int else (minimum + maximum) / 2
            required = [add({**model["before"], controller: value}) for value in dict.fromkeys((minimum, middle, maximum))]
            for value in (minimum - 1, maximum + 1):
                if _valid_field_value(model["metadata"][controller], value):
                    before = {**model["before"], controller: value}
                    if not _satisfies(model, before):
                        control_id = audit.digest(before)
                        controls[control_id] = {"id": control_id, "before": before,
                            "expected_error_code": "REFERENCE_ACTIVATION_REQUIRED", "source_member": member["id"]}
                        break
        if any(value is None for value in required):
            unresolved.append({"id": member["id"], "shape_sha256": member["shape_sha256"],
                "reason": "source alternative conflicts with active sibling/recursive prerequisites or the controller's declared domain; behavioral reachability requires review"})
            continue
        member["behavioral_workflow_ids"] = list(dict.fromkeys(required))
        pending_members.append(member)
    members = []
    for member in pending_members:
        if member["alternative"].startswith("Enumeration/") and "/value/" not in member["alternative"]:
            choices = shape_values[member["source_occurrence_id"]]
            if any(value is None for value in choices):
                unresolved.append({"id": member["id"], "shape_sha256": member["shape_sha256"],
                    "reason": "enumeration disclosure contains a source alternative whose behavioral reachability conflicts with the combined prerequisites"})
                continue
            member["behavioral_workflow_ids"] = list(dict.fromkeys(choices))
        members.append(member)
    group.update(members=members, workflows=list(workflows.values()), negative_controls=list(controls.values()))

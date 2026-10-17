"""Predeclared exact source models for original scalar-condition program evidence.

Installed XML establishes a predicate, not effective instance/class metadata.
No cross-member PASS inheritance or native applicability is inferred here.
"""
from __future__ import annotations

from collections import defaultdict
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
    parents = json.loads(gzip.decompress(parent_bytes))["parents"]
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
            for index, row in enumerate(lane["rows"]):
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
                              "attributes": deepcopy(attrs), "controller": attrs["Name"],
                              "predicate": predicate, "receiver": receiver, "members": members,
                              "native_applicability": "unverified"})
    return {"contract": "waapi-skill.condition-scalar-members/v1",
            "source_sha256": audit.digest(source), "parent_artifact_sha256": hashlib.sha256(parent_bytes).hexdigest(),
            "evidence_kind": "installed_definition_only",
            "occurrences": cases}


def scalar_model(case: dict) -> dict:
    """Model only the exact isolated source predicate, never native field facts."""
    if case["receiver"]["kind"] != "Property":
        raise ValueError("receiver needs separate exact field applicability proof")
    field, controller = case["receiver"]["field"], case["controller"]
    if field == controller:
        raise ValueError("self-referential scalar predicate needs separate review")
    predicate = case["predicate"]
    if predicate["kind"] == "enum":
        restriction = {"type": "enum", "values": [{"value": v} for v in predicate["values"]]}
        satisfied = predicate["values"][0]
    else:
        restriction = {"type": "range", "min": predicate["min"], "max": predicate["max"]}
        satisfied = predicate["min"]
    dependency = {"type": "property", "action": "Enable", "context": "Self", "property": controller,
                  "conditions": [{"restriction": restriction}]}
    receiver = case["receiver"]
    field_type = receiver["source_declared_type"]
    if field_type is None:
        raise ValueError("source dependent type unavailable; controlled model cannot grant product evidence")
    field_metadata = {"name": field, "type": field_type, "dependencies": [dependency]}
    if "source_default" in receiver:
        field_metadata["default"] = deepcopy(receiver["source_default"])
    if "source_restriction" in receiver:
        field_metadata["restriction"] = deepcopy(receiver["source_restriction"])
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
            requested = limits["min"] if before != limits["min"] else limits["max"]
        else:
            requested = 1 if before != 1 else 0
    return {"field": field, "controller": controller,
            "metadata": {field: field_metadata,
                         controller: {"name": controller, "type": predicate["type"]}},
            "before": {field: before, controller: satisfied}, "requested": requested,
            "provenance": {"predicate": "exact_installed_definition_model", "isolated_predicate_only": True,
                           "dependent_type": "exact_installed_parent_Property_Type",
                           "instance_identity": "explicit_program_model_native_class_applicability_unavailable",
                           "effective_native_metadata": "unobserved", "native_effect": "unverified"}}

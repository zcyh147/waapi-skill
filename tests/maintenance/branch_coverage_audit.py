"""Offline branch accounting, independent of the typed-surface enumerator.

A route mapping is NOT a branch implementation or execution claim. Unreviewed
branches deliberately retain unknown status, even when their route is deep.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def escape(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def schema_branches(schema, pointer=""):
    """Enumerate schema nodes, enum values and optional presence independently.

    References remain explicit graph edges; definition documents are enumerated
    separately, avoiding an infinite expansion of recursive object definitions.
    """
    yield {"pointer": pointer, "kind": "schema", "value": schema}
    if not isinstance(schema, dict):
        return
    for name, child in sorted(schema.get("properties", {}).items()):
        path = pointer + "/properties/" + escape(name)
        if name not in schema.get("required", []):
            for presence in ("absent", "present"):
                yield {"pointer": path + "/@presence/" + presence,
                       "kind": "optional_presence", "value": presence}
        yield from schema_branches(child, path)
    for keyword in ("patternProperties", "definitions", "localDefinitions"):
        for name, child in sorted(schema.get(keyword, {}).items()):
            yield from schema_branches(child, pointer + "/" + keyword + "/" + escape(name))
    for keyword in ("oneOf", "anyOf", "allOf", "items"):
        children = schema.get(keyword)
        if isinstance(children, list):
            for index, child in enumerate(children):
                yield from schema_branches(child, pointer + f"/{keyword}/{index}")
        elif isinstance(children, dict):
            yield from schema_branches(children, pointer + "/" + keyword)
    if "additionalProperties" in schema:
        yield from schema_branches(schema["additionalProperties"], pointer + "/additionalProperties")
    for index, value in enumerate(schema.get("enum", [])):
        yield {"pointer": pointer + f"/enum/{index}", "kind": "enum_value", "value": value}
    if isinstance(schema.get("type"), list):
        for index, value in enumerate(schema["type"]):
            yield {"pointer": pointer + f"/type/{index}", "kind": "type_variant", "value": value}
    known = {"properties", "patternProperties", "definitions", "localDefinitions",
             "oneOf", "anyOf", "allOf", "items", "additionalProperties", "enum",
             "type", "required", "examples", "descriptions", "synopsis", "optionalPositional"}
    for keyword, value in sorted(schema.items()):
        if keyword not in known and isinstance(value, (dict, list)):
            yield {"pointer": pointer + "/" + escape(keyword),
                   "kind": "unreviewed_keyword", "value": value}
    for keyword in ("$ref", "#ref"):
        if keyword in schema:
            yield {"pointer": pointer + "/" + keyword, "kind": "reference", "value": schema[keyword]}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def route_key(version, kind, uri):
    return f"{version}|{kind}|{uri}"


def build_inventory(root=ROOT, *, surface=None):
    """Reconcile reflection identity before linking branches to public routes.

    ``surface`` is an optional independently supplied execution partition for
    maintainer comparisons. It cannot influence reflection enumeration.
    """
    manifest = root / "skills/waapi-skill/resources/manifest"
    surface = surface if surface is not None else load(manifest / "typed-request-surface.json")
    routes = {}
    sources = {}
    schemas = []
    definitions = []
    for version in VERSIONS:
        folder = manifest / version
        for kind, filename, key in (("function", "functions.json", "functions"),
                                    ("topic", "topics.json", "topics")):
            path = folder / filename
            sources[str(path.relative_to(root))] = digest(load(path))
            for row in load(path)[key]:
                routes[route_key(version, kind, row["uri"])] = kind
        for filename in ("schemas.json", "authoring-ui-commands-supplement.json",
                         "authoring-ui-topics-supplement.json", "authoring-core-supplement.json"):
            path = folder / filename
            if not path.exists():
                continue
            data = load(path)
            source = str(path.relative_to(root))
            sources[source] = digest(data)
            if filename == "authoring-ui-commands-supplement.json":
                for kind, key in (("function", "functions"), ("topic", "topics")):
                    for row in data[key]:
                        routes[route_key(version, kind, row["uri"])] = kind
            entries = data["schemas"]
            if isinstance(entries, dict):
                kind = "topic" if "topics" in filename else "function"
                entries = [{"uri": uri, "schema": schema} for uri, schema in entries.items()]
                for row in entries:
                    routes[route_key(version, kind, row["uri"])] = kind
            for row in entries:
                schemas.append((version, source, row["uri"], row["schema"]))
        path = folder / "definitions.json"
        data = load(path)
        source = str(path.relative_to(root))
        sources[source] = digest(data)
        for document, schema in data["documents"].items():
            definitions.append((version, source, document, schema))
    partition = {route_key(r["version"], r["item_type"], r["uri"]): r for r in surface["lanes"]}
    if len(partition) != len(surface["lanes"]) or set(partition) != set(routes):
        raise ValueError("route partition mismatch: " + str(sorted(set(partition) ^ set(routes))))
    sources["skills/waapi-skill/resources/manifest/typed-request-surface.json"] = digest(surface)
    depth = load(root / "docs/interface-depth-inventory.json")
    sources["docs/interface-depth-inventory.json"] = digest(depth)
    public = {route_key(r["version"], r["item_type"], r["uri"]): r for r in depth["native_lanes"]}
    if set(public) != set(routes):
        raise ValueError("public route mapping mismatch")
    route_rows = []
    for key in sorted(routes):
        lane = partition[key]
        policy = lane["execution_policy"]
        named = [r for r in depth["operation_lanes"] if r["version"] == lane["version"] and r["uri"] == lane["uri"]]
        route_rows.append({"id": key, "public_schema": public[key]["field_contract_sha256"],
                           "public_commands": public[key]["continuation_commands"],
                           "named_operations": [{"name": r["operation"], "contract": r["contract_sha256"]} for r in named],
                           "execution_policy": policy, "correct_host": lane["correct_host"],
                           "route_depth_claim": public[key]["disposition"],
                           "branch_mapping": "unknown", "compiler": "unknown",
                           "verifier": policy["verification_strategy"],
                           "program_evidence": {"declared_case": policy["program_case"], "branch_result": "unknown"},
                           "real_evidence": "unknown", "agent_evidence": "unknown"})
    branch_rows = []
    for version, source, uri, schema in sorted(schemas):
        keys = [key for key in routes if key.startswith(version + "|") and key.endswith("|" + uri)]
        if len(keys) != 1:
            raise ValueError(f"schema has no unique route: {version} {uri}")
        for section in ("argsSchema", "optionsSchema", "resultSchema", "publishSchema"):
            if section not in schema:
                continue
            for row in schema_branches(schema[section], "/" + section):
                branch_rows.append(branch_record(version, source, uri, keys[0], row))
    for version, source, document, schema in sorted(definitions):
        for row in schema_branches(schema):
            branch_rows.append(branch_record(version, source, document, None, row))
    return {"contract": "waapi-skill.branch-audit/v1", "sources": sources,
            "routes": route_rows, "branches": branch_rows,
            "business_branches": load(root / "docs/branch-coverage-business-baseline.json")["rows"],
            "evidence_defaults": {"implementation": "unknown", "program": "unknown", "real": "unknown", "agent": "unknown"},
            "summary": {"routes": len(route_rows), "branches": len(branch_rows),
                        "branch_kinds": dict(sorted(Counter(r["kind"] for r in branch_rows).items()))}}


def branch_record(version, source, subject, route, row):
    record = {"id": f"{version}|{source}|{subject}|{row['pointer']}",
              "route": route, "pointer": row["pointer"], "kind": row["kind"],
              "schema_sha256": digest(row["value"]), "mapping": "unknown"}
    if row["kind"] != "schema":
        record["value"] = row["value"]
    return record


def check_inventory(inventory, root=ROOT):
    """Return structural drift separately from unresolved business coverage."""
    expected = build_inventory(root)
    errors = []
    for key, label in (("sources", "source inventory"), ("routes", "route ledger"),
                       ("branches", "branch ledger"), ("business_branches", "business ledger"),
                       ("summary", "summary"), ("evidence_defaults", "evidence defaults"),
                       ("contract", "contract")):
        if inventory.get(key) != expected[key]:
            errors.append(label + " differs")
    return errors


def render_inventory(inventory):
    # One record per line keeps large generated ledgers reviewable in Git.
    return "{\n" + ",\n".join(
        json.dumps(key) + ": " + (
            "[\n" + ",\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in value) + "\n]"
            if isinstance(value, list) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        ) for key, value in inventory.items()
    ) + "\n}\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/branch-coverage-inventory.json")
    parser.add_argument("--check", action="store_true", help="verify reproducibility, not coverage completion")
    parser.add_argument("--require-complete", action="store_true", help="fail on missing or unknown branches")
    args = parser.parse_args()
    inventory = build_inventory()
    if args.check:
        errors = check_inventory(load(args.output))
        if errors:
            print(json.dumps({"errors": errors}))
            return 1
    else:
        args.output.write_text(render_inventory(inventory), encoding="utf-8")
    print(json.dumps({"structural_check": "consistent", "business_coverage": "incomplete",
                      "summary": inventory["summary"]}))
    return 2 if args.require_complete else 0


if __name__ == "__main__":
    raise SystemExit(main())

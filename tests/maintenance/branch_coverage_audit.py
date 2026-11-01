"""Offline comparison of reflected WAAPI schemas and public wrapper routes.

This checker reports API and parameter gaps. It does not collect execution
receipts, assign evidence obligations, or decide product completion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
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
    for keyword in ("oneOf", "OneOf", "anyOf", "allOf", "items"):
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
    if "default" in schema:
        yield {"pointer": pointer + "/@default", "kind": "default", "value": schema["default"]}
    types = schema.get("type", [])
    types = types if isinstance(types, list) else [types]
    if "boolean" in types:
        for value in (False, True):
            if "enum" not in schema or value in schema["enum"]:
                yield {"pointer": pointer + "/@boolean/" + str(value).lower(), "kind": "boolean_value", "value": value}
    if "object" in types and not schema.get("required") and schema.get("minProperties", 0) == 0:
        yield {"pointer": pointer + "/@empty/object", "kind": "empty_object", "value": {}}
    for keyword in ("minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "pattern", "uniqueItems", "minProperties", "maxProperties", "multipleOf"):
        if keyword in schema:
            yield {"pointer": pointer + "/" + keyword, "kind": "constraint", "value": schema[keyword]}
    if "array" in types:
        for cardinality, count in (("empty", 0), ("single", 1), ("multiple", max(2, schema.get("minItems", 0)))):
            if schema.get("minItems", 0) <= count <= schema.get("maxItems", float("inf")):
                yield {"pointer": pointer + "/@cardinality/" + cardinality,
                       "kind": "collection_cardinality", "value": cardinality}
    if "null" in types:
        yield {"pointer": pointer + "/@nullable", "kind": "nullable", "value": None}
    if "string" in types and schema.get("minLength", 0) == 0:
        import re
        if ("enum" not in schema or "" in schema["enum"]) and re.search(schema.get("pattern", ""), ""):
            yield {"pointer": pointer + "/@empty/string", "kind": "empty_string", "value": ""}
    if "OneOf" in schema:
        yield {"pointer": pointer + "/@OneOf", "kind": "native_keyword_semantics", "value": "OneOf"}
    known = {"properties", "patternProperties", "definitions", "localDefinitions",
             "oneOf", "OneOf", "anyOf", "allOf", "items", "additionalProperties", "enum",
             "type", "required", "default", "examples", "descriptions", "synopsis", "optionalPositional"}
    for keyword, value in sorted(schema.items()):
        if keyword not in known and isinstance(value, (dict, list)):
            yield {"pointer": pointer + "/" + escape(keyword),
                   "kind": "unreviewed_keyword", "value": value}
            children = value if isinstance(value, list) else [value]
            for index, child in enumerate(children):
                child_path = pointer + "/" + escape(keyword) + ("/" + str(index) if isinstance(value, list) else "")
                for nested in schema_branches(child, child_path):
                    if nested['pointer'] != pointer + "/" + escape(keyword):
                        yield nested
    for keyword in ("$ref", "#ref"):
        if keyword in schema:
            yield {"pointer": pointer + "/" + keyword, "kind": "reference", "value": schema[keyword]}

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def route_key(version, kind, uri):
    return f"{version}|{kind}|{uri}"

def build_inventory(root=ROOT, *, surface=None, native_policy=None):
    """Reconcile reflection identity before linking branches to public routes.

    ``surface`` is an optional independently supplied execution partition for
    maintainer comparisons. It cannot influence reflection enumeration.
    """
    import sys
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "skills/waapi-skill"))
    from tests.maintenance.source_identity import repository_source_identity

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
            sources[repository_source_identity(path, root)] = digest(load(path))
            for row in load(path)[key]:
                routes[route_key(version, kind, row["uri"])] = kind
        for filename in ("schemas.json", "authoring-ui-commands-supplement.json",
                         "authoring-ui-topics-supplement.json", "authoring-core-supplement.json",
                         "authoring-layout-read-supplement.json", "authoring-layout-mutation-supplement.json",
                         "authoring-model-supplement.json"):
            path = folder / filename
            if not path.exists():
                continue
            data = load(path)
            source = repository_source_identity(path, root)
            sources[source] = digest(data)
            if filename == "authoring-layout-read-supplement.json":
                definitions.append((version, source, "waapi_ui_definitions.json", data["definitions"]))
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
        source = repository_source_identity(path, root)
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
    from wwise_waapi.native_surface_policy import validate_native_surface_policy
    from wwise_waapi.builders.schema import SemanticSchemaValidator
    policy = native_policy if native_policy is not None else load(
        root / "skills/waapi-skill/resources/native_surface_policy.json")
    validate_native_surface_policy(policy, manifest_root=manifest)
    route_rows = [{"id": key, "public_schema": public[key]["field_contract_sha256"],
                   "public_commands": public[key]["continuation_commands"],
                   "correct_host": partition[key]["correct_host"]} for key in sorted(routes)]
    branches = []
    for version, source, uri, schema in sorted(schemas):
        keys = [key for key in routes if key.startswith(version + "|") and key.endswith("|" + uri)]
        if len(keys) != 1:
            raise ValueError(f"schema has no unique route: {version} {uri}")
        for section in ("argsSchema", "optionsSchema", "resultSchema", "publishSchema"):
            if section in schema:
                branches.extend(branch_record(version, source, uri, keys[0], row)
                                for row in schema_branches(schema[section], "/" + section))
    for version, source, document, schema in sorted(definitions):
        branches.extend(branch_record(version, source, document, None, row)
                        for row in schema_branches(schema))
    occurrences = {"|".join((version, source, uri)): digest(schema)
                   for version, source, uri, schema in schemas}
    mappings, candidates, validators = {}, defaultdict(list), {}
    for index, rule in enumerate(policy["rules"]):
        hashes = {}
        for version in rule["versions"]:
            key = (version, rule["profile"])
            if key not in validators:
                validators[key] = SemanticSchemaValidator(version=version,
                    authoring_ui_profile=rule["profile"] == "wwise-authoring-ui")
            hashes[version] = digest(validators[key].schema_for(rule["uri"]))
        for scope_index, scope in enumerate(rule["scopes"]):
            for disposition, selectors in scope["classifications"].items():
                for selector in selectors:
                    if selector.startswith("pattern:"):
                        pointer = scope["pointer"] + "/patternProperties/" + escape(selector[8:])
                    elif selector.startswith("$ref:"):
                        pointer = scope["pointer"] + "/$ref"
                    else:
                        pointer = scope["pointer"] + "/properties/" + escape(selector)
                    identity = f"policy:{index}:{scope_index}:{selector}"
                    mappings[identity] = {"disposition": disposition, "selector": selector,
                        "native_pointer": pointer, "profile": rule["profile"],
                        "schema_sha256_by_version": hashes,
                        "public_operations": rule["operations"], "fixed_commands": rule["fixed_commands"]}
                    for version in rule["versions"]:
                        candidates[route_key(version, "function", rule["uri"])].append(
                            (pointer, identity, hashes[version]))
    for matches in candidates.values():
        matches.sort(key=lambda item: len(item[0]), reverse=True)
    for branch in branches:
        occurrence = "|".join(branch["id"].split("|", 3)[:3])
        matching = [(identity, seal) for pointer, identity, seal in candidates.get(branch["route"], [])
                    if branch["pointer"] == pointer or branch["pointer"].startswith(pointer + "/")]
        mapping = next((identity for identity, seal in matching if seal == occurrences.get(occurrence)), None)
        branch["mapping"] = mapping or "no_selector_disposition"
        branch["mapping_relation"] = ("selector" if mapping and branch["pointer"] == mappings[mapping]["native_pointer"]
            else "descendant_scope_only" if mapping else "profile_schema_mismatch" if matching else "not_joined")
    return {"contract": "waapi-skill.reflection-wrapper-comparison/v1", "sources": sources,
            "routes": route_rows, "branches": branches, "mappings": mappings,
            "schema_occurrences": occurrences,
            "summary": {"routes": len(route_rows), "branches": len(branches),
                        "branch_kinds": dict(sorted(Counter(row["kind"] for row in branches).items())),
                        "declared_selector_dispositions": len(mappings)}}


def branch_record(version, source, subject, route, row):
    record = {"id": f"{version}|{source}|{subject}|{row['pointer']}",
              "route": route, "pointer": row["pointer"], "kind": row["kind"],
              "schema_sha256": digest(row["value"]), "mapping": "unknown"}
    if row["kind"] != "schema":
        record["value"] = row["value"]
    return record

def check_inventory(inventory, root=ROOT, *, expected=None):
    """Compare the current reflected/public surfaces without execution claims."""
    expected = build_inventory(root) if expected is None else expected
    return [key + " differs" for key in expected if inventory.get(key) != expected[key]]


def render_inventory(inventory):
    # One record per line keeps large generated ledgers reviewable in Git.
    return "{\n" + ",\n".join(
        json.dumps(key) + ": " + (
            "[\n" + ",\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in value) + "\n]"
            if isinstance(value, list) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        ) for key, value in inventory.items()
    ) + "\n}\n"

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check and args.output is None:
        parser.error("--check requires --output")
    inventory = build_inventory()
    if args.check:
        errors = check_inventory(load(args.output), expected=inventory)
        print(json.dumps({"errors": errors, "summary": inventory["summary"]}))
        return int(bool(errors))
    if args.output:
        args.output.write_text(render_inventory(inventory), encoding="utf-8")
    print(json.dumps(inventory["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    document = json.loads(path.read_text(encoding="utf-8"))
    descriptor = document.get("native_coverage", {}).get("obligations_artifact") if isinstance(document, dict) else None
    if descriptor is not None:
        import gzip
        name = descriptor["path"]
        if Path(name).name != name:
            raise ValueError("native obligation artifact must be an adjacent file")
        raw = (path.parent / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise ValueError("native obligation artifact digest mismatch")
        packed = json.loads(gzip.decompress(raw))
        rows = unpack_native_rows(packed)
        if len(rows) != descriptor["rows"] or digest(rows) != descriptor["rows_sha256"]:
            raise ValueError("native obligation row seal mismatch")
        document["native_coverage"].pop("obligations_artifact")
        document["native_coverage"]["obligations"] = rows
    return document


def route_key(version, kind, uri):
    return f"{version}|{kind}|{uri}"


def build_inventory(root=ROOT, *, surface=None, native_policy=None):
    """Reconcile reflection identity before linking branches to public routes.

    ``surface`` is an optional independently supplied execution partition for
    maintainer comparisons. It cannot influence reflection enumeration.
    """
    import sys
    sys.path.insert(0, str(root))
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
    inventory = {"contract": "waapi-skill.branch-audit/v2", "sources": sources,
            "routes": route_rows, "branches": branch_rows,
            "business_branches": load(root / "docs/branch-coverage-business-baseline.json")["rows"],
            "evidence_defaults": {"implementation": "unknown", "program": "unknown", "real": "unknown", "agent": "unknown"},
            "summary": {"routes": len(route_rows), "branches": len(branch_rows),
                        "branch_kinds": dict(sorted(Counter(r["kind"] for r in branch_rows).items()))}}
    from tests.maintenance.branch_audit_mapping import enrich_inventory
    enrich_inventory(inventory, root, public, schemas,
                     native_policy if native_policy is not None else load(root / "skills/waapi-skill/resources/native_surface_policy.json"),
                     digest=digest)
    from tests.maintenance.branch_audit_completion import native_coverage
    inventory["native_coverage"] = native_coverage(root, inventory, digest=digest, schema_branches=schema_branches, load=load)
    from tests.maintenance.branch_audit_completion import evaluate_coverage
    inventory["native_coverage"] = evaluate_coverage(root, inventory, {"contract": "waapi-skill.branch-bindings/v1", "bindings": {}}, digest=digest)
    return inventory


def branch_record(version, source, subject, route, row):
    record = {"id": f"{version}|{source}|{subject}|{row['pointer']}",
              "route": route, "pointer": row["pointer"], "kind": row["kind"],
              "schema_sha256": digest(row["value"]), "mapping": "unknown"}
    if row["kind"] != "schema":
        record["value"] = row["value"]
    return record


def check_inventory(inventory, root=ROOT, *, expected=None):
    """Return structural drift separately from unresolved business coverage."""
    expected = build_inventory(root) if expected is None else expected
    errors = []
    for key, label in (("sources", "source inventory"), ("routes", "route ledger"),
                       ("branches", "branch ledger"), ("business_branches", "business ledger"),
                       ("summary", "summary"), ("evidence_defaults", "evidence defaults"),
                       ("contract", "contract"), ("source_index", "source index"),
                       ("contract_index", "current contracts"), ("mappings", "selector mappings"),
                       ("residual_groups", "residual groups"),
                       ("reviewed_snapshot_seal", "reviewed seal"),
                       ("current_business_branches", "current business reconciliation"),
                       ("policy_rule_index", "policy rule index"),
                       ("family_findings", "family findings"),
                       ("schema_occurrences", "schema occurrences"),
                       ("native_coverage", "native coverage")):
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



def pack_native_rows(rows):
    """Storage deduplication only: no branch/evidence equivalence is inferred."""
    routes, shapes, contexts, records = [], [], [], []
    route_index, shape_index, context_index = {}, {}, {}
    shared_fields = ('owner_issue', 'parent_issue', 'blocks_issue', 'state', 'reasons',
                     'requirements', 'evidence_results', 'source_evidence_kind', 'dependencies')
    for original in rows:
        row = dict(original)
        context = {key: row.pop(key) for key in shared_fields if key in row}
        key = digest(context)
        if key not in context_index:
            context_index[key] = len(contexts)
            contexts.append(context)
        row['context'] = context_index[key]
        shape = row.pop('shape_sha256')
        if shape not in shape_index:
            shape_index[shape] = len(shapes)
            shapes.append(shape)
        row['shape'] = shape_index[shape]
        route = row['route']
        if route is not None:
            if row['id'] != route + '|' + row['pointer']:
                raise ValueError('noncanonical native branch identity')
            row.pop('id')
            if route not in route_index:
                route_index[route] = len(routes)
                routes.append(route)
            row['route'] = route_index[route]
        records.append(row)
    return {'contract': 'waapi-skill.branch-row-storage/v1', 'routes': routes,
            'shapes': shapes, 'contexts': contexts, 'rows': records}


def unpack_native_rows(packed):
    if packed.get('contract') != 'waapi-skill.branch-row-storage/v1':
        raise ValueError('unsupported native obligation storage')
    rows = []
    for encoded in packed['rows']:
        row = dict(encoded)
        row.update(packed['contexts'][row.pop('context')])
        row['shape_sha256'] = packed['shapes'][row.pop('shape')]
        if row['route'] is not None:
            row['route'] = packed['routes'][row['route']]
            row['id'] = row['route'] + '|' + row['pointer']
        rows.append(row)
    return rows


def write_inventory(path, inventory):
    rows = inventory['native_coverage']['obligations']
    if len(rows) <= 1000:
        path.write_text(render_inventory(inventory), encoding='utf-8')
        return
    import gzip
    import io
    packed = json.dumps(pack_native_rows(rows), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buffer, mtime=0) as stream:
        stream.write(packed)
    compressed = buffer.getvalue()
    artifact = path.with_name(path.stem + '.native-obligations.json.gz')
    artifact.write_bytes(compressed)
    native = {key: value for key, value in inventory['native_coverage'].items() if key != 'obligations'}
    native['obligations_artifact'] = {'path': artifact.name, 'sha256': hashlib.sha256(compressed).hexdigest(),
        'rows_sha256': digest(rows), 'rows': len(rows), 'compact_bytes': len(packed), 'compressed_bytes': len(compressed)}
    path.write_text(render_inventory({**inventory, 'native_coverage': native}), encoding='utf-8')

def portable_binding_inputs(index_path, requirements):
    """Select sealed original receipts through reviewed locator-only projections.

    This maintainer code is in candidate_identity's existing source closure.
    Evidence/index bytes have separate integrity seals, avoiding self-reference.
    """
    from copy import deepcopy
    from tests.maintenance.branch_audit_completion import read_sealed_artifact
    raw = index_path.read_bytes()
    index = json.loads(raw)
    if (not {'contract', 'base', 'entries'} <= set(index) or set(index) - {'contract', 'base', 'entries', 'metadata_attachments', 'source_attachments', 'source_native_attachments', 'condition_mechanism_attachments'}
            or index['contract'] != 'waapi-skill.branch-evidence-index/v1'
            or not isinstance(index['base'], str) or Path(index['base']).is_absolute()
            or not isinstance(index['entries'], list) or not index['entries']):
        raise ValueError('invalid portable evidence index')
    boundary = ROOT.resolve() if index_path.resolve().is_relative_to(ROOT.resolve()) else index_path.parent.resolve()
    base = (index_path.parent / index['base']).resolve(strict=True)
    if not base.is_relative_to(boundary):
        raise ValueError('portable evidence base escapes its index context')
    def read(descriptor, *, record_index=None):
        if (not isinstance(descriptor, dict) or set(descriptor) != {'artifact', 'sha256'}
                or not isinstance(descriptor['artifact'], str) or Path(descriptor['artifact']).is_absolute()
                or not (base / descriptor['artifact']).resolve().is_relative_to(base)):
            raise ValueError('portable evidence descriptor must remain relative to its bundle')
        if record_index is not None:
            if type(record_index) is not int or record_index < 0:
                raise ValueError("invalid original metadata JSONL index")
            descriptor = {**descriptor, "record_index":record_index}
        return read_sealed_artifact(descriptor, base)
    bindings, names = {}, set()
    for entry in index['entries']:
        if (set(entry) != {'id', 'bindings', 'origin'} or not isinstance(entry['id'], str)
                or not entry['id'] or entry['id'] in names):
            raise ValueError('invalid or duplicate portable evidence entry')
        names.add(entry['id'])
        origin = entry['origin']
        if not isinstance(origin, dict) or set(origin) != {'bindings', 'program', 'requirements', 'capture'}:
            raise ValueError('portable evidence original descriptors missing')
        originals = {name: read(descriptor) for name, descriptor in origin.items()}
        projected = read(entry['bindings'])
        original = originals['bindings']
        if (set(original) != {'contract', 'bindings'}
                or original['contract'] != 'waapi-skill.branch-bindings/v1'
                or not isinstance(original['bindings'], dict) or not original['bindings']):
            raise ValueError('invalid original branch bindings')
        # Only this closed program-receipt transport is imported. Other existing
        # reader closures require their own reviewed portable attachment.
        program = originals['program']
        if any(program.get(key) for key in ('artifacts', 'native_runs', 'metadata_run', 'observation_artifacts')):
            raise ValueError('portable program has an unresolved nested artifact dependency')
        expected = deepcopy(original)
        for branch_id, binding in expected['bindings'].items():
            if branch_id in bindings:
                raise ValueError('duplicate exact branch binding in portable evidence index')
            if (set(binding.get('evidence', {})) != {'program'}
                    or binding.get('equivalence') or binding.get('native_equivalence')
                    or binding['evidence']['program']['sha256'] != origin['program']['sha256']):
                raise ValueError('portable projection must retain its original program evidence')
            binding['evidence']['program']['artifact'] = origin['program']['artifact']
        if projected != expected:
            raise ValueError('portable projection changed more than its original artifact locator')
        policy = originals['requirements']
        if (policy.get('contract') != 'waapi-skill.branch-evidence-requirements/v1'
                or set(policy['branches']) != set(expected['bindings'])
                or any(key in requirements['branches'] and requirements['branches'][key] != value
                       for key, value in policy['branches'].items())):
            raise ValueError('portable requirement differs from reviewed exact branch policy')
        bindings.update(projected['bindings'])
    attachments = index.get('metadata_attachments', [])
    if not isinstance(attachments, list):
        raise ValueError('closed metadata attachment list required')
    attached = set()
    if attachments:
        from tests.support.metadata_replay_branch_evidence import selected_ids
    for descriptor in attachments:
        attachment = read(descriptor)
        if (set(attachment) != {'contract','branch_id','native_shape_sha256','category_inputs','evidence'}
                or attachment['contract'] not in {'waapi-skill.r51-metadata-attachment/v1','waapi-skill.class-metadata-attachment/v1'}):
            raise ValueError('closed R51 metadata attachment fields required')
        identity = attachment['branch_id']
        class_attachment = attachment['contract'] == 'waapi-skill.class-metadata-attachment/v1'
        eligible = selected_ids()
        if class_attachment:
            from tests.maintenance.collect_class_metadata import collection_plan
            eligible = set(collection_plan(identity.split('|',1)[0])['eligible_branch_ids'])
            if identity.split('|',1)[0] != '2025.1':
                eligible.update(collection_plan(identity.split('|',1)[0],cohort='r55')['eligible_branch_ids'])
        policy = requirements['branches'].get(identity, {})
        if (identity in attached or identity not in bindings
                or identity not in eligible
                or policy.get('categories') != ['program','live_metadata']
                or policy.get('native_shape_sha256') != attachment['native_shape_sha256']
                or bindings[identity]['native_shape_sha256'] != attachment['native_shape_sha256']
                or 'live_metadata' in bindings[identity]['evidence'] or bindings[identity].get('category_inputs')):
            raise ValueError('duplicate/conflicting or out-of-scope metadata attachment')
        attached.add(identity)
        evidence = attachment['evidence']
        if set(evidence) != {'artifact','sha256','nodeid'}:
            raise ValueError('closed metadata evidence descriptor required')
        record = read({key:evidence[key] for key in ('artifact','sha256')})
        if class_attachment:
            historical=record.get('evidence_kind')=='historical_class_metadata_current_program_replay'
            common={'candidate_sha256','scope_kind','evidence_kind','metadata_run','invocation','branch_assertions','category_inputs'}
            expected=common|({'replay','replay_bindings','source_bridge'} if historical else {'source_context'})
            if (set(record)!=expected or record['category_inputs']!=attachment['category_inputs']
                    or identity not in record['branch_assertions']
                    or (not historical and (record['evidence_kind']!='current_public_class_metadata'
                        or set(record['category_inputs'])!={'native'}
                        or not isinstance(record['category_inputs']['native'],list)
                        or set(record['source_context'])!={'native_candidate','relevant_sources'}))):
                raise ValueError('Closed current native class attachment required')
            if historical:
                from tests.support.metadata_replay_branch_evidence import class_original_profile
                profiles={class_original_profile(c)['bridge_contract']:c for c in ('r54','r55')}
                cohort=profiles.get(record['source_bridge'].get('contract'))
                if cohort is None:raise ValueError('Unreviewed original class bridge contract')
                profile=class_original_profile(cohort)
                if (record['source_bridge'].get('historical_candidate')!=profile['candidate']
                        or identity not in collection_plan(identity.split('|',1)[0],cohort=cohort)['eligible_branch_ids']
                        or set(record['category_inputs'])!={'historical','replay'}
                        or any(not isinstance(v,list) or not v for v in record['category_inputs'].values())
                        or identity not in record['replay_bindings']
                        or set(record['source_bridge'])!={'contract','attribution','historical_candidate','historical_sources','current_sources','changed_files'}):
                    raise ValueError('Closed historical R54 metadata attachment required')
                replay=record['replay']
                if set(replay)!={'artifact','sha256','nodeid'} or replay['nodeid']!=evidence['nodeid']:
                    raise ValueError('Exact R54 current replay descriptor required')
                program=read({key:replay[key] for key in ('artifact','sha256')})
                if any(program.get(key) for key in ('artifacts','native_runs','metadata_run','observation_artifacts')):
                    raise ValueError('R54 replay has unresolved nested dependency')
            archive=record['metadata_run']
            if (set(archive) != {'contract','root','seal','status_receipt','receipt','target_index'}
                    or archive['contract'] != 'waapi-skill.class-metadata-read/v1'
                    or not isinstance(archive['root'],str) or Path(archive['root']).is_absolute()
                    or type(archive['target_index']) is not int or archive['target_index'] < 0):
                raise ValueError('Closed portable class metadata archive required')
            capture_root=(base/archive['root']).resolve()
            if not capture_root.is_relative_to(base):raise ValueError('Class metadata root escapes bundle')
            seal=read(archive['seal'])
            if (set(seal) != {'contract','files'} or seal['contract'] != 'waapi-skill.class-metadata-seal/v1'
                    or not isinstance(seal['files'],list) or len(seal['files']) > 512):
                raise ValueError('Bounded class metadata seal required')
            paths=set();total=0
            for entry in seal['files']:
                if (set(entry) != {'path','bytes','sha256'} or not isinstance(entry['path'],str)
                        or Path(entry['path']).is_absolute() or '..' in Path(entry['path']).parts
                        or '\\' in entry['path'] or entry['path'] in paths
                        or type(entry['bytes']) is not int or not 0 <= entry['bytes'] <= 1_048_576):
                    raise ValueError('Closed bounded class metadata file descriptor required')
                paths.add(entry['path']);total+=entry['bytes']
                path=capture_root/entry['path']
                if (path.is_symlink() or not path.resolve().is_relative_to(capture_root)
                        or not path.resolve().is_relative_to(base) or total > 128*1024*1024):
                    raise ValueError('Class metadata dependency escapes bundle or bounds')
                content=path.read_bytes()
                if len(content)!=entry['bytes'] or hashlib.sha256(content).hexdigest()!=entry['sha256']:
                    raise ValueError('Original class metadata file digest/size mismatch')
            bindings[identity]['evidence']['live_metadata']=deepcopy(evidence)
            bindings[identity]['category_inputs']={'live_metadata':deepcopy(attachment['category_inputs'])}
            continue
        if (set(record) != {'candidate_sha256','scope_kind','evidence_kind','metadata_run','invocation','replay',
                'replay_bindings','source_bridge','branch_assertions','category_inputs'}
                or record['evidence_kind'] != 'historical_metadata_current_program_replay'
                or record['category_inputs'] != attachment['category_inputs']
                or set(attachment['category_inputs']) != {'historical','replay'}
                or any(not isinstance(value,list) or not value for value in attachment['category_inputs'].values())
                or identity not in record['branch_assertions'] or identity not in record['replay_bindings']):
            raise ValueError('closed exact metadata attachment record required')
        archive = record['metadata_run']
        if (set(archive) != {'contract','category','observation','status','identity','reply','native','call_index'}
                or archive['contract'] != 'waapi-skill.r51-metadata-read/v1'):
            raise ValueError('closed original metadata archive required')
        for role in ('category','observation','status','identity','reply','native'):
            expected = {'artifact','sha256','record_index','nodeid'} if role == 'category' else {'artifact','sha256'}
            if set(archive[role]) != expected:
                raise ValueError('closed original metadata dependency required')
            read({key:archive[role][key] for key in ('artifact','sha256')},
                 record_index=archive[role]['record_index'] if role == 'category' else None)
        replay = record['replay']
        if set(replay) != {'artifact','sha256','nodeid'} or replay['nodeid'] != evidence['nodeid']:
            raise ValueError('exact current metadata replay node required')
        program = read({key:replay[key] for key in ('artifact','sha256')})
        if any(program.get(key) for key in ('artifacts','native_runs','metadata_run','observation_artifacts')):
            raise ValueError('metadata replay has an unresolved nested dependency')
        # Add only this category's evidence and independently bound input.
        # Existing program projections, source mappings and inputs stay exact.
        bindings[identity]['evidence']['live_metadata'] = deepcopy(evidence)
        bindings[identity]['category_inputs'] = {'live_metadata':deepcopy(attachment['category_inputs'])}
    source_business_facts = []
    if 'source_attachments' in index:
        from tests.support.source_copy_branch_evidence import portable_source_attachments
        source_business_facts = portable_source_attachments(index['source_attachments'], bindings, read, base)
    if 'source_native_attachments' in index:
        from tests.support.source_copy_native_evidence import portable_source_native_attachments
        portable_source_native_attachments(index['source_native_attachments'], bindings, read, base)
    condition_mechanism_reuse = []
    if 'condition_mechanism_attachments' in index:
        from tests.support.condition_mechanism_reuse import attach_condition_mechanisms
        condition_mechanism_reuse = attach_condition_mechanisms(index['condition_mechanism_attachments'], bindings, read, base, ROOT)
    return {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings}, base, {
        **({'source_business_facts': source_business_facts} if source_business_facts else {}),
        **({'condition_mechanism_reuse': condition_mechanism_reuse} if condition_mechanism_reuse else {}),
        'mode': 'portable-index', 'index_sha256': hashlib.sha256(raw).hexdigest(),
        'selected_documents_sha256': digest({'entries':index['entries'],'metadata_attachments':attachments,
            'source_attachments':index.get('source_attachments', []),
            'source_native_attachments':index.get('source_native_attachments', []),
            **({'condition_mechanism_attachments':index['condition_mechanism_attachments']} if 'condition_mechanism_attachments' in index else {})}) if index.get('source_attachments') or index.get('source_native_attachments') or index.get('condition_mechanism_attachments') else
            digest({'entries':index['entries'],'metadata_attachments':attachments}) if attachments else digest(index['entries'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/branch-coverage-inventory.json")
    parser.add_argument("--check", action="store_true", help="verify reproducibility, not coverage completion")
    parser.add_argument("--require-complete", action="store_true", help="fail on missing or unknown branches")
    parser.add_argument("--controlled-scope", type=Path, help="sealed test-only scope; never product completion credit")
    parser.add_argument("--scope-sha256", help="independent byte seal of controlled scope")
    parser.add_argument("--requirements", type=Path, help="reviewed exact branch evidence requirements")
    parser.add_argument("--bindings", type=Path, help="exact branch implementation/evidence bindings")
    parser.add_argument("--binding-index", type=Path, help="reviewed portable evidence index (default: committed product index)")
    args = parser.parse_args(argv)
    try:
        inventory = build_inventory()
        scope = None
        if args.controlled_scope is not None:
            if hashlib.sha256(args.controlled_scope.read_bytes()).hexdigest() != args.scope_sha256:
                raise ValueError("controlled scope seal mismatch")
            scope = load(args.controlled_scope)
        elif args.scope_sha256 is not None:
            raise ValueError("scope seal requires explicit controlled scope")
        if args.binding_index is not None and (args.bindings is not None or scope is not None):
            raise ValueError('binding index cannot be combined with explicit bindings or controlled scope')
        requirements = load(args.requirements) if args.requirements else load(ROOT / 'docs/branch-coverage-requirements.json')
        if args.bindings is not None:
            bindings, evidence_base = load(args.bindings), args.bindings.parent
            inputs = {'mode': 'explicit-bindings', 'document_sha256': hashlib.sha256(args.bindings.read_bytes()).hexdigest()}
        elif scope is not None:
            bindings, evidence_base = {"contract": "waapi-skill.branch-bindings/v1", "bindings": {}}, ROOT
            inputs = {'mode': 'controlled'}
        else:
            bindings, evidence_base, inputs = portable_binding_inputs(
                args.binding_index or ROOT / 'docs/branch-coverage-evidence-index.json', requirements)
        from tests.maintenance.branch_audit_completion import evaluate_coverage
        inventory["native_coverage"] = evaluate_coverage(ROOT, inventory, bindings, digest=digest,
            scope=scope, evidence_base=evidence_base,
            requirements_document=requirements if scope is None or args.requirements else None)
        inventory['native_coverage']['binding_inputs'] = inputs
        if args.check:
            previous = load(args.output)
            errors = [("branch ledger" if key == "branches" else key) + " differs" for key in inventory if previous.get(key) != inventory[key]]
            if errors:
                print(json.dumps({"structural_check": "inconsistent", "errors": errors}))
                return 1
        else:
            write_inventory(args.output, inventory)
        coverage = inventory["native_coverage"]
        complete = coverage["completion"]["complete"]
        print(json.dumps({"structural_check": "consistent", "business_coverage": "complete" if complete else "incomplete",
            "scope_kind": coverage["scope_kind"], "product_coverage": "not_evaluated" if scope else "complete" if complete else "incomplete",
            "summary": inventory["summary"], "completion": coverage["completion"]}))
        return 2 if args.require_complete and not complete else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"structural_check": "invalid", "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Source-backed joins for the branch audit; declaration is never execution proof."""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import inspect
from pathlib import Path
import sys

from tests.maintenance.source_identity import repository_source_identity

LIB = "skills/waapi-skill/wwise_waapi/"
POLICY = "skills/waapi-skill/resources/native_surface_policy.json"
GATEWAY = "skills/waapi-skill/scripts/gateway.py"

MAPPING_FIELDS = frozenset({'branch_id', 'native_shape_sha256', 'public_route',
    'public_route_sha256', 'input', 'construction', 'validation', 'verifier',
    'representative_mechanism'})

REQUIREMENTS_IDENTITY_KIND = 'waapi-skill.requirements-publication-identity/v1'
SOURCE_DERIVED_DESCRIPTORS = frozenset({'source_copy_successor_context',
    'source_copy_program_equivalence', 'equivalence', 'native_equivalence'})


def requirements_identity_projection(document, mapping_bindings=None, *, root):
    """Identify policy/current mappings without derived Source proof feedback.

    This is only a source-identity preimage. Ordinary admission still checks the
    complete requirements, member hashes, descriptors and historical origins.
    """
    import hashlib
    import json
    import re
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import digest
    projected = deepcopy(document)
    candidates = {identity for review in document.get('representative_mechanisms', {}).values()
                  for identity in review.get('members', {})
                  if '|function|ak.wwise.core.object.copy|' in identity}
    roster = {}
    if candidates:
        from tests.support.source_copy_branch_evidence import REVIEW_PATH, REVIEW_SHA256
        raw = (Path(root) / REVIEW_PATH).read_bytes()
        if hashlib.sha256(raw).hexdigest() != REVIEW_SHA256:
            raise ValueError('Requirements identity requires the exact original Source roster')
        roster = json.loads(raw)['selected_native_shapes']
    wanted = candidates & roster.keys()
    bindings = (_requirements_source_bindings(root, document, wanted)
                if mapping_bindings is None and wanted else mapping_bindings or {})
    for review in projected.get('representative_mechanisms', {}).values():
        if 'candidate_sha256' in review:
            review['candidate_sha256'] = 'waapi-skill.candidate-self-attestation/v1'
        for identity in set(review['members']) & wanted:
            binding = bindings.get(identity)
            member = review['members'][identity]
            if (not isinstance(binding, dict) or binding.get('branch_id') != identity
                    or binding.get('native_shape_sha256') != roster[identity]
                    or member.get('native_shape_sha256') != roster[identity]
                    or member.get('mapping_sha256') != digest({key: value for key, value in binding.items() if key != 'evidence'})):
                raise ValueError('Requirements identity Source member/mapping differs')
            semantic = {key: deepcopy(value) for key, value in binding.items() if key != 'evidence'}
            for key in SOURCE_DERIVED_DESCRIPTORS & semantic.keys():
                descriptor = semantic[key]
                if (not isinstance(descriptor, dict) or set(descriptor) != {'artifact', 'sha256'}
                        or not isinstance(descriptor['artifact'], str)
                        or not re.fullmatch('[0-9a-f]{64}', descriptor.get('sha256', ''))):
                    raise ValueError('Requirements identity needs closed Source derived descriptors')
                from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
                parse_archive_relative_path(descriptor['artifact'])
                semantic[key] = REQUIREMENTS_IDENTITY_KIND + ':' + key
            member['mapping_sha256'] = digest(semantic)
    return {'contract': REQUIREMENTS_IDENTITY_KIND, 'requirements': projected}


def _requirements_source_bindings(root, requirements, wanted):
    """Resolve the sealed Source prefix, never claim full-index admission.

    Assembly orders existing Source-containing whole-mechanism sidecars first.
    The ordinary importer independently owns every later descriptor, including
    duplicate/invalid ones; identity lookup must not re-read that unrelated tail.
    """
    import json
    from tests.maintenance.branch_coverage_audit import digest
    from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
    root = Path(root).resolve()
    path = root / 'docs/branch-coverage-evidence-index.json'
    index = json.loads(path.read_bytes())
    allowed = {'contract', 'base', 'entries', 'metadata_attachments', 'source_attachments',
        'source_native_attachments', 'runtime_observation_attachments', 'qualified_runtime_read_attachments',
        'condition_mechanism_attachments', 'condition_definition_attachments',
        'installed_applicability_attachments', 'mapping_attachments'}
    if (not isinstance(index, dict) or not {'contract', 'base', 'entries'} <= set(index)
            or set(index) - allowed or index['contract'] != 'waapi-skill.branch-evidence-index/v1'
            or not isinstance(index['base'], str) or Path(index['base']).is_absolute()
            or not isinstance(index['entries'], list)):
        raise ValueError('Requirements identity needs a closed canonical evidence index')
    base = (path.parent / index['base']).resolve(strict=True)
    if not base.is_relative_to(root):
        raise ValueError('Requirements identity evidence base escapes repository')
    def read(descriptor):
        from tests.maintenance.branch_audit_completion import read_sealed_artifact
        if not isinstance(descriptor, dict) or set(descriptor) != {'artifact', 'sha256'}:
            raise ValueError('Requirements identity needs closed sealed descriptors')
        name = parse_archive_relative_path(descriptor['artifact']).canonical
        if descriptor['artifact'] != name:
            raise ValueError('Requirements identity descriptor must use canonical POSIX spelling')
        target = base / name
        if target.is_symlink() or not target.resolve(strict=True).is_relative_to(base):
            raise ValueError('Requirements identity descriptor escapes bundle')
        return read_sealed_artifact(descriptor, base)
    found = {}
    descriptors = index.get('mapping_attachments', [])
    if not isinstance(descriptors, list):
        raise ValueError('Requirements identity needs closed mapping sidecars')
    requirements_sha256 = digest(requirements)
    for descriptor in descriptors:
        attachment = read(descriptor)
        if (not isinstance(attachment, dict) or set(attachment) != {'contract', 'scope_kind',
                'requirements_sha256', 'mechanisms', 'bindings', 'predecessors'}
                or attachment['contract'] != 'waapi-skill.branch-mapping-attachment/v1'
                or attachment['scope_kind'] != 'product'
                or attachment['requirements_sha256'] != requirements_sha256
                or not isinstance(attachment['bindings'], dict)):
            raise ValueError('Requirements identity mapping document differs')
        selected = wanted & attachment['bindings'].keys()
        if found.keys() & selected:
            raise ValueError('Requirements identity has duplicate Source mappings')
        found.update({identity: attachment['bindings'][identity] for identity in selected})
        if set(found) == wanted:
            members = {identity: member for review in requirements['representative_mechanisms'].values()
                       for identity, member in review['members'].items() if identity in wanted}
            for identity, binding in found.items():
                if (not isinstance(binding, dict) or binding.get('branch_id') != identity
                        or members[identity]['mapping_sha256'] != digest({key: value for key, value in binding.items() if key != 'evidence'})):
                    raise ValueError('Requirements identity Source member/mapping differs')
            break
    if set(found) != wanted:
        raise ValueError('Requirements identity Source mappings are missing')
    return found


def debug_control_component(root):
    """Read only the five accepted internal controls, never execute Debug APIs."""
    import json
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import digest, schema_branches
    from tests.maintenance.branch_audit_completion import candidate_identity
    from wwise_waapi.debug_business_contracts import DEBUG_BUSINESS_LANES
    from wwise_waapi.operation_registry import OPERATION_SPECS, operation_business_contract
    from wwise_waapi.native_catalog import load_native_catalog
    operations = {OPERATION_SPECS[name].uri: name for name in DEBUG_BUSINESS_LANES}
    expected = {f'{version}|function|{uri}' for uri, operation in operations.items()
                for version in DEBUG_BUSINESS_LANES[operation]}
    snapshot = json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())
    public = {row['id']: deepcopy(row) for row in snapshot['routes'] if row['id'] in expected}
    if set(public) != expected:
        raise ValueError('Debug component public version/route roster differs')
    surface = json.loads((root / 'skills/waapi-skill/resources/manifest/typed-request-surface.json').read_bytes())
    packaged = {f"{row['version']}|{row['item_type']}|{row['uri']}": row for row in surface['lanes']}
    for key, row in public.items():
        version, _, uri = key.split('|')
        operation = operations[uri]
        contract = digest(operation_business_contract(operation, version))
        if (row['public_contracts'] != [contract]
                or row['named_operations'] != [{'name': operation, 'contract': contract}]
                or row['execution_policy'] != packaged[key]['execution_policy']):
            raise ValueError('Debug public snapshot no longer matches its current closed contract')
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    routes, branches, catalogs = [], [], {}
    for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'):
        wanted = {uri for uri, operation in operations.items() if version in DEBUG_BUSINESS_LANES[operation]}
        for host in ('wwise-console', 'wwise-authoring'):
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            if set(operations) & set(catalog['functions']) != wanted:
                raise ValueError('Debug native version/host roster differs')
            for uri in sorted(wanted):
                identity = f'{version}|{host}|{build}|function|{uri}'
                schema = catalog['schemas'][uri]
                routes.append({'id': identity, 'version': version, 'host': host, 'build': build,
                    'kind': 'function', 'uri': uri, 'native_schema_sha256': digest(schema),
                    'public_route': f'{version}|function|{uri}'})
                for section in ('argsSchema', 'optionsSchema', 'resultSchema'):
                    for item in schema_branches(schema[section], '/' + section):
                        branch = {'id': identity + '|' + item['pointer'], 'route': identity,
                            'pointer': item['pointer'], 'kind': item['kind'], 'shape_sha256': digest(item['value']),
                            'owner_issue': owners['function|' + uri]['owner_issue'], 'parent_issue': 174,
                            'blocks_issue': 195, 'state': 'unresolved'}
                        if item['kind'] != 'schema':
                            branch['value'] = item['value']
                        branches.append(branch)
    # candidate_identity replaces every packaged source with its own complete
    # packaged-tree seal. Retain the same non-packaged source inputs that the
    # normal enrich_inventory path adds, without expanding unrelated branches.
    names = {'docs/branch-coverage-current-business.json', 'docs/interface-depth-review-policy.json',
        'tests/maintenance/interface_depth_inventory.py', 'tests/maintenance/source_identity.py',
        'tests/maintenance/branch_audit_mapping.py', 'tests/maintenance/branch_coverage_audit.py'}
    business = json.loads((root / 'docs/branch-coverage-current-business.json').read_bytes())['rows']
    for row in business:
        for field in ('public_contract', 'compiler', 'preflight', 'verifier', 'program_definition'):
            if field in row:
                name = row[field].partition('#')[0]
                if not name.startswith('skills/waapi-skill/'):
                    names.add(name)
    sources = {name: digest((root / name).read_text(encoding='utf-8')) for name in names}
    sources['docs/interface-depth-inventory.json'] = digest(json.loads((root / 'docs/interface-depth-inventory.json').read_bytes()))
    inventory = {'routes': list(public.values()), 'sources': sources,
        'component': 'five-retained-internal-debug-controls',
        'native_coverage': {'catalogs': catalogs, 'routes': routes, 'obligations': branches}}
    inventory['native_coverage']['candidate_sha256'] = candidate_identity(root, inventory, catalogs, digest=digest)
    return inventory


def debug_control_bindings(inventory):
    """Expand Boolean identity and fixed empty-envelope rules at exact pointers."""
    from tests.maintenance.branch_coverage_audit import digest
    from wwise_waapi.debug_business_contracts import DEBUG_BUSINESS_LANES
    from wwise_waapi.operation_registry import OPERATION_SPECS
    contexts = [key.split('|') for key in inventory['native_coverage']['catalogs']]
    expected = {f'{version}|{host}|{build}|function|{OPERATION_SPECS[operation].uri}'
                for version, host, build in contexts for operation, versions in DEBUG_BUSINESS_LANES.items()
                if version in versions}
    if ({row['id'] for row in inventory['native_coverage']['routes']} != expected
            or len(inventory['native_coverage']['routes']) != 46
            or {(version, host) for version, host, _ in contexts} != {
                (version, host) for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
                for host in ('wwise-console', 'wwise-authoring')}):
        raise ValueError('Debug component exact version/host/route roster differs')
    basic = {'/' + section + suffix for section in ('argsSchema', 'optionsSchema', 'resultSchema')
             for suffix in ('', '/additionalProperties', '/@empty/object')}
    boolean = (basic - {'/argsSchema/@empty/object'}) | {'/argsSchema/properties/enable',
        '/argsSchema/properties/enable/@boolean/false', '/argsSchema/properties/enable/@boolean/true'}
    public = {row['id']: row for row in inventory['routes']}
    result = {}
    for route in inventory['native_coverage']['routes']:
        mode = route['uri'].endswith(('.enableAsserts', '.enableAutomationMode'))
        members = [row for row in inventory['native_coverage']['obligations'] if row['route'] == route['id']]
        if ({row['pointer'] for row in members} != (boolean if mode else basic)
                or len(members) != (11 if mode else 9)):
            raise ValueError('Unhandled or missing exact reflected Debug field/choice')
        lane = public[route['public_route']]
        operation = lane['named_operations'][0]['name']
        prepare = '_prepare_debug_mode_change' if mode else '_prepare_debug_host_control'
        for row in members:
            pointer = row['pointer']
            section = pointer.split('/')[1]
            correspondence = {'rule': ('boolean_identity' if '/properties/enable' in pointer
                else 'closed_boolean_envelope' if mode and section == 'argsSchema'
                else 'empty_business_intent' if section == 'argsSchema'
                else 'gateway_empty_options' if section == 'optionsSchema'
                else 'terminal_acknowledgement_or_indeterminate_without_result_validation' if not mode
                else 'empty_acknowledgement_without_effect_claim')}
            if mode and section == 'argsSchema':
                correspondence['fields'] = {'enable': 'debug_intent.enabled'}
            if '/@boolean/' in pointer:
                correspondence['value'] = row['value']
            result[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
                'public_route': route['public_route'], 'public_route_sha256': digest(lane),
                'input': {'gateway_argv': ['draft-start', operation], 'selector': pointer,
                    'declaration': 'draft-declare-debug-intent',
                    'choices': ['--enable', '--disable'] if mode else [], 'correspondence': correspondence},
                'construction': {'source': LIB + 'debug_business.py#materialize_debug_business_request'
                    if section == 'argsSchema' else LIB + 'operation_registry.py#' + prepare, 'selector': pointer},
                'validation': {'source': GATEWAY + '#dispatch_host_control_transaction'
                    if section == 'resultSchema' and not mode else LIB + 'builders/schema.py#' +
                    ('validate_semantic_result' if section == 'resultSchema' else 'validate_semantic_payload'), 'selector': pointer},
                'verifier': {'source': LIB + 'operation_registry.py#verify_prepared_operation' if mode
                    else GATEWAY + '#dispatch_host_control_transaction', 'selector': pointer}, 'evidence': {}}
    return result


def read_mapping_attachments(descriptors, requirements, read, root):
    """Read sealed mapping successors without altering any original evidence."""
    from tests.maintenance.branch_coverage_audit import digest
    from tests.maintenance.branch_audit_completion import apply_representative_mechanisms
    if not isinstance(descriptors, list):
        raise ValueError('closed mapping attachment list required')
    pending, predecessors = {}, {}
    requirements_sha256 = digest(requirements)
    for descriptor in descriptors:
        attachment = read(descriptor)
        if (not isinstance(attachment, dict)
                or set(attachment) != {'contract', 'scope_kind', 'requirements_sha256',
                                      'mechanisms', 'bindings', 'predecessors'}
                or attachment['contract'] != 'waapi-skill.branch-mapping-attachment/v1'
                or attachment['scope_kind'] not in {'product', 'controlled'}
                or attachment['requirements_sha256'] != requirements_sha256
                or not isinstance(attachment['mechanisms'], list) or not attachment['mechanisms']
                or len(set(attachment['mechanisms'])) != len(attachment['mechanisms'])
                or not isinstance(attachment['bindings'], dict) or not attachment['bindings']
                or not isinstance(attachment['predecessors'], dict)
                or set(attachment['bindings']) != set(attachment['predecessors'])):
            raise ValueError('closed reviewed mapping attachment required')
        reviews = {key: requirements.get('representative_mechanisms', {}).get(key)
                   for key in attachment['mechanisms']}
        if any(not isinstance(review, dict) for review in reviews.values()):
            raise ValueError('mapping attachment names an unreviewed mechanism')
        members = {key: value for review in reviews.values() for key, value in review['members'].items()}
        if set(members) != set(attachment['bindings']) or pending.keys() & members.keys():
            raise ValueError('mapping attachment has missing or conflicting members')
        rows = []
        for identity, member in members.items():
            binding = attachment['bindings'][identity]
            predecessor = attachment['predecessors'][identity]
            route = member['native_route']
            if not isinstance(route, str):
                raise ValueError('mapping attachment requires an exact reflected route')
            parts = route.split('|')
            if (not isinstance(binding, dict) or binding.get('evidence') != {}
                    or binding.get('branch_id') != identity or not identity.startswith(route + '|')
                    or len(parts) != 5 or binding.get('public_route') != '|'.join((parts[0], parts[3], parts[4]))
                    or (predecessor is not None and (not isinstance(predecessor, dict)
                        or set(predecessor) != {'binding_sha256', 'policy_sha256'}))):
                raise ValueError('exact evidence-free mapping or predecessor required')
            policy = requirements['branches'].get(identity, {})
            if policy.get('native_shape_sha256') != member['native_shape_sha256']:
                raise ValueError('mapping attachment policy shape differs')
            rows.append({'id': identity, 'route': route, 'shape_sha256': member['native_shape_sha256'],
                'state': 'unresolved', 'requirements': policy.get('categories', []), 'evidence_results': {}})
        # Existing relation validation checks exact mappings and current sources.
        # Unresolved staging rows give no execution credit: ordinary evaluation
        # still checks actual catalog mappings and selected receipts afterward.
        stage = {'candidate_sha256': next(iter(reviews.values()))['candidate_sha256'], 'obligations': rows}
        apply_representative_mechanisms(stage, attachment['bindings'],
            {'branches': {key: requirements['branches'][key] for key in members},
             'representative_mechanisms': reviews}, root, digest=digest, scope_kind=attachment['scope_kind'])
        pending.update(attachment['bindings'])
        predecessors.update(attachment['predecessors'])
    return {'bindings': pending, 'predecessors': predecessors}


def apply_mapping_attachments(reviewed, bindings, original_policies):
    """Atomically merge declared mapping changes, retaining proof metadata."""
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import digest
    pending = {}
    for identity, proposed in reviewed['bindings'].items():
        old = bindings.get(identity)
        predecessor = reviewed['predecessors'][identity]
        if old is None:
            if predecessor is not None or set(proposed) - MAPPING_FIELDS - {'evidence'}:
                raise ValueError('new mapping cannot overwrite or invent original proof metadata')
        else:
            policy = original_policies.get(identity)
            if (predecessor is None or policy is None
                    or predecessor['binding_sha256'] != digest(old)
                    or predecessor['policy_sha256'] != digest(policy)):
                raise ValueError('mapping successor lacks its exact original binding/policy')
            protected = {key: value for key, value in old.items() if key not in MAPPING_FIELDS | {'evidence'}}
            replacement = {key: value for key, value in proposed.items() if key not in MAPPING_FIELDS | {'evidence'}}
            if protected != replacement:
                raise ValueError('mapping successor changed original proof metadata')
        merged = deepcopy(proposed)
        if old is not None:
            merged['evidence'] = deepcopy(old['evidence'])
        pending[identity] = merged
    bindings.update(pending)

# These are reviewed family entrypoints, not claims about each enum alternative.
FAMILY_MODULES = {
    "authoring-layout-partial": "authoring_layout.py",
    "authoring-model-partial": "authoring_model_business.py",
    "generic-cli-console": "cli_console_business.py",
    "generic-core-media-build": "media_build_business.py",
    "generic-core-project-object": "core_business.py",
    "generic-core-remaining": "core_business.py",
    "generic-core-runtime-inspection": "runtime_inspection_business.py",
    "generic-host-ui-debug-waapi": "host_ui_debug_business.py",
    "generic-soundengine-runtime": "soundengine_business.py",
    "generic-topics": "topic_business.py",
    "generic-fixed-query-metadata": "metadata_discovery.py",
    "generic-dedicated-route-boundary": "operation_registry.py",
    "generic-fixed-command-audited-deep": "operation_registry.py",
    "generic-zero-input-audited-deep": "operation_registry.py",
}


FAMILY_FINDINGS = {
    "authoring-layout-partial": "#188 functional wrapper migration is complete under the user-approved lightweight bounded-interface policy: all 30 exact layout rows expose closed reads or Gateway-owned mutation plans with scoped identities and existing safety controls. Disclosed Gateway capacities, pinned definition contradictions, read-versus-input differences and height/sidebar/frontend/arrangement/reset uncertainty remain; native input/effect acceptance and reset defaults are not independently established. Exact branch mappings retain their separate evidence requirements; no native PASS or historical host/UI family credit is inherited, and further vendor QA is not a wrapper completion requirement.",
    "authoring-model-partial": "#189 functional wrapper migration is complete under the user-approved lightweight policy: nine closed owned model/window/signal functions on each captured 2024.1/2025.1 lane retain configuration/session-bound resources, typed constructors, Preview, execute-once, drift and lifetime controls. Native effects remain not_independently_verified; emission is not delivery and consumed cleanup authority is not independent resource-retirement proof. Original window-identity failures and the consumed startup BLOCKED attempt remain unchanged. Exact branch mappings retain their separate evidence requirements; no native PASS or historical host/UI family credit is inherited, and no further native/Fresh attempt is required or authorized.",
    "generic-cli-console": "CLI option spelling, repeatable bank/platform/language rows, default omission and hook exclusions need exact declaration-to-native correspondence; process success is not generated-bank verification.",
    "generic-core-media-build": "Import path/source replacement and SoundBank inclusion/build alternatives need independent public value mapping and output verification, including partial results.",
    "generic-core-project-object": "Reference/property, identity, destination and conflict-mode alternatives need exact target-type and dependency mappings; route attribution does not prove each nested value.",
    "generic-core-remaining": "Remaining core contracts need URI-local field/enum mapping; inherited family materializer attribution does not identify which declaration emits each native leaf.",
    "generic-core-runtime-inspection": "Inspection selector/filter and runtime-control alternatives need bounded readback and lifetime-specific evidence; result-schema validation is weaker than state verification.",
    "generic-host-ui-debug-waapi": "UI command/registration and debug option alternatives need fresh catalog, correct-host and cleanup boundary mapping; catalog snapshots cannot establish current command availability.",
    "generic-soundengine-runtime": "Game object, playing/transport capability, enum and numeric union meanings need exact business encoding, revocation/lifetime and wrong-handle negatives per API.",
    "generic-topics": "Subscription match/options, publish payload alternatives, count/time/idle bounds and cancellation cleanup need per-topic mapping; publish-schema enumeration alone does not prove delivered events.",
    "generic-fixed-query-metadata": "Query selectors/return projections and metadata result alternatives need exact closed/advanced contract correspondence, default bounds and reference-target reachability.",
    "generic-dedicated-route-boundary": "Named operation alternatives must be separated by target type, placement, mode and verifier; plugin owner/ShareSet and class/instance property semantics cannot inherit family PASS.",
    "generic-fixed-command-audited-deep": "Fixed commands need native option and result-alternative mapping to their actual Gateway branch; a fixed CLI command name does not prove every schema alternative.",
    "generic-zero-input-audited-deep": "Zero-input routes still have host restrictions, return alternatives, side effects and paired cleanup; empty args establish no branch-specific effect verification.",
    "shared-definitions": "Resolve every reference edge from its route/profile to the definition document before assigning public reachability; structurally identical definition nodes alone establish no reachable business combination.",
}


def enrich_inventory(inventory, root, public, schemas, policy, *, digest):
    sys.path.insert(0, str(root / "skills/waapi-skill"))
    from wwise_waapi.business_adapters import business_adapter, business_adapter_operations
    from wwise_waapi.native_surface_policy import validate_native_surface_policy
    from wwise_waapi.builders.schema import SemanticSchemaValidator
    from wwise_waapi.authoring_layout import LAYOUT_READ_URIS

    # This validates selector completeness against the independently packaged
    # reflection, including normalized-equivalence evidence requirements.
    validate_native_surface_policy(policy)
    source_index, contract_index, mappings = {}, {}, {}
    module_trees = {}

    def source(path, symbol=None):
        key = path + ("#" + symbol if symbol else "")
        if key in source_index:
            return key
        full = root / path
        text = full.read_text(encoding="utf-8")
        if path not in module_trees:
            module_trees[path] = ast.parse(text) if path.endswith(".py") else None
        node = None
        if symbol:
            node = next((item for item in ast.walk(module_trees[path])
                         if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name == symbol), None)
            if node is None:
                raise ValueError(f"source symbol missing: {path}#{symbol}")
        key = path + ("#" + symbol if symbol else "")
        source_index[key] = {"path": path, "symbol": symbol, "line": node.lineno if node else 1,
                             "sha256": digest(ast.dump(node, include_attributes=False) if node else text)}
        inventory["sources"][path] = digest(text)
        return key

    def callable_sources(function):
        path = repository_source_identity(Path(inspect.getsourcefile(function)).resolve(), root.resolve())
        refs = [source(path, function.__name__)]
        node = next(item for item in ast.walk(module_trees[path]) if isinstance(item, ast.FunctionDef) and item.name == function.__name__)
        # Adapter wrappers import their operation compiler locally. Record that
        # concrete compiler as well as the authoritative registered wrapper.
        for item in ast.walk(node):
            if isinstance(item, ast.ImportFrom) and item.level == 1 and item.module:
                target = LIB + item.module.replace(".", "/") + ".py"
                for alias in item.names:
                    refs.append(source(target, alias.name))
        return refs

    adapter_names = business_adapter_operations()
    routes = {row["id"]: row for row in inventory["routes"]}
    for key, row in routes.items():
        version, kind, uri = key.split("|", 2)
        family = public[key]["classification"]
        row["family"] = family
        row["reviewed_snapshot"] = {"field_contract_sha256": row.pop("public_schema"),
                                     "current_execution_credit": False}
        compiler_refs, contracts = [], []
        for operation in sorted({uri, *(item["name"] for item in row["named_operations"])}):
            if operation not in adapter_names:
                continue
            adapter = business_adapter(operation)
            try:
                contract = adapter.contract(version)
            except ValueError:
                continue
            contract_id = digest(contract)
            definition = callable_sources(adapter._contract_builder)
            compiler_refs.extend(callable_sources(adapter._materializer))
            # Public values remain indexed by current registry digest. Do not
            # copy a second full schema ledger or infer native equivalence.
            declaration = contract.get("declaration", {})
            contract_index[contract_id] = {
                "operation": operation, "version": version, "definition": definition,
                "sha256": contract_id,
                "declared_fields": sorted(declaration.get("field_value_types", {})),
                "required_fields": declaration.get("required_fields", []),
                "optional_fields": declaration.get("optional_fields", []),
                "business_dimensions": {key: contract[key] for key in ("binding", "type_discovery", "declaration", "safety") if key in contract},
                "status": "current_registry_declaration_not_execution",
            }
            contracts.append(contract_id)
        row["public_contracts"] = contracts or [source(GATEWAY, "dispatch_offline_command")]
        row["compiler"] = sorted(set(compiler_refs)) or [source(LIB + FAMILY_MODULES[family])]
        row["compiler_attribution"] = "registered_adapter" if compiler_refs else "reviewed_family_entrypoint_not_branch_proof"
        row["gateway_entrypoint"] = source(GATEWAY, "dispatch_command")
        row["verifier_source"] = [source(LIB + "operation_registry.py", "verify_prepared_operation")] if row["execution_policy"]["effect"] != "read" and kind == "function" else [source(LIB + "builders/schema.py", "validate_semantic_result")]
        if kind == "topic":
            row["verifier_source"] = [source(LIB + "subscriptions.py", "SubscriptionManager")]
        if uri == "ak.wwise.core.object.get":
            row["public_contracts"] = [source(GATEWAY, "query_business_schema_payload")]
            row["compiler"] = [source(GATEWAY, "_compile_query_business_projection"),
                               source(LIB + "builders/query.py")]
            row["compiler_attribution"] = "fixed_query_entrypoint_not_branch_proof"
            row["verifier_source"] = [source(GATEWAY, "validate_query_business_view_result")]
        if uri in LAYOUT_READ_URIS:
            row["public_contracts"] = [source(LIB + "authoring_layout.py", "layout_read_contract")]
            row["compiler"] = [source(LIB + "authoring_layout.py", "layout_read_arguments")]
            row["compiler_attribution"] = "closed_layout_read_entrypoint_not_branch_proof"
            row["verifier_source"] = [source(LIB + "authoring_layout.py", "validate_layout_read_result")]
        row["branch_mapping"] = "source_attribution_joined; see per-branch mapping"

    inventory["family_findings"] = FAMILY_FINDINGS
    inventory["policy_rule_index"] = {
        str(index): {key: value for key, value in rule.items() if key != "scopes"}
        for index, rule in enumerate(policy["rules"])
    }
    mapping_candidates = defaultdict(list)
    validators = {}
    declared = 0
    for index, rule in enumerate(policy["rules"]):
        profile_hashes = {}
        for version in rule["versions"]:
            key = (version, rule["profile"])
            if key not in validators:
                validators[key] = SemanticSchemaValidator(
                    version=version, authoring_ui_profile=rule["profile"] == "wwise-authoring-ui")
            profile_hashes[version] = digest(validators[key].schema_for(rule["uri"]))
        for scope_index, scope in enumerate(rule["scopes"]):
            for disposition, selectors in scope["classifications"].items():
                for selector in selectors:
                    declared += 1
                    if selector.startswith("pattern:"):
                        pointer = scope["pointer"] + "/patternProperties/" + selector[8:].replace("~", "~0").replace("/", "~1")
                    elif selector.startswith("$ref:"):
                        pointer = scope["pointer"] + "/$ref"
                    else:
                        pointer = scope["pointer"] + "/properties/" + selector.replace("~", "~0").replace("/", "~1")
                    mapping_id = f"policy:{index}:{scope_index}:{selector}"
                    mappings[mapping_id] = {
                        "basis": "native_surface_policy_selector", "disposition": disposition,
                        "policy_rule": str(index), "schema_sha256_by_version": profile_hashes,
                        "source": f"{POLICY}#/rules/{index}/scopes/{scope_index}/classifications/{disposition}",
                        "selector": selector, "native_pointer": pointer, "profile": rule["profile"],
                        "public_operations": rule["operations"], "fixed_commands": rule["fixed_commands"],
                        "public_contract_and_compiler_join": "branch.route -> routes.public_contracts/compiler/verifier_source",
                        "public_value_binding": "selector disposition declared; exact value/enum correspondence still requires review",
                        "program_result": "not_established_by_source_mapping", "native_result": "not_established_by_source_mapping",
                    }
                    for version in rule["versions"]:
                        mapping_candidates[f"{version}|function|{rule['uri']}"].append((pointer, mapping_id, profile_hashes[version]))
    inventory["sources"][POLICY] = digest(policy)
    for route in mapping_candidates:
        mapping_candidates[route].sort(key=lambda item: len(item[0]), reverse=True)

    schema_occurrences = {
        "|".join((version, source, uri)): digest(schema)
        for version, source, uri, schema in schemas
    }
    inventory["schema_occurrences"] = schema_occurrences
    residuals = {}
    counts = Counter()
    for branch in inventory["branches"]:
        route = routes.get(branch["route"])
        occurrence = "|".join(branch["id"].split("|", 3)[:3])
        occurrence_hash = schema_occurrences.get(occurrence)
        matching_pointers = [
            (mapping_id, schema_hash)
            for pointer, mapping_id, schema_hash in mapping_candidates.get(branch["route"], [])
            if branch["pointer"] == pointer or branch["pointer"].startswith(pointer + "/")
        ]
        mapping = next((mapping_id for mapping_id, schema_hash in matching_pointers
                        if schema_hash == occurrence_hash), None)
        branch["mapping"] = mapping or "no_selector_disposition"
        branch["mapping_relation"] = (
            "selector" if mapping and branch["pointer"] == mappings[mapping]["native_pointer"]
            else "descendant_scope_only" if mapping
            else "profile_schema_mismatch" if matching_pointers else "not_joined"
        )
        counts[branch["mapping_relation"]] += 1
        if route:
            version, _, uri = branch["route"].split("|", 2)
            family, hashes = route["family"], [occurrence_hash]
        else:
            family, hashes = "shared-definitions", [branch["schema_sha256"]]
        # Enum and union alternatives never inherit their parent's policy as
        # execution proof. Every unresolved branch is assigned a finite group.
        group_id = digest([family, hashes])[:24]
        branch["residual_group"] = group_id
        group = residuals.setdefault(group_id, {
            "family": family, "native_schema_sha256": hashes, "routes": set(), "branch_count": 0,
            "kinds": Counter(), "selector_mapping_relations": Counter(), "sample_pointers": [],
            "missing": ["exact native branch to public value/boundary correspondence", "branch-specific positive and fail-closed program evidence", "native version evidence where behavior depends on Wwise"],
            "priority": "P1" if family != "shared-definitions" else "P2",
            "disposition": "unproven_not_unsupported",
        })
        group["branch_count"] += 1
        group["kinds"][branch["kind"]] += 1
        group["selector_mapping_relations"][branch["mapping_relation"]] += 1
        if route:
            group["routes"].add(route["id"])
        if len(group["sample_pointers"]) < 4:
            group["sample_pointers"].append(branch["pointer"])
    for group in residuals.values():
        group["routes"] = sorted(group["routes"])
        group["kinds"] = dict(sorted(group["kinds"].items()))
        group["selector_mapping_relations"] = dict(group["selector_mapping_relations"])
        if group["kinds"].get("reference"):
            group["missing"].append("reference target reachability from each public contract")
        if group["kinds"].get("enum_value") or group["kinds"].get("type_variant"):
            group["missing"].append("each enum/union alternative's business encoding or explicit boundary")
        if group["kinds"].get("optional_presence"):
            group["missing"].append("omitted value native default versus explicit public value semantics")
    # Compare, never silently reseal, the earlier depth review against current
    # public contracts. Its classification remains historical attribution.
    import json
    from tests.maintenance.interface_depth_inventory import (
        _operation_contract_rows, _public_continuation_rows,
        _gateway_parser_contract_rows, canonical_sha256)
    surface = json.loads((root / "skills/waapi-skill/resources/manifest/typed-request-surface.json").read_text())
    reviewed = json.loads((root / "docs/interface-depth-review-policy.json").read_text())["source_contracts"]
    observed = {
        "typed_request_surface_sha256": surface["inventory_sha256"],
        "operation_contract_sha256": canonical_sha256(_operation_contract_rows()),
        "public_continuation_sha256": canonical_sha256(_public_continuation_rows(surface)),
        "gateway_parser_sha256": canonical_sha256(_gateway_parser_contract_rows()),
    }
    inventory["reviewed_snapshot_seal"] = {
        "reviewed": reviewed, "current": observed,
        "status": "current" if reviewed == observed else "stale_requires_reviewed_regeneration",
        "execution_credit": False,
    }
    current_business_path = "docs/branch-coverage-current-business.json"
    inventory["current_business_branches"] = json.loads((root / current_business_path).read_text())["rows"]
    source(current_business_path)
    for business in inventory["current_business_branches"]:
        for field in ("public_contract", "compiler", "preflight", "verifier", "program_definition"):
            if field in business:
                path, _, symbol = business[field].partition("#")
                source(path, symbol or None)
    source("docs/interface-depth-review-policy.json")
    source("tests/maintenance/interface_depth_inventory.py")
    source("tests/maintenance/source_identity.py")
    source("tests/maintenance/branch_audit_mapping.py")
    source("tests/maintenance/branch_coverage_audit.py")
    inventory.update(source_index=source_index, contract_index=contract_index, mappings=mappings,
                     residual_groups=residuals)
    inventory["summary"].update(declared_selector_dispositions=declared, mapping_relations=dict(counts),
                                residual_groups=len(residuals), current_registry_contracts=len(contract_index))


def runtime_read_log_component(root):
    """Expand only the sealed ten-URI roster, with current versioned definitions."""
    import json
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import digest, schema_branches
    from tests.maintenance.branch_audit_completion import candidate_identity
    from wwise_waapi.native_catalog import load_native_catalog
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    base = root / 'tests/fixtures/branch-evidence/product/runtime-read-log-195-r1'
    roster = json.loads((base / 'source-roster.json').read_bytes())
    expected = roster['entries']
    wanted = {entry['route'] for entry in expected.values()}
    if len(expected) != 11366 or len(wanted) != 86 or len({i.split('|')[4] for i in wanted}) != 10:
        raise ValueError('Runtime exact finite source roster differs')
    snapshot = json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())
    public_ids = {'|'.join((i.split('|')[0], 'function', i.split('|')[4])) for i in wanted}
    public = [deepcopy(row) for row in snapshot['routes'] if row['id'] in public_ids]
    if {row['id'] for row in public} != public_ids:
        raise ValueError('Runtime current public version/route missing')
    routes, rows, catalogs = [], [], {}
    for version, host in sorted({tuple(i.split('|')[:2]) for i in wanted}):
        catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
        build = catalog['provenance']['build']
        catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
        definitions = catalog['definitions']
        graph = DefinitionGraph(**{k: definitions[k] for k in ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
        for uri in catalog['functions']:
            route = f'{version}|{host}|{build}|function|{uri}'
            if route not in wanted: continue
            routes.append({'id': route, 'version': version, 'host': host, 'build': build,
                'kind': 'function', 'uri': uri, 'native_schema_sha256': digest(catalog['schemas'][uri]),
                'public_route': f'{version}|function|{uri}'})
            for section in ('argsSchema', 'optionsSchema', 'resultSchema'):
                schema = catalog['schemas'][uri][section]; visited = set()
                def visit(value, pointer, context, document, active):
                    for item in schema_branches(value, pointer):
                        identity = route + '|' + item['pointer']
                        old = expected.get(identity)
                        if old is None or old.get('native_shape_sha256', old.get('shape_sha256')) != digest(item['value']) or old['kind'] != item['kind']:
                            raise ValueError('Unhandled runtime native field/choice/definition')
                        row = {'id': identity, 'route': route, 'pointer': item['pointer'], 'kind': item['kind'],
                            'shape_sha256': digest(item['value']), 'owner_issue': old['owner_issue'],
                            'parent_issue': old['parent_issue'], 'blocks_issue': old['blocks_issue'], 'state': 'unresolved'}
                        if item['kind'] != 'schema': row['value'] = item['value']
                        rows.append(row)
                        if item['kind'] == 'reference':
                            target = resolve_schema_reference(item['value'], root_schema=context, graph=graph)
                            doc = document if target.document_name == '<schema>' else target.document_name
                            key = (doc, target.pointer)
                            ptr = '/' + section + '/@definition/' + doc + target.pointer
                            row['reference'] = {'target': route + '|' + ptr, 'recursive': key in active,
                                'document': doc, 'target_sha256': digest(target.target)}
                            if key not in visited:
                                visited.add(key)
                                visit(target.target, ptr, context if target.document_name == '<schema>' else graph.documents[doc], doc, active | {key})
                visit(schema, '/' + section, schema, '<schema>', set())
    if {row['id'] for row in rows} != set(expected) or len(rows) != len(expected):
        raise ValueError('Runtime source roster has missing/duplicate field choices')
    # Reuse the established compact component source inputs and candidate function.
    debug = debug_control_component(root)
    result = {'component': 'runtime-read-log-195-r1', 'routes': public, 'sources': debug['sources'],
        'native_coverage': {'routes': routes, 'catalogs': catalogs, 'obligations': rows}}
    result['native_coverage']['candidate_sha256'] = candidate_identity(root, result, catalogs, digest=digest)
    return result


def runtime_read_log_bindings(root, inventory):
    """Join finite reviewed rules at exact native pointers, never emit receipts."""
    import json
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import digest
    base = root / 'tests/fixtures/branch-evidence/product/runtime-read-log-195-r1'
    rules = json.loads((base / 'mapping-rules.json').read_bytes())['bindings']
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    if set(rules) != set(rows):
        raise ValueError('Runtime mapping omits or adds a native branch')
    public = {row['id']: row for row in inventory['routes']}
    bindings = deepcopy(rules)
    for identity, binding in bindings.items():
        row = rows[identity]
        if (binding['branch_id'] != identity or binding['native_shape_sha256'] != row['shape_sha256']
                or binding['public_route_sha256'] != digest(public[binding['public_route']])
                or binding.get('evidence') != {}
                or any(binding[field]['selector'] != row['pointer'] for field in ('construction', 'validation', 'verifier'))):
            raise ValueError('Runtime current closed public/native correspondence differs')
    return bindings

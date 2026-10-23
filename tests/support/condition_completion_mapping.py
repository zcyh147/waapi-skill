"""Reviewed source-definition coverage over the existing branch evidence reader.

Source definitions, original row observations and shared public/native mechanisms
are separate facts. No row here pretends to be a newly observed native instance.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from tests.maintenance.branch_coverage_audit import digest, load
from tests.maintenance.branch_audit_completion import installed_obligations
from tests.support.condition_source_resolution import reconcile_sources, _scope, _pointer, _catalog_identity

REVIEW_PATH = 'tests/fixtures/metadata-conditions/condition-completion-review.json'
PROOF_PATH = 'tests/fixtures/metadata-conditions/condition-completion-proof-inputs.json.gz'
REVIEW_SHA256 = '56fe04bfe969fdafa404184a1166002a827c702561918dcc03a7948605acff84'


def definition_mapping(root):
    scalar = reconcile_sources(root)
    scalar_rows = {r['occurrence_id']: r for r in scalar['occurrences']}
    source = load(root / 'docs/branch-coverage-condition-sources.json')
    snapshot = json.loads(gzip.decompress((root / 'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz').read_bytes()))
    roots = {}
    for key, value in snapshot['files'].items():
        raw = base64.b64decode(value['bytes_base64'], validate=True)
        if hashlib.sha256(raw).hexdigest() != value['sha256']:
            raise ValueError('Condition source snapshot differs')
        roots[key] = ET.fromstring(raw)
    branches = {b['id']: b for b in installed_obligations(root, digest=digest, load=load)
                if b['owner_issue'] == 177 and b['kind'] == 'metadata_condition'}
    by_occurrence = {}
    for branch in branches.values():
        alternative = branch['business_dimensions']['alternative']
        key = branch['id'][:-len(alternative)] + 'condition'
        by_occurrence.setdefault(key, []).append({'id': branch['id'], 'shape_sha256': branch['shape_sha256']})
    catalogs = {version: load(root / f'skills/waapi-skill/resources/metadata/{version}/object-types.json')['types']
                for version in {b['version'] for b in branches.values()}}
    ownership = load(root / 'docs/branch-coverage-ownership.json')['routes']
    rows, scopes, field_nodes = [], {}, {}
    def indexed_fields(key):
        if key not in field_nodes:
            found = {}
            def visit(node, prefix):
                here = prefix + '/' + node.tag + ('[' + node.get('Name') + ']' if node.get('Name') else '')
                if node.tag in {'Property', 'Reference'}:
                    found[here.lstrip('/')] = node
                for child in node:
                    visit(child, here)
            visit(roots[key], '')
            field_nodes[key] = found
        return field_nodes[key]
    for corpus in source['corpora']:
        for lane in corpus['lanes']:
            build = lane['build']; version = '.'.join(build.split('.')[:2])
            for index, case in enumerate(lane['rows']):
                identity = f'{version}|installed|{build}|{corpus["name"]}|existing-object|{case["file"]}|{case["path"]}/{index}/condition'
                original = scalar_rows.get(identity)
                xml = ET.fromstring(case['xml'])
                if original:
                    recipe = 'scalar:' + original['predicate']['kind'] + ':' + original['predicate']['type']
                    consumers, fields = deepcopy(original['consumers']), deepcopy(original['source_fields'])
                else:
                    recipe = (case['tag'] + ':' + case['attributes'].get('Action', 'Enable') + ':'
                              + case['attributes'].get('Context', 'Self'))
                    source_root = roots['|'.join((build, corpus['name'], case['file']))]
                    top_path = '/'.join(case['path'].split('/')[:2])
                    top = next(n for n in source_root if _pointer(source_root, n) == top_path)
                    candidates = source_root.findall('./WwiseObject') if top.tag == 'ObjectBase' else [top]
                    consumers = []
                    for node in candidates:
                        key = (build, corpus['name'], case['file'], node)
                        if key not in scopes:
                            scopes[key] = _scope(source_root, node)
                        lineage, _ = scopes[key]
                        if top not in lineage:
                            continue
                        consumers.append({'catalog': _catalog_identity(node, catalogs[version]),
                            'source_pointer': _pointer(source_root, node),
                            'source_lineage': [_pointer(source_root, n) for n in lineage]})
                    # Exact direct field or all declared fields of a gated base.
                    selected = next((n for n in top.findall('./Properties/*')
                        if case['path'].startswith(_pointer(source_root, n) + '/')), None)
                    selected_fields = [selected] if selected is not None else top.findall('./Properties/*')
                    fields = [{'name': n.get('Name'), 'kind': n.tag, 'type': n.get('Type'),
                        'source_pointer': _pointer(source_root, n),
                        'definition_sha256': hashlib.sha256(ET.tostring(n)).hexdigest()}
                        for n in selected_fields if n.tag in {'Property', 'Reference'}]
                dependency_kind, dependencies = None, []
                if original and original['scope'] == 'inner-tool-record':
                    dependency_kind, dependencies = 'batch', deepcopy(original['control_dependencies'])
                    for route, fact in (
                        ('function|ak.wwise.core.object.getPropertyInfo',
                         'Registered UserProjectSettings/BatchRenameSettings instance and field discovery; InnerTypes declaration alone proves no accessor.'),
                        ('function|ak.wwise.core.object.set',
                         'Supported owned Inner identity/addressability under UserProjectSettings; no invented ordinary GUID.')):
                        dependencies.append({'owner_issue': ownership[route]['owner_issue'], 'parent_issue': 174,
                            'route': route, 'missing_fact': fact})
                elif original and original['resolution'] == 'controller_source_unresolved':
                    dependency_kind, dependencies = 'music', deepcopy(original['control_dependencies'])
                elif original and original['resolution'] == 'declared_group_without_selected_field':
                    dependency_kind = 'fieldless'
                    route = 'function|ak.wwise.core.object.getPropertyInfo'
                    dependencies = [{'owner_issue': ownership[route]['owner_issue'], 'parent_issue': 174,
                        'route': route, 'missing_fact': 'Exact native field applicability of the fieldless PositioningType source group.'}]
                if not consumers or any(c['catalog'] is None for c in consumers):
                    raise ValueError('Unresolved condition source consumer must be assigned explicitly')
                source_key = '|'.join((build, corpus['name'], case['file']))
                for field in fields:
                    definition = indexed_fields(source_key)[field['source_pointer']]
                    field['definition_sha256'] = hashlib.sha256(ET.tostring(definition)).hexdigest()
                    field['attributes'] = dict(definition.attrib)
                parent = None
                if dependency_kind == 'batch':
                    source_root = roots[source_key]
                    top = next(n for n in source_root if n.tag == 'WwiseObject' and n.get('Name') == 'UserProjectSettings')
                    parent = {'source_pointer': _pointer(source_root, top),
                        'catalog': _catalog_identity(top, catalogs[version]),
                        'definition_sha256': hashlib.sha256(ET.tostring(top)).hexdigest(),
                        'instance_or_accessor_observed': False}
                rows.append({'occurrence_id': identity, 'version': version, 'build': build,
                    'source_file': case['file'], 'source_pointer': case['path'],
                    'source_file_sha256': branches[identity]['source_file_sha256'],
                    'source_xml': case['xml'], 'source_attributes': deepcopy(case['attributes']),
                    'recipe': recipe, 'consumers': consumers, 'source_fields': fields, 'source_parent': parent,
                    'effective_platform': 'not_observed; current live selected view and link-state guards remain mandatory',
                    'mutation_addressability': 'not_inferred_from_source_definition',
                    'predicate': deepcopy(original['predicate']) if original else None,
                    'members': sorted(by_occurrence[identity], key=lambda m: m['id']),
                    'original_program_groups': deepcopy(original['original_program_groups']) if original else [],
                    'dependency_kind': dependency_kind, 'dependencies': dependencies,
                    'metadata_scope': 'source_definition', 'direct_recipient_class_metadata': 'not_observed',
                    'direct_recipient_instance_metadata': 'not_observed', 'direct_recipient_native_effect': 'not_observed'})
    expected = {i: b['shape_sha256'] for i, b in branches.items()}
    pairs = [(m['id'], m['shape_sha256']) for r in rows for m in r['members']]
    if len(pairs) != len(expected) or dict(pairs) != expected:
        raise ValueError('Exact full installed condition ID/shape roster differs')
    return {'contract': 'waapi-skill.condition-definition-mapping/v1', 'owner_issue': 177,
        'parent_issue': 174, 'source_manifest_sha256': hashlib.sha256((root / 'docs/branch-coverage-condition-sources.json').read_bytes()).hexdigest(),
        'members_sha256': digest(sorted(pairs)), 'recipes': sorted({r['recipe'] for r in rows}),
        'occurrences': rows}


def _review(root):
    raw = (root / REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEW_SHA256:
        raise ValueError('Exact reviewed condition completion proof differs')
    review = json.loads(raw)
    if hashlib.sha256((root / PROOF_PATH).read_bytes()).hexdigest() != review['proof_archive_sha256']:
        raise ValueError('Original condition proof archive changed')
    sources = {**review['current_sources'],
        'docs/branch-coverage-condition-sources.json': review['source_manifest_sha256'],
        'tests/fixtures/metadata-conditions/self-scalar-source-parents.json.gz': review['source_snapshot_sha256']}
    if any(hashlib.sha256((root / p).read_bytes()).hexdigest() != h for p, h in sources.items()):
        raise ValueError('Reviewed current public condition mechanism source changed')
    return review


@lru_cache(maxsize=2)
def _proofs(root_string, review_sha):
    root = Path(root_string); review = _review(root)
    raw = (root / PROOF_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != review['proof_archive_sha256']:
        raise ValueError('Original condition proof archive changed')
    archive = json.loads(gzip.decompress(raw)); files = {}
    for name, entry in archive.items():
        value = base64.b64decode(entry['bytes_base64'], validate=True)
        if hashlib.sha256(value).hexdigest() != entry['sha256']:
            raise ValueError('Original condition witness digest differs')
        files[name] = value
    for descriptor in [*review['anchors'].values(), *review['class_metadata'].values()]:
        if hashlib.sha256(files[descriptor['file']]).hexdigest() != descriptor['sha256']:
            raise ValueError('Reviewed original condition witness differs')
    current = json.loads(files[review['anchors']['current_program']['file']])
    _validate_current_program(current, review, root, 'product')
    return files


def _validate_current_program(current, review, root, scope_kind):
    from tests.support.condition_mechanism_reuse import _require_object_scope_mechanism
    if (current.get('contract') != 'waapi-skill.condition-current-public-mechanism/v1'
            or current.get('scope_kind') != scope_kind
            or current.get('evidence_kind') != 'injected_client_program'
            or current.get('reports') != {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}
            or current.get('metadata_scope') != 'source_definition'
            or any(current.get(k) != 'not_observed' for k in ('direct_recipient_class_metadata',
                'direct_recipient_instance_metadata', 'direct_recipient_native_effect'))):
        raise ValueError('Exact current public mechanism scope/outcome differs; controlled cannot grant product credit')
    if any(current['sources'].get(p) != h for p, h in review['current_sources'].items() if p in current['sources']):
        raise ValueError('Current public program source seal differs')
    for kind, field, controller in (('Source', 'BaseFrequency', 'FrequencyMode'),
                                   ('AudioDevice', 'MainMixHeadphoneConfiguration', 'Allow3DAudio')):
        bridge = review['class_route_bridge'][kind]
        flow = current['observations'][bridge['current_public_observation']]
        catalog = load(root / 'skills/waapi-skill/resources/metadata/2025.1/object-types.json')['types']
        registered, = [c for c in catalog if c['classId'] == bridge['representative_class_id']]
        if (flow['before'].get('type') != bridge['live_type']
                or flow['before'].get('classId') != bridge['representative_class_id']
                or flow.get('class_catalog') != registered or registered['type'] != kind
                or flow['after'] != {**flow['before'], field: flow['native_call']['args']['value']}
                or flow['gateway']['exit_code'] != 0 or flow['gateway']['payload'].get('verified') is not True):
            raise ValueError('Specific current class-route bridge differs')
        _require_object_scope_mechanism(flow, {'selected_field': field, 'controller': controller})


@lru_cache(maxsize=2)
def _expected(root_string, review_sha):
    root = Path(root_string)
    mapping = definition_mapping(root)
    branches = {b['id']: b for b in installed_obligations(root, digest=digest, load=load)
                if b['owner_issue'] == 177 and b['kind'] == 'metadata_condition'}
    return mapping, branches


def validate_mapping_attachment(descriptor, base, root, *, selected_mapping=None):
    from tests.support.condition_mechanism_reuse import _read
    review = _review(root); files = _proofs(str(root), REVIEW_SHA256)
    attachment = _read(descriptor, base)
    if (set(attachment) != {'contract', 'review', 'mapping'}
            or attachment['contract'] != 'waapi-skill.condition-definition-attachment/v1'
            or attachment['review'].get('sha256') != REVIEW_SHA256
            or _read(attachment['review'], base) != review):
        raise ValueError('Closed exact reviewed condition definition attachment required')
    proposed = _read(attachment['mapping'], base) if selected_mapping is None else selected_mapping
    expected, branches = _expected(str(root), REVIEW_SHA256)
    if proposed != expected:
        raise ValueError('The exact source definition/member/class/grammar mapping differs')
    if set(proposed['recipes']) != set(review['recipe_public_proofs']):
        raise ValueError('Every exact source recipe needs its reviewed public proof')
    members = {m['id']: r for r in proposed['occurrences'] for m in r['members']}
    for row in proposed['occurrences']:
        for group in row['original_program_groups']:
            original = review['original_program_groups'][group]
            if original['original_observation_status'] != 'passed' or original['not_a_current_recipient_run'] is not True:
                raise ValueError('An original failed row cannot be promoted by shared proof')
    return {'review': review, 'mapping': proposed, 'members': members, 'branches': branches, 'files': files}


def _class_metadata(row, context):
    """Only the exact accepted R85 fields and explicit LFO version bridge."""
    review, files = context['review'], context['files']
    selected = None
    for name, field, number in (('ModulatorLfo', 'LfoSmoothing', '017'), ('ModulatorLfo', 'LfoPWM', '018'),
            ('Wwise Compressor', 'ChannelLinkPercentage', '034'), ('Ak Sidechain Send', 'LPF', '038'),
            ('MediaPoolFilter', 'FieldName', '042')):
        if any(c['catalog']['name'] == name for c in row['consumers']) and f'Property[{field}]/Dependencies' in row['source_pointer']:
            if name != 'ModulatorLfo' and row['version'] != '2025.1':
                continue
            version = '2021' if row['version'] == '2021.1' and name == 'ModulatorLfo' else '2025'
            selected = (review['class_metadata'][version + '-' + number], field)
            break
    if selected is None:
        return None
    descriptor, field = selected
    raw = json.loads(files[descriptor['file']])
    actual = raw['agent_result']
    if (raw.get('ok') is not True or actual['scope'].get('kind') != 'object_type'
            or actual['metadata']['name'] != field
            or actual['scope']['resolved'] not in [c['catalog'] for c in row['consumers']]
            or actual.get('mutation_authority') is not False):
        raise ValueError('Actual exact class metadata/source recipient differs')
    definition, = [f for f in row['source_fields'] if f['name'] == field]
    source = ET.fromstring(row['source_xml'])
    enumeration = source.find('.//Enumeration')
    from tests.support.condition_scalar_batch import _scalar
    literals = (row['predicate']['values'] if row['predicate'] is not None else
        [_scalar(n.text, enumeration.get('Type')) for n in enumeration if n.tag == 'Value'])
    dependencies = actual['metadata']['dependencies']
    if (len(dependencies) != 1 or actual['metadata']['type'] != definition['type']
            or dependencies[0].get('type') != 'property'
            or dependencies[0].get('property') != row['source_attributes']['Name']
            or dependencies[0].get('action') != row['source_attributes'].get('Action', 'Enable')
            or dependencies[0].get('context') != row['source_attributes'].get('Context', 'Self')
            or len(dependencies[0].get('conditions', [])) != 1
            or dependencies[0]['conditions'][0].get('restriction', {}).get('type') != 'enum'
            or digest([v['value'] for v in dependencies[0]['conditions'][0]['restriction']['values']]) != digest(literals)):
        raise ValueError('Actual exact class metadata/source typed dependency graph differs')
    return {'receipt': descriptor, 'scope': actual['scope'],
        'version_bridge': 'accepted-r85-five-version-LFO-source-and-class' if row['version'] not in ('2021.1', '2025.1') else None}


def witness_references(row, context):
    """Stable original proof identities, never a fabricated per-member run ID."""
    names = [n for n in context['review']['recipe_public_proofs'][row['recipe']]
             if n in {'time', 'bed', 'weight', 'association', 'action', 'eq', 'system-reference'}]
    return [{'original_proof_id': n + ':' + context['review']['anchors'][n]['sha256'],
        'original': context['review']['anchors'][n],
        'scope': 'reviewed original witness package; internal original run/observation identities retained verbatim; not one run per binding'} for n in names]


def _binding(row, member, attachment):
    return {'branch_id': member['id'], 'native_shape_sha256': member['shape_sha256'],
        'condition_source_mapping_attachment': attachment, 'definition_occurrence': row['occurrence_id'],
        'evidence': {c: attachment for c in ('program', 'native', 'live_metadata')},
        'public_mechanism': {'entrypoint': 'skills/waapi-skill/scripts/run.py gateway.py',
            'operations': ['object.setProperty', 'object.setReference'],
            'identity': 'selected existing object and live discovered field handles; no invented recipient GUID',
            'construction': 'operation_registry.py#_apply_reference_activation_dependencies',
            'verification': 'operation_registry.py#verify_prepared_operation',
            'source_definition_only': True}}


def mapping_evidence_result(descriptor, branch, category, scope_kind, base, binding, root, *, context=None):
    """Called by the existing reader, retaining definition versus observation."""
    try:
        proof = binding['condition_source_mapping_attachment']
        if descriptor != proof:
            raise ValueError('Exact condition source attachment descriptor required')
        context = context or validate_mapping_attachment(proof, base, root)
        row = context['members'][branch['id']]
        expected = context['branches'][branch['id']]
        member = next(m for m in row['members'] if m['id'] == branch['id'])
        if (any(branch.get(k) != v for k, v in expected.items() if k != 'state')
                or binding != _binding(row, member, proof)):
            raise ValueError('Exact source branch owner/type/version/controller/shape differs')
        if scope_kind != 'product':
            raise ValueError('Reviewed product source definition cannot change evidence scope')
        if row['dependencies']:
            return 'implementation_dependency', json.dumps(row['dependencies'], sort_keys=True)
        if category == 'live_metadata':
            observed = _class_metadata(row, context)
            if observed is None:
                return 'missing', 'Source definition supplies no observed recipient class or instance metadata'
            return 'reviewed_class_metadata_and_object_scope_mechanism', json.dumps(observed, sort_keys=True)
        if category == 'program':
            return 'reviewed_source_definition_and_public_mechanism', ('metadata_scope=source_definition; '
                'direct_recipient_class_metadata=not_observed; direct_recipient_instance_metadata=not_observed; '
                'original_row_program_is_not_a_new_recipient_execution')
        if category == 'native':
            return 'reviewed_source_definition_and_native_mechanism', json.dumps({'original_native_witness_proofs': witness_references(row, context),
                'direct_recipient_native_effect': 'not_observed', 'new_native_runs': 0}, sort_keys=True)
        raise ValueError('Unknown condition source proof category')
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return 'missing', str(exc)


def export_mapping(root, destination):
    """Add this exact source scope to existing accounting; never run a recipient."""
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    review = _review(root); _proofs(str(root), REVIEW_SHA256)
    mapping, branches = _expected(str(root), REVIEW_SHA256)
    def write(name, value):
        path = destination / name
        if path.exists():
            raise ValueError('Condition mapping publication is immutable')
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
        return {'artifact': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    attachment = write('attachment.json', {'contract': 'waapi-skill.condition-definition-attachment/v1',
        'review': write('review.json', review), 'mapping': write('mapping.json', mapping)})
    bindings, policies = {}, {}
    context = {'review': review, 'files': _proofs(str(root), REVIEW_SHA256)}
    for row in mapping['occurrences']:
        observed = _class_metadata(row, context)
        for member in row['members']:
            identity = member['id']
            bindings[identity] = _binding(row, member, attachment)
            policies[identity] = {'native_shape_sha256': member['shape_sha256'],
                'categories': ['program', 'native', *(['live_metadata'] if observed else [])],
                'reason': 'Reviewed exact source definition and shared current public/native mechanism; no direct recipient observation inferred.',
                'definition_scope': 'source_definition', 'original_requirement_lineage': 'f72 pending proposal remains unchanged',
                'implementation_dependencies': row['dependencies']}
    document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings}
    write('bindings.json', document)
    # Preserve every pre-existing non-installed metadata/result/verification row.
    requirements = deepcopy(load(root / 'docs/branch-coverage-requirements.json'))
    requirements['branches'].update(policies)
    write('requirements.json', requirements)
    return {'attachment': attachment, 'mapping': mapping, 'bindings': document, 'requirements': requirements}


def attach_definition_mappings(descriptors, bindings, base, root):
    """One portable attachment adds the exact source scope, atomically."""
    if not isinstance(descriptors, list) or len(descriptors) != 1:
        raise ValueError('One exact complete condition definition attachment required')
    descriptor = descriptors[0]
    context = validate_mapping_attachment(descriptor, base, root)
    pending = {}
    for row in context['mapping']['occurrences']:
        for member in row['members']:
            if member['id'] in bindings:
                raise ValueError('Conflicting condition definition binding; original evidence must remain separate')
            pending[member['id']] = _binding(row, member, descriptor)
    bindings.update(pending)
    return {'review_id': context['review']['review_id'], 'exact_source_members': len(pending),
        'metadata_scope': 'source_definition', 'new_native_runs': 0}


def evaluate_definition_binding(branch, binding, policy, scope_kind, base, root, context):
    """Existing completion reader's source-specific category hook."""
    if (policy.get('native_shape_sha256') != branch['shape_sha256']
            or not policy.get('reason') or policy.get('definition_scope') != 'source_definition'
            or policy.get('categories') not in (['program', 'native'], ['program', 'native', 'live_metadata'])):
        branch.update(state='unresolved', reasons=['Exact final source-definition requirements missing or stale'])
        return
    branch['requirements'] = policy['categories'][:]
    branch['evidence_results'] = {}
    for category in branch['requirements']:
        outcome, reason = mapping_evidence_result(binding.get('evidence', {}).get(category), branch,
            category, scope_kind, base, binding, root, context=context)
        branch['evidence_results'][category] = {'outcome': outcome, 'reason': reason}
    outcomes = {r['outcome'] for r in branch['evidence_results'].values()}
    branch.update(metadata_scope='source_definition', direct_recipient_class_metadata='not_observed',
        direct_recipient_instance_metadata='not_observed', direct_recipient_native_effect='not_observed')
    branch['state'] = ('implementation_dependency' if outcomes == {'implementation_dependency'} else
        'source_definition_verified' if outcomes <= {'reviewed_source_definition_and_public_mechanism',
        'reviewed_source_definition_and_native_mechanism', 'reviewed_class_metadata_and_object_scope_mechanism'} else 'implemented_unverified')
    if branch['state'] == 'implementation_dependency':
        branch['implementation_dependencies'] = deepcopy(context['members'][branch['id']]['dependencies'])
    if 'reviewed_class_metadata_and_object_scope_mechanism' in outcomes:
        branch['metadata_scope'] = 'object_type'
        branch['class_metadata_receipt'] = _class_metadata(context['members'][branch['id']], context)
        branch['direct_recipient_class_metadata'] = ('reviewed_version_bridge; not_directly_observed_in_this_version'
            if branch['class_metadata_receipt']['version_bridge'] else 'observed_object_type_receipt')

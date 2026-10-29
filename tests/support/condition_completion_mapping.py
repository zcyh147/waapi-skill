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

NEW_OBJECT_PROOF_SHA256 = 'f8e1c64cae348dd48a6906b8789bdb1212595b5666038e97e935c6767e7a20f9'
REVIEW_PATH = 'tests/fixtures/metadata-conditions/condition-completion-review.json'
PROOF_PATH = 'tests/fixtures/metadata-conditions/condition-completion-proof-inputs.json.gz'
REVIEW_SHA256 = '56fe04bfe969fdafa404184a1166002a827c702561918dcc03a7948605acff84'
SOURCE_RECONCILIATION_PATH = 'tests/fixtures/metadata-conditions/condition-source-reconciliation.json'
SOURCE_RECONCILIATION_SHA256 = 'a7878fdc332b5e2b1b9764d09f05468fab7e2974ec77015a6bf8075543977963'
FIELDLESS_REVIEW_PATH = 'tests/fixtures/metadata-conditions/condition-fieldless-structure-review.json'
FIELDLESS_REVIEW_SHA256 = 'ad1abc319b41b1bfc157a09ed6630bd9af65d8a68cfe56a963a2d618c751d794'
BATCH_EXCLUSION_REVIEW_PATH = 'tests/fixtures/metadata-conditions/batch-rename-settings-exclusion-review.json'
BATCH_EXCLUSION_REVIEW_SHA256 = '40f248258e77b9216aea0608484299f9b021f34300b4bbcf6c7fdcc9892e2716'
MUSIC_LIMIT_REVIEW_PATH = 'tests/fixtures/metadata-conditions/music-hidden-dependency-review.json'
MUSIC_LIMIT_REVIEW_SHA256 = '9995235ea5c3494866cb97cd9d6e8ac32e259c2d84d9d5bf9b153a809f1ba74d'


def _music_limit_review(root):
    raw = (root / MUSIC_LIMIT_REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != MUSIC_LIMIT_REVIEW_SHA256:
        raise ValueError('Exact Music Playlist hidden-dependency review differs')
    review = json.loads(raw)
    text = (root / review['authority_path']).read_text(encoding='utf-8')
    heading = review['authority_heading'] + '\n'
    if text.count(heading) != 1:
        raise ValueError('Music Playlist hidden-dependency decision is missing or ambiguous')
    section = heading + text.split(heading, 1)[1].split('\n## ', 1)[0].strip() + '\n'
    if hashlib.sha256(section.encode('utf-8')).hexdigest() != review['authority_section_sha256']:
        raise ValueError('Exact Music Playlist hidden-dependency decision differs')
    return review


def _map_music_limit(rows, review):
    """Accept only the hidden-controller mutation boundary, preserving its source."""
    selected = {r['occurrence_id']: r for r in rows if r['dependency_kind'] == 'music'}
    if set(selected) != {r['occurrence_id'] for r in review['occurrences']}:
        raise ValueError('Exact Music Playlist hidden-dependency roster differs')
    members = sorted((m['id'], m['shape_sha256']) for r in selected.values() for m in r['members'])
    if len(members) != review['member_count'] or digest(members) != review['members_sha256']:
        raise ValueError('Exact Music Playlist hidden-dependency members differ')
    for expected in review['occurrences']:
        row = selected[expected['occurrence_id']]
        if (digest(row) != expected['source_row_sha256']
                or [c['catalog'] for c in row['consumers']] != [
                    {'classId': 2359312, 'name': 'MusicPlaylistItem', 'type': 'WObject'}]
                or row['source_pointer'] != 'PluginModule/WwiseObject[MusicPlaylistItem]/Properties/Property[LoopCount]/Dependencies'
                or row['predicate'] != {'kind': 'enum', 'type': 'bool', 'values': [False]}):
            raise ValueError('Exact Music Playlist hidden-dependency identity/source differs')
    for row in selected.values():
        row['dependencies'] = []
        row['approved_exclusion'] = {key: review[key] for key in (
            'review_id', 'authority', 'authority_section_sha256', 'scope', 'when',
            'reads_retained', 'exposed_controller_path_retained', 'execution_credit',
            'native_absence_claim', 'writable_field_proof', 'observation_scope')}
        row['approved_exclusion']['review_sha256'] = MUSIC_LIMIT_REVIEW_SHA256


def _batch_exclusion_review(root):
    raw = (root / BATCH_EXCLUSION_REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != BATCH_EXCLUSION_REVIEW_SHA256:
        raise ValueError('Exact Batch Rename window exclusion review differs')
    review = json.loads(raw)
    text = (root / review['authority_path']).read_text(encoding='utf-8')
    heading = review['authority_heading'] + '\n'
    if text.count(heading) != 1:
        raise ValueError('Batch Rename window exclusion decision is missing or ambiguous')
    section = heading + text.split(heading, 1)[1].split('\n## ', 1)[0].strip() + '\n'
    if hashlib.sha256(section.encode('utf-8')).hexdigest() != review['authority_section_sha256']:
        raise ValueError('Exact Batch Rename window exclusion decision differs')
    return review


def _map_batch_exclusions(rows, review):
    """Apply the recorded scope decision only to the frozen window-setting rows."""
    selected = {r['occurrence_id']: r for r in rows if r['dependency_kind'] == 'batch'}
    if set(selected) != {r['occurrence_id'] for r in review['occurrences']}:
        raise ValueError('Exact Batch Rename window exclusion roster differs')
    members = sorted((m['id'], m['shape_sha256']) for r in selected.values() for m in r['members'])
    if len(members) != review['member_count'] or digest(members) != review['members_sha256']:
        raise ValueError('Exact Batch Rename window exclusion members differ')
    for expected in review['occurrences']:
        row = selected[expected['occurrence_id']]
        if (digest(row) != expected['source_row_sha256']
                or row['source_parent']['catalog'] != {'classId': 3342352, 'name': 'UserProjectSettings', 'type': 'WObject'}
                or [c['catalog'] for c in row['consumers']] != [
                    {'classId': 65011712, 'name': 'BatchRenameSettings', 'type': 'Inner'}]):
            raise ValueError('Exact Batch Rename window exclusion identity/source differs')
    for row in selected.values():
        row['dependencies'] = []
        row['approved_exclusion'] = {key: review[key] for key in (
            'review_id', 'authority', 'decision_url', 'authority_section_sha256',
            'settings_class_id', 'parent_class_id')}
        row['approved_exclusion'].update(review_sha256=BATCH_EXCLUSION_REVIEW_SHA256,
            execution_credit=False, native_absence_claim=False)


def _fieldless_review(root):
    raw = (root / FIELDLESS_REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIELDLESS_REVIEW_SHA256:
        raise ValueError('Exact fieldless source structure review differs')
    review = json.loads(raw)
    for key in ('original_mapping', 'source_snapshot'):
        source = review[key]
        if hashlib.sha256((root / source['path']).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Reviewed fieldless source structure input differs: ' + key)
    return review


def _map_fieldless_structure(rows, roots, review):
    """Account for exact source groups without asserting a field or UI effect."""
    by_id = {row['occurrence_id']: row for row in rows}
    selected = {row['occurrence_id'] for row in rows if row['dependency_kind'] == 'fieldless'}
    if selected != {row['occurrence_id'] for row in review['occurrences']}:
        raise ValueError('Exact fieldless source structure roster differs')
    pending = []
    for expected in review['occurrences']:
        row = by_id[expected['occurrence_id']]
        if digest(row) != expected['source_row_sha256'] or row['members'] != expected['members']:
            raise ValueError('Exact fieldless source structure identity/controller/consumer differs')
        source = roots['|'.join((row['build'], 'condition', row['source_file']))]
        def node(pointer):
            matches = [n for n in source if _pointer(source, n) == pointer]
            if len(matches) != 1:
                raise ValueError('Fieldless source structure node is missing or ambiguous')
            return matches[0]
        group = node(expected['group_pointer'])
        wrapper = node(expected['wrapper_pointer'])
        peer_node = node(expected['peer_pointer'])
        for item, key in ((group, 'group_node_sha256'), (wrapper, 'wrapper_node_sha256'),
                          (peer_node, 'peer_node_sha256')):
            if hashlib.sha256(ET.tostring(item)).hexdigest() != expected[key]:
                raise ValueError('Exact fieldless source structure node differs')
        # No base edges means no fields can be inherited into this group.
        # Siblings in the wrapper retain their own fields and conditions.
        if (group.findall('./Properties/*') or group.findall('./ObjectBaseRef')
                or group.findall('./ObjectLists/*') or row['source_fields']):
            raise ValueError('Fieldless source structure gained owned/inherited fields or lists')
        if (row['source_attributes'] != {'Name': 'ListenerRelativeRouting', 'Action': 'Enable'}
                or row['predicate'] != {'kind': 'enum', 'type': 'bool', 'values': [True]}
                or any(c['controller']['state'] != 'declared'
                       or c['controller']['type'] != 'bool' for c in row['consumers'])):
            raise ValueError('Fieldless source structure controller or predicate differs')
        peer = by_id.get(expected['peer_occurrence_id'])
        if (peer is None or digest(peer) != expected['peer_mapping_sha256']
                or peer['dependencies'] or not peer['source_fields']
                or peer['recipe'] != row['recipe'] or peer['predicate'] != row['predicate']):
            raise ValueError('Fieldless source structure lacks its mapped real-field peer')
        pending.append((row, {'review_id': review['review_id'],
            'review_sha256': FIELDLESS_REVIEW_SHA256,
            'source_node_sha256': expected['group_node_sha256'],
            'declared_fields': [], 'inherited_fields': [], 'object_lists': [],
            'peer_occurrence_id': peer['occurrence_id'], 'shared_recipe': row['recipe'],
            'native_absence_claim': False, 'ui_effect': 'not_inferred_from_source_definition'}))
    for row, structure in pending:
        row['dependencies'] = []
        row['source_structure'] = structure


def definition_mapping(root, *, operation_mode='existing-object'):
    if operation_mode == 'new-object':
        from tests.support.new_condition_completion import expected as new_expected
        return deepcopy(new_expected(str(root))[0])
    if operation_mode != 'existing-object':
        raise ValueError('Unknown installed-condition operation mode')
    fieldless_review = _fieldless_review(root)
    batch_review = _batch_exclusion_review(root)
    music_review = _music_limit_review(root)
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
    _map_fieldless_structure(rows, roots, fieldless_review)
    _map_batch_exclusions(rows, batch_review)
    _map_music_limit(rows, music_review)
    return {'contract': 'waapi-skill.condition-definition-mapping/v1', 'owner_issue': 177,
        'parent_issue': 174, 'source_manifest_sha256': hashlib.sha256((root / 'docs/branch-coverage-condition-sources.json').read_bytes()).hexdigest(),
        'members_sha256': digest(sorted(pairs)), 'recipes': sorted({r['recipe'] for r in rows}),
        'occurrences': rows}


def _current_sources(root, review):
    """Admit only the pinned source successor, keeping original proof seals."""
    raw = (root / SOURCE_RECONCILIATION_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_RECONCILIATION_SHA256:
        raise ValueError('Exact condition source reconciliation differs')
    successor = json.loads(raw)
    if (set(successor) != {'contract', 'original_review_sha256', 'scope',
            'source_changes', 'source_additions', 'review_provenance'}
            or successor['contract'] != 'waapi-skill.condition-source-reconciliation/v1'
            or successor['original_review_sha256'] != REVIEW_SHA256):
        raise ValueError('Condition source reconciliation requires its exact original review')
    changes, additions = successor['source_changes'], successor['source_additions']
    sources = dict(review['current_sources'])
    for path, change in changes.items():
        if (sources.get(path) != change['before_sha256']
                or change['before_sha256'] == change['current_sha256']):
            raise ValueError('Condition source reconciliation predecessor differs')
        sources[path] = change['current_sha256']
    for path, addition in additions.items():
        if path in sources or addition['before_sha256'] is not None:
            raise ValueError('Condition source reconciliation addition has a predecessor')
        sources[path] = addition['current_sha256']
    return sources


def _review(root):
    raw = (root / REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEW_SHA256:
        raise ValueError('Exact reviewed condition completion proof differs')
    review = json.loads(raw)
    if hashlib.sha256((root / PROOF_PATH).read_bytes()).hexdigest() != review['proof_archive_sha256']:
        raise ValueError('Original condition proof archive changed')
    sources = {**_current_sources(root, review),
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
    attachment = _read(descriptor, base)
    if not isinstance(attachment, dict):
        raise ValueError('Closed condition definition attachment must be an object')
    if attachment.get('operation_mode') == 'new-object':
        from tests.support.new_condition_completion import validate_attachment
        return validate_attachment(attachment, base, root, selected_mapping=selected_mapping)
    review = _review(root); files = _proofs(str(root), REVIEW_SHA256)
    _fieldless_review(root)  # Recheck immutable inputs even after an expected-map cache hit.
    _batch_exclusion_review(root)
    _music_limit_review(root)
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
    if row.get('operation_mode') == 'new-object':
        return []
    names = [n for n in context['review']['recipe_public_proofs'][row['recipe']]
             if n in {'time', 'bed', 'weight', 'association', 'action', 'eq', 'system-reference'}]
    return [{'original_proof_id': n + ':' + context['review']['anchors'][n]['sha256'],
        'original': context['review']['anchors'][n],
        'scope': 'reviewed original witness package; internal original run/observation identities retained verbatim; not one run per binding'} for n in names]


def _binding(row, member, attachment):
    categories = (() if 'approved_exclusion' in row else ('program',) if 'source_structure' in row or row.get('operation_mode') == 'new-object'
                  else ('program', 'native', 'live_metadata'))
    result = {'branch_id': member['id'], 'native_shape_sha256': member['shape_sha256'],
        'condition_source_mapping_attachment': attachment, 'definition_occurrence': row['occurrence_id'],
        'evidence': {c: attachment for c in categories}}
    if 'approved_exclusion' in row:
        return {**result, 'approved_exclusion': deepcopy(row['approved_exclusion'])}
    if 'source_structure' in row:
        return {**result, 'source_structure': deepcopy(row['source_structure'])}
    if row.get('operation_mode') == 'new-object':
        result['public_mechanism'] = deepcopy(row['construction_correspondence'])
        result['applicability_obligations'] = deepcopy(row['applicability_obligations'])
        return result
    result['public_mechanism'] = {'entrypoint': 'skills/waapi-skill/scripts/run.py gateway.py',
            'operations': ['object.setProperty', 'object.setReference'],
            'identity': 'selected existing object and live discovered field handles; no invented recipient GUID',
            'construction': 'operation_registry.py#_apply_reference_activation_dependencies',
            'verification': 'operation_registry.py#verify_prepared_operation',
            'source_definition_only': True}
    return result


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
        if row.get('operation_mode') == 'new-object' and category != 'program':
            return 'missing', 'New-object correspondence supplies no native or recipient metadata observation'
        if row['dependencies']:
            return 'implementation_dependency', json.dumps(row['dependencies'], sort_keys=True)
        if 'approved_exclusion' in row:
            return 'missing', 'User-approved bounded exclusion supplies no execution or metadata evidence'
        if 'source_structure' in row:
            if category != 'program':
                return 'missing', 'Structural source mapping supplies no native or recipient metadata evidence'
            return 'reviewed_source_definition_and_public_mechanism', json.dumps({
                'metadata_scope': 'source_definition', 'source_structure': row['source_structure'],
                'direct_recipient_native_effect': 'not_observed', 'new_native_runs': 0}, sort_keys=True)
        if category == 'live_metadata':
            observed = _class_metadata(row, context)
            if observed is None:
                return 'missing', 'Source definition supplies no observed recipient class or instance metadata'
            return 'reviewed_class_metadata_and_object_scope_mechanism', json.dumps(observed, sort_keys=True)
        if category == 'program' and row.get('operation_mode') == 'new-object':
            return 'reviewed_source_definition_and_public_mechanism', json.dumps({
                'metadata_scope': 'source_definition',
                'representative_public_mechanism': row['representative_public_mechanism'],
                'program_proof': context['review']['program_proof'],
                'applicability_obligations': row['applicability_obligations'],
                'direct_recipient_native_effect': 'not_observed', 'new_native_runs': 0}, sort_keys=True)
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


def export_mapping(root, destination, *, operation_mode='existing-object'):
    """Add this exact source scope to existing accounting; never run a recipient."""
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    if operation_mode == 'new-object':
        from tests.support.new_condition_completion import review as new_review, expected as new_expected
        review = new_review(root)
        mapping, branches = new_expected(str(root))
    elif operation_mode == 'existing-object':
        review = _review(root); _proofs(str(root), REVIEW_SHA256)
        mapping, branches = _expected(str(root), REVIEW_SHA256)
    else:
        raise ValueError('Unknown installed-condition operation mode')
    _fieldless_review(root)
    _batch_exclusion_review(root)
    _music_limit_review(root)
    def write(name, value):
        path = destination / name
        if path.exists():
            raise ValueError('Condition mapping publication is immutable')
        path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
        return {'artifact': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    attachment = write('attachment.json', {'contract': 'waapi-skill.condition-definition-attachment/v1',
        **({'operation_mode': operation_mode} if operation_mode == 'new-object' else {}),
        'review': write('review.json', review), 'mapping': write('mapping.json', mapping)})
    bindings, policies = {}, {}
    context = {'review': review, 'files': {} if operation_mode == 'new-object' else _proofs(str(root), REVIEW_SHA256)}
    for row in mapping['occurrences']:
        observed = None if operation_mode == 'new-object' else _class_metadata(row, context)
        for member in row['members']:
            identity = member['id']
            bindings[identity] = _binding(row, member, attachment)
            policies[identity] = {'native_shape_sha256': member['shape_sha256'],
                'categories': ([] if 'approved_exclusion' in row else ['program'] if 'source_structure' in row or operation_mode == 'new-object' else
                    ['program', 'native', *(['live_metadata'] if observed else [])]),
                'reason': ('User-approved conditional refusal of MusicPlaylistItem LoopCount when its controller is not exposed; reads and exposed-controller paths remain in scope.'
                    if row['dependency_kind'] == 'music' else
                    'User-approved exclusion of exact internal Batch Rename window settings; object renaming remains in scope.'
                    if 'approved_exclusion' in row else
                    'Reviewed exact structural source group and shared scalar condition mechanism; no field, native effect or absence inferred.'
                    if 'source_structure' in row else
                    'Exact new-object source correspondence and shared public condition mechanism; independent target/plugin applicability stays assigned; no recipient-native effect inferred.'
                    if operation_mode == 'new-object' else
                    'Reviewed exact source definition and shared current public/native mechanism; no direct recipient observation inferred.'),
                'definition_scope': 'source_definition', 'original_requirement_lineage': 'f72 pending proposal remains unchanged',
                'implementation_dependencies': row['dependencies']}
            if 'approved_exclusion' in row:
                policies[identity]['approved_exclusion'] = deepcopy(row['approved_exclusion'])
    document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings}
    write('bindings.json', document)
    # Preserve every pre-existing non-installed metadata/result/verification row.
    requirements = deepcopy(load(root / 'docs/branch-coverage-requirements.json'))
    requirements['branches'].update(policies)
    write('requirements.json', requirements)
    return {'attachment': attachment, 'mapping': mapping, 'bindings': document, 'requirements': requirements}


def attach_definition_mappings(descriptors, bindings, base, root):
    """Import one complete attachment per mode atomically, preserving both scopes."""
    if not isinstance(descriptors, list) or not 1 <= len(descriptors) <= 2:
        raise ValueError('One exact complete condition definition attachment per mode required')
    contexts = [validate_mapping_attachment(d, base, root) for d in descriptors]
    modes = [c['mapping'].get('operation_mode', 'existing-object') for c in contexts]
    if len(set(modes)) != len(modes):
        raise ValueError('Duplicate condition definition operation mode')
    pending = {}
    for descriptor, context in zip(descriptors, contexts):
        for row in context['mapping']['occurrences']:
            for member in row['members']:
                if member['id'] in bindings or member['id'] in pending:
                    raise ValueError('Conflicting condition definition binding; original evidence must remain separate')
                pending[member['id']] = _binding(row, member, descriptor)
    bindings.update(pending)
    return {'review_id': contexts[0]['review']['review_id'] if len(contexts) == 1 else
            [c['review']['review_id'] for c in contexts], 'exact_source_members': len(pending),
        'metadata_scope': 'source_definition', 'new_native_runs': 0}


def evaluate_definition_binding(branch, binding, policy, scope_kind, base, root, context):
    """Existing completion reader's source-specific category hook."""
    row = context['members'][branch['id']]
    if 'approved_exclusion' in row:
        member = next(m for m in row['members'] if m['id'] == branch['id'])
        expected = context['branches'][branch['id']]
        if (scope_kind != 'product' or policy.get('categories') != []
                or policy.get('native_shape_sha256') != branch['shape_sha256'] or not policy.get('reason')
                or policy.get('definition_scope') != 'source_definition'
                or policy.get('approved_exclusion') != row['approved_exclusion']
                or any(branch.get(k) != v for k, v in expected.items() if k != 'state')
                or binding != _binding(row, member, binding.get('condition_source_mapping_attachment'))):
            branch.update(state='unresolved', reasons=['Exact user-approved bounded exclusion missing or stale'])
            return
        branch.update(state='approved_exclusion', requirements=[], evidence_results={},
            exclusion=deepcopy(row['approved_exclusion']), metadata_scope='source_definition',
            direct_recipient_class_metadata='not_observed', direct_recipient_instance_metadata='not_observed',
            direct_recipient_native_effect='not_observed')
        return
    structural = 'source_structure' in context['members'][branch['id']]
    allowed = (['program'],) if structural or row.get('operation_mode') == 'new-object' else (['program', 'native'], ['program', 'native', 'live_metadata'])
    if (policy.get('native_shape_sha256') != branch['shape_sha256']
            or not policy.get('reason') or policy.get('definition_scope') != 'source_definition'
            or policy.get('categories') not in allowed):
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

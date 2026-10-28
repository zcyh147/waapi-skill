"""Finite source-backed TransitionRoot/rule construction on two music owners.

The children collection certifies membership only: this adapter claims neither
rule priority nor automatic fade allocation/configuration or playback quality.
"""
from __future__ import annotations

from hashlib import sha256
import gzip
import json
from pathlib import Path
import re
from typing import Mapping
import xml.etree.ElementTree as ET

from .canonical import canonical_json_bytes, canonical_sha256
from .metadata_restrictions import condition_values_equal
from .builders.metadata import parse_get_property_info_result

VERSIONS = ('2023.1', '2024.1', '2025.1')
CLASS = 2424848
OWNERS = {'MusicSwitchContainer': 2293776, 'MusicPlaylistContainer': 2228240}
MAX_ITEMS, MAX_BYTES = 64, 32768
ROOT = Path(__file__).resolve().parents[1]
BUILDS = {'2023.1': '2023.1.19.8928', '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}
MANIFESTS = {'2023.1': '103f35083206246ccbcade0c43a159d6f51c0758efff48109ecb2844c19040d7',
    '2024.1': '45e1f3cd2e18f0c9d6b86adcc5ce5823a05bb059c26a6713c6c99e9461aa0f68',
    '2025.1': '1d6d6e32ec042c19c5ebd99b7b964c88410f9b90d26b073eb0869950b1a39c60'}
SOURCES = {
    '2023.1': ('bae4d5fdd821fef226f1939d34ba1810e08bf79578fb8edc4ae3bdc3c66bd468', '18feb6864dc219f6468b32c1670db14b6a23138c2d27bb5028a82310026b5a3d'),
    '2024.1': ('28c19c59fe681a9cb81e11cec8f80caea006274ea670dc1388966239d4ee8e7f', 'be298cfbaa7a82cd3c7975cc94f6cd3a90bed5df0465fbadeb489ba825ef868d'),
    '2025.1': ('3b363c24b7ffa032d7efc12f36023cd944b8f53323af33fcbe738c2193918454', '96244aad7c796698f8d965a80131b160ba02e03c592b139280a4a9ac79a589d6'),
}
GET = 'ak.wwise.core.object.get'
INFO = 'ak.wwise.core.object.getPropertyInfo'
NAMES = 'ak.wwise.core.object.getPropertyAndReferenceNames'
IDENTITY = ('id', 'name', 'type', 'path', 'classId', 'parent', 'owner', 'notes')
SCOPE = 'stored_root_rule_membership_and_selected_fields; priority_not_verified; fade_allocation_configuration_and_playback_not_verified'


def declaration_contract(version):
    return {'field': 'music_transitions', 'available': version in VERSIONS, 'supported_versions': list(VERSIONS),
        'scope': 'one_exact_existing_MusicSwitchContainer_or_MusicPlaylistContainer; standalone_object.set',
        'required': ['kind_handle', 'root_field_handle', 'mode', 'entries'],
        'kind_handle': 'live_discovered_MusicTransition_Type_Handle',
        'root_field_handle': 'TransitionRoot_Reference_Field_Handle_for_exact_existing_owner',
        'mode': ['append-rules', 'replace-entire-root'],
        'entries': 'bounded_array_of_rule_objects_with_only_optional_field_values',
        'field_values': 'selected_MusicTransition_class_scoped_scalar_or_reference_Field_Handle_to_business_value_map; references_are_bound_existing_Object_Handles_or_legal_null',
        'derived': 'Gateway_requests_Root_and_Transition_role_names_and_owns_IsFolder_true_root_false_rules; native_rename_conflicts_bind_actual_returned_names; omitted_fields_keep_native_defaults_and_only_selected_or_required_fields_are_verified',
        'effects': 'append_preserves_complete_existing_root_and_rules; explicit_replacement_removes_complete_root_and_all_rules; unrelated_owner_and_reference_target_state_preserved',
        'additive': 'append-rules_targets_bound_existing_root_GUID; preserves_all_old_rules_and_root_identity',
        'native_fields_names_GUIDs_custom_reference_JSON': 'forbidden',
        'limits': {'items_including_root': MAX_ITEMS, 'depth': 1, 'UTF8_bytes': MAX_BYTES},
        'verification_scope': SCOPE,
        'older_versions': 'this_modern_TransitionRoot_constructor_is_not_exposed; older_constructor_roles_remain_separately_assigned_not_native_absence'}


def fail(code, message):
    from .operation_registry import OperationContractError
    raise OperationContractError(code, message, details={'tracking_issue': 195})


def authority(version, *, root=None):
    if version not in VERSIONS:
        fail('MUSIC_TRANSITION_VERSION_BOUNDARY', 'This source-backed TransitionRoot constructor covers 2023.1–2025.1; older roles remain separate')
    package = ROOT if root is None else Path(root)
    source = package / 'references/semantic' / version / 'music-transition-sources'
    record_bytes = (source / 'source-contract.json').read_bytes()
    record = json.loads(record_bytes)
    manifest_sha = sha256((package / 'resources/manifest' / version / 'schemas.json').read_bytes()).hexdigest()
    if (record.get('contract') != 'waapi-skill.music-transition-source/v1' or record.get('version') != version
            or record.get('build') != BUILDS[version] or manifest_sha != record.get('manifest_sha256') or manifest_sha != MANIFESTS[version]
            or record['installed_xml']['source_key'] != BUILDS[version] + '|condition|WObjects/WObjects.xml'
            or record['installed_xml']['decompressed_sha256'] != SOURCES[version][0]
            or record['sdk']['sha256'] != SOURCES[version][1]):
        fail('MUSIC_TRANSITION_SOURCE_DRIFT', 'Transition source/version/build/reflected grammar differs')
    xml = gzip.decompress((source / 'WObjects.xml.gz').read_bytes())
    sdk = (source / 'ak_wwise_core_object_set.html').read_bytes()
    if (sha256(xml).hexdigest(), sha256(sdk).hexdigest()) != SOURCES[version]:
        fail('MUSIC_TRANSITION_SOURCE_DRIFT', 'Matching TransitionRoot definition or custom-object grammar changed')
    tree = ET.fromstring(xml)
    base = tree.find(".//ObjectBase[@Name='Common_TransitionNode']")
    reference = base.find("Properties/Reference[@Name='TransitionRoot']")
    if (reference.get('SupportLink') != 'false' or reference.get('SupportCustom') != 'true'
            or reference.find('Restrictions/NotNullRestriction') is None
            or [e.get('Name') for e in reference.findall('Restrictions/TypeEnumerationRestriction/Type')] != ['MusicTransition']):
        fail('MUSIC_TRANSITION_SOURCE_DRIFT', 'TransitionRoot must remain custom-only, non-null and exactly MusicTransition')
    for owner in OWNERS:
        if tree.find(".//WwiseObject[@Name='%s']/ObjectBaseRef[@Name='Common_TransitionNode']" % owner) is None:
            fail('MUSIC_TRANSITION_SOURCE_DRIFT', 'Music owner no longer inherits TransitionRoot')
    prop = tree.find(".//WwiseObject[@Name='MusicTransition']/Properties/Property[@Name='IsFolder']")
    if prop.get('Type') != 'bool' or prop.findtext('DefaultValue') != 'false':
        fail('MUSIC_TRANSITION_SOURCE_DRIFT', 'Transition rule structural default changed')
    return {'version': version, 'build': BUILDS[version], 'source_sha256': list(SOURCES[version]),
        'source_contract_sha256': sha256(record_bytes).hexdigest(), 'manifest_sha256': manifest_sha,
        'source_contract': 'custom_only_non_null_TransitionRoot_MusicTransition_recursive_children',
        'evidence': 'matching_primary_source_and_program_mechanism_only; no_new_native_execution'}


def guid(value):
    if not isinstance(value, str) or re.fullmatch(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}', value) is None:
        fail('INVALID_TRANSITION_READBACK', 'Transition identity must be an exact canonical GUID')
    if value == '{00000000-0000-0000-0000-000000000000}':
        fail('INVALID_TRANSITION_READBACK', 'TransitionRoot and rule identities cannot be null')
    return value.upper()


def ref(value, nullable=False):
    from .operation_plugin import _closed_object_reference_id
    if nullable:
        return _closed_object_reference_id(value, field='transition-reference', allow_none=True)
    return guid(value.get('id') if isinstance(value, Mapping) else value)


def field(row, name):
    if name in row: return row[name]
    if '@' + name in row: return row['@' + name]
    fail('INVALID_TRANSITION_READBACK', 'Required transition field absent: ' + name)


def compile_business(session, owner, payload):
    from .business_declarations import business_repair
    def reject(code, action):
        raise business_repair(code, field='music_transitions', action=action, tracking_issue=195)
    if session.context.wwise_version not in VERSIONS:
        reject('MUSIC_TRANSITION_VERSION_BOUNDARY', 'Use the separately assigned older-version role; this source-backed constructor covers 2023.1–2025.1 only')
    if owner.object_type not in OWNERS or owner.class_id not in (None, OWNERS[owner.object_type]):
        reject('MUSIC_TRANSITION_OWNER_REQUIRED', 'Bind an exact existing MusicSwitchContainer or MusicPlaylistContainer')
    if (not isinstance(payload, Mapping) or set(payload) != {'kind_handle', 'root_field_handle', 'mode', 'entries'}
            or payload['mode'] not in ('append-rules', 'replace-entire-root') or len(canonical_json_bytes(payload)) > MAX_BYTES):
        reject('MUSIC_TRANSITION_DECLARATION_INVALID', 'Choose append-rules or replace-entire-root explicitly and provide only the disclosed fields')
    kind = session.handles.resolve_type(payload['kind_handle'])
    root = session.handles.bound_field(payload['root_field_handle'])
    if kind.name != 'MusicTransition' or kind.class_id != CLASS:
        reject('MUSIC_TRANSITION_TYPE_REQUIRED', 'Select the discovered exact MusicTransition class')
    if (root.scope_kind != 'object' or guid(root.scope_value) != guid(owner.object_id) or root.field_kind != 'reference'
            or root.token != 'TransitionRoot' or root.platform is not None):
        reject('FIELD_HANDLE_SCOPE_MISMATCH', 'Discover TransitionRoot on this exact existing owner without a platform override')
    if not isinstance(payload['entries'], list) or not payload['entries'] or len(payload['entries']) >= MAX_ITEMS:
        reject('MUSIC_TRANSITION_TREE_LIMIT', 'Provide one to 63 transition rules')
    entries = []
    for raw in payload['entries']:
        if not isinstance(raw, Mapping) or set(raw) - {'field_values'} or not isinstance(raw.get('field_values', {}), Mapping) or len(raw.get('field_values', {})) > 32:
            reject('MUSIC_TRANSITION_DECLARATION_INVALID', 'Each rule accepts only a bounded Field Handle map')
        properties, references, seen = [], [], set()
        for handle, value in raw.get('field_values', {}).items():
            selected = session.handles.bound_field(handle)
            if (selected.scope_kind != 'class' or selected.scope_value != CLASS or selected.platform is not None
                    or selected.field_kind not in ('property', 'reference') or selected.token == 'IsFolder'):
                reject('FIELD_HANDLE_SCOPE_MISMATCH', 'Select MusicTransition class scalar/reference fields; Gateway owns IsFolder')
            if selected.token in seen:
                reject('OBJECT_GRAPH_FIELD_CONFLICT', 'Assign every transition field once')
            seen.add(selected.token)
            value = session.handles.validate_field_value(selected, value)
            if selected.field_kind == 'property':
                properties.append({'name': selected.token, 'value': value})
            else:
                target = None if value is None else {'kind': 'id', 'value': session.handles.resolve_object(value).object_id}
                references.append({'name': selected.token, 'target': target})
        entries.append({'properties': properties, 'references': references})
    return {'mode': payload['mode'], 'entries': entries, 'authority': authority(session.context.wwise_version)}


def validate_descriptor(payload, version):
    if version not in VERSIONS: authority(version)
    if (not isinstance(payload, Mapping) or set(payload) != {'mode', 'entries', 'authority'} or payload['mode'] not in ('append-rules', 'replace-entire-root') or len(canonical_json_bytes(payload)) > MAX_BYTES
            or not isinstance(payload['entries'], list) or not payload['entries'] or len(payload['entries']) >= MAX_ITEMS):
        fail('MUSIC_TRANSITION_DECLARATION_INVALID', 'Expected one bounded transition root/rule declaration')
    if payload['authority'] != authority(version):
        fail('MUSIC_TRANSITION_SOURCE_DRIFT', 'Transition constructor authority changed; create a fresh Draft')
    for node in payload['entries']:
        if not isinstance(node, Mapping) or set(node) != {'properties', 'references'}:
            fail('MUSIC_TRANSITION_DECLARATION_INVALID', 'Transition rule shapes are closed')
        seen = set()
        for collection, value_key in [('properties', 'value'), ('references', 'target')]:
            rows = node[collection]
            if not isinstance(rows, list) or len(rows) > 32:
                fail('MUSIC_TRANSITION_DECLARATION_INVALID', 'Transition rule fields exceed bounds')
            for row in rows:
                if (not isinstance(row, Mapping) or set(row) != {'name', value_key} or not isinstance(row['name'], str)
                        or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', row['name']) is None or row['name'] == 'IsFolder' or row['name'] in seen):
                    fail('MUSIC_TRANSITION_DECLARATION_INVALID', 'Transition fields are invalid or duplicated')
                seen.add(row['name'])
                if collection == 'references' and row['target'] is not None:
                    if not isinstance(row['target'], Mapping) or set(row['target']) != {'kind', 'value'} or row['target']['kind'] != 'id':
                        fail('MUSIC_TRANSITION_DECLARATION_INVALID', 'Transition references require exact bound IDs')
                    guid(row['target']['value'])
        if len(seen) > 32: fail('MUSIC_TRANSITION_DECLARATION_INVALID', 'Too many rule fields')
    return len(payload['entries']) + 1


def names(read, scope):
    rows = read(NAMES, scope, {}).get('return')
    if (not isinstance(rows, list) or len(rows) > 256 or not all(isinstance(x, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', x) for x in rows)
            or len(set(rows)) != len(rows)):
        fail('INVALID_METADATA', 'Transition field inventory must be exact and bounded')
    return rows


def rows(read, ids, fields):
    values = read(GET, {'from': {'id': ids}}, {'return': list(fields)}).get('return')
    if not isinstance(values, list) or len(values) > MAX_ITEMS or not all(isinstance(row, Mapping) for row in values):
        fail('INVALID_TRANSITION_READBACK', 'Transition readback must be bounded object rows')
    return values


def snapshot(read, object_id, tokens):
    fields = list(dict.fromkeys([*IDENTITY, 'children', *tokens]))
    result = {}
    for start in range(0, len(fields), 32):
        found = rows(read, [object_id], list(dict.fromkeys(['id', *fields[start:start + 32]])))
        if len(found) != 1 or guid(found[0].get('id')) != guid(object_id):
            fail('INVALID_TRANSITION_READBACK', 'Exact transition GUID must resolve once')
        if any(result[key] != value for key, value in found[0].items() if key in result):
            fail('INVALID_TRANSITION_READBACK', 'Object changed during bounded snapshot')
        result.update(found[0])
    return result


def tree_snapshot(read, root, tokens, owner_id):
    seen = set()
    def walk(object_id, parent, depth):
        object_id = guid(object_id)
        if object_id in seen or len(seen) >= MAX_ITEMS or depth > 1:
            fail('MUSIC_TRANSITION_TREE_LIMIT', 'Transition tree is duplicated, cyclic or exceeds root/rule bounds')
        seen.add(object_id)
        row = snapshot(read, object_id, tokens)
        if row.get('type') != 'MusicTransition' or row.get('classId') != CLASS or field(row, 'IsFolder') is not (depth == 0):
            fail('INVALID_TRANSITION_READBACK', 'Transition root/rule class or structural role differs')
        if ref(row.get('owner') if depth == 0 else row.get('parent')) != guid(parent):
            fail('INVALID_TRANSITION_READBACK', 'Transition root/rule ownership differs')
        edges = row.get('children')
        if edges is None:
            edges = read(GET, {'from': {'id': [object_id]}, 'transform': [{'select': ['children']}, {'range': [0, MAX_ITEMS + 1]}]}, {'return': ['id']}).get('return')
        if not isinstance(edges, list) or len(edges) > MAX_ITEMS:
            fail('INVALID_TRANSITION_READBACK', 'Transition membership must be independently returned and bounded')
        ids = [ref(edge) for edge in edges]
        if len(set(ids)) != len(ids): fail('INVALID_TRANSITION_READBACK', 'Duplicate transition member GUID')
        # Child enumeration has no authoritative priority semantics.
        row = {**row, 'children': [{'id': value} for value in sorted(ids)]}
        return {'row': row, 'children': [walk(value, object_id, depth + 1) for value in sorted(ids)]}
    return walk(root, owner_id, 0)


def prepare(payload, *, version, owner, catalog, read, resolve_target, validate_scalar, validate_reference):
    validate_descriptor(payload, version)
    if owner.row.get('type') not in OWNERS:
        fail('MUSIC_TRANSITION_OWNER_REQUIRED', 'TransitionRoot requires an exact existing supported music owner')
    classes = [row.as_dict() for row in catalog]
    selected = []
    for name, class_id in [(owner.row['type'], OWNERS[owner.row['type']]), ('MusicTransition', CLASS)]:
        match = [row for row in classes if row.get('classId') == class_id]
        if len(match) != 1 or match[0].get('name') != name:
            fail('INVALID_METADATA', 'Transition class catalog differs from matching source')
        selected.extend(match)
    inventory = names(read, {'classId': CLASS})
    metadata, cache = [], {}
    def info(scope, token):
        key = canonical_sha256([scope, token])
        if key not in cache:
            if scope == {'classId': CLASS} and token not in inventory:
                fail('MUSIC_TRANSITION_HIDDEN_DEPENDENCY', 'Required transition field is not exposed; do not probe hidden controls')
            value = parse_get_property_info_result(read(INFO, {**scope, 'property': token}, {}))
            if value.name != token: fail('INVALID_METADATA', 'Transition metadata field differs')
            cache[key] = value
            metadata.append({'scope': scope, 'name': token, 'value': value.as_dict()})
        return cache[key]
    root_info = info({'object': owner.object}, 'TransitionRoot')
    if root_info.restriction.get('type') != 'reference' or 'notNull' not in root_info.restriction.get('restrictions', []) or not any(isinstance(r, Mapping) and r.get('type') == ['MusicTransition'] for r in root_info.restriction.get('restrictions', [])):
        fail('INVALID_METADATA', 'TransitionRoot live target type contradicts matching owned reference source')
    structural = info({'classId': CLASS}, 'IsFolder')
    if structural.type != 'bool' or structural.default is not False: fail('INVALID_METADATA', 'Transition IsFolder source/live defaults differ')
    targets, conditions = {}, {}
    from .new_object_defaults import class_default_evidence, NewObjectDefaultError
    def native(node, path, root=False):
        props = {row['name']: row['value'] for row in node.get('properties', [])}
        props['IsFolder'] = root
        refs = {}
        infos = [info({'classId': CLASS}, token) for token in props]
        for record in infos: validate_scalar(record, props[record.name])
        for row in node.get('references', []):
            record = info({'classId': CLASS}, row['name'])
            if record.restriction.get('type') != 'reference':
                fail('INVALID_METADATA', 'Transition reference field is not a live Reference')
            resolved = None if row['target'] is None else resolve_target(row['target'], path + '.' + row['name'])
            if resolved is None:
                if 'notNull' in record.restriction.get('restrictions', []):
                    fail('INVALID_REFERENCE_TARGET', 'Selected transition reference cannot be null')
            else:
                validate_reference(record, resolved)
            refs[row['name']] = None if resolved is None else resolved.object
            infos.append(record)
            if resolved is not None and resolved.object not in targets:
                tokens = names(read, {'object': resolved.object})
                targets[resolved.object] = {'id': resolved.object, 'names': tokens, 'row': snapshot(read, resolved.object, tokens)}
        def guarded(uri, args, options):
            if uri != INFO or set(args) != {'classId', 'property'} or args['classId'] != CLASS:
                fail('MUSIC_TRANSITION_CONDITION_BOUNDARY', 'New transition conditions must stay in the exact class scope')
            return info({'classId': CLASS}, args['property']).as_dict()
        try:
            defaults = class_default_evidence(infos=infos, scope={'classId': CLASS}, read_call=guarded,
                supplied_values=props, supplied_references=refs, validate_scalar=validate_scalar, version=version)
        except NewObjectDefaultError as exc: fail(exc.error_code, str(exc))
        props.update(defaults.get('derived_properties', {}))
        conditions[path] = defaults['requirements']
        return {'type': 'MusicTransition', 'name': 'Root' if root else 'Transition',
            **{'@' + key: value for key, value in {**props, **refs}.items()}}
    native_root = native({}, '$.music_transitions', True)
    native_root['children'] = [native(node, '$.music_transitions.children[' + str(i) + ']') for i, node in enumerate(payload['entries'])]
    owner_names = names(read, {'object': owner.object})
    owner_state = snapshot(read, owner.object, owner_names)
    if owner_state.get('classId') != OWNERS[owner.row['type']]:
        fail('MUSIC_TRANSITION_OWNER_REQUIRED', 'Existing transition owner class differs from source')
    old = tree_snapshot(read, ref(field(owner_state, 'TransitionRoot')), inventory, owner.object)
    if payload['mode'] == 'append-rules' and len(old['children']) + len(payload['entries']) + 1 > MAX_ITEMS:
        fail('MUSIC_TRANSITION_TREE_LIMIT', 'Existing plus appended rules exceed the complete membership bound')
    return native_root, {'version': version, 'authority': payload['authority'], 'owner_id': owner.object,
        'classes': selected, 'metadata': metadata, 'class_field_names': inventory, 'owner_field_names': owner_names,
        'owner_snapshot': owner_state, 'old_tree': old, 'targets': list(targets.values()), 'native_tree': native_root,
        'condition_plans': conditions, 'mode': payload['mode'],
        'replacement_intent': 'append_rules_preserve_existing_root_and_rules' if payload['mode'] == 'append-rules' else 'replace_entire_transition_root_and_rules', 'verification_scope': SCOPE}


def replacement_notice(proof):
    def count(node): return 1 + sum(count(child) for child in node.get('children', []))
    return {'owner_id': proof['owner_id'], 'owner_name': proof['owner_snapshot']['name'], 'owner_path': proof['owner_snapshot']['path'],
        'old_root_id': proof['old_tree']['row']['id'], 'intent': proof['replacement_intent'],
        'removed_item_count': count(proof['old_tree']) if proof['mode'] == 'replace-entire-root' else 0,
        'preserved_item_count': count(proof['old_tree']) if proof['mode'] == 'append-rules' else 0,
        'replacement_item_count': count(proof['native_tree']) if proof['mode'] == 'replace-entire-root' else 0,
        'added_rule_count': len(proof['native_tree']['children']), 'verification_scope': SCOPE}


def guard_assertions(proof, *, read, after_write=False):
    checks = []
    def check(name, passed, evidence): checks.append({'name': name, 'passed': bool(passed), 'evidence': evidence})
    try:
        check('Transition source authority unchanged', authority(proof['version']) == proof['authority'], proof['authority'])
        classes = read('ak.wwise.core.object.getTypes', {}, {}).get('return', [])
        check('Transition exact classes unchanged', all([r for r in classes if r.get('classId') == wanted['classId']] == [wanted] for wanted in proof['classes']), classes)
        check('Transition class fields unchanged', names(read, {'classId': CLASS}) == proof['class_field_names'], proof['class_field_names'])
        for row in proof['metadata']:
            actual = parse_get_property_info_result(read(INFO, {**row['scope'], 'property': row['name']}, {})).as_dict()
            check('Transition selected field metadata unchanged: ' + row['name'], actual == row['value'], actual)
        check('Transition owner field inventory unchanged', names(read, {'object': proof['owner_id']}) == proof['owner_field_names'], proof['owner_field_names'])
        actual = snapshot(read, proof['owner_id'], proof['owner_field_names'])
        expected = proof['owner_snapshot']
        if after_write and proof['mode'] == 'replace-entire-root':
            actual = {k: v for k, v in actual.items() if k not in ('TransitionRoot', '@TransitionRoot')}
            expected = {k: v for k, v in expected.items() if k not in ('TransitionRoot', '@TransitionRoot')}
        check('Transition owner unrelated state preserved', actual == expected, {'expected': expected, 'actual': actual})
        for target in proof['targets']:
            check('Transition reference target field inventory unchanged', names(read, {'object': target['id']}) == target['names'], target['names'])
            actual = snapshot(read, target['id'], target['names'])
            check('Transition selected reference target preserved', actual == target['row'], {'expected': target['row'], 'actual': actual})
        if not after_write:
            actual = tree_snapshot(read, proof['old_tree']['row']['id'], proof['class_field_names'], proof['owner_id'])
            check('Transition complete previous root and rule membership unchanged', actual == proof['old_tree'], actual)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        check('Transition immutable facts remain readable', False, {'error': str(exc)})
    return checks


def verify(proof, payload, *, read):
    checks = guard_assertions(proof, read=read, after_write=True)
    def check(name, passed, evidence): checks.append({'name': name, 'passed': bool(passed), 'evidence': evidence})
    owner_id = guid(proof['owner_id'])
    owners = payload.get('objects', [])
    if not isinstance(owners, list) or not all(isinstance(row, Mapping) for row in owners):
        fail('INVALID_TRANSITION_RESULT', 'Native result associations must be bounded object rows')
    append = proof['mode'] == 'append-rules'
    association_id = proof['old_tree']['row']['id'] if append else owner_id
    associations = [row for row in owners if guid(row.get('id')) == guid(association_id)]
    if len(associations) != 1:
        fail('INVALID_TRANSITION_RESULT', 'Native result must associate the exact existing owner/root with new rules')
    result = associations[0] if append else associations[0].get('@TransitionRoot')
    if not isinstance(result, Mapping):
        fail('INVALID_TRANSITION_RESULT', 'TransitionRoot result identity is missing')
    owner = snapshot(read, owner_id, ['TransitionRoot'])
    observed = tree_snapshot(read, ref(field(owner, 'TransitionRoot')), proof['class_field_names'], owner_id)
    new_ids, identities = set(), []
    references = {row['name'] for row in proof['metadata'] if row['value'].get('restriction', {}).get('type') == 'reference'}
    def matches(native, actual, path):
        try:
            for token, value in native.items():
                if token.startswith('@'):
                    actual_value = field(actual['row'], token[1:])
                    if token[1:] in references: actual_value = ref(actual_value, True)
                    if not condition_values_equal(actual_value, value): return False
            for requirement in proof['condition_plans'].get(path, []):
                actual_value = field(actual['row'], requirement['name'])
                if requirement['kind'] == 'reference': actual_value = ref(actual_value, True)
                if not condition_values_equal(actual_value, requirement['effective_value']): return False
            return True
        except ValueError:
            return False
    def bind_children(wanted, returned, actual, path):
        if not isinstance(returned, list) or len(returned) != len(wanted) or len(actual) != len(wanted):
            fail('INVALID_TRANSITION_RESULT', 'Complete new transition rule cardinality differs')
        by_id = {guid(child['row']['id']): child for child in actual}
        result_by_id = {guid(child.get('id')): child for child in returned if isinstance(child, Mapping)}
        if len(result_by_id) != len(returned) or set(by_id) != set(result_by_id):
            fail('INVALID_TRANSITION_RESULT', 'Result GUID set differs from independent complete new membership')
        # Match requested fields to independently stored GUIDs, never by an
        # unordered children enumeration or native result-array position.
        candidates = [[identity for identity, node in sorted(by_id.items())
            if matches(native, node, path + '.children[' + str(i) + ']')]
            for i, native in enumerate(wanted)]
        assigned = {}
        def assign(index, visited):
            for identity in candidates[index]:
                if identity in visited: continue
                visited.add(identity)
                if identity not in assigned or assign(assigned[identity], visited):
                    assigned[identity] = index
                    return True
            return False
        if not all(assign(i, set()) for i in range(len(wanted))):
            fail('INVALID_TRANSITION_RESULT', 'New GUIDs do not independently satisfy the complete requested rule population')
        bindings = {index: identity for identity, index in assigned.items()}
        for i, native in enumerate(wanted):
            identity = bindings[i]
            walk(native, result_by_id[identity], by_id[identity], path + '.children[' + str(i) + ']')
    def walk(native, returned, actual, path):
        if not isinstance(returned, Mapping): fail('INVALID_TRANSITION_RESULT', 'Transition result identities are missing')
        object_id = guid(returned.get('id'))
        check('Transition result GUID matches independent owner/member relation', object_id == guid(actual['row']['id']) and object_id not in new_ids, {'result': returned, 'actual': actual['row']['id']})
        new_ids.add(object_id)
        check('Transition returned native identity name matches independent readback',
            isinstance(returned.get('name'), str) and returned.get('name') == actual['row'].get('name'), actual['row'])
        for token, value in native.items():
            if token.startswith('@'):
                actual_value = field(actual['row'], token[1:])
                if token[1:] in references: actual_value = ref(actual_value, True)
                check('Transition selected/derived field matches', condition_values_equal(actual_value, value), {'field': token, 'expected': value, 'actual': actual_value})
        for requirement in proof['condition_plans'].get(path, []):
            actual_value = field(actual['row'], requirement['name'])
            if requirement['kind'] == 'reference': actual_value = ref(actual_value, True)
            check('Transition class prerequisite matches', condition_values_equal(actual_value, requirement['effective_value']), {'requirement': requirement, 'actual': actual_value})
        identities.append({'id': object_id, 'result_handle': 'bnh1-' + canonical_sha256([owner_id, path])[:32], 'occurrence_path': path})
        children = returned.get('children', [])
        if not isinstance(children, list): fail('INVALID_TRANSITION_RESULT', 'Transition result children must be bounded identity rows')
        wanted = native.get('children', [])
        check('Transition complete new rule membership matches', len(wanted) == len(children) == len(actual['children']), {'wanted': len(wanted), 'result': len(children), 'actual': len(actual['children'])})
        if len(wanted) == len(children) == len(actual['children']):
            bind_children(wanted, children, actual['children'], path)
    old_ids = [proof['old_tree']['row']['id'], *[child['row']['id'] for child in proof['old_tree']['children']]]
    if append:
        check('Transition append retains exact root GUID', guid(observed['row']['id']) == guid(old_ids[0]) == guid(result.get('id')), observed['row'])
        check('Transition existing-root result name matches independent identity', result.get('name') == observed['row'].get('name'), result)
        expected_root = {k: v for k, v in proof['old_tree']['row'].items() if k != 'children'}
        actual_root = {k: v for k, v in observed['row'].items() if k != 'children'}
        check('Transition append preserves root fields and identity', actual_root == expected_root, {'expected': expected_root, 'actual': actual_root})
        by_id = {guid(node['row']['id']): node for node in observed['children']}
        for node in proof['old_tree']['children']:
            actual = by_id.get(guid(node['row']['id']))
            check('Transition append preserves every existing rule', actual == node, {'expected': node, 'actual': actual})
        returned = result.get('children')
        if not isinstance(returned, list) or len(returned) != len(proof['native_tree']['children']):
            fail('INVALID_TRANSITION_RESULT', 'Append result must report every new rule identity')
        returned_ids = [guid(node.get('id')) for node in returned if isinstance(node, Mapping)]
        if (len(returned_ids) != len(returned) or len(set(returned_ids)) != len(returned)
                or set(returned_ids) & set(old_ids) or set(by_id) != set(old_ids[1:]) | set(returned_ids)):
            fail('INVALID_TRANSITION_RESULT', 'Append must create fresh rules and exact old plus new membership')
        bind_children(proof['native_tree']['children'], returned,
            [by_id[identity] for identity in returned_ids], '$.music_transitions')
    else:
        walk(proof['native_tree'], result, observed, '$.music_transitions')
        missing = [row for old_id in old_ids for row in rows(read, [old_id], ['id'])]
        check('Transition replaced root and complete old rule GUIDs absent', missing == [], {'old_ids': old_ids, 'actual': missing})
    check('Transition new root and rule GUIDs fresh', not set(old_ids) & new_ids, {'old_ids': old_ids, 'new_ids': sorted(new_ids)})
    return checks, identities


def without_result_tree(payload, proof):
    # Consume only the owned association; malformed or extra rows remain for
    # generic result validation, including after an owned-verifier failure.
    objects = payload.get('objects', [])
    if not isinstance(objects, list):
        return payload
    if proof['mode'] == 'append-rules':
        root_id = guid(proof['old_tree']['row']['id'])
        return {**payload, 'objects': [row for row in objects if not (isinstance(row, Mapping)
            and isinstance(row.get('id'), str) and row['id'].upper() == root_id)]}
    return {**payload, 'objects': [{k: v for k, v in row.items() if k != '@TransitionRoot'}
        if isinstance(row, Mapping) else row for row in objects]}

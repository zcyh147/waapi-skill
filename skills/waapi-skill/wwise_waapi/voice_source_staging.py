"""Closed two-Preview completion of one new Voice and localized Source.

Records live inside existing Drafts/immutable transactions. They are generated
from Business Declarations; no public command accepts a serialized record.
"""
from copy import deepcopy
from dataclasses import replace
from typing import Mapping
import re

from .canonical import canonical_sha256, canonical_json_bytes
from .business_declaration_state import BusinessDeclarationSession

KEY = 'voice_source_staging'
CONTRACT = 'waapi-skill.voice-source-stages/v1'


def fail(message):
    from .operation_registry import OperationContractError
    raise OperationContractError('VOICE_SOURCE_STAGE_INVALID', message)


def parts(raw):
    """Recognize the entire request; never lower a matching subset."""
    def localized(node):
        return (isinstance(node, dict) and
            (node.get('plugin', {}).get('kind') == 'source' and node['plugin'].get('language') is not None
             or any(localized(child) for child in node.get('children', []))))
    args = raw['arguments']
    rows = args.get('objects', [])
    if not any(localized(node) for row in rows for node in row.get('children', [])):
        return None
    if (len(rows) != 1 or set(args) - {'objects', 'on_name_conflict', 'list_mode', 'auto_add_to_source_control', 'platform'}
            or args.get('on_name_conflict', 'fail') != 'fail' or args.get('list_mode', 'append') != 'append'
            or set(rows[0]) - {'object', 'children', 'platform'} or len(rows[0].get('children', [])) != 1):
        fail('Localized planned Source completion requires a separately implemented stage mapping for this complete graph; no declarations were dropped.')
    voice = rows[0]['children'][0]
    children = voice.get('children', [])
    if (voice.get('type') != 'Sound' or len(children) != 1
            or not any(p['name'].casefold() == 'isvoice' and p['value'] is True for p in voice.get('properties', []))
            or set(voice) - {'type', 'name', 'notes', 'platform', 'language', 'properties', 'references', 'children'}):
        fail('The complete graph needs a new single Voice root and one localized Source; wider graph staging remains unfinished.')
    source = children[0]
    if (source.get('plugin', {}).get('kind') != 'source' or not source['plugin'].get('language')
            or set(source) - {'type', 'name', 'notes', 'platform', 'properties', 'references', 'plugin'}):
        fail('The entire Source declaration must have a closed staged mapping.')
    owner = {key: deepcopy(value) for key, value in voice.items() if key not in {'children', 'language'}}
    owner['parent'] = rows[0]['object']
    owner['on_name_conflict'] = 'fail'
    if 'platform' not in owner and 'platform' in rows[0]:
        owner['platform'] = rows[0]['platform']
    for key in ('platform', 'auto_add_to_source_control'):
        if key not in owner and key in args:
            owner[key] = args[key]
    return owner, source, voice.get('language')


def lower(raw, session):
    if session.settings.get('voice_source_completion') != 'separate-previews':
        return raw
    recognized = parts(raw)
    if recognized is None:
        return raw
    if len(session.declarations) != 2:
        fail('Every declaration must belong to the single Voice/Source stage mapping.')
    facts = replace(session, active_preview=None, preview_audit=()).as_dict()
    original_digest = canonical_sha256(facts)
    # Discovery can bind many candidates. Only handles actually used by the
    # complete declarations are continuation inputs; retain the full source
    # session seal separately, and never prune a declaration or its values.
    used = set()
    def referenced(value):
        if isinstance(value, str):
            used.add(value)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                referenced(key); referenced(item)
        elif isinstance(value, list):
            for item in value:
                referenced(item)
    referenced(facts['declarations'])
    referenced(facts['settings'])
    changed = True
    while changed:
        before = len(used)
        for collection in ('objects', 'fields', 'types'):
            for row in facts['handles'][collection]:
                if row['handle'] in used:
                    referenced(row)
        changed = len(used) != before
    for collection in ('objects', 'fields', 'types'):
        facts['handles'][collection] = [row for row in facts['handles'][collection] if row['handle'] in used]
    record = {'contract': CONTRACT, 'stage': 'voice', 'original_operation': 'object.set',
        'declarations': facts, 'declarations_sha256': canonical_sha256(facts),
        'original_declarations_sha256': original_digest,
        'source_request_sha256': canonical_sha256(raw),
        'reason': 'localized_Source_requires_independently_verified_existing_Voice'}
    return {**raw, 'arguments': {**voice_arguments(raw), KEY: record}}


def voice_arguments(raw):
    args = deepcopy(raw['arguments'])
    voice = args['objects'][0]['children'][0]
    del voice['children']
    voice.pop('language', None)
    return args


def validate_record(record, version):
    base = {'contract', 'stage', 'original_operation', 'declarations', 'declarations_sha256', 'original_declarations_sha256', 'source_request_sha256', 'reason'}
    if not isinstance(record, Mapping) or set(record) not in (base, base | {'origin'}):
        fail('Staged completion record fields changed.')
    if (record['contract'] != CONTRACT or record['original_operation'] != 'object.set'
            or record['reason'] != 'localized_Source_requires_independently_verified_existing_Voice'
            or record['stage'] not in {'voice', 'source'} or ('origin' in record) != (record['stage'] == 'source')
            or len(canonical_json_bytes(record)) > 64 * 1024
            or canonical_sha256(record['declarations']) != record['declarations_sha256']
            or not isinstance(record['original_declarations_sha256'], str)
            or re.fullmatch(r'[a-f0-9]{64}', record['original_declarations_sha256']) is None):
        fail('Staged completion provenance changed or exceeds its bound.')
    session = BusinessDeclarationSession.from_dict(record['declarations'])
    if (session.as_dict() != record['declarations']
            or session.context.wwise_version != version or session.active_preview is not None or session.preview_audit
            or session.settings.get('voice_source_completion') != 'separate-previews'):
        fail('Staged declaration context or facts changed.')
    from .object_graph_business import _materialize_set
    raw = _materialize_set(session)
    recognized = parts(raw)
    if recognized is None or len(session.declarations) != 2 or canonical_sha256(raw) != record['source_request_sha256']:
        fail('Staged record does not represent the complete original graph.')
    if record['stage'] == 'source':
        origin = record['origin']
        if (not isinstance(origin, Mapping) or set(origin) != {'transaction_id', 'artifact_hash', 'identity', 'languages'}
                or not isinstance(origin['transaction_id'], str) or not origin['transaction_id'].startswith('tx1-')
                or not isinstance(origin['artifact_hash'], str) or re.fullmatch(r'[a-f0-9]{64}', origin['artifact_hash']) is None
                or not isinstance(origin['languages'], list)):
            fail('Source stage origin is malformed.')
        from .transactions import validate_transaction_id
        validate_transaction_id(origin['transaction_id'])
        if not isinstance(origin['identity'], Mapping) or set(origin['identity']) != {'id', 'name', 'type', 'path'}:
            fail('Source origin requires the exact verified root identity.')
        from .business_declarations import normalize_live_object_identity
        identity = normalize_live_object_identity(origin['identity'])
        parent = session.handles.resolve_object(next(row.target.parent_handle for row in session.declarations
            if row.target.parent_handle in {entry['handle'] for entry in session.handles.as_dict()['objects']}))
        if identity.name != recognized[0]['name'] or identity.object_type != 'Sound' or identity.path != parent.path.rstrip('\\') + '\\' + identity.name:
            fail('Source continuation retargets the declared Voice.')
    return session, recognized


def validate_parent_transaction(record, state_dir):
    """Authenticate deferred facts against the existing immutable parent proof."""
    if state_dir is None or record['stage'] != 'source':
        fail('Source completion requires its owned parent transaction store.')
    from .transactions import TransactionStore, TransactionState
    from .creation_observations import verified_created_root_identity
    origin = record['origin']
    snapshot = TransactionStore(state_dir).load_snapshot(origin['transaction_id'])
    artifact = snapshot.preview.artifact
    expected = {key: deepcopy(value) for key, value in record.items() if key != 'origin'}
    expected['stage'] = 'voice'
    verifications = [event.get('details', {}).get('verification', {}) for event in snapshot.events
        if event.get('event_type') == 'verification_recorded']
    if (snapshot.record.state is not TransactionState.VERIFIED
            or snapshot.preview.artifact_hash != origin['artifact_hash']
            or artifact.get('request', {}).get('operation') != 'object.set'
            or artifact.get('request', {}).get('arguments', {}).get(KEY) != expected
            or len(verifications) != 1 or verifications[0].get('business_state_verified') is not True
            or verified_created_root_identity(verifications[0]) != origin['identity']
            or artifact.get('prepared_operation', {}).get('pre_state', {}).get(KEY, {}).get('languages') != origin['languages']):
        fail('Source continuation provenance differs from its exact verified parent transaction.')


def source_arguments(record):
    session, (voice, source, _) = validate_record(record, record['declarations']['context']['wwise_version'])
    from .object_graph_business import _materialize_set
    args = deepcopy(_materialize_set(session)['arguments'])
    child = deepcopy(source)
    selector = child['plugin']['language']
    choices = [row['selected'] for row in record['origin']['languages'] if row['requested'] == selector]
    if len(choices) != 1:
        fail('Source language lacks one sealed Project selection.')
    child['plugin']['language'] = choices[0]['name']
    args['objects'] = [{'object': {'kind': 'id', 'value': record['origin']['identity']['id']}, 'children': [child]}]
    if 'platform' in voice:
        args['platform'] = voice['platform']
    return args


def validate_request(operation, version, args):
    record = args.get(KEY)
    if record is None:
        return
    _, recognized = validate_record(record, version)
    if record['stage'] == 'voice':
        from .object_graph_business import _materialize_set
        expected = voice_arguments(_materialize_set(BusinessDeclarationSession.from_dict(record['declarations'])))
    else:
        expected = source_arguments(record)
    if operation != 'object.set' or {k: v for k, v in args.items() if k != KEY} != expected:
        fail('Canonical stage operation or fields differ from the sealed complete declaration.')


def revalidate(record, read, *, languages=None, owner=False, before_source=False, references=None, observed_references=None):
    session, (voice, source, voice_language) = validate_record(record, record['declarations']['context']['wwise_version'])
    from .business_declarations import revalidate_live_objects, revalidate_live_field, revalidate_live_types
    registry = session.handles
    revalidate_live_objects(registry, tuple(registry.resolve_object(row['handle']) for row in registry.as_dict()['objects']), read_call=read)
    revalidate_live_types(registry, tuple(registry.resolve_type(row['handle']) for row in registry.as_dict()['types']), read_call=read)
    for row in registry.as_dict()['fields']:
        revalidate_live_field(registry, registry.bound_field(row['handle']), read_call=read)
    from .operation_registry import _read_import_language_inventory, _select_construction_language
    inventory = _read_import_language_inventory(session.context.wwise_version, read=read)
    selected = [{'requested': value, 'selected': _select_construction_language(inventory, value), 'project': inventory['project']}
        for value in dict.fromkeys(value for value in (voice_language, source['plugin']['language']) if value is not None)]
    if languages is not None and selected != languages:
        fail('Selected Project language identity or project changed between stages.')
    if owner:
        identity = record['origin']['identity']
        properties = {row['name']: row['value'] for row in voice.get('properties', [])}
        refs = {row['name']: row['target'] for row in voice.get('references', [])}
        fields = ['id', 'name', 'type', 'path', 'parent', 'notes', *('@' + key for key in {**properties, **refs})]
        result = read('ak.wwise.core.object.get', {'from': {'id': [identity['id']]}},
            {'return': fields, **({'platform': voice['platform']} if 'platform' in voice else {})})
        rows = result.get('return')
        if not isinstance(rows, list) or len(rows) != 1:
            fail('Created Voice identity is missing or ambiguous.')
        row = rows[0]
        if (any(row.get(k) != v for k, v in identity.items()) or row.get('parent', {}).get('id') != voice['parent']['value']
                or 'notes' in voice and row.get('notes') != voice['notes']
                or any(type(row.get('@' + k)) is not bool if isinstance(v, bool) else False for k, v in properties.items())
                or any(row.get('@' + k) != v for k, v in properties.items())):
            fail('Verified Voice identity or declared fields changed before Source completion.')
        from .operation_registry import _reference_requirement_matches, _native_snapshot_equal, _PLUGIN_GUID
        actual_refs = {}
        for name, expected in refs.items():
            actual = row.get('@' + name)
            if isinstance(expected, Mapping) and 'curve_points' in expected:
                curve_id = actual.get('id') if isinstance(actual, Mapping) else None
                if not isinstance(curve_id, str) or _PLUGIN_GUID.fullmatch(curve_id) is None:
                    fail('Verified Voice inline Curve identity is unavailable.')
                curves = read('ak.wwise.core.object.get', {'from': {'id': [curve_id]}},
                    {'return': ['id', 'type', 'owner']}).get('return')
                if (not isinstance(curves, list) or len(curves) != 1 or curves[0].get('id') != curve_id
                        or curves[0].get('type') != 'Curve' or curves[0].get('owner', {}).get('id') != identity['id']
                        or not _native_snapshot_equal(actual.get('points'), expected['curve_points'])):
                    fail('Verified Voice inline Curve class, ownership or points changed.')
                actual_refs[name] = {'id': curve_id, 'points': deepcopy(actual['points'])}
            else:
                value = ([target['value'] for target in expected] if isinstance(expected, list)
                         else expected['value'] if expected is not None else None)
                if not _reference_requirement_matches(row, name, value):
                    fail('Verified Voice reference changed before Source completion.')
                actual_refs[name] = deepcopy(actual)
        if references is not None and not _native_snapshot_equal(actual_refs, references):
            fail('Prepared Voice reference identity changed before Source completion.')
        if observed_references is not None:
            observed_references.update(actual_refs)
        if before_source:
            children = read('ak.wwise.core.object.get', {'from': {'id': [identity['id']]}, 'transform': [{'select': ['children']}]}, {'return': ['id']})
            if children.get('return') != []:
                fail('Source stage requires the independently verified Voice still to be empty.')
    return selected


def prepare(record, read):
    references = {}
    languages = revalidate(record, read, languages=record.get('origin', {}).get('languages'),
        owner=record['stage'] == 'source', before_source=record['stage'] == 'source', observed_references=references)
    return {'record': deepcopy(record), 'languages': languages, 'references': references}


def assertions(state, read, *, after_write=False):
    guard = state.get(KEY)
    if guard is None:
        return []
    try:
        record = guard['record']
        revalidate(record, read, languages=guard['languages'], owner=record['stage'] == 'source',
            before_source=record['stage'] == 'source' and not after_write, references=guard['references'])
        return [{'name': 'staged Voice/Source intent and live bindings remain valid', 'passed': True}]
    except (ValueError, TypeError, KeyError) as exc:
        return [{'name': 'staged Voice/Source intent and live bindings remain valid', 'passed': False,
            'evidence': {'error_type': type(exc).__name__, 'message': str(exc)[:1024]}}]


def projection(record, *, verified=False):
    _, (_, source, _) = validate_record(record, record['declarations']['context']['wwise_version'])
    complete = record['stage'] == 'source' and verified
    fields = list(source.get('properties', []))
    fields.extend(row for row in source['plugin'].get('properties', []) if row not in fields)
    references = list(source.get('references', []))
    references.extend(row for row in source['plugin'].get('references', []) if row not in references)
    return {'contract': CONTRACT, 'complete': complete, 'atomic': False,
        'current_stage': 'complete' if complete else 'voice_created_source_pending' if verified else record['stage'],
        'separate_Preview_authorization_required': True,
        'remaining_work': [] if complete else [{'Source': source['name'], 'class_id': source['plugin']['class_id'],
            'language': source['plugin']['language'], 'fields': fields, 'references': references}],
        'partial_failure': 'retain_verified_Voice_and_report_Source_incomplete_never_repeat_creation'}


def child_capability(record):
    digest = canonical_sha256({'contract': CONTRACT, 'origin': record})
    return 'od1-' + digest[:32], 'da1-' + canonical_sha256({'authority': digest})[:40]


def child_session(record, context):
    """Reissue validated handles for the new task; retain every Source value."""
    from .business_declarations import BusinessHandleRegistry, NewDescendantTarget
    original, _ = validate_record(record, context.wwise_version)
    registry = BusinessHandleRegistry(context)
    old = original.handles
    remap = {}
    for entry in old.as_dict()['objects']:
        bound = old.resolve_object(entry['handle'])
        fresh = registry.bind_object(object_id=bound.object_id, name=bound.name, object_type=bound.object_type,
            path=bound.path, semantic_kind=bound.semantic_kind, role=bound.role)
        remap[bound.handle] = fresh.handle
    for entry in old.as_dict()['types']:
        bound = old.resolve_type(entry['handle'])
        fresh = registry.bind_type(class_id=bound.class_id, name=bound.name,
            type_category=bound.type_category, catalog_digest=bound.catalog_digest)
        remap[bound.handle] = fresh.handle
    for entry in old.as_dict()['fields']:
        bound = old.bound_field(entry['handle'])
        fresh = registry.bind_field(scope_kind=bound.scope_kind, scope_value=bound.scope_value, token=bound.token,
            field_kind=bound.field_kind, value_type=bound.value_type, platform=bound.platform,
            restrictions=bound.restrictions, metadata_digest=bound.metadata_digest, trusted_native_token=True)
        remap[bound.handle] = fresh.handle
    identity = record['origin']['identity']
    owner = registry.bind_object(object_id=identity['id'], name=identity['name'], object_type=identity['type'],
        path=identity['path'], semantic_kind='sound-voice')
    source, = [row for row in original.declarations if row.target.kind in remap and old.resolve_type(row.target.kind).type_category.casefold() == 'source']
    def mapped(value):
        if isinstance(value, str):
            return remap.get(value, value)
        if isinstance(value, dict):
            return {remap.get(key, key): mapped(item) for key, item in value.items()}
        if isinstance(value, list):
            return [mapped(item) for item in value]
        return value
    fields = mapped(dict(source.fields))
    fields['language'] = source_arguments(record)['objects'][0]['children'][0]['plugin']['language']
    settings = {key: value for key, value in original.settings.items() if key != 'voice_source_completion'}
    if 'platform' in source_arguments(record):
        settings['platform'] = source_arguments(record)['platform']
    child = BusinessDeclarationSession.create(context).with_handle_registry(registry)
    if settings:
        child = child.with_settings(settings)
    return child.with_new_declaration(declaration_id=source.declaration_id,
        target=NewDescendantTarget(parent_handle=owner.handle, name=source.target.name, kind=remap[source.target.kind]), fields=fields)

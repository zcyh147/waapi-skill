"""Operation-owned saved Source proof; never saves or accepts caller file paths."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid
import re

from .canonical import canonical_sha256
from .console_project_operations import _read_xml_artifact, _project_io_root_identity, MAX_PROJECT_FILE_BYTES
from .host_paths import localize_waapi_host_path
from .object_lifecycle_graph import GET, MAX_NODES, MAX_FIELDS, capture_lifecycle_fields, lifecycle_snapshot_equal
from .platform_paths import localize_live_wwise_project_path
from .operation_soundbank import FILE_PROOF_CONTRACT, _require_sealed
from .transaction_locality import is_loopback_waapi_host

KEY = 'source_copy_saved_proof'
ORIGIN = 'source_copy_save_origin'
RETURN = 'source_copy_parent_return'
DECISION = 'source_copy_proof_decision'
CONTRACT = 'waapi-skill.source-copy-saved-proof/v1'
CHILD_PREFIX = 'od1-f54c50'
SAVE = 'ak.wwise.core.project.save'
# Native host/build and Source class admission remain separate from graph shape.
SOURCE_CLASS = 9699330
# Native-proven declaration classes are independent of address/cardinality.
OWNED_CLASSES = {'RTPC': 1441808, 'ModulatorLfo': 4194320, 'Curve': 917520}
GRAPH_FORMAT = 'waapi-skill.source-copy-owned-declarations/v1'
MATCHING_BUILDS = {
    '2021.1': (2021, 1, 14, 8108),
    '2022.1': (2022, 1, 19, 8584),
    '2023.1': (2023, 1, 19, 8928),
    '2024.1': (2024, 1, 13, 9056),
    '2025.1': (2025, 1, 7, 9143),
}
# Concrete GUID-pointer encodings in the matching 2021 saved SampleProject.
# They are not declarations. Unknown encodings are never admitted by suffix.
SAVED_POINTER_TAGS = frozenset({
    'ObjectRef', 'ActiveSource', 'ArgumentRef', 'PathElementRef', 'AudioNodeRef',
    'AudioSourceRef', 'MidiSourceRef', 'SegmentRef', 'JumpToPlaylistItemRef',
    'StateGroupRef', 'StateRef', 'TransitionObjectRef', 'TriggerRef', 'ItemRef',
    'SwitchRef', 'BusRef', 'GameParameterRef', 'CurrentStateRef', 'CurrentSwitchRef',
})


class SavedCopyProofError(ValueError):
    error_code = 'SOURCE_COPY_SAVED_PROOF_INVALID'
    def as_dict(self):
        return {'error_code': self.error_code, 'message': str(self)}


class UnsupportedSavedShape(SavedCopyProofError):
    error_code = 'SOURCE_COPY_SAVED_SHAPE_UNFINISHED'


def require_graph_format(proof):
    require(isinstance(proof, dict) and proof.get('graph_format') == GRAPH_FORMAT,
        'Saved Source graph format is obsolete or unknown; start a new object.copy Draft for new work. '
        'Inspect any existing executed copy without retrying it.')


def require_shape(condition, message):
    if not condition: raise UnsupportedSavedShape(message)


def require(condition, message):
    if not condition: raise SavedCopyProofError(message)


def guid(value):
    if isinstance(value, dict): value = value.get('id')
    try:
        identity = uuid.UUID(value)
        require(bool(identity.int), 'Saved proof requires a nonzero GUID')
        return '{' + str(identity).upper() + '}'
    except (ValueError, TypeError, AttributeError) as exc:
        raise SavedCopyProofError('Saved proof requires an exact GUID') from exc


def exact(identity, fields, read):
    rows = read(GET, {'from': {'id': [identity]}}, {'return': ['id', *fields]}).get('return')
    require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
        and guid(rows[0].get('id')) == guid(identity), 'Saved proof identity is missing or ambiguous')
    return dict(rows[0])


def secure_path(raw, *, directory=False):
    from .operation_registry import _secure_import_filesystem_path
    path = Path(localize_waapi_host_path(raw))
    _secure_import_filesystem_path(path, field='live project model read', require_directory=directory)
    return path


def matching_runtime(context):
    if not isinstance(context, dict): return False
    guard = context.get('project_guard', {})
    info = guard.get('wwise', {})
    version = info.get('version', {})
    expected = MATCHING_BUILDS.get(guard.get('version'))
    return (expected is not None and info.get('isCommandLine') is True
        and tuple(version.get(k) for k in ('year', 'major', 'minor', 'build')) == expected
        and is_loopback_waapi_host(guard.get('endpoint', {}).get('host', ''))
        and isinstance(info.get('sessionId'), str) and bool(info['sessionId'])
        and type(info.get('processId')) is int and info['processId'] > 0
        and isinstance(info.get('processPath'), str) and bool(info['processPath']))


def supported(context):
    # Modern saved syntax and runtime origins are independently classified;
    # selected Source membership/field observations still gate their admission.
    return matching_runtime(context) and context['project_guard']['version'] == '2021.1'


def authority(context, source_id, destination_id, read):
    guard = context['project_guard']
    project = exact(guard['project']['id'], ['type', 'path', 'filePath', 'workunitIsDirty'], read)
    require(project.get('type') == 'Project' and project.get('path') == '\\', 'Saved proof requires the current Project root')
    require(type(project.get('workunitIsDirty')) is bool, 'Project clean state is unavailable')
    localized = localize_live_wwise_project_path(project['filePath'], endpoint=guard['endpoint'], wwise=guard['wwise'])
    project_path = secure_path(localized)
    require(project_path.suffix.casefold() == '.wproj', 'Current Project file is not a WPROJ')
    root = secure_path(str(project_path.parent), directory=True)
    units, objects = {}, {}
    for identity in dict.fromkeys((source_id, destination_id)):
        row = exact(identity, ['type', 'filePath', 'workunit'], read)
        unit_id = guid(row.get('workunit'))
        unit = units.get(unit_id)
        if unit is None:
            unit = exact(unit_id, ['name', 'type', 'filePath', 'workunitType', 'workunitIsDirty'], read)
            require(unit.get('type') == 'WorkUnit' and unit.get('workunitType') in {'rootFile', 'nestedFile'}, 'Saved proof requires a file-backed Work Unit')
            require(type(unit.get('workunitIsDirty')) is bool, 'Work Unit clean state is unavailable')
            unit_path = secure_path(unit['filePath'])
            require(unit_path.suffix.casefold() == '.wwu' and unit_path.is_relative_to(root), 'Selected Work Unit is outside the current Project read root')
            unit['local_path'] = str(unit_path)
            units[unit_id] = unit
        require(secure_path(row['filePath']) == Path(unit['local_path']), 'Object filePath does not match its independently bound Work Unit')
        objects[guid(identity)] = row
    return {'project': project, 'project_path': str(project_path), 'root': str(root),
        'root_identity': _project_io_root_identity(str(root)), 'units': units, 'objects': objects}


def read_documents(binding):
    paths = [binding['project_path'], *(row['local_path'] for row in binding['units'].values())]
    documents, proofs = {}, {}
    for path in dict.fromkeys(paths):
        document, proof = _read_xml_artifact(path, binding['root'])
        documents[path], proofs[path] = document, proof
    project = documents[binding['project_path']]
    matches = [node for node in project.iter('Project') if guid(node.get('ID')) == guid(binding['project']['id'])]
    require(len(matches) == 1, 'WPROJ declaration does not bind the live Project GUID')
    for identity, row in binding['units'].items():
        matches = [node for node in documents[row['local_path']].iter('WorkUnit') if guid(node.get('ID')) == identity]
        require(len(matches) == 1, 'WWU declaration does not bind its live Work Unit GUID')
    return documents, proofs


def source_nodes(documents, identity, owner_id, *, version='2021.1'):
    found = []
    for document in documents.values():
        parents = {child: node for node in document.iter() for child in node}
        for node in document.iter():
            if node.tag != 'SourcePlugin' or guid(node.get('ID')) != guid(identity): continue
            children = parents.get(node); owner = parents.get(children)
            require(children is not None and children.tag == 'ChildrenList' and owner is not None
                and owner.tag == 'Sound' and guid(owner.get('ID')) == guid(owner_id), 'Saved Source owner differs from live owner')
            found.append(node)
    require(len(found) == 1, 'Saved Source is missing or duplicated')
    source = found[0]
    require_shape(source.get('PluginName') == 'Wwise Synth One' and source.get('PluginID') == '148'
        and source.get('CompanyID') == '0' and not list(source.iter('ObjectRef')), 'Serialized plugin/reference shape is not certified')
    # Ordered XML addresses distinguish repeated declarations without relying on
    # property names, GUIDs, plugin class tuples, or a fixed role cardinality.
    nodes = {}
    def collect(node, address):
        if 'ID' in node.attrib:
            nodes[address] = node
            require_shape(len(nodes) <= MAX_NODES, 'Saved owned graph exceeds the complete object bound')
        for index, child in enumerate(node):
            collect(child, address + '/' + str(index))
    collect(source, 'source')
    # Saved selections/references can repeat a declaration GUID elsewhere in
    # the selected WWU. Unknown GUID-bearing encodings remain conservatively
    # counted so real declarations cannot hide aliases under another tag.
    all_ids = [guid(node.get('ID')) for document in documents.values() for node in document.iter()
        if node.tag not in SAVED_POINTER_TAGS
        and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', node.get('ID', ''))]
    ids = [guid(node.get('ID')) for node in nodes.values()]
    require(len(set(ids)) == len(ids) and all(all_ids.count(x) == 1 for x in ids),
        'Saved owned GUIDs alias another declaration')
    # Saved wrapper grammar is versioned independently of live selector
    # applicability. Parsing a matching original never establishes that proof.
    require_shape(version in {'2021.1', '2022.1', '2023.1', '2024.1', '2025.1'},
        'Saved Source version grammar is unfinished')
    parents = {child: node for node in source.iter() for child in node}
    for node in nodes.values():
        if node.tag != 'RTPC': continue
        container = parents.get(node)
        if version == '2021.1':
            require_shape(container is not None and container.tag == 'RTPCList'
                and parents.get(container) is not None and parents[container].tag == 'Property',
                'Saved RTPC membership wrapper differs from its version')
        else:
            if version != '2025.1':
                require_shape(container is not None and container.tag == 'Local'
                    and len(container) == 1 and parents.get(container) is not None
                    and parents[container].tag == 'Reference',
                    'Saved RTPC membership wrapper differs from its version')
                container = parents.get(parents[container])
            require_shape(container is not None and container.tag == 'ObjectList'
                and container.attrib == {'Name': 'RTPC'} and parents.get(container) is not None
                and parents[container].tag == 'ObjectLists',
                'Saved RTPC membership wrapper differs from its version')
    for reference in source.iter('Reference'):
        custom = reference.find('Custom')
        local = reference.find('Local')
        owner_list = parents.get(reference)
        local_member = (version in {'2022.1', '2023.1', '2024.1'} and not reference.attrib
            and owner_list is not None and owner_list.tag == 'ObjectList'
            and owner_list.attrib == {'Name': 'RTPC'} and len(reference) == 1
            and local is not None and not local.attrib and len(local) == 1
            and local[0].tag == 'RTPC' and local[0] in nodes.values())
        allowed = {'ControlInput'} if version == '2021.1' else {'ControlInput', 'Curve'}
        custom_member = (reference.get('Name') in allowed
            and set(reference.attrib) == {'Name'} and len(reference) == 1
            and custom is not None and not custom.attrib and len(custom) == 1
            and custom[0] in nodes.values()
            and custom[0].tag == ('ModulatorLfo' if reference.get('Name') == 'ControlInput' else 'Curve'))
        require_shape(local_member or custom_member, 'Saved owned reference semantics are unfinished')
    return nodes


def graph_edges(nodes):
    """Nearest serialized declaration owner, independent of wrapper layout."""
    addresses = {node: role for role, node in nodes.items()}
    owners, controls = {}, {}
    def visit(node, owner):
        role = addresses.get(node)
        if role is not None:
            if owner is not None: owners[role] = owner
            owner = role
        if node.tag == 'Reference' and node.get('Name') == 'ControlInput':
            control = node.find('Custom')[0]
            require_shape(owner not in controls, 'Owned ControlInput is ambiguous')
            controls[owner] = addresses[control]
        for child in node: visit(child, owner)
    visit(nodes['source'], None)
    return owners, controls


def serialized(node, nodes=None, *, rename_root=None):
    attrs = dict(node.attrib)
    if nodes and node in nodes.values():
        role = next(role for role, item in nodes.items() if item is node)
        attrs['ID'] = 'owned:' + role
        if 'ShortID' in attrs: attrs['ShortID'] = 'live-bound:' + role
        if role == 'source' and rename_root is not None: attrs['Name'] = rename_root
    text, tail = node.text, node.tail
    if len(node) and text is not None and not text.strip() and '\n' in text: text = None
    if tail is not None and not tail.strip() and '\n' in tail: tail = None
    return [node.tag, [[key, value] for key, value in sorted(attrs.items())], text, tail, [serialized(child, nodes) for child in node]]


def live_roles(nodes, owner, read):
    rows = {}
    owners, controls = graph_edges(nodes)
    field_count = 0
    for role, node in nodes.items():
        expected_class = SOURCE_CLASS if role == 'source' else OWNED_CLASSES.get(node.tag)
        require_shape(expected_class is not None, 'Saved owned declaration class has no reviewed native authority')
        row = exact(guid(node.get('ID')), ['name', 'type', 'classId', 'parent', 'owner', 'notes', 'shortId'], read)
        require(type(row.get('classId')) is int and row['classId'] == expected_class
            and row.get('type') in ({'Source', 'SourcePlugin'} if role == 'source' else {node.tag}),
            'Saved/live role class or type differs')
        expected_owner = owner if role == 'source' else nodes[owners[role]].get('ID')
        require(guid(row.get('parent' if role == 'source' else 'owner')) == guid(expected_owner), 'Saved/live owned role edge differs')
        require(row.get('name') == node.get('Name') and row.get('notes', '') == node.findtext('Comment', ''), 'Saved/live role name or notes differs')
        if 'ShortID' in node.attrib:
            require(type(row.get('shortId')) is int and str(row['shortId']) == node.get('ShortID'), 'Saved ShortID is not independently live-bound')
        else:
            require_shape(node.tag == 'Curve', 'Unclassified missing serialized ShortID')
        if role != 'source':
            fields = capture_lifecycle_fields(row['id'], read=read, strict=False)
            field_count += fields['field_inventory']['count']
            require_shape(field_count <= MAX_FIELDS, 'Saved owned graph exceeds the complete field bound')
            for metadata in fields['field_metadata'].values():
                metadata.pop('scope', None)
                metadata.pop('available_names', None)
            allowed = {'ControlInput'} if role in controls else set()
            require_shape(set(fields['unreadable_fields']) <= allowed
                and set(fields['reference_fields']) <= allowed,
                'Owned live field/reference scope is not certified by this serialized shape')
            row['default_fields'] = fields
        rows[role] = row
    for role, target in controls.items():
        identity = rows[role]['id']
        hop = read(GET, {'waql': f'from object "{identity}" select @ControlInput take 2'}, {'return': ['id']}).get('return')
        require(isinstance(hop, list) and len(hop) == 1 and guid(hop[0].get('id')) == guid(rows[target]['id']),
            'Documented ControlInput does not bind the saved owned declaration')
    return rows


def compare_owned_fields(original_live, copied_live, original_ids, new_ids):
    require(set(original_live) == set(copied_live), 'Copied owned declaration graph differs')
    for role in original_live:
        require(original_live[role]['classId'] == copied_live[role]['classId']
            and original_live[role]['type'] == copied_live[role]['type'], 'Copied live owned class or type differs')
        if role == 'source': continue  # Shared Source observer already compares all observed Source scalars.
        def mapped_fields(fields, role_ids):
            fields = deepcopy(fields)
            aliases = {identity: 'owned:' + name for name, identity in role_ids.items()}
            def mapped(value):
                if isinstance(value, dict): return {key: mapped(item) for key, item in value.items()}
                if isinstance(value, list): return [mapped(item) for item in value]
                return aliases.get(value.upper(), value) if isinstance(value, str) else value
            for name in fields['reference_fields']:
                if name in fields['field_values']:
                    fields['field_values'][name] = mapped(fields['field_values'][name])
            return fields
        require(lifecycle_snapshot_equal(mapped_fields(original_live[role]['default_fields'], original_ids),
            mapped_fields(copied_live[role]['default_fields'], new_ids)), 'Copied live owned default fields differ')


def capture_baseline(context, snapshot, read):
    if not supported(context): return {'status': 'unavailable', 'reason': 'version_host_or_local_runtime_authority_unavailable'}
    source = snapshot['source']['frame']; destination = snapshot['destination']
    if source.get('classId') != SOURCE_CLASS: return {'status': 'unavailable', 'reason': 'serialized_source_shape_not_certified'}
    if snapshot['source']['unreadable_fields'] or snapshot['source']['reference_fields']:
        return {'status': 'unavailable', 'reason': 'source_live_field_scope_unfinished'}
    if not all(owner['children_complete'] for owner in snapshot['owners'].values()):
        return {'status': 'unavailable', 'reason': 'owner_childset_scope_unfinished'}
    if not all(type(owner['frame'].get('@IsVoice')) is bool for owner in snapshot['owners'].values()):
        return {'status': 'unavailable', 'reason': 'owner_is_voice_scope_unfinished'}
    try:
        binding = authority(context, source['id'], destination, read)
        dirty = binding['project']['workunitIsDirty'] or any(row['workunitIsDirty'] for row in binding['units'].values())
        decision = context.get('proof_decision')
        if decision and decision.get('request_digest') == context.get('request_digest'):
            require(decision['origin']['context'] == context['binding'], 'Baseline decision context changed')
            if decision['status'] == 'declined':
                return {'status': 'unavailable', 'reason': 'baseline_Save_declined'}
            require(resolve_save_receipt(decision['origin'], context) == decision['receipt'], 'Baseline Save receipt changed')
            require(not dirty, 'Authorized baseline Save did not establish clean selected documents')
            require(lifecycle_snapshot_equal(without_dirty(binding), without_dirty(decision['origin']['file_binding']['authority'])),
                'Baseline Save file membership changed before copy Preview')
        else:
            decision = None
        # Dirty live nodes need not exist on disk yet. The existing Project and
        # selected Work Units must still be valid, independently bound documents;
        # Save is not permission to repair or overwrite unexpected disk state.
        documents, proofs = read_documents(binding)
        if dirty:
            return {'status': 'baseline_save_pending', 'graph_format': GRAPH_FORMAT, 'authority': binding, 'context': context['binding'],
                'source_id': guid(source['id']), 'destination_id': guid(destination), 'files': proofs}
        nodes = source_nodes(documents, source['id'], guid(source['parent']))
        live = live_roles(nodes, guid(source['parent']), read)
        after = authority(context, source['id'], destination, read)
        require(lifecycle_snapshot_equal(binding, after), 'Model authority changed during baseline observation')
        _, proof_after = read_documents(after)
        require(proofs == proof_after, 'Model files changed during baseline observation')
        body = {'contract': CONTRACT, 'graph_format': GRAPH_FORMAT, 'status': 'ready', 'origin': 'authorized_baseline_Save' if decision else 'already_clean',
            **({'baseline_save_receipt': decision['receipt']} if decision else {}),
            'authority': binding, 'context': context['binding'], 'files': proofs,
            'source_id': guid(source['id']), 'source_owner': guid(source['parent']), 'destination_id': destination,
            'source_exact_digest': canonical_sha256(serialized(nodes['source'])),
            'source_normalized_digest': canonical_sha256(serialized(nodes['source'], nodes)),
            'roles': live, 'role_ids': {key: guid(node.get('ID')) for key, node in nodes.items()}}
        return {**body, 'digest': canonical_sha256(body)}
    except UnsupportedSavedShape as exc:
        return {'status': 'unavailable', 'reason': exc.error_code, 'message': str(exc)}
    except Exception as exc:
        if context.get('proof_decision') and context['proof_decision'].get('request_digest') == context.get('request_digest'):
            raise SavedCopyProofError('Persisted baseline decision could not be revalidated: ' + str(exc)) from exc
        # This optional observer has not established authority. No Save is
        # offered to repair malformed/inaccessible/unsupported file semantics.
        return {'status': 'unavailable', 'reason': getattr(exc, 'error_code', type(exc).__name__), 'message': str(exc)[:512]}


def validate_baseline(baseline, context, read):
    require_graph_format(baseline)
    require(supported(context) and baseline['context'] == context['binding'], 'Saved-copy context drifted')
    observed = authority(context, baseline['source_id'], baseline['destination_id'], read)
    require(lifecycle_snapshot_equal(observed, baseline['authority']), 'Saved-copy clean file authority drifted before dispatch')
    documents, proofs = read_documents(observed)
    require(proofs == baseline['files'], 'Saved-copy baseline files changed before dispatch')
    nodes = source_nodes(documents, baseline['source_id'], baseline['source_owner'])
    require(lifecycle_snapshot_equal(live_roles(nodes, baseline['source_owner'], read), baseline['roles']),
        'Original owned live state drifted before copy dispatch')


def baseline_summary(baseline):
    return {'status': baseline['status'], 'complete_copy_preservation': False,
        **({'baseline_origin': baseline['origin'], 'baseline_digest': baseline['digest'],
            'read_only_paths': list(baseline['files'])} if baseline['status'] == 'ready' else {'reason': baseline.get('reason', 'selected_documents_dirty')})}


def validate_origin(origin, version):
    require(isinstance(origin, dict) and origin.get('contract') == CONTRACT
        and origin.get('version') == version and version in MATCHING_BUILDS, 'Save child origin/version is invalid')
    expected = {'contract', 'version', 'stage', 'parent', 'context', 'baseline_digest'}
    if origin.get('stage') == 'baseline': expected.add('file_binding')
    require(set(origin) == expected, 'Save child origin fields are invalid')
    require(origin['stage'] in {'baseline', 'final'} and isinstance(origin['parent'], dict)
        and isinstance(origin['context'], dict), 'Save child stage/parent is invalid')
    parent = origin['parent']
    if origin['stage'] == 'final':
        require(set(parent) == {'transaction_id', 'artifact_hash', 'execution_event_hash', 'copied_id'}, 'Final Save parent fields are invalid')
        guid(parent['copied_id'])
        from .transactions import validate_transaction_id
        validate_transaction_id(parent['transaction_id'])
    else:
        require(set(parent) == {'draft_id', 'authority_digest', 'source_revision', 'request_digest', 'audit_event_hash'}, 'Baseline Save parent fields are invalid')
        require(type(parent['source_revision']) is int and parent['source_revision'] > 0, 'Baseline Save revision is invalid')
        validate_file_binding(origin['file_binding'], version)
    hashes = [origin['baseline_digest']]
    if origin['stage'] == 'final':
        hashes.extend(parent[key] for key in ('artifact_hash', 'execution_event_hash'))
    else:
        require(isinstance(parent['draft_id'], str) and re.fullmatch(r'od1-[0-9a-f]{32}', parent['draft_id']), 'Baseline parent ID is invalid')
        hashes.extend(parent[key] for key in ('authority_digest', 'request_digest', 'audit_event_hash'))
    require(all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes), 'Save origin hash binding is invalid')
    require(set(origin['context']) == {'project_guard', 'connection_configuration'}
        and origin['context']['project_guard'].get('version') == version
        and matching_runtime({'project_guard': origin['context']['project_guard']}), 'Save origin requires its exact supported runtime context')


def child_capability(origin):
    digest = canonical_sha256({'contract': CONTRACT, 'origin': origin})
    return CHILD_PREFIX + digest[:26], 'da1-' + canonical_sha256({'authority': digest})[:40]


def execution(snapshot):
    events = [row for row in snapshot.events if row['event_type'] == 'execution_completed']
    require(len(events) == 1, 'Copy/Save requires exactly one durable execution completion')
    return events[0]


def copied_id(snapshot):
    result = execution(snapshot)['details']['dispatch_result']['result']
    return guid(result.get('id'))


def final_origin(snapshot):
    from .transactions import TransactionState
    require(snapshot.record.state is TransactionState.EXECUTED_UNVERIFIED, 'Final Save requires its still-unverified executed copy')
    baseline = snapshot.preview.artifact['prepared_operation']['pre_state'][KEY]
    require_graph_format(baseline)
    require(baseline['status'] == 'ready', 'Copy has no certified saved baseline')
    return {'contract': CONTRACT, 'version': snapshot.preview.artifact['request']['version'],
        'stage': 'final', 'baseline_digest': baseline['digest'],
        'context': baseline['context'], 'parent': {'transaction_id': snapshot.record.transaction_id,
            'artifact_hash': snapshot.preview.artifact_hash, 'execution_event_hash': execution(snapshot)['event_hash'],
            'copied_id': copied_id(snapshot)}}


def validate_pending_files(baseline, context, read):
    require_graph_format(baseline)
    require(supported(context) and context['binding'] == baseline['context'], 'Saved proof runtime/configuration changed')
    binding = authority(context, baseline['source_id'], baseline['destination_id'], read)
    def without_dirty(value):
        if isinstance(value, dict): return {k: without_dirty(v) for k, v in value.items() if k != 'workunitIsDirty'}
        return value
    require(lifecycle_snapshot_equal(without_dirty(binding), without_dirty(baseline['authority'])), 'Saved proof live file membership/root changed')
    _, proofs = read_documents(binding)
    require(proofs == baseline['files'], 'Unexpected baseline disk changes block the optional Save')
    return binding


def revalidate_origin(origin, context, *, read=None, before_write=True):
    from .transactions import TransactionStore, TransactionState
    validate_origin(origin, context['project_guard']['version'])
    if origin['stage'] == 'baseline': require_graph_format(origin['file_binding'])
    require(context['binding'] == origin['context'], 'Generated Save context changed')
    if origin['stage'] == 'final':
        snapshot = TransactionStore(context['state_dir']).load_snapshot(origin['parent']['transaction_id'])
        require(final_origin(snapshot) == origin, 'Generated final Save differs from its executed parent')
        if read is not None and before_write:
            baseline = snapshot.preview.artifact['prepared_operation']['pre_state'][KEY]
            binding = validate_pending_files(baseline, context, read)
            documents, _ = read_documents(binding)
            nodes = source_nodes(documents, baseline['source_id'], baseline['source_owner'])
            require(lifecycle_snapshot_equal(live_roles(nodes, baseline['source_owner'], read), baseline['roles']), 'Original owned live state changed before optional Save')
            from .operation_registry import verify_prepared_operation
            require(verify_prepared_operation(snapshot.preview.artifact['prepared_operation'],
                execution_result=execution(snapshot)['details']['dispatch_result'], read_call=read).status == 'verified',
                'Source/owner preservation changed before optional Save')
    else:
        from .operation_drafts import OperationDraftStore
        OperationDraftStore(context['state_dir']).inspect_source_copy_parent(origin)
        if read is not None and before_write:
            file_binding = origin['file_binding']
            require_graph_format(file_binding)
            observed = authority(context, file_binding['source_id'], file_binding['destination_id'], read)
            require(lifecycle_snapshot_equal(without_dirty(observed), without_dirty(file_binding['authority'])),
                'Baseline Save selected file authority changed')
            _, proofs = read_documents(observed)
            require(proofs == file_binding['files'], 'Unexpected baseline disk changes block the optional Save')
    return True


def resolve_save_receipt(origin, context, *, child=None):
    from .operation_drafts import OperationDraftStore, OperationDraftNotAvailable
    from .transactions import TransactionStore, TransactionState
    child_id, authority_token = child_capability(origin)
    if child is None:
        try:
            child = OperationDraftStore(context['state_dir']).inspect(child_id, task_authority=authority_token)
        except OperationDraftNotAvailable:
            return None
    require(child.composition.get(ORIGIN) == origin, 'Save child origin changed')
    if child.seal is None: return None
    saved = TransactionStore(context['state_dir']).load_snapshot(child.seal['transaction_id'])
    if saved.record.state not in {TransactionState.RESULT_SCHEMA_CHECKED, TransactionState.VERIFIED}: return None
    artifact = saved.preview.artifact
    require(artifact['prepared_operation']['pre_state'].get(ORIGIN) == origin, 'Save receipt is unrelated to this copy')
    require(artifact['request']['operation'] == 'waapi.call' and artifact['request']['arguments'] == {'api': SAVE, 'args': {}, 'options': {}}, 'Save receipt is not the fixed versioned closed request')
    require(artifact['connection_configuration'] == origin['context']['connection_configuration']
        and artifact['project_guard'] == origin['context']['project_guard'], 'Save receipt connection/runtime/project differs')
    execution_event = execution(saved)
    verifications = [x for x in saved.events if x['event_type'] == 'verification_recorded']
    require(len(verifications) == 1 and any(x['event_type'] in {'confirmed', 'policy_authorized'} for x in saved.events), 'Save receipt completion/authorization is incomplete')
    return {'transaction_id': saved.record.transaction_id, 'artifact_hash': saved.preview.artifact_hash,
        'execution_event_hash': execution_event['event_hash'], 'verification_event_hash': verifications[0]['event_hash']}


def verify_saved(baseline, context, snapshot, read):
    require_graph_format(baseline)
    origin = final_origin(snapshot)
    receipt = resolve_save_receipt(origin, context)
    if receipt is None: return None
    binding = authority(context, baseline['source_id'], baseline['destination_id'], read)
    require(binding['root_identity'] == baseline['authority']['root_identity'], 'Saved proof read-root identity changed')
    require(not binding['project']['workunitIsDirty'] and not any(x['workunitIsDirty'] for x in binding['units'].values()), 'Saved documents remain dirty')
    def membership(value):
        return {k: v for k, v in value.items() if k not in {'workunitIsDirty'}}
    require(membership(binding['project']) == membership(baseline['authority']['project'])
        and binding['objects'] == baseline['authority']['objects']
        and {k: membership(v) for k, v in binding['units'].items()} == {k: membership(v) for k, v in baseline['authority']['units'].items()}, 'Saved proof file/identity membership changed')
    documents, proofs = read_documents(binding)
    original = source_nodes(documents, baseline['source_id'], baseline['source_owner'])
    copied = source_nodes(documents, origin['parent']['copied_id'], baseline['destination_id'])
    require(canonical_sha256(serialized(original['source'])) == baseline['source_exact_digest'], 'Original saved Source/owned state changed')
    original_ids, new_ids = baseline['role_ids'], {k: guid(v.get('ID')) for k, v in copied.items()}
    require(set(original_ids.values()).isdisjoint(new_ids.values()) and len(set(new_ids.values())) == len(original_ids) and set(original_ids) == set(new_ids), 'Copied GUID mapping aliases original/owned identities')
    rename = snapshot.preview.artifact['prepared_operation']['verification_plan']['on_name_conflict'] == 'rename'
    expected_name = original['source'].get('Name') if rename else None
    require(canonical_sha256(serialized(copied['source'], copied, rename_root=expected_name)) == baseline['source_normalized_digest'], 'Copied serialized fields/attributes/text/order/points differ')
    original_live = live_roles(original, baseline['source_owner'], read)
    require(lifecycle_snapshot_equal(original_live, baseline['roles']), 'Original live owned identities or fields changed')
    copied_live = live_roles(copied, baseline['destination_id'], read)
    compare_owned_fields(original_live, copied_live, original_ids, new_ids)
    after = authority(context, baseline['source_id'], baseline['destination_id'], read)
    require(after == binding, 'Saved proof authority changed during final observation')
    _, after_proofs = read_documents(after)
    require(proofs == after_proofs, 'Saved model changed during final observation')
    return {'complete_copy_preservation': True, 'supported_shape': '2021.1.14.8108_Synth_owned_declaration_graph_zero_ObjectRefs',
        'baseline_digest': baseline['digest'], 'final_save_receipt': receipt, 'model_proofs_digest': canonical_sha256(proofs),
        'owned_guid_mapping': {original_ids[k]: new_ids[k] for k in original_ids}, 'owned_role_count': len(original_ids) - 1,
        'ordered_point_count': sum(len(node.findall('PointList/Point')) for node in copied.values() if node.tag == 'Curve'),
        'live_role_digest': canonical_sha256(copied_live)}


def unexecuted_child(origin, context):
    from .operation_drafts import OperationDraftStore, OperationDraftNotAvailable
    from .transactions import TransactionStore
    child_id, token = child_capability(origin)
    try:
        child = OperationDraftStore(context['state_dir']).inspect_source_copy_child(origin, include_expired=True)
    except OperationDraftNotAvailable:
        return {'draft_id': child_id, 'state': 'not_allocated_or_unavailable', 'save_prevention_claim': False}
    require(child.composition.get(ORIGIN) == origin, 'Save child refusal origin differs')
    if child.seal is None:
        return {'draft_id': child_id, 'state': child.state.value}
    saved = TransactionStore(context['state_dir']).load_snapshot(child.seal['transaction_id'])
    require(not any(x['event_type'] == 'execution_started' for x in saved.events),
        'The optional Save already has an execution attempt; refusal cannot claim it was prevented')
    return {'draft_id': child_id, 'transaction_id': saved.record.transaction_id,
        'artifact_hash': saved.preview.artifact_hash, 'state': saved.record.state.value}


def _validate_decline_observed(baseline, context, snapshot, read):
    require_graph_format(baseline)
    # A refusal never hides an observable original/copied graph contradiction.
    binding = authority(context, baseline['source_id'], baseline['destination_id'], read)
    documents, _ = read_documents(binding)
    original = source_nodes(documents, baseline['source_id'], baseline['source_owner'])
    require(canonical_sha256(serialized(original['source'])) == baseline['source_exact_digest'], 'Original saved graph changed before refusal')
    original_live = live_roles(original, baseline['source_owner'], read)
    require(lifecycle_snapshot_equal(original_live, baseline['roles']), 'Original owned state changed before refusal')
    identity = copied_id(snapshot)
    present = [node for doc in documents.values() for node in doc.iter('SourcePlugin') if guid(node.get('ID')) == identity]
    if present:
        copied = source_nodes(documents, identity, baseline['destination_id'])
        rename = snapshot.preview.artifact['prepared_operation']['verification_plan']['on_name_conflict'] == 'rename'
        require(canonical_sha256(serialized(copied['source'], copied, rename_root=original['source'].get('Name') if rename else None))
            == baseline['source_normalized_digest'], 'Copied saved graph corruption cannot become scoped success')
        copied_live = live_roles(copied, baseline['destination_id'], read)
        compare_owned_fields(original_live, copied_live, baseline['role_ids'], {role: guid(node.get('ID')) for role, node in copied.items()})
    return True


def baseline_origin(record, request_digest, context):
    from .operation_drafts import OperationDraftState
    require(record.operation == 'object.copy' and record.state is OperationDraftState.EDITABLE
        and isinstance(record.check, dict) and record.check['request_digest'] == request_digest
        and record.check['source_revision'] == record.revision - 1, 'Baseline Save requires the current checked copy Draft')
    require(record.check['project_guard'] == context['project_guard'], 'Checked parent runtime changed')
    require_graph_format(record.check['source_copy_file_binding'])
    return {'contract': CONTRACT, 'version': record.version, 'stage': 'baseline',
        'parent': {'draft_id': record.draft_id, 'authority_digest': record.authority_digest,
            'source_revision': record.revision, 'request_digest': request_digest,
            'audit_event_hash': record.audit[-1]['event_hash']},
        'context': context['binding'], 'baseline_digest': record.check['prepared_digest'],
        'file_binding': record.check['source_copy_file_binding']}


def validate_return(envelope, origin):
    require(isinstance(origin, dict) and origin.get('stage') == 'baseline' and isinstance(envelope, dict)
        and set(envelope) == {'draft_id', 'task_authority', 'source_revision', 'origin_digest'}, 'Private baseline return envelope is invalid')
    token = envelope['task_authority']
    require(isinstance(token, str) and token.startswith('da1-') and len(token) == 44
        and envelope['draft_id'] == origin['parent']['draft_id']
        and envelope['source_revision'] == origin['parent']['source_revision']
        and envelope['origin_digest'] == canonical_sha256(origin), 'Private baseline return binding differs')
    # Use the same capability digest as the Draft store, including its domain.
    from .operation_drafts import operation_draft_authority_digest
    require(operation_draft_authority_digest(token) == origin['parent']['authority_digest'], 'Private baseline return authority differs')


def validate_decision(decision):
    require(isinstance(decision, dict) and set(decision) == {'status', 'request_digest', 'origin', 'receipt'}
        and decision['status'] in {'declined', 'baseline_saved'}, 'Baseline decision is invalid')
    validate_origin(decision['origin'], decision['origin'].get('version') if isinstance(decision['origin'], dict) else None)
    require(decision['origin']['stage'] == 'baseline' and decision['request_digest'] == decision['origin']['parent']['request_digest'], 'Baseline decision request differs')
    require((decision['receipt'] is None) == (decision['status'] == 'declined'), 'Baseline decision receipt differs')


def validate_decline(baseline, context, snapshot, read):
    try:
        _validate_decline_observed(baseline, context, snapshot, read)
        return {'status': 'available_observations_preserved'}
    except Exception as exc:
        # Explicit refusal may finish the independently verified live scope if
        # optional bytes are inaccessible. Semantic/identity/XML/graph failures
        # have no I/O cause and must never be converted to scoped success.
        cause, seen = exc, set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, OSError):
                return {'status': 'read_authority_unavailable',
                    'reason': getattr(exc, 'error_code', type(exc).__name__)}
            cause = cause.__cause__
        raise


def without_dirty(value):
    if isinstance(value, dict): return {key: without_dirty(item) for key, item in value.items() if key != 'workunitIsDirty'}
    if isinstance(value, list): return [without_dirty(item) for item in value]
    return value


def validate_file_binding(binding, version):
    require(version in MATCHING_BUILDS and isinstance(binding, dict)
        and set(binding) in ({'source_id', 'destination_id', 'authority', 'files'},
            {'graph_format', 'source_id', 'destination_id', 'authority', 'files'}), 'Baseline file binding is invalid')
    source, destination = guid(binding['source_id']), guid(binding['destination_id'])
    observed = binding['authority']
    require(isinstance(observed, dict) and set(observed) == {'project', 'project_path', 'root', 'root_identity', 'units', 'objects'}
        and isinstance(observed['objects'], dict) and set(observed['objects']) == {source, destination}
        and isinstance(observed['units'], dict) and 1 <= len(observed['units']) <= 2, 'Baseline file membership is invalid')
    require(all(isinstance(observed[key], str) and observed[key] for key in ('project_path', 'root')),
        'Baseline project read paths are invalid')

    paths = {observed['project_path'], *(row['local_path'] for row in observed['units'].values())}
    proofs = binding['files']
    require(isinstance(proofs, dict) and set(proofs) == paths, 'Baseline document proofs do not bind the selected files')
    for path, proof in proofs.items():
        _require_sealed(proof, contract=FILE_PROOF_CONTRACT, seal_field='proof_sha256', field='baseline document')
        require(set(proof) == {'contract', 'path', 'size', 'sha256', 'mtime_ns', 'device', 'inode', 'proof_sha256'}
            and proof['path'] == path and type(proof['size']) is int and 0 <= proof['size'] <= MAX_PROJECT_FILE_BYTES
            and isinstance(proof['sha256'], str) and re.fullmatch('[0-9a-f]{64}', proof['sha256'])
            and all(type(proof[key]) is int for key in ('mtime_ns', 'device', 'inode')),
            'Baseline document proof is invalid')

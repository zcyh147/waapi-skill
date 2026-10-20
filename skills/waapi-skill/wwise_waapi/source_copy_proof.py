"""Operation-owned saved Source proof; never saves or accepts caller file paths."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

from .canonical import canonical_sha256
from .console_project_operations import _read_xml_artifact, _project_io_root_identity
from .host_paths import localize_waapi_host_path
from .object_lifecycle_graph import GET, LifecycleGraphError, capture_lifecycle_fields, lifecycle_snapshot_equal
from .platform_paths import localize_live_wwise_project_path
from .transaction_locality import is_loopback_waapi_host

KEY = 'source_copy_saved_proof'
ORIGIN = 'source_copy_save_origin'
CONTRACT = 'waapi-skill.source-copy-saved-proof/v1'
CHILD_PREFIX = 'od1-f54c50'
SAVE = 'ak.wwise.core.project.save'
ROLES = {'source': ('SourcePlugin', 9699330), 'rtpc': ('RTPC', 1441808),
    'control_input': ('ModulatorLfo', 4194320), 'curve': ('Curve', 917520)}


class SavedCopyProofError(ValueError):
    error_code = 'SOURCE_COPY_SAVED_PROOF_INVALID'
    def as_dict(self):
        return {'error_code': self.error_code, 'message': str(self)}


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


def supported(context):
    if not isinstance(context, dict): return False
    guard = context.get('project_guard', {})
    info = guard.get('wwise', {})
    version = info.get('version', {})
    return (guard.get('version') == '2021.1' and info.get('isCommandLine') is True
        and tuple(version.get(k) for k in ('year', 'major', 'minor', 'build')) == (2021, 1, 14, 8108)
        and is_loopback_waapi_host(guard.get('endpoint', {}).get('host', ''))
        and isinstance(info.get('sessionId'), str) and bool(info['sessionId'])
        and type(info.get('processId')) is int and info['processId'] > 0
        and isinstance(info.get('processPath'), str) and bool(info['processPath']))


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


def source_nodes(documents, identity, owner_id):
    found, all_ids = [], []
    for document in documents.values():
        parents = {child: node for node in document.iter() for child in node}
        for node in document.iter():
            if node.tag in {row[0] for row in ROLES.values()} and 'ID' in node.attrib:
                all_ids.append(guid(node.get('ID')))
            if node.tag != 'SourcePlugin' or guid(node.get('ID')) != guid(identity): continue
            children = parents.get(node); owner = parents.get(children)
            require(children is not None and children.tag == 'ChildrenList' and owner is not None
                and owner.tag == 'Sound' and guid(owner.get('ID')) == guid(owner_id), 'Saved Source owner differs from live owner')
            found.append(node)
    require(len(found) == 1, 'Saved Source is missing or duplicated')
    source = found[0]
    require(source.get('PluginName') == 'Wwise Synth One' and source.get('PluginID') == '148'
        and source.get('CompanyID') == '0' and not list(source.iter('ObjectRef')), 'Serialized plugin/reference shape is not certified')
    base = "PropertyList/Property[@Name='OutputLevel']/RTPCList/RTPC"
    selections = {'source': [source], 'rtpc': source.findall(base),
        'control_input': source.findall(base + "/ReferenceList/Reference[@Name='ControlInput']/Custom/ModulatorLfo"),
        'curve': source.findall(base + '/Curve')}
    require(all(len(rows) == 1 for rows in selections.values()), 'Saved owned roles are missing or ambiguous')
    nodes = {key: value[0] for key, value in selections.items()}
    declarations = [node for node in source.iter() if 'ID' in node.attrib]
    require(set(declarations) == set(nodes.values()), 'Saved owned declaration shape is unclassified')
    ids = [guid(node.get('ID')) for node in declarations]
    require(len(set(ids)) == 4 and all(all_ids.count(x) == 1 for x in ids), 'Saved owned GUIDs alias another declaration')
    return nodes


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
    return [node.tag, sorted(attrs.items()), text, tail, [serialized(child, nodes) for child in node]]


def live_roles(nodes, owner, read):
    rows = {}
    for role, (tag, cls) in ROLES.items():
        node = nodes[role]
        row = exact(guid(node.get('ID')), ['name', 'type', 'classId', 'parent', 'owner', 'notes', 'shortId'], read)
        require(row.get('classId') == cls and row.get('type') in ({'Source', 'SourcePlugin'} if role == 'source' else {tag}), 'Saved/live role class or type differs')
        expected_owner = owner if role == 'source' else nodes['source' if role == 'rtpc' else 'rtpc'].get('ID')
        require(guid(row.get('parent' if role == 'source' else 'owner')) == guid(expected_owner), 'Saved/live owned role edge differs')
        require(row.get('name') == node.get('Name') and row.get('notes', '') == node.findtext('Comment', ''), 'Saved/live role name or notes differs')
        if 'ShortID' in node.attrib:
            require(type(row.get('shortId')) is int and str(row['shortId']) == node.get('ShortID'), 'Saved ShortID is not independently live-bound')
        else:
            require(role == 'curve', 'Unclassified missing serialized ShortID')
        rows[role] = row
    rtpc = rows['rtpc']['id']
    hop = read(GET, {'waql': f'from object "{rtpc}" select @ControlInput take 2'}, {'return': ['id']}).get('return')
    require(isinstance(hop, list) and len(hop) == 1 and guid(hop[0].get('id')) == guid(rows['control_input']['id']), 'Documented ControlInput does not bind the saved LFO')
    return rows


def capture_baseline(context, snapshot, read):
    if not supported(context): return {'status': 'unavailable', 'reason': 'version_host_or_local_runtime_authority_unavailable'}
    source = snapshot['source']['frame']; destination = snapshot['destination']
    if source.get('classId') != 9699330: return {'status': 'unavailable', 'reason': 'serialized_source_shape_not_certified'}
    try:
        binding = authority(context, source['id'], destination, read)
        dirty = binding['project']['workunitIsDirty'] or any(row['workunitIsDirty'] for row in binding['units'].values())
        if dirty:
            return {'status': 'baseline_save_pending', 'authority': binding, 'context': context['binding']}
        documents, proofs = read_documents(binding)
        nodes = source_nodes(documents, source['id'], guid(source['parent']))
        live = live_roles(nodes, guid(source['parent']), read)
        after = authority(context, source['id'], destination, read)
        require(lifecycle_snapshot_equal(binding, after), 'Model authority changed during baseline observation')
        _, proof_after = read_documents(after)
        require(proofs == proof_after, 'Model files changed during baseline observation')
        body = {'contract': CONTRACT, 'status': 'ready', 'origin': 'already_clean',
            'authority': binding, 'context': context['binding'], 'files': proofs,
            'source_id': guid(source['id']), 'source_owner': guid(source['parent']), 'destination_id': destination,
            'source_exact': serialized(nodes['source']), 'source_normalized': serialized(nodes['source'], nodes),
            'roles': live, 'role_ids': {key: guid(node.get('ID')) for key, node in nodes.items()}}
        return {**body, 'digest': canonical_sha256(body)}
    except Exception as exc:
        # This optional observer has not established authority. No Save is
        # offered to repair malformed/inaccessible/unsupported file semantics.
        return {'status': 'unavailable', 'reason': getattr(exc, 'error_code', type(exc).__name__), 'message': str(exc)[:512]}


def validate_baseline(baseline, context, read):
    require(supported(context) and baseline['context'] == context['binding'], 'Saved-copy context drifted')
    observed = authority(context, baseline['source_id'], baseline['destination_id'], read)
    require(lifecycle_snapshot_equal(observed, baseline['authority']), 'Saved-copy clean file authority drifted before dispatch')
    _, proofs = read_documents(observed)
    require(proofs == baseline['files'], 'Saved-copy baseline files changed before dispatch')


def baseline_summary(baseline):
    return {'status': baseline['status'], 'complete_copy_preservation': False,
        **({'baseline_origin': baseline['origin'], 'baseline_digest': baseline['digest'],
            'read_only_paths': list(baseline['files'])} if baseline['status'] == 'ready' else {'reason': baseline.get('reason', 'selected_documents_dirty')})}

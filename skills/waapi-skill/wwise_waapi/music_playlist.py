"""Owner-scoped Music Playlist construction; no general custom-reference grammar.

Matching SDK examples own native PlaylistRoot/anonymous item syntax. The one
2025 native discriminator, when collected, establishes only the ordered getter
contract; neither source examples nor fake-host tests prove playback behavior.
"""
from __future__ import annotations

VERSIONS = ('2023.1', '2024.1', '2025.1')
MAX_ITEMS = 64  # includes the implicit group root
MAX_DEPTH = 8
MAX_BYTES = 32768
ITEM_CLASS = 2359312
CONTAINER_CLASS = 2228240
SEGMENT_CLASS = 1769488


def declaration_contract(version):
    return {
        'field': 'music_playlist', 'supported_versions': list(VERSIONS),
        'available': version in VERSIONS,
        'scope': 'one_bound_existing_MusicPlaylistContainer; standalone_object.set',
        'required': ['kind_handle', 'root_field_handle', 'entries'],
        'kind_handle': 'live_discovered_MusicPlaylistItem_Type_Handle',
        'root_field_handle': 'PlaylistRoot_Reference_Field_Handle_for_exact_bound_owner',
        'optional': ['field_values'],
        'entries': {'group': {'required': ['kind', 'entries'], 'kind': 'group', 'optional': ['field_values']},
            'segment': {'required': ['kind', 'segment_handle'], 'kind': 'segment', 'optional': ['field_values']}},
        'field_values': 'selected_MusicPlaylistItem_class_scoped_scalar_Field_Handle_to_value_map',
        'derived_fields': 'Gateway_owns_PlaylistItemType_Group_or_Segment_and_Segment_reference',
        'group_play_mode': 'omitted_class_Field_Handle_choice_selects_source_and_live_default_Sequence_Continuous; explicit_discovered_choices_preserved',
        'identity': 'each_ordered_occurrence_is_distinct; repeated_Segment_handles_allowed',
        'root': 'implicit_anonymous_Group; complete_tree_replacement; old_GUID_lifetime_independently_checked',
        'native_fields_names_GUIDs_custom_reference_JSON': 'forbidden',
        'hidden_loop_controller': 'do_not_invent_or_probe_unexposed_IsLoopingInfinite; existing_conditional_refusal_retained',
        'limits': {'items_including_root': MAX_ITEMS, 'depth': MAX_DEPTH, 'UTF8_bytes': MAX_BYTES},
        'ordered_readback': 'independent_exact_root_and_per_group_child_GUID_sequence_and_Segment_references; native_discriminator_pending',
        'verification_scope': 'stored_playlist_tree; never_audio_or_playback_quality',
        'older_version_boundary': 'this_PlaylistRoot_constructor_introduced_2023.1; independent_existing_item_edits_and_other_older_factories_unclassified',
    }

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping

from .canonical import canonical_json_bytes, canonical_sha256
from .builders.metadata import parse_get_property_info_result

_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE_SHA = {'2023.1': '10fdc3112e485e03009daa3e3822ec4d30644ac4a524436fdfab1e961b7a8cbf',
    '2024.1': '71decf0495bb28ab251ec457ea3f056e5bb7c195260b742d26c3897fec4c2ab1',
    '2025.1': '64c0f930c51ef7dbc99ca6ac9899eec48b972195c25de439927dab71456f4794'}
_CLASS_SHA = {'2023.1': 'deaf5d5dce2f0d2f7e045d8d84c81545077cbcc27fcb4306620c757708384efa',
    '2024.1': 'ed6ce04c586d3dd5faed4e608d2ad1bb7bf30770a3870676547e8d051fbbdd91',
    '2025.1': '89f54369c93c47b6f5ce2262795c1c629d0ebdf459737507f7a1bbcd6893fda6'}
_GUID = re.compile(r'^\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}$')
GET = 'ak.wwise.core.object.get'
INFO = 'ak.wwise.core.object.getPropertyInfo'
NAMES = 'ak.wwise.core.object.getPropertyAndReferenceNames'
IDENTITY_FIELDS = ('id', 'name', 'type', 'path', 'classId', 'parent', 'owner', 'notes')


def authority(version):
    if version not in VERSIONS:
        raise ValueError('This PlaylistRoot constructor is supported in 2023.1–2025.1 only')
    path = _ROOT / 'resources/metadata' / version / 'music-playlist-construction.json'
    raw = path.read_bytes()
    if len(raw) > 16384:
        raise ValueError('Music Playlist source contract exceeds its bound')
    proof = json.loads(raw)
    expected_member = ('ak_wwise_core_object_set_example_' + ('creating' if version == '2025.1' else 'create')
        + '_a_music_playlist_container_with_segment_and_playlist.html')
    expected = {expected_member: _EXAMPLE_SHA[version], 'wwiseobject_musicplaylistitem.html': _CLASS_SHA[version]}
    if (proof['contract'] != 'waapi-skill.music-playlist-construction-source/v1' or proof['version'] != version
            or proof['item_class'] != ITEM_CLASS or proof['source_enum'] != {'Group': 0, 'Segment': 1}
            or proof['native_root'] != 'PlaylistRoot' or proof['native_segment'] != 'Segment'
            or proof['intrinsic_name'] != '' or len(proof['sources']) != 2
            or {row['member']: row['sha256'] for row in proof['sources']} != expected):
        raise ValueError('Music Playlist source/version mapping is invalid')
    for member, digest in expected.items():
        if sha256((_ROOT / 'references/semantic' / version / 'music-playlist-sources' / member).read_bytes()).hexdigest() != digest:
            raise ValueError('Music Playlist retained primary source drifted')
    if sha256((_ROOT / 'resources/manifest' / version / 'schemas.json').read_bytes()).hexdigest() != proof['manifest_sha256']:
        raise ValueError('Music Playlist reflected grammar drifted')
    return {'version': version, 'resource_sha256': sha256(raw).hexdigest(), 'source_enum': proof['source_enum'],
        'sources': proof['sources'], 'build': proof['build']}


def _fail(code, message):
    from .operation_registry import OperationContractError
    raise OperationContractError(code, message, details={'tracking_issue': 206})


def _guid(value):
    if not isinstance(value, str) or _GUID.fullmatch(value) is None:
        _fail('INVALID_PLAYLIST_READBACK', 'Music Playlist identities must be canonical GUIDs')
    return value.upper()


def _reference(value, *, nullable=False):
    if nullable and value is None:
        return None
    return _guid(value.get('id') if isinstance(value, Mapping) else value)


def _field(row, name):
    if name in row:
        return row[name]
    if '@' + name in row:
        return row['@' + name]
    _fail('INVALID_PLAYLIST_READBACK', 'Required Music Playlist field is absent: ' + name)


def _rows(read, ids, fields):
    result = read(GET, {'from': {'id': ids}}, {'return': list(fields)})
    rows = result.get('return') if isinstance(result, Mapping) else None
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS + 1 or not all(isinstance(row, Mapping) for row in rows):
        _fail('INVALID_PLAYLIST_READBACK', 'Music Playlist readback must be a bounded row array')
    return rows


def _one(read, guid, fields):
    rows = _rows(read, [guid], fields)
    if len(rows) != 1 or _guid(rows[0].get('id')) != _guid(guid):
        _fail('INVALID_PLAYLIST_READBACK', 'Music Playlist GUID must resolve exactly once')
    return rows[0]


def compile_business(session, owner, payload):
    """Resolve only current-task Type, Field and existing Segment handles."""
    from .business_declarations import business_repair
    def reject(code, action):
        raise business_repair(code, field='music_playlist', action=action, tracking_issue=206)
    if session.context.wwise_version not in VERSIONS:
        reject('MUSIC_PLAYLIST_VERSION_BOUNDARY', 'This PlaylistRoot constructor was introduced in Wwise 2023.1; existing-item edits remain separate')
    if owner.object_type != 'MusicPlaylistContainer' or owner.class_id not in (None, CONTAINER_CLASS):
        reject('MUSIC_PLAYLIST_OWNER_REQUIRED', 'Bind one exact existing MusicPlaylistContainer')
    if not isinstance(payload, Mapping) or not {'kind_handle', 'root_field_handle', 'entries'} <= set(payload) or set(payload) - {'kind_handle', 'root_field_handle', 'entries', 'field_values'}:
        reject('MUSIC_PLAYLIST_DECLARATION_INVALID', 'Use only the disclosed bounded Music Playlist business fields')
    if len(canonical_json_bytes(payload)) > MAX_BYTES:
        reject('MUSIC_PLAYLIST_BYTE_LIMIT', 'Split the playlist into a smaller bounded declaration')
    kind = session.handles.resolve_type(payload['kind_handle'])
    root = session.handles.bound_field(payload['root_field_handle'])
    if kind.name != 'MusicPlaylistItem' or kind.class_id != ITEM_CLASS:
        reject('MUSIC_PLAYLIST_TYPE_REQUIRED', 'Select the discovered MusicPlaylistItem class')
    if (root.scope_kind != 'object' or _guid(root.scope_value) != _guid(owner.object_id)
            or root.field_kind != 'reference' or root.token != 'PlaylistRoot' or root.platform is not None):
        reject('FIELD_HANDLE_SCOPE_MISMATCH', 'Discover PlaylistRoot for this exact existing MusicPlaylistContainer without a platform override')
    count = 0
    def item(raw, depth):
        nonlocal count
        count += 1
        if count > MAX_ITEMS or depth > MAX_DEPTH:
            reject('MUSIC_PLAYLIST_TREE_LIMIT', 'Reduce the total playlist item count or nesting depth')
        if not isinstance(raw, Mapping) or raw.get('kind') not in ('group', 'segment'):
            reject('MUSIC_PLAYLIST_ITEM_INVALID', 'Choose group or segment for every ordered occurrence')
        group = raw['kind'] == 'group'
        required = {'kind', 'entries'} if group else {'kind', 'segment_handle'}
        if not required <= set(raw) or set(raw) - required - {'field_values'}:
            reject('MUSIC_PLAYLIST_ITEM_INVALID', 'Groups contain entries; Segment occurrences contain one bound Segment handle')
        values = raw.get('field_values', {})
        if not isinstance(values, Mapping) or len(values) > 32:
            reject('MUSIC_PLAYLIST_FIELDS_INVALID', 'Provide a bounded class Field Handle scalar map')
        props, seen = [], set()
        for handle, value in values.items():
            field = session.handles.bound_field(handle)
            if (field.scope_kind != 'class' or field.scope_value != ITEM_CLASS or field.field_kind != 'property'
                    or field.platform is not None or field.token == 'PlaylistItemType'):
                reject('FIELD_HANDLE_SCOPE_MISMATCH', 'Use scalar MusicPlaylistItem class fields without overriding the Gateway-owned item kind or platform')
            if field.token in seen:
                reject('OBJECT_GRAPH_FIELD_CONFLICT', 'Assign each playlist property once')
            seen.add(field.token)
            props.append({'name': field.token, 'value': session.handles.validate_field_value(field, value)})
        result = {'kind': raw['kind'], 'properties': props}
        if group:
            entries = raw['entries']
            if not isinstance(entries, list) or not entries or len(entries) > MAX_ITEMS:
                reject('MUSIC_PLAYLIST_ENTRIES_INVALID', 'Provide a nonempty bounded ordered entry array')
            result['children'] = [item(child, depth + 1) for child in entries]
        else:
            target = session.handles.resolve_object(raw['segment_handle'])
            if target.object_type != 'MusicSegment' or target.class_id not in (None, SEGMENT_CLASS):
                reject('MUSIC_PLAYLIST_SEGMENT_REQUIRED', 'Bind the exact existing MusicSegment for this occurrence')
            result['segment'] = {'kind': 'id', 'value': target.object_id}
        return result
    tree = item({'kind': 'group', 'entries': payload['entries'], 'field_values': payload.get('field_values', {})}, 0)
    return {'tree': tree, 'authority': authority(session.context.wwise_version)}


def validate_descriptor(payload, version):
    if version not in VERSIONS:
        _fail('MUSIC_PLAYLIST_VERSION_BOUNDARY', 'This PlaylistRoot constructor was introduced in Wwise 2023.1')
    if not isinstance(payload, Mapping) or set(payload) != {'tree', 'authority'} or len(canonical_json_bytes(payload)) > MAX_BYTES:
        _fail('MUSIC_PLAYLIST_DECLARATION_INVALID', 'Expected one bounded Gateway-owned Music Playlist declaration')
    if payload['authority'] != authority(version):
        _fail('MUSIC_PLAYLIST_SOURCE_DRIFT', 'The source-backed PlaylistRoot constructor changed; create a fresh Draft')
    count = 0
    def walk(node, depth):
        nonlocal count
        count += 1
        if count > MAX_ITEMS or depth > MAX_DEPTH or not isinstance(node, Mapping):
            _fail('MUSIC_PLAYLIST_TREE_LIMIT', 'Music Playlist exceeds its bounded tree contract')
        group = node.get('kind') == 'group'
        if set(node) != ({'kind', 'properties', 'children'} if group else {'kind', 'properties', 'segment'}) or node.get('kind') not in ('group', 'segment'):
            _fail('MUSIC_PLAYLIST_DECLARATION_INVALID', 'Music Playlist group and Segment shapes are distinct and closed')
        props = node['properties']
        if not isinstance(props, list) or len(props) > 32:
            _fail('MUSIC_PLAYLIST_DECLARATION_INVALID', 'Music Playlist properties must be bounded')
        seen = set()
        for prop in props:
            if (not isinstance(prop, Mapping) or set(prop) != {'name', 'value'} or not isinstance(prop['name'], str)
                    or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', prop['name']) is None
                    or prop['name'] in {'PlaylistItemType', 'Segment'} or prop['name'] in seen):
                _fail('MUSIC_PLAYLIST_DECLARATION_INVALID', 'Playlist scalar property fields are invalid or duplicated')
            seen.add(prop['name'])
        if group:
            if not isinstance(node['children'], list) or not node['children'] or len(node['children']) > MAX_ITEMS:
                _fail('MUSIC_PLAYLIST_DECLARATION_INVALID', 'Music Playlist group entries must be nonempty and bounded')
            for child in node['children']:
                walk(child, depth + 1)
        elif not isinstance(node['segment'], Mapping) or set(node['segment']) != {'kind', 'value'} or node['segment']['kind'] != 'id':
            _fail('MUSIC_PLAYLIST_DECLARATION_INVALID', 'A Segment occurrence needs one Gateway-bound exact ID')
        else:
            _guid(node['segment']['value'])
    if not isinstance(payload['tree'], Mapping) or payload['tree'].get('kind') != 'group':
        _fail('MUSIC_PLAYLIST_DECLARATION_INVALID', 'PlaylistRoot must be a group')
    walk(payload['tree'], 0)
    return count


def _names(read, scope):
    result = read(NAMES, scope, {})
    names = result.get('return') if isinstance(result, Mapping) else None
    if (not isinstance(names, list) or len(names) > 256 or len(set(names)) != len(names)
            or not all(isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) for name in names)):
        _fail('INVALID_METADATA', 'Music Playlist needs a bounded exact field inventory')
    return names


def _snapshot(read, guid, names):
    fields = list(dict.fromkeys([*IDENTITY_FIELDS, 'children', *names]))
    result = {}
    for start in range(0, len(fields), 32):
        row = _one(read, guid, list(dict.fromkeys(['id', *fields[start:start + 32]])))
        if result and any(result[key] != value for key, value in row.items() if key in result):
            _fail('INVALID_PLAYLIST_READBACK', 'Music Playlist object changed during its bounded snapshot')
        result.update(row)
    return result


def _tree_snapshot(read, root, names):
    seen = set()
    def walk(guid, parent, depth):
        guid = _guid(guid)
        if guid in seen or len(seen) >= MAX_ITEMS or depth > MAX_DEPTH:
            _fail('MUSIC_PLAYLIST_TREE_LIMIT', 'Existing Music Playlist tree is cyclic, duplicated or outside the bounded snapshot')
        seen.add(guid)
        row = _snapshot(read, guid, names)
        if row.get('type') != 'MusicPlaylistItem' or row.get('classId') != ITEM_CLASS or row.get('name') != '':
            _fail('INVALID_PLAYLIST_READBACK', 'Every owned playlist occurrence must have the exact class and anonymous name')
        if 'children' in row:
            edges = row['children']
        else:
            # Native leaf items can omit this projection. Resolve the relation
            # independently; omission alone never proves an empty collection.
            relation = read(GET, {'from': {'id': [guid]},
                'transform': [{'select': ['children']}, {'range': [0, MAX_ITEMS + 1]}]}, {'return': ['id']})
            edges = relation.get('return') if isinstance(relation, Mapping) else None
        if not isinstance(edges, list) or len(edges) > MAX_ITEMS:
            _fail('INVALID_PLAYLIST_READBACK', 'Playlist children must be an independently returned bounded ordered array')
        child_ids = [_reference(edge) for edge in edges]
        if len(set(child_ids)) != len(child_ids):
            _fail('INVALID_PLAYLIST_READBACK', 'Playlist children may repeat Segment references, never occurrence GUIDs')
        row = dict(row)
        row['children'] = [{'id': value} for value in child_ids]
        return {'row': row, 'children': [walk(child, guid, depth + 1) for child in child_ids]}
    return walk(root, None, 0) if root is not None else None


def prepare(payload, *, version, owner, catalog, read, resolve_segment, validate_scalar):
    """Build one immutable owner-root plan using the Registry's identity resolver."""
    validate_descriptor(payload, version)
    if owner.row.get('type') != 'MusicPlaylistContainer':
        _fail('MUSIC_PLAYLIST_OWNER_REQUIRED', 'PlaylistRoot construction requires one existing MusicPlaylistContainer')
    classes = [row.as_dict() for row in catalog]
    expected = {'MusicPlaylistContainer': CONTAINER_CLASS, 'MusicPlaylistItem': ITEM_CLASS, 'MusicSegment': SEGMENT_CLASS}
    selected = []
    for name, class_id in expected.items():
        matches = [row for row in classes if row.get('name') == name and row.get('classId') == class_id]
        if len(matches) != 1 or len([row for row in classes if row.get('classId') == class_id]) != 1:
            _fail('INVALID_METADATA', 'Playlist constructor class differs from its exact source-backed class')
        selected.append(matches[0])
    class_names = _names(read, {'classId': ITEM_CLASS})
    metadata = []
    cached = {}
    def info(scope, name):
        key = canonical_sha256({'scope': scope, 'name': name})
        if key not in cached:
            if scope == {'classId': ITEM_CLASS} and name not in class_names:
                _fail('MUSIC_PLAYLIST_HIDDEN_DEPENDENCY', 'Required playlist controller is not exposed; retain reads and refuse the write without probing hidden controls')
            raw = read(INFO, {**scope, 'property': name}, {})
            parsed = parse_get_property_info_result(raw)
            if parsed.name != name:
                _fail('INVALID_METADATA', 'Playlist field metadata names a different field')
            cached[key] = parsed
            metadata.append({'scope': scope, 'name': name, 'value': parsed.as_dict()})
        return cached[key]
    root_info = info({'object': owner.object}, 'PlaylistRoot')
    item_info = info({'classId': ITEM_CLASS}, 'PlaylistItemType')
    segment_info = info({'classId': ITEM_CLASS}, 'Segment')
    for record, native_type in ((root_info, 'MusicPlaylistItem'), (segment_info, 'MusicSegment')):
        restrictions = record.restriction
        if (restrictions.get('type') != 'reference'
                or not any(isinstance(row, Mapping) and row.get('type') == [native_type] for row in restrictions.get('restrictions', []))):
            _fail('INVALID_METADATA', 'Playlist ownership or Segment reference metadata contradicts its source-backed target type')
    values = item_info.restriction.get('values', [])
    if item_info.restriction.get('type') != 'enum' or {row.get('value') for row in values} != {0, 1}:
        _fail('INVALID_METADATA', 'Playlist item-kind metadata differs from the matching Group/Segment source enumeration')
    segment_snapshots, segment_names, condition_plans = {}, {}, {}
    from .new_object_defaults import class_default_evidence, NewObjectDefaultError
    def native(node, path):
        group = node['kind'] == 'group'
        props = {prop['name']: prop['value'] for prop in node['properties']}
        props['PlaylistItemType'] = payload['authority']['source_enum']['Group' if group else 'Segment']
        if group and 'PlayMode' not in props:
            # Source table: Group's default is Sequence Continuous, not random.
            mode_info = info({'classId': ITEM_CLASS}, 'PlayMode')
            if mode_info.default != 0 or mode_info.restriction.get('type') != 'enum' or {row.get('value') for row in mode_info.restriction.get('values', [])} != {0, 1, 2, 3}:
                _fail('INVALID_METADATA', 'Playlist group default differs from its source-defined Sequence Continuous meaning')
            props['PlayMode'] = 0
        infos = [info({'classId': ITEM_CLASS}, name) for name in props]
        for record in infos:
            validate_scalar(record, props[record.name])
        def guarded_metadata(uri, args, options):
            if uri != INFO or set(args) != {'classId', 'property'} or args['classId'] != ITEM_CLASS:
                _fail('MUSIC_PLAYLIST_CONDITION_BOUNDARY', 'Playlist class conditions cannot read unrelated object state')
            return info({'classId': ITEM_CLASS}, args['property']).as_dict()
        try:
            defaults = class_default_evidence(infos=infos, scope={'classId': ITEM_CLASS}, read_call=guarded_metadata,
                supplied_values=props, supplied_references={}, validate_scalar=validate_scalar, version=version)
        except NewObjectDefaultError as exc:
            _fail(exc.error_code, str(exc))
        props.update(defaults.get('derived_properties', {}))
        condition_plans[path] = defaults['requirements']
        result = {'type': 'MusicPlaylistItem', 'name': '', **{'@' + name: value for name, value in props.items()}}
        if group:
            result['children'] = [native(child, path + '.children[' + str(index) + ']') for index, child in enumerate(node['children'])]
        else:
            segment = resolve_segment(node['segment'], path + '.segment')
            if segment.row.get('type') != 'MusicSegment' or segment.row.get('classId') not in (None, SEGMENT_CLASS):
                _fail('MUSIC_PLAYLIST_SEGMENT_REQUIRED', 'Each occurrence requires one exact existing MusicSegment')
            guid = _guid(segment.object)
            if guid not in segment_snapshots:
                names = _names(read, {'object': segment.object})
                segment_names[guid] = names
                snapshot = _snapshot(read, guid, names)
                if snapshot.get('classId') != SEGMENT_CLASS or snapshot.get('type') != 'MusicSegment':
                    _fail('MUSIC_PLAYLIST_SEGMENT_REQUIRED', 'Each Segment must match its source-backed live class')
                segment_snapshots[guid] = snapshot
            result['@Segment'] = segment.object
        return result
    native_root = native(payload['tree'], '$.music_playlist')
    owner_names = _names(read, {'object': owner.object})
    owner_snapshot = _snapshot(read, owner.object, owner_names)
    if owner_snapshot.get('classId') != CONTAINER_CLASS:
        _fail('MUSIC_PLAYLIST_OWNER_REQUIRED', 'Playlist owner must match the exact existing container class')
    root_id = _reference(_field(owner_snapshot, 'PlaylistRoot'), nullable=True)
    old_tree = _tree_snapshot(read, root_id, class_names)
    proof = {'version': version, 'owner_id': owner.object, 'authority': payload['authority'], 'classes': selected,
        'metadata': metadata, 'class_field_names': class_names, 'owner_field_names': owner_names,
        'owner_snapshot': owner_snapshot, 'old_tree': old_tree,
        'segments': [{'id': guid, 'names': segment_names[guid], 'row': row} for guid, row in segment_snapshots.items()],
        'native_tree': native_root, 'requested_tree': payload['tree'], 'condition_plans': condition_plans,
        'replacement_intent': 'remove_previous_playlist_tree',
        'verification_scope': declaration_contract(version)['verification_scope'],
        'ordered_getter_evidence': 'pending_native_discriminator'}
    return native_root, proof


def guard_assertions(proof, *, read, after_write=False):
    """Revalidate source, metadata and every retained identity before one write."""
    checks = []
    def check(name, predicate, evidence):
        checks.append({'name': name, 'passed': bool(predicate), 'evidence': evidence})
    try:
        check('Music Playlist source/version authority unchanged', authority(proof['version']) == proof['authority'], proof['authority'])
        classes = read('ak.wwise.core.object.getTypes', {}, {}).get('return', [])
        check('Music Playlist selected classes unchanged', all([row for row in classes if row.get('classId') == wanted['classId']] == [wanted]
            for wanted in proof['classes']), {'expected': proof['classes'], 'actual': classes})
        names = _names(read, {'classId': ITEM_CLASS})
        check('Music Playlist class inventory unchanged', names == proof['class_field_names'], {'expected': proof['class_field_names'], 'actual': names})
        for row in proof['metadata']:
            actual = parse_get_property_info_result(read(INFO, {**row['scope'], 'property': row['name']}, {})).as_dict()
            check('Music Playlist field metadata unchanged: ' + row['name'], actual == row['value'], {'expected': row['value'], 'actual': actual})
        owner = _snapshot(read, proof['owner_id'], proof['owner_field_names'])
        expected = proof['owner_snapshot']
        if after_write:
            owner = {key: value for key, value in owner.items() if key not in {'PlaylistRoot', '@PlaylistRoot'}}
            expected = {key: value for key, value in expected.items() if key not in {'PlaylistRoot', '@PlaylistRoot'}}
        check('Music Playlist owner unrelated state preserved', owner == expected, {'expected': expected, 'actual': owner})
        for row in proof['segments']:
            actual = _snapshot(read, row['id'], row['names'])
            check('Music Playlist Segment identity and state preserved', actual == row['row'], {'expected': row['row'], 'actual': actual})
        if not after_write:
            root = _reference(_field(proof['owner_snapshot'], 'PlaylistRoot'), nullable=True)
            actual = _tree_snapshot(read, root, proof['class_field_names'])
            check('Music Playlist previous root and complete ordered tree unchanged', actual == proof['old_tree'], {'expected': proof['old_tree'], 'actual': actual})
    except (ValueError, KeyError, TypeError, OSError) as exc:
        check('Music Playlist immutable facts remain readable', False, {'error': str(exc)})
    return checks


def verify(proof, payload, *, read):
    """Bind native result occurrences to independent ordered relationship reads."""
    checks = guard_assertions(proof, read=read, after_write=True)
    def check(name, predicate, evidence):
        checks.append({'name': name, 'passed': bool(predicate), 'evidence': evidence})
    owner_id = _guid(proof['owner_id'])
    owners = payload.get('objects', [])
    returned = [row for row in owners if isinstance(row, Mapping) and _guid(row.get('id')) == owner_id]
    if len(returned) != 1 or '@PlaylistRoot' not in returned[0]:
        _fail('INVALID_PLAYLIST_RESULT', 'The native result must associate one playlist tree with the exact owner')
    result_root = returned[0]['@PlaylistRoot']
    root_id = _reference(_field(_one(read, owner_id, ['id', 'PlaylistRoot']), 'PlaylistRoot'))
    tree = _tree_snapshot(read, root_id, proof['class_field_names'])
    seen = set()
    identities = []
    def walk(expected, native, result, observed, parent, path, root=False):
        row = observed['row']
        guid = _guid(row['id'])
        returned_id = _guid(result.get('id')) if isinstance(result, Mapping) else None
        check('Music Playlist ordered occurrence matches independent GUID', guid == returned_id and guid not in seen
            and result.get('name') == '', {'actual': guid, 'result': returned_id})
        seen.add(guid)
        relation = _reference(row.get('owner') if root else row.get('parent'), nullable=True)
        check('Music Playlist occurrence owner/parent matches requested tree', relation == _guid(parent), {'actual': relation, 'expected': parent})
        expected_kind = proof['authority']['source_enum']['Group' if expected['kind'] == 'group' else 'Segment']
        check('Music Playlist occurrence kind matches requested role', _field(row, 'PlaylistItemType') == expected_kind, row)
        for token, value in native.items():
            if token.startswith('@') and token != '@Segment':
                check('Music Playlist selected or derived scalar value matches', _field(row, token[1:]) == value, {'property': token, 'expected': value, 'row': row})
        for requirement in proof['condition_plans'].get(path, []):
            actual = _field(row, requirement['name'])
            if requirement['kind'] == 'reference':
                actual = _reference(actual, nullable=True)
            check('Music Playlist constructor prerequisite matches', actual == requirement['effective_value'], {'requirement': requirement, 'actual': actual})
        identities.append({'id': guid, 'kind': expected['kind'], 'parent_id': parent, 'occurrence_path': path,
            'result_handle': 'bnh1-' + canonical_sha256({'owner_id': owner_id, 'tree': proof['requested_tree'], 'occurrence_path': path})[:32]})
        result_children = result.get('children', [])
        wanted_children = expected.get('children', [])
        actual_children = observed['children']
        if not isinstance(result_children, list):
            _fail('INVALID_PLAYLIST_RESULT', 'Playlist result children must be an ordered array')
        check('Music Playlist ordered group cardinality matches', len(wanted_children) == len(result_children) == len(actual_children),
            {'requested': len(wanted_children), 'result': len(result_children), 'actual': len(actual_children)})
        if len(wanted_children) == len(result_children) == len(actual_children):
            for index, (wanted, native_child, result_child, actual_child) in enumerate(zip(wanted_children, native.get('children', []), result_children, actual_children, strict=True)):
                walk(wanted, native_child, result_child, actual_child, guid, path + '.children[' + str(index) + ']')
        if expected['kind'] == 'segment':
            check('Music Playlist repeated Segment reference matches exact occurrence', _reference(_field(row, 'Segment')) == _guid(expected['segment']['value']), row)
    walk(proof['requested_tree'], proof['native_tree'], result_root, tree, owner_id, '$.music_playlist', True)
    old_ids = []
    def old(node):
        if node is not None:
            old_ids.append(node['row']['id'])
            for child in node['children']:
                old(child)
    old(proof['old_tree'])
    if old_ids:
        rows = _rows(read, old_ids, ['id'])
        check('Music Playlist previous owned tree GUIDs are absent', rows == [], {'old_ids': old_ids, 'actual': rows})
    check('Music Playlist created occurrence GUIDs are fresh', not set(old_ids) & seen, {'old_ids': old_ids, 'new_ids': sorted(seen)})
    return checks, identities


def without_result_tree(payload):
    """Project already independently verified custom results for generic binding."""
    return {**payload, 'objects': [{key: value for key, value in row.items() if key != '@PlaylistRoot'} for row in payload.get('objects', [])]}

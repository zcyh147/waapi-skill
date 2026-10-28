"""One fixed 2025 Music Playlist discriminator; parent owns its native launch.

Uses the existing ScenarioLifecycle finalizer and bounded owned native actor.
It records root lifetime instead of prescribing it. Collection is not a public
Gateway pass and never certifies audible playback or other native versions.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from wwise_waapi.builders.schema import SemanticSchemaValidator
from wwise_waapi.music_playlist import authority

VERSION = '2025.1'
BOUNDS = {'native_calls': 48, 'native_writes': 2, 'items_per_tree': 8,
    'bytes_per_result': 262144, 'evidence_bytes': 2097152}
BASE = ['id', 'name', 'type', 'classId', 'path', 'parent', 'owner', 'notes']


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def _one(rows):
    assert isinstance(rows, list) and len(rows) == 1, rows
    return rows[0]


def _identity(value):
    from wwise_waapi.operation_plugin import _closed_object_reference_id
    return _closed_object_reference_id(value, field='playlist-reference')


def collect(actor, evidence):
    validator = SemanticSchemaValidator(version=VERSION)
    def call(uri, args, options=None):
        assert len(evidence['native_calls']) < BOUNDS['native_calls']
        if uri == 'ak.wwise.core.object.set':
            assert sum(row['uri'] == uri for row in evidence['native_calls']) < BOUNDS['native_writes']
        record = {'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options or {}),
            'schema_validation': validator.validate(uri, args, options or {}).as_dict()}
        evidence['native_calls'].append(record)
        try:
            result = actor(uri, args, options or {})
            assert len(_encoded(result)) <= BOUNDS['bytes_per_result']
            record['result'] = result
            assert len(_encoded(evidence)) <= BOUNDS['evidence_bytes']
            return result
        except BaseException as exc:
            record['error'] = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
            raise
    def get(guid, fields):
        return _one(call('ak.wwise.core.object.get', {'from': {'id': [guid]}}, {'return': fields})['return'])
    info = call('ak.wwise.core.getInfo', {})
    evidence['get_info'] = info
    build = '.'.join(str(info['version'][key]) for key in ('year', 'major', 'minor', 'build'))
    assert info['isCommandLine'] is True and build == evidence['source']['build']
    types = call('ak.wwise.core.object.getTypes', {})['return']
    for name, class_id in [('MusicPlaylistContainer', 2228240), ('MusicPlaylistItem', 2359312), ('MusicSegment', 1769488)]:
        assert _one([row for row in types if row['name'] == name])['classId'] == class_id
    kind_info = call('ak.wwise.core.object.getPropertyInfo', {'classId': 2359312, 'property': 'PlaylistItemType'})
    choices = kind_info['restriction']['values']
    selected = {meaning: _one([row for row in choices if row['displayName'].strip('/').casefold() == meaning.casefold()])['value']
        for meaning in ('Group', 'Segment')}
    assert selected == evidence['source']['source_enum']
    mode_info = call('ak.wwise.core.object.getPropertyInfo', {'classId': 2359312, 'property': 'PlayMode'})
    mode = _one([row for row in mode_info['restriction']['values']
        if row['displayName'].strip('/').casefold() == 'sequence continuous'])['value']
    evidence['selected_metadata'] = {'PlaylistItemType': kind_info, 'PlayMode': mode_info}
    unit = _one(call('ak.wwise.core.object.get', {'from': {'path': [r'\Containers\Default Work Unit']}}, {'return': BASE})['return'])
    assert unit['type'] == 'WorkUnit'
    # Same source-defined native object.set hierarchy constructor; no media or Voice staging is needed.
    assert call('ak.wwise.core.object.get', {'from': {'path': [unit['path'] + r'\GatewayPlaylist206']}}, {'return': BASE})['return'] == []
    seed = call('ak.wwise.core.object.set', {'objects': [{'object': unit['id'], 'children': [{
        'type': 'MusicPlaylistContainer', 'name': 'GatewayPlaylist206', 'notes': 'Preserve owner',
        'children': [{'type': 'MusicSegment', 'name': name, 'notes': 'Preserve ' + name} for name in ('SegmentA', 'SegmentB')],
        '@PlaylistRoot': {'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': selected['Group'], '@PlayMode': mode,
            'children': [{'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': selected['Segment'],
                '@Segment': unit['path'] + r'\GatewayPlaylist206\SegmentA'}]}}]}],
        'onNameConflict': 'merge', 'listMode': 'replaceAll'}, {'return': BASE})
    container = _one(seed['objects'][0]['children'])
    container_id = container['id']
    segments = container['children']
    assert len(segments) == 2 and {row['name'] for row in segments} == {'SegmentA', 'SegmentB'}
    segment_ids = {row['name']: row['id'] for row in segments}
    def tree():
        owner = get(container_id, BASE + ['PlaylistRoot', 'children'])
        seen = set()
        def walk(identity):
            assert identity not in seen and len(seen) < BOUNDS['items_per_tree']
            seen.add(identity)
            row = get(identity, BASE + ['children', 'PlaylistItemType', 'Segment', 'PlayMode'])
            assert row['type'] == 'MusicPlaylistItem' and row['classId'] == 2359312 and row['name'] == ''
            children = row['children']
            assert isinstance(children, list) and len(children) <= BOUNDS['items_per_tree']
            transform = call('ak.wwise.core.object.get', {'from': {'id': [identity]},
                'transform': [{'select': ['children']}, {'range': [0, BOUNDS['items_per_tree'] + 1]}]}, {'return': BASE})['return']
            assert [child['id'] for child in transform] == [_identity(child) for child in children]
            return {'row': row, 'transformed_children': transform, 'children': [walk(_identity(child)) for child in children]}
        root = _identity(owner['PlaylistRoot'])
        return {'owner': owner, 'tree': walk(root), 'occurrence_ids': sorted(seen)}
    evidence['before'] = tree()
    evidence['segments_before'] = [get(segment_ids[name], BASE + ['children']) for name in ('SegmentA', 'SegmentB')]
    a, b = segment_ids['SegmentA'], segment_ids['SegmentB']
    def segment(guid):
        return {'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': selected['Segment'], '@Segment': guid}
    native_tree = {'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': selected['Group'], '@PlayMode': mode,
        'children': [segment(a), {'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': selected['Group'], '@PlayMode': mode,
            'children': [segment(b), segment(a)]}]}
    request = {'objects': [{'object': container_id, '@PlaylistRoot': native_tree}], 'onNameConflict': 'merge', 'listMode': 'replaceAll'}
    evidence['request'] = deepcopy(request)
    evidence['result'] = call('ak.wwise.core.object.set', request, {'return': BASE})
    evidence['after'] = tree()
    evidence['segments_after'] = [get(segment_ids[name], BASE + ['children']) for name in ('SegmentA', 'SegmentB')]
    assert evidence['segments_before'] == evidence['segments_after']
    actual = evidence['after']['tree']
    def compare(wanted, node):
        row = node['row']
        assert row['PlaylistItemType'] == wanted['@PlaylistItemType']
        if '@Segment' in wanted:
            assert _identity(row['Segment']) == wanted['@Segment']
        else:
            assert row['PlayMode'] == wanted['@PlayMode']
        assert len(wanted.get('children', [])) == len(node['children'])
        for child, observed in zip(wanted.get('children', []), node['children'], strict=True):
            compare(child, observed)
    compare(native_tree, actual)
    old_ids = evidence['before']['occurrence_ids']
    old_rows = call('ak.wwise.core.object.get', {'from': {'id': old_ids}}, {'return': BASE})['return']
    evidence['old_guid_lifetime'] = {'before': old_ids, 'survivors': old_rows,
        'root_reused': evidence['before']['owner']['PlaylistRoot'] == evidence['after']['owner']['PlaylistRoot']}
    evidence['ordered_getter_observed'] = True
    evidence['playback_quality_verified'] = False
    return evidence


def run_diagnostic(lifecycle, *, actor_factory=None):
    """Persist collection before the existing lifecycle's authoritative receipt."""
    if actor_factory is None:
        from tests.semantic.support.codex_heavy_project_runner_v3 import OwnedDirectWaapiCall
        actor_factory = OwnedDirectWaapiCall
    evidence = {'contract': 'waapi-skill.music-playlist-discriminator/v1', 'version': VERSION,
        'source': authority(VERSION), 'bounds': BOUNDS, 'native_calls': [],
        'public_gateway_pass': False, 'agent_semantic_pass': False}
    runtime, actor = None, None
    status, reason, closed = 'FAIL', '', True
    try:
        runtime = lifecycle.start()
        actor = actor_factory(host=runtime.host, port=runtime.port)
        collect(actor, evidence)
        status = 'PASS'
    except BaseException as exc:
        reason = str(exc)[:4096]
        evidence['error'] = {'type': type(exc).__name__, 'message': reason}
        raise
    finally:
        if actor is not None:
            try:
                closed = actor.close() and actor.fully_closed
            except BaseException as exc:
                closed = False
                evidence['actor_close_error'] = str(exc)[:4096]
            if not closed:
                status, reason = 'BLOCKED', 'Owned native actor could not close'
        evidence['collection_status'] = status
        evidence['status'] = 'PENDING'
        evidence['final_outcome'] = {'path': 'lifecycle.json', 'field': 'final_status'}
        if runtime is not None:
            try:
                encoded = _encoded(evidence)
                assert len(encoded) <= BOUNDS['evidence_bytes']
                (runtime.evidence_root / 'music-playlist-discriminator.json').write_bytes(encoded)
            except BaseException:
                status, reason = 'BLOCKED', 'Music Playlist diagnostic evidence could not be sealed'
                raise
            finally:
                finished = lifecycle.finish(status, reason=reason)
                assert finished.final_status == status, finished
        if 'error' not in evidence:
            assert closed, reason
    return evidence

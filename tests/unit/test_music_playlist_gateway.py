"""Ordered Music Playlist declarations through persisted Gateway transactions.

Program evidence only: the fake host independently stores child GUID sequences.
It does not establish native ordering or playback behavior.
"""
from copy import deepcopy
import json
import pytest

from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, FIRST, SECOND, ROOT, CHILD
from tests.unit.test_object_graph_business_gateway import gateway

A = '{AAAAAAAA-1111-1111-1111-111111111111}'
B = '{BBBBBBBB-1111-1111-1111-111111111111}'
OLD = '{CCCCCCCC-1111-1111-1111-111111111111}'


def test_music_playlist_schema_discloses_closed_tree_and_exact_version_boundary(tmp_path):
    for version in ('2022.1', '2023.1', '2024.1', '2025.1'):
        code, result = gateway.execute_gateway(['--version', version, 'operation-schema', 'object.set'],
            env={'WAAPI_SKILL_CONFIG_PATH': str(tmp_path / 'absent.json')})
        assert code == 0, result
        assert 'music_playlist' in json.dumps(result)
        encoded = json.dumps(result)
        assert 'root_field_handle' in encoded and 'segment_handle' in encoded
        assert 'ordered_readback' in encoded


class MusicPlaylistTask(OwnedGraphTask):
    def __init__(self, path, version='2025.1'):
        super().__init__(path, version, 'object.set')
        self.types = [{'name': name, 'classId': class_id, 'type': 'WObject'} for name, class_id in (
            ('MusicPlaylistContainer', 2228240), ('MusicPlaylistItem', 2359312), ('MusicSegment', 1769488), ('WorkUnit', 1638416))]
        self.objects = {
            FIRST: {'id': FIRST, 'name': 'Sequence', 'type': 'MusicPlaylistContainer', 'classId': 2228240,
                'path': r'\Interactive Music Hierarchy\Default Work Unit\Sequence', 'parent': {'id': SECOND},
                'notes': 'Keep container', '@PlaylistRoot': {'id': OLD}},
            SECOND: {'id': SECOND, 'name': 'Default Work Unit', 'type': 'WorkUnit', 'classId': 1638416,
                'path': r'\Interactive Music Hierarchy\Default Work Unit', 'parent': None, 'notes': ''},
            OLD: {'id': OLD, 'name': '', 'type': 'MusicPlaylistItem', 'classId': 2359312,
                'path': r'\old-root', 'parent': None, 'owner': {'id': FIRST}, 'notes': '',
                '@PlaylistItemType': 0, '@PlayMode': 0, 'children': []},
        }
        for guid, name in ((A, 'A'), (B, 'B')):
            self.objects[guid] = {'id': guid, 'name': name, 'type': 'MusicSegment', 'classId': 1769488,
                'path': self.objects[FIRST]['path'] + '\\' + name, 'parent': {'id': FIRST}, 'notes': 'Keep segment ' + name}
        self.metadata = {
            'PlaylistRoot': {'name': 'PlaylistRoot', 'type': 'Reference',
                'restriction': {'type': 'reference', 'restrictions': [{'type': ['MusicPlaylistItem']}]}},
            'PlaylistItemType': {'name': 'PlaylistItemType', 'type': 'int16', 'default': 0,
                'restriction': {'type': 'enum', 'values': [{'value': 0, 'displayName': 'Group'}, {'value': 1, 'displayName': 'Segment'}]}},
            'Segment': {'name': 'Segment', 'type': 'Reference',
                'restriction': {'type': 'reference', 'restrictions': [{'type': ['MusicSegment']}, 'notNull']}},
            'PlayMode': {'name': 'PlayMode', 'type': 'int16', 'default': 0,
                'restriction': {'type': 'enum', 'values': [{'value': 0, 'displayName': 'Sequence Continuous'}, {'value': 1, 'displayName': 'Sequence Step'}, {'value': 2, 'displayName': 'Random Continuous'}, {'value': 3, 'displayName': 'Random Step'}]}},
            'Weight': {'name': 'Weight', 'type': 'Real64', 'default': 50,
                'restriction': {'type': 'range', 'min': 0.001, 'max': 100}},
        }
        self.writes, self.fault = [], None
        self.next_id = 100

    def call(self, uri, args=None, options=None):
        if uri.endswith('object.get') and args.get('transform') == [{'select': ['children']}, {'range': [0, 65]}]:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            parent = self.objects[args['from']['id'][0]]
            return {'return': self.project_rows([self.objects[item['id']] for item in parent.get('children', [])], options)}
        if uri.endswith('object.get') and args.get('from', {}).get('id') and not args.get('transform'):
            # A relationship array is independent from result and object-map order.
            if len(args['from']['id']) == 1 and 'children' in options['return']:
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                return {'return': self.project_rows([self.objects[key] for key in args['from']['id'] if key in self.objects], options)}
        if uri.endswith('object.set'):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.writes.append(deepcopy(args))
            item, = args['objects']
            assert item['object'] == FIRST and item['listMode'] == 'replaceAll'
            assert set(item) == {'object', 'listMode', '@PlaylistRoot'}
            def create(node, owner, root=False):
                self.next_id += 1
                guid = '{00000000-0000-0000-0000-%012d}' % self.next_id
                assert node['type'] == 'MusicPlaylistItem' and node['name'] == ''
                children = [create(child, guid) for child in node.get('children', [])]
                row = {'id': guid, 'name': '', 'type': 'MusicPlaylistItem', 'classId': 2359312,
                    'path': '\\opaque-' + str(self.next_id), 'notes': '', 'parent': None if root else {'id': owner},
                    'owner': {'id': owner} if root else None, 'children': [{'id': child['id']} for child in children],
                    **{key: deepcopy(value) for key, value in node.items() if key.startswith('@')}}
                if '@Segment' in row:
                    row['@Segment'] = {'id': row['@Segment']}
                self.objects[guid] = row
                return {'id': guid, 'name': '', **({'children': children} if children else {})}
            root = create(item['@PlaylistRoot'], FIRST, True)
            self.objects[FIRST]['@PlaylistRoot'] = {'id': root['id']}
            self.objects.pop(OLD, None)
            if self.fault == 'reordered-readback':
                self.objects[root['id']]['children'].reverse()
            if self.fault == 'wrong-owner':
                self.objects[root['id']]['owner'] = {'id': SECOND}
            if self.fault == 'wrong-class':
                self.objects[root['id']]['classId'] = 1769488
            if self.fault == 'retained-old-root':
                self.objects[OLD] = deepcopy(self.old_snapshot)
            if self.fault == 'changed-segment':
                self.objects[A]['notes'] = 'Unrequested'
            if self.fault == 'reordered-result':
                root['children'].reverse()
            return {'objects': [{'id': FIRST, 'name': 'Sequence', '@PlaylistRoot': root}]}
        return super().call(uri, args, options)

    def declare(self):
        owner = self.bind(FIRST)
        a, b = self.bind(A), self.bind(B)
        kind = self.discover_kind('MusicPlaylistItem')
        root_field = self.discover(owner, 'PlaylistRoot')
        code, found = self.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'Weight')
        assert code == 0, found
        weight = found['meaning_results'][0]['candidates'][0]['handle']
        self.payload = {'kind_handle': kind, 'root_field_handle': root_field,
            'entries': [{'kind': 'segment', 'segment_handle': a},
                {'kind': 'group', 'entries': [{'kind': 'segment', 'segment_handle': b},
                    {'kind': 'segment', 'segment_handle': a, 'field_values': {weight: 25}}]}]}
        code, declared = self.step('draft-declare-existing', '--declaration-id', 'playlist', '--object-handle', owner,
            '--field', 'music_playlist', json.dumps(self.payload))
        assert code == 0, declared
        self.old_snapshot = deepcopy(self.objects[OLD])
        return self

    def discover_kind(self, meaning):
        code, result = self.step('draft-discover-types', '--role', 'object', '--meaning', meaning)
        assert code == 0, result
        return result['type_candidates'][0]['handle']


def test_existing_playlist_nested_repeated_occurrences_survive_persisted_transaction(tmp_path):
    task = MusicPlaylistTask(tmp_path).declare()
    preserved = {guid: deepcopy(task.objects[guid]) for guid in (A, B, SECOND)}
    tx, shown = task.preview()
    assert task.writes == []
    assert 'remove_previous_playlist_tree' in json.dumps(shown)
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)
    assert len(task.writes) == 1 and OLD not in task.objects
    assert all(task.objects[guid] == row for guid, row in preserved.items())
    code, rejected = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, rejected


@pytest.mark.parametrize('exposed', (False, True))
def test_playlist_class_loop_discovery_uses_only_disclosed_controllers(tmp_path, exposed):
    from tests.unit.test_conditional_reference_gateway import condition
    task = MusicPlaylistTask(tmp_path)
    task.metadata['LoopCount'] = {'name': 'LoopCount', 'type': 'int16', 'default': 1,
        'restriction': {'type': 'range', 'min': 0, 'max': 32767},
        'dependencies': [condition('IsLoopingInfinite', False)]}
    task.metadata['IsLoopingInfinite'] = {'name': 'IsLoopingInfinite', 'type': 'bool', 'default': False}
    original = task.call
    def call(uri, args=None, options=None):
        if not exposed and uri.endswith('getPropertyAndReferenceNames'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': [name for name in task.metadata if name != 'IsLoopingInfinite']}
        return original(uri, args, options)
    task.call = call
    task.bind(FIRST)
    kind = task.discover_kind('MusicPlaylistItem')
    code, found = task.step('draft-discover-fields', '--type-handle', kind, '--meaning', 'LoopCount')
    if exposed:
        assert code == 0, found
        assert found['meaning_results'][0]['candidates'][0]['handle']
    else:
        assert 'MUSIC_PLAYLIST_HIDDEN_DEPENDENCY' in json.dumps(found), found
        assert not any(uri.endswith('getPropertyInfo') and args.get('property') == 'IsLoopingInfinite'
            for uri, args, _ in task.calls)
    assert task.writes == []


def test_playlist_omitted_empty_children_uses_independent_relationship_query(tmp_path):
    task = MusicPlaylistTask(tmp_path)
    project = task.project_rows
    def native_rows(rows, options):
        result = project(rows, options)
        for row in result:
            if row.get('children') == []:
                del row['children']
        return result
    task.project_rows = native_rows
    task.declare()
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert any(args.get('transform') for uri, args, _ in task.calls if uri.endswith('object.get'))
    assert len(task.writes) == 1


def test_playlist_replacement_checks_each_missing_old_guid_independently(tmp_path):
    from waapi import WaapiRequestFailed
    from autobahn.wamp.exception import ApplicationError
    task = MusicPlaylistTask(tmp_path)
    old_child = '{DDDDDDDD-1111-1111-1111-111111111111}'
    task.objects[OLD]['children'] = [{'id': old_child}]
    task.objects[old_child] = {**deepcopy(task.objects[OLD]), 'id': old_child,
        'parent': {'id': OLD}, 'owner': None, 'children': [], '@PlaylistItemType': 1, '@Segment': {'id': A}}
    original = task.call
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and any(guid not in task.objects for guid in args.get('from', {}).get('id', [])):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            raise WaapiRequestFailed(ApplicationError('ak.wwise.query.unknown_object',
                message='from id object is unknown', details={'procedureUri': uri}))
        result = original(uri, args, options)
        if uri.endswith('object.set'):
            del task.objects[old_child]
        return result
    task.call = call
    task.declare()
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    for guid in (OLD, old_child):
        assert any(args.get('from') == {'id': [guid]} for uri, args, _ in task.calls if uri.endswith('object.get'))
    assert len(task.writes) == 1


def test_playlist_null_root_reference_allows_first_tree(tmp_path):
    task = MusicPlaylistTask(tmp_path).declare()
    task.objects[FIRST]['@PlaylistRoot'] = {'id': '{00000000-0000-0000-0000-000000000000}'}
    del task.objects[OLD]
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, verified
    assert len(task.writes) == 1


@pytest.mark.parametrize('fault', ('reordered-readback', 'reordered-result', 'wrong-owner', 'wrong-class', 'retained-old-root', 'changed-segment'))
def test_playlist_result_or_independent_state_fault_fails_verification_without_retry(tmp_path, fault):
    task = MusicPlaylistTask(tmp_path).declare()
    tx, shown = task.preview()
    task.fault = fault
    code, verified = task.finish(tx, shown)
    assert code == 2 and verified.get('verified') is False, json.dumps(verified)
    assert len(task.writes) == 1
    code, rejected = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1, rejected


@pytest.mark.parametrize('version', ('2023.1', '2024.1', '2025.1'))
def test_source_supported_versions_compile_the_same_closed_playlist_tree(tmp_path, version):
    task = MusicPlaylistTask(tmp_path, version).declare()
    tx, shown = task.preview()
    prepared = shown['artifact']['prepared_operation']
    node = prepared['dispatch']['args']['objects'][0]['@PlaylistRoot']
    assert node == {'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': 0, '@PlayMode': 0,
        'children': [{'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': 1, '@Segment': A},
            {'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': 0, '@PlayMode': 0,
                'children': [{'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': 1, '@Segment': B},
                    {'type': 'MusicPlaylistItem', 'name': '', '@PlaylistItemType': 1, '@Weight': 25, '@Segment': A}]}]}
    assert prepared['pre_state']['music_playlists'][0]['authority']['version'] == version
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True, json.dumps(verified)


@pytest.mark.parametrize('fault', ('old-tree', 'segment', 'metadata', 'class', 'config'))
def test_playlist_immutable_preview_blocks_drift_before_write(tmp_path, fault):
    task = MusicPlaylistTask(tmp_path).declare()
    tx, shown = task.preview()
    if fault == 'old-tree':
        task.objects[OLD]['@PlayMode'] = 2
    elif fault == 'segment':
        task.objects[A]['notes'] = 'Changed after preview'
    elif fault == 'metadata':
        task.metadata['Weight']['restriction']['max'] = 80
    elif fault == 'class':
        task.types[1]['classId'] = 2359313
    else:
        config = json.loads((tmp_path / 'config.json').read_text())
        config['waapi_port'] = 31338
        (tmp_path / 'config.json').write_text(json.dumps(config))
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    if fault != 'config':
        assert code == 0, confirmed
        code, rejected = task.run('execute', tx)
    else:
        rejected = confirmed
    assert code == 2 and task.writes == [], json.dumps(rejected)


def test_playlist_constructor_older_version_is_a_scoped_boundary(tmp_path):
    task = MusicPlaylistTask(tmp_path, '2022.1')
    owner = task.bind(FIRST)
    code, rejected = task.step('draft-declare-existing', '--declaration-id', 'playlist', '--object-handle', owner,
        '--field', 'music_playlist', '{}')
    assert code == 2 and rejected['error_code'] == 'MUSIC_PLAYLIST_VERSION_BOUNDARY', rejected
    assert task.writes == []


@pytest.mark.parametrize('fault', ('owner', 'segment', 'raw-node', 'raw-reference', 'depth', 'count'))
def test_playlist_closed_declaration_rejects_wrong_roles_raw_fields_and_oversized_trees(tmp_path, fault):
    task = MusicPlaylistTask(tmp_path)
    if fault == 'owner':
        task.objects[FIRST]['type'] = 'MusicSegment'
        task.objects[FIRST]['classId'] = 1769488
    if fault == 'segment':
        task.objects[A]['type'] = 'MusicPlaylistContainer'
        task.objects[A]['classId'] = 2228240
    if fault in ('owner', 'segment'):
        with pytest.raises(AssertionError, match='MUSIC_PLAYLIST_(OWNER|SEGMENT)_REQUIRED'):
            task.declare()
    else:
        task.declare()
        payload = deepcopy(task.payload)
        if fault == 'raw-node':
            payload['entries'][0]['type'] = 'MusicPlaylistItem'
        elif fault == 'raw-reference':
            payload['entries'][0]['@Segment'] = A
        elif fault == 'depth':
            for _ in range(9):
                payload['entries'] = [{'kind': 'group', 'entries': payload['entries']}]
        else:
            payload['entries'] = [payload['entries'][0]] * 64
        code, rejected = task.step('draft-declare-existing', '--declaration-id', 'playlist', '--object-handle', task.bind(FIRST),
            '--field', 'music_playlist', json.dumps(payload))
        assert code == 2, rejected
    assert task.writes == []


def test_playlist_source_version_drift_blocks_persisted_execution(monkeypatch, tmp_path):
    import shutil
    from wwise_waapi import music_playlist
    task = MusicPlaylistTask(tmp_path).declare()
    tx, shown = task.preview()
    replacement = tmp_path / 'tampered-package'
    source = music_playlist._ROOT
    for relative in ('resources/metadata/2025.1/music-playlist-construction.json',
            'resources/manifest/2025.1/schemas.json'):
        target = replacement / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    shutil.copytree(source / 'references/semantic/2025.1/music-playlist-sources',
        replacement / 'references/semantic/2025.1/music-playlist-sources')
    metadata_file = replacement / 'resources/metadata/2025.1/music-playlist-construction.json'
    value = json.loads(metadata_file.read_text())
    value['version'] = '2024.1'
    metadata_file.write_text(json.dumps(value))
    monkeypatch.setattr(music_playlist, '_ROOT', replacement)
    code, confirmed = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    assert code == 0, confirmed
    code, rejected = task.run('execute', tx)
    assert code == 2 and task.writes == [], rejected


def test_playlist_source_class_enum_drift_is_rejected_before_preview(tmp_path):
    task = MusicPlaylistTask(tmp_path).declare()
    task.metadata['PlaylistItemType']['restriction']['values'][1]['value'] = 7
    code, rejected = task.step('draft-check')
    assert code == 2 and rejected['error_code'] == 'INVALID_METADATA' and task.writes == [], rejected

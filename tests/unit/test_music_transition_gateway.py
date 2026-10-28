"""Source-backed owned TransitionRoot construction through persisted Gateway state.

Fake-host program proof; children membership never establishes rule priority.
"""
from copy import deepcopy
import json
import pytest

from tests.unit.test_music_playlist_gateway import MusicPlaylistTask, FIRST, SECOND, OLD, A

CLASS = 2424848
EXISTING = '{DDDDDDDD-1111-1111-1111-111111111111}'

class TransitionTask(MusicPlaylistTask):
    def __init__(self, path, version='2025.1', owner='MusicSwitchContainer', mode='replace-entire-root'):
        super().__init__(path, version)
        self.mode = mode
        self.types = [{'name': owner, 'classId': 2293776 if owner == 'MusicSwitchContainer' else 2228240, 'type': 'WObject'},
            {'name': 'MusicTransition', 'classId': CLASS, 'type': 'WObject'},
            {'name': 'MusicSegment', 'classId': 1769488, 'type': 'WObject'},
            {'name': 'WorkUnit', 'classId': 1638416, 'type': 'WObject'}]
        self.objects[FIRST].update(type=owner, classId=self.types[0]['classId'])
        del self.objects[FIRST]['@PlaylistRoot']
        self.objects[FIRST]['@TransitionRoot'] = {'id': OLD}
        self.objects[OLD] = {'id': OLD, 'name': 'Root', 'type': 'MusicTransition', 'classId': CLASS,
            'path': r'\opaque-root', 'owner': {'id': FIRST}, 'parent': None, 'notes': '',
            '@IsFolder': True, 'children': []}
        self.objects[OLD]['children'] = [{'id': EXISTING}]
        self.objects[EXISTING] = {**deepcopy(self.objects[OLD]), 'id': EXISTING, 'name': 'Transition',
            'owner': None, 'parent': {'id': OLD}, '@IsFolder': False, 'children': [],
            '@SourceContextType': 1, 'notes': 'Keep existing rule'}
        self.metadata = {
            'TransitionRoot': {'name': 'TransitionRoot', 'type': 'Reference',
                'restriction': {'type': 'reference', 'restrictions': [{'type': ['MusicTransition']}, 'notNull']}},
            'IsFolder': {'name': 'IsFolder', 'type': 'bool', 'default': False},
            'SourceContextType': {'name': 'SourceContextType', 'type': 'int16', 'default': 0,
                'restriction': {'type': 'enum', 'values': [{'value': 0, 'displayName': 'Any'}, {'value': 1, 'displayName': 'Nothing'}, {'value': 2, 'displayName': 'Object'}]}},
            'SourceContextObject': {'name': 'SourceContextObject', 'type': 'Reference',
                'restriction': {'type': 'reference', 'restrictions': [{'type': ['MusicSegment', 'MusicPlaylistContainer', 'MusicSwitchContainer', 'Folder']}]}},
        }

    def call(self, uri, args=None, options=None):
        if uri.endswith('object.set'):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.writes.append(deepcopy(args))
            item, = args['objects']
            append = self.mode == 'append-rules'
            assert set(item) == ({'object', 'children', 'onNameConflict'} if append else {'object', 'listMode', '@TransitionRoot', 'onNameConflict'})
            assert item['onNameConflict'] == args['onNameConflict'] == 'rename'
            assert args['listMode'] == ('append' if append else 'replaceAll')
            assert item['object'] == (OLD if append else FIRST)
            if not append: assert item['listMode'] == 'replaceAll'
            def create(node, parent, root=False):
                self.next_id += 1
                guid = '{00000000-0000-0000-0000-%012d}' % self.next_id
                assert node['type'] == 'MusicTransition' and node['name'] == ('Root' if root else 'Transition')
                children = [create(child, guid) for child in node.get('children', [])]
                row = {'id': guid, 'name': node['name'], 'type': 'MusicTransition', 'classId': CLASS,
                    'path': '\\opaque-' + str(self.next_id), 'notes': '', 'parent': None if root else {'id': parent},
                    'owner': {'id': parent} if root else None, 'children': [{'id': child['id']} for child in children],
                    **{key: deepcopy(value) for key, value in node.items() if key.startswith('@')}}
                if '@SourceContextObject' in row:
                    row['@SourceContextObject'] = {'id': row['@SourceContextObject']}
                self.objects[guid] = row
                return {'id': guid, 'name': node['name'], 'children': children}
            if append:
                children = [create(node, OLD) for node in item['children']]
                self.objects[OLD]['children'].extend({'id': node['id']} for node in children)
                root = {'id': OLD, 'name': self.objects[OLD]['name'], 'children': children}
            else:
                root = create(item['@TransitionRoot'], FIRST, True)
                self.objects[FIRST]['@TransitionRoot'] = {'id': root['id']}
                self.objects.pop(OLD)
                if self.fault != 'retained-old-rule': self.objects.pop(EXISTING)
            if self.fault == 'changed-old-rule': self.objects[EXISTING]['notes'] = 'Changed existing rule'
            if self.fault == 'extra-rule':
                extra = create({'type': 'MusicTransition', 'name': 'Transition', '@IsFolder': False}, root['id'])
                self.objects[root['id']]['children'].append({'id': extra['id']})
            if self.fault == 'wrong-owner': self.objects[root['id']]['owner'] = {'id': SECOND}
            if self.fault == 'wrong-class': self.objects[root['children'][0]['id']]['classId'] = 1769488
            if self.fault == 'missing-result': root['children'][0].pop('id')
            if self.fault == 'unrelated': self.objects[A]['notes'] = 'Changed'
            if self.fault == 'wrong-value': self.objects[root['children'][0]['id']]['@SourceContextType'] = 1
            if self.fault == 'result-order':
                root['children'].reverse()
                self.objects[root['id']]['children'].reverse()
            return {'objects': [root] if append else [{'id': FIRST, 'name': self.objects[FIRST]['name'], '@TransitionRoot': root}]}
        return super().call(uri, args, options)

    def declare(self):
        owner, segment = self.bind(FIRST), self.bind(A)
        kind = self.discover_kind('MusicTransition')
        root = self.discover(owner, 'TransitionRoot')
        values = {}
        for name, value in [('SourceContextType', 2), ('SourceContextObject', segment)]:
            code, found = self.step('draft-discover-fields', '--type-handle', kind, '--meaning', name)
            assert code == 0, found
            values[found['meaning_results'][0]['candidates'][0]['handle']] = value
        self.payload = {'kind_handle': kind, 'root_field_handle': root, 'mode': self.mode,
            'entries': [{'field_values': values}, {'field_values': {}}]}
        code, result = self.step('draft-declare-existing', '--declaration-id', 'transitions', '--object-handle', owner,
            '--field', 'music_transitions', json.dumps(self.payload))
        assert code == 0, result
        return self

@pytest.mark.parametrize('version,owner', [('2023.1', 'MusicPlaylistContainer'), ('2025.1', 'MusicSwitchContainer')])
def test_transition_root_replacement_is_reviewable_and_verified_once(tmp_path, version, owner):
    task = TransitionTask(tmp_path, version, owner).declare()
    preserved = deepcopy(task.objects[A])
    tx, shown = task.preview()
    code, compact = task.run('transaction-show', tx, '--summary-only')
    assert code == 0, compact
    notice, = compact['preview_summary']['music_transition_replacements']
    assert notice['intent'] == 'replace_entire_transition_root_and_rules'
    assert notice['old_root_id'] == OLD and notice['removed_item_count'] == 2
    assert notice['replacement_item_count'] == 3 and 'priority_not_verified' in notice['verification_scope']
    assert task.writes == []
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, json.dumps(result)
    assert task.objects[A] == preserved and len(task.writes) == 1
    code, result = task.run('execute', tx)
    assert code == 2 and len(task.writes) == 1

@pytest.mark.parametrize('mode,fault', [
    ('replace-entire-root', 'wrong-owner'), ('replace-entire-root', 'wrong-class'),
    ('replace-entire-root', 'missing-result'), ('replace-entire-root', 'unrelated'),
    ('replace-entire-root', 'wrong-value'), ('replace-entire-root', 'retained-old-rule'),
    ('append-rules', 'changed-old-rule'), ('append-rules', 'extra-rule')])
def test_transition_independent_result_faults_fail_without_retry(tmp_path, mode, fault):
    task = TransitionTask(tmp_path, mode=mode).declare()
    tx, shown = task.preview()
    task.fault = fault
    code, result = task.finish(tx, shown)
    assert code == 2 and result['verified'] is False, json.dumps(result)
    assert len(task.writes) == 1


def test_append_transition_rules_preserves_root_and_every_existing_rule(tmp_path):
    task = TransitionTask(tmp_path, mode='append-rules').declare()
    existing = '{DDDDDDDD-1111-1111-1111-111111111111}'
    task.objects[OLD]['children'] = [{'id': existing}]
    task.objects[existing] = {**deepcopy(task.objects[OLD]), 'id': existing, 'name': 'Transition',
        'owner': None, 'parent': {'id': OLD}, '@IsFolder': False, 'children': [],
        '@SourceContextType': 1, 'notes': 'Keep existing rule'}
    preserved = deepcopy(task.objects[existing])
    tx, shown = task.preview()
    code, compact = task.run('transaction-show', tx, '--summary-only')
    assert code == 0, compact
    notice, = compact['preview_summary']['music_transition_replacements']
    assert notice['intent'] == 'append_rules_preserve_existing_root_and_rules'
    assert notice['removed_item_count'] == 0 and notice['preserved_item_count'] == 2
    assert notice['added_rule_count'] == 2
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, json.dumps(result)
    assert task.objects[existing] == preserved
    assert task.objects[FIRST]['@TransitionRoot'] == {'id': OLD}
    assert len(task.objects[OLD]['children']) == 3
    assert task.writes[0]['objects'][0]['object'] == OLD
    assert len(task.writes) == 1


def test_rule_membership_and_field_verification_does_not_treat_result_order_as_priority(tmp_path):
    task = TransitionTask(tmp_path, mode='append-rules').declare()
    tx, shown = task.preview()
    task.fault = 'result-order'
    code, result = task.finish(tx, shown)
    assert code == 0 and result['verified'] is True, json.dumps(result)
    assert len(task.writes) == 1


@pytest.mark.parametrize('fault', ['root', 'metadata', 'config', 'source'])
def test_transition_preview_rejects_drift_without_dispatch(tmp_path, monkeypatch, fault):
    task = TransitionTask(tmp_path, mode='append-rules').declare()
    tx, shown = task.preview()
    if fault == 'root': task.objects[OLD]['notes'] = 'Drift'
    elif fault == 'metadata': task.metadata['SourceContextType']['default'] = 1
    elif fault == 'config':
        config = json.loads((tmp_path / 'config.json').read_text())
        config['waapi_port'] = 31338
        (tmp_path / 'config.json').write_text(json.dumps(config))
    else:
        from wwise_waapi import music_transitions
        path = tmp_path / 'changed-package'
        monkeypatch.setattr(music_transitions, 'ROOT', path)
    code, result = task.run('confirm', tx, '--confirmation-token', shown['confirmation']['token'])
    if fault != 'config':
        assert code == 0, result
        code, result = task.run('execute', tx)
    assert code == 2 and task.writes == [], json.dumps(result)


@pytest.mark.parametrize('fault', ['root-handle', 'kind', 'raw-field', 'folder-field', 'count', 'implicit-replacement'])
def test_transition_declaration_rejects_unbound_or_uncontrolled_construction(tmp_path, fault):
    task = TransitionTask(tmp_path).declare()
    payload = deepcopy(task.payload)
    if fault == 'root-handle': payload['root_field_handle'] = task.discover(task.bind(A), 'TransitionRoot')
    elif fault == 'kind': payload['kind_handle'] = task.discover_kind('MusicSegment')
    elif fault == 'raw-field': payload['entries'][0]['@SourceContextObject'] = A
    elif fault == 'folder-field':
        code, found = task.step('draft-discover-fields', '--type-handle', payload['kind_handle'], '--meaning', 'IsFolder')
        assert code == 0, found
        payload['entries'][0]['field_values'][found['meaning_results'][0]['candidates'][0]['handle']] = True
    elif fault == 'count': payload['entries'] = payload['entries'] * 32
    else: payload.pop('mode')
    code, result = task.step('draft-revise-declaration', '--declaration-id', 'transitions',
        '--field', 'music_transitions', json.dumps(payload))
    expected = {'root-handle': 'FIELD_HANDLE_SCOPE_MISMATCH', 'kind': 'MUSIC_TRANSITION_TYPE_REQUIRED',
        'raw-field': 'MUSIC_TRANSITION_DECLARATION_INVALID', 'folder-field': 'FIELD_HANDLE_SCOPE_MISMATCH',
        'count': 'MUSIC_TRANSITION_TREE_LIMIT', 'implicit-replacement': 'MUSIC_TRANSITION_DECLARATION_INVALID'}
    assert code == 2 and result['error_code'] == expected[fault] and task.writes == [], result


def test_transition_schema_and_older_version_limit_do_not_claim_native_absence(tmp_path):
    from tests.unit.test_object_graph_business_gateway import gateway
    for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'):
        code, schema = gateway.execute_gateway(['--version', version, 'operation-schema', 'object.set'],
            env={'WAAPI_SKILL_CONFIG_PATH': str(tmp_path / 'absent.json')})
        assert code == 0, schema
        if version == '2021.1':
            # object.set itself is absent from this pinned native lane.
            assert 'music_transitions' not in json.dumps(schema)
            continue
        assert 'append-rules' in json.dumps(schema) and 'replace-entire-root' in json.dumps(schema)
        assert 'older_constructor_roles_remain_separately_assigned_not_native_absence' in json.dumps(schema)
    task = TransitionTask(tmp_path, '2022.1')
    owner = task.bind(FIRST)
    code, result = task.step('draft-declare-existing', '--declaration-id', 'transitions', '--object-handle', owner,
        '--field', 'music_transitions', '{}')
    assert code == 2 and result['error_code'] == 'MUSIC_TRANSITION_VERSION_BOUNDARY', result
    assert task.writes == []


@pytest.mark.parametrize('choose_prerequisite', [True, False])
def test_transition_new_rule_uses_existing_condition_default_validator(tmp_path, choose_prerequisite):
    task = TransitionTask(tmp_path, mode='append-rules')
    task.metadata['ExitSourceAt'] = {'name': 'ExitSourceAt', 'type': 'int16', 'default': 7,
        'restriction': {'type': 'enum', 'values': [{'value': value} for value in (0, 1, 2, 3, 4, 5, 7, 8)]}}
    task.metadata['ExitSourceCustomCueMatchName'] = {'name': 'ExitSourceCustomCueMatchName', 'type': 'string', 'default': '',
        'dependencies': [{'type': 'property', 'action': 'Enable', 'context': 'Self', 'property': 'ExitSourceAt',
            'conditions': [{'restriction': {'type': 'enum', 'values': [{'value': 4}, {'value': 5}]}}]}]}
    task.declare()
    values = {}
    for name, value in [('ExitSourceCustomCueMatchName', 'Outro'), *([('ExitSourceAt', 5)] if choose_prerequisite else [])]:
        code, found = task.step('draft-discover-fields', '--type-handle', task.payload['kind_handle'], '--meaning', name)
        assert code == 0, found
        values[found['meaning_results'][0]['candidates'][0]['handle']] = value
    task.payload['entries'][0]['field_values'].update(values)
    code, result = task.step('draft-revise-declaration', '--declaration-id', 'transitions',
        '--field', 'music_transitions', json.dumps(task.payload))
    assert code == 0, result
    if choose_prerequisite:
        tx, shown = task.preview()
        code, result = task.finish(tx, shown)
        assert code == 0 and result['verified'] is True, result
        assert len(task.writes) == 1
    else:
        code, result = task.step('draft-check')
        assert code == 2 and 'REFERENCE_ACTIVATION_REQUIRED' in json.dumps(result), result
        assert task.writes == []

"""The maintainer diagnostic owns nine discriminators and always closes its host."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tests.destructive.support.object_constructor_collision import run_diagnostic, selected_profiles


def guid(number):
    return '{00000000-0000-0000-0000-%012d}' % number


class FakeActor:
    def __init__(self, *, fail=False, close_ok=True, wrong_seed_language=False):
        self.fail, self.close_ok = fail, close_ok
        self.wrong_seed_language = wrong_seed_language
        self.calls, self.objects, self.writes = [], {}, []
        self.closed = False
        self.fully_closed = False
        self.types = [{'name': name, 'classId': value, 'type': kind} for name, value, kind in
            [('Action', 327696, 'WObject'), ('Event', 262160, 'WObject'),
             ('Sound', 65552, 'WObject'), ('EffectSlot', 5505040, 'Inner'),
             ('Wwise Tone Generator', 6684674, 'Source')]]
        for index, category in enumerate(('Events', 'Containers'), 1):
            self.objects[guid(index)] = {'id': guid(index), 'name': 'Default Work Unit',
                'path': '\\' + category + '\\Default Work Unit', 'type': 'WorkUnit', 'classId': 196624}

    def __call__(self, uri, args, options):
        self.calls.append({'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options)})
        if self.fail:
            raise RuntimeError('transport indeterminate')
        if uri.endswith('getInfo'):
            return {'isCommandLine': True, 'version': {'displayName': '2025.1.7', 'year': 2025, 'major': 1, 'minor': 7, 'build': 9143}}
        if uri.endswith('getProjectInfo'):
            return {'languages': [{'id': guid(91), 'name': 'English(US)', 'shortId': 1},
                                  {'id': guid(92), 'name': 'Japanese', 'shortId': 2}]}
        if uri.endswith('getTypes'):
            return {'return': self.types}
        if uri.endswith('getPropertyInfo'):
            if args['property'] == 'ActionType':
                return {'name': 'ActionType', 'restriction': {'type': 'enum', 'values': [{'displayName': '/Play', 'value': 17}]}}
            return {'name': args['property'], 'restriction': {'type': 'range', 'min': 20, 'max': 20000}}
        if uri.endswith('object.get'):
            source = args['from']
            rows = [row for row in self.objects.values() if row.get('path') in source.get('path', []) or row['id'] in source.get('id', [])]
            if args.get('transform'):
                rows = [row for row in self.objects.values() if row.get('parent', {}).get('id') in {item['id'] for item in rows}]
            return {'return': [{key: deepcopy(row[key]) for key in options['return'] if key in row} for row in rows]}
        if uri.endswith('object.create'):
            self.writes.append((uri, deepcopy(args)))
            return self.add(args, args['parent'])
        if uri.endswith('object.set'):
            self.writes.append((uri, deepcopy(args)))
            results = []
            for root in args['objects']:
                parent = self.objects[root['object']]
                result = {'id': parent['id'], 'name': parent['name']}
                for key in ('children', '@Effects'):
                    if key in root:
                        result[key] = [self.add(node, parent['id'], owned=key == '@Effects') for node in root[key]]
                results.append(result)
            return {'objects': results}
        raise AssertionError(uri)

    def add(self, node, parent, *, owned=False):
        identity = guid(100 + len(self.objects))
        selected = next((row for row in self.types if row['name'] == node['type']), None)
        row = {'id': identity, 'name': node['name'], 'classId': node.get('classId', selected['classId'] if selected else 0),
            'type': 'SourcePlugin' if node['type'] == 'Source' else 'EffectSlot' if owned else node['type'],
            'path': self.objects[parent]['path'] + '\\' + (node['name'] or identity),
            'owner' if owned else 'parent': {'id': parent}, 'notes': node.get('notes', '')}
        row.update({key: deepcopy(value) for key, value in node.items() if key.startswith('@') and key != '@Effects'})
        if owned and row.get('@Effect') is None:
            row['@Effect'] = {'id': '{00000000-0000-0000-0000-000000000000}'}
        if node.get('language'):
            row['audioSource:language'] = {'name': 'Japanese' if self.wrong_seed_language else node['language']}
            row['@WaveType'] = 0
        self.objects[identity] = row
        for key in ('children', '@Effects'):
            if key in node:
                members = [self.add(child, identity, owned=key == '@Effects') for child in node[key]]
                if key == '@Effects': row[key] = members
        if owned:
            self.objects[parent].setdefault('@Effects', []).append({'id': identity})
        return {'id': identity, 'name': row['name']}

    def close(self):
        self.closed = True
        self.fully_closed = self.close_ok
        return self.close_ok


class FakeLifecycle:
    def __init__(self, root):
        self.runtime = SimpleNamespace(host='127.0.0.1', port=9999, evidence_root=root)
        self.finished = []
        self.final_status = None
    def start(self): return self.runtime
    def finish(self, status, *, reason):
        self.finished.append((status, reason))
        return SimpleNamespace(final_status=self.final_status or status)


def test_diagnostic_records_nine_independent_discriminators_with_exact_membership(tmp_path):
    actor, lifecycle = FakeActor(), FakeLifecycle(tmp_path)
    evidence = run_diagnostic(lifecycle, actor_factory=lambda **_: actor)
    assert lifecycle.finished == [('PASS', '')] and actor.closed
    assert [(row['profile'], row['mode']) for row in evidence['cases']] == [
        (profile, mode) for profile in ('action', 'effect_slot', 'source') for mode in ('rename', 'merge', 'replace')]
    assert len({row['before']['owner']['id'] for row in evidence['cases']}) == 9
    assert len([args for _, args in actor.writes if args.get('onNameConflict') in {'rename', 'merge', 'replace'}]) == 9
    for row in evidence['cases']:
        assert row['before']['members'] and row['after']['members']
        assert all({'id', 'classId', 'name', 'type', 'path'} <= set(member) for member in row['before']['members'])
        assert row['schema_validation']['version'] == '2025.1'
        assert row['after']['owner']['id'] == row['before']['owner']['id']
        assert row['outcome'] == 'returned'
    source = evidence['cases'][-1]
    assert source['request']['objects'][0]['children'][0]['language'] == 'Japanese'
    assert source['before']['members'][0]['audioSource:language']['name'] == 'English(US)'
    assert evidence['public_gateway_pass'] is False and evidence['agent_semantic_pass'] is False
    assert evidence['selected_profiles'] == ['action', 'effect_slot', 'source']
    assert evidence['requested_discriminators'] == 9
    assert len(evidence['native_calls']) <= evidence['bounds']['native_calls']
    assert json.loads((tmp_path / 'object-constructor-collisions.json').read_text())['status'] == 'PASS'


@pytest.mark.parametrize('close_ok,expected', [(True, 'FAIL'), (False, 'BLOCKED')])
def test_indeterminate_call_stops_without_retry_and_still_finalizes_owned_host(tmp_path, close_ok, expected):
    actor, lifecycle = FakeActor(fail=True, close_ok=close_ok), FakeLifecycle(tmp_path)
    with pytest.raises(RuntimeError, match='transport indeterminate'):
        run_diagnostic(lifecycle, actor_factory=lambda **_: actor)
    assert actor.closed and len(actor.calls) == 1 and not actor.writes
    assert lifecycle.finished[0][0] == expected
    evidence = json.loads((tmp_path / 'object-constructor-collisions.json').read_text())
    assert evidence['status'] == expected and evidence['cases'] == []


def test_remaining_profiles_issue_only_six_discriminators_without_action_setup(tmp_path):
    actor, lifecycle = FakeActor(), FakeLifecycle(tmp_path)
    evidence = run_diagnostic(lifecycle, profiles=selected_profiles('effect_slot,source'), actor_factory=lambda **_: actor)
    assert evidence['selected_profiles'] == ['effect_slot', 'source']
    assert evidence['requested_discriminators'] == len(evidence['cases']) == 6
    assert {row['profile'] for row in evidence['cases']} == {'effect_slot', 'source'}
    assert len(actor.writes) == 12
    assert not any(row.get('args', {}).get('property') == 'ActionType' for row in actor.calls)
    assert not any(uri.endswith('object.create') for uri, _ in actor.writes)
    assert evidence['targets_before'] == evidence['targets_after'] == []
    assert evidence['cases'][0]['before']['members'][0]['@Effect'] == {'id': '{00000000-0000-0000-0000-000000000000}'}


@pytest.mark.parametrize('profiles', [(), ('source', 'source'), ('unknown',)])
def test_invalid_profile_selection_is_rejected_before_lifecycle_start(tmp_path, profiles):
    actor, lifecycle = FakeActor(), FakeLifecycle(tmp_path)
    with pytest.raises(ValueError):
        run_diagnostic(lifecycle, profiles=profiles, actor_factory=lambda **_: actor)
    assert not lifecycle.finished and not actor.calls


def test_source_discriminator_requires_exact_two_language_seed_before_its_write(tmp_path):
    actor, lifecycle = FakeActor(wrong_seed_language=True), FakeLifecycle(tmp_path)
    with pytest.raises(AssertionError):
        run_diagnostic(lifecycle, actor_factory=lambda **_: actor)
    assert len([args for _, args in actor.writes if args.get('onNameConflict') in {'rename', 'merge', 'replace'}]) == 6
    assert actor.closed and lifecycle.finished[0][0] == 'FAIL'


@pytest.mark.parametrize('shutdown_error,expected', [(False, 'PASS'), (True, 'BLOCKED')])
def test_real_lifecycle_persists_final_outcome_and_cleanup_after_collector(monkeypatch, tmp_path, shutdown_error, expected):
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle_v3
    from tests.destructive.test_object_constructor_collision_diagnostic import make_collision_lifecycle
    source, _ = _install_fakes(monkeypatch, tmp_path, shutdown_error=shutdown_error, version='2025.1')
    source.write_bytes((Path(__file__).parents[1] / '_org/2025.1/SampleProject.wproj').read_bytes())
    source_bytes, source_mtime = source.read_bytes(), source.stat().st_mtime_ns
    prepare, launch = lifecycle_v3.prepare_sample_project_sandbox, lifecycle_v3.launch_sandboxed_wwise
    copied_before_launch = {}
    def copy_project(*args, **kwargs):
        sandbox = prepare(*args, **kwargs)
        sandbox.sandbox_project.write_bytes(source.read_bytes())
        return sandbox
    def inspect_launch(sandbox, environment, **kwargs):
        language_rows = ET.parse(sandbox.sandbox_project).findall('.//LanguageList/Language')
        names = {row.get('Name') for row in language_rows}
        assert names == {'English(US)', 'Japanese', 'External', 'Mixed', 'SFX'}
        assert names - {'SFX', 'External', 'Mixed'} == {'English(US)', 'Japanese'}
        assert len({row.get('ID') for row in language_rows}) == len(language_rows)
        assert source.read_bytes() == source_bytes and source.stat().st_mtime_ns == source_mtime
        copied_before_launch['languages'] = sorted(names)
        return launch(sandbox, environment, **kwargs)
    monkeypatch.setattr(lifecycle_v3, 'prepare_sample_project_sandbox', copy_project)
    monkeypatch.setattr(lifecycle_v3, 'launch_sandboxed_wwise', inspect_launch)
    actor = FakeActor()
    root = tmp_path / 'scenario'
    lifecycle = make_collision_lifecycle(root, live_environment={'WWISE_TEST_CONFIG': 'unused'})
    if shutdown_error:
        with pytest.raises(AssertionError):
            run_diagnostic(lifecycle, profiles=('effect_slot', 'source'), actor_factory=lambda **_: actor)
    else:
        run_diagnostic(lifecycle, profiles=('effect_slot', 'source'), actor_factory=lambda **_: actor)
    evidence = json.loads((root / 'evidence/object-constructor-collisions.json').read_text())
    finalized = json.loads((root / 'evidence/lifecycle.json').read_text())
    assert evidence['status'] == finalized['final_status'] == expected
    assert evidence['collection_status'] == 'PASS' and len(evidence['cases']) == 6
    assert evidence['selected_profiles'] == ['effect_slot', 'source'] and evidence['requested_discriminators'] == 6
    assert finalized['sandbox_retained'] is shutdown_error
    assert (root / 'owned').exists() is shutdown_error
    assert copied_before_launch['languages'] == ['English(US)', 'External', 'Japanese', 'Mixed', 'SFX']
    assert source.read_bytes() == source_bytes and source.stat().st_mtime_ns == source_mtime
    assert actor.closed

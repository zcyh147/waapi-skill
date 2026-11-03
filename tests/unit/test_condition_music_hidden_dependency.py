"""Accepted hidden-controller limitation keeps source, reads and writes distinct."""

from copy import deepcopy

import hashlib

import json

from pathlib import Path

import shutil

import pytest


from tests.unit.test_conditional_reference_gateway import ScalarPropertyTask, FIRST, condition

from tests.unit.test_field_interface_closure_gateway import VERSIONS

from tests.unit.test_time_modulator_range_gateway import declare, finish

ROOT = Path(__file__).parents[2]

AUTHORITY = ('docs/plans/full-waapi-coverage/SPEC.md#'
             'user-approved-music-playlist-hidden-dependency-boundary--2026-10-28')

class MusicTask(ScalarPropertyTask):
    """Only Wwise transport is substituted; no native acceptance is claimed."""
    def __init__(self, path, version, *, exposed=False):
        super().__init__(path, version)
        self.set_object_type(FIRST, 'MusicPlaylistItem', 2359312)
        self.objects[FIRST].update(LoopCount=1, Weight=50.0)
        self.metadata = {
            'LoopCount': {'name': 'LoopCount', 'type': 'int16',
                'restriction': {'type': 'range', 'min': 0, 'max': 32767},
                'dependencies': [condition('IsLoopingInfinite', False)]},
            'Weight': {'name': 'Weight', 'type': 'Real64'},
        }
        self.enabled = exposed
        if exposed:
            self.metadata['IsLoopingInfinite'] = {'name': 'IsLoopingInfinite', 'type': 'bool'}
            self.objects[FIRST]['IsLoopingInfinite'] = False

    def call(self, uri, args=None, options=None):
        if uri.endswith('getPropertyInfo') and args['property'] not in self.metadata:
            self.calls.append((uri, deepcopy(args), options))
            return {}
        if uri.endswith('object.get') and args.get('waql') == f'from object "{FIRST}"':
            self.calls.append((uri, deepcopy(args), options))
            row = deepcopy(self.objects[FIRST])
            row['@LoopCount'] = row['LoopCount']
            return {'return': self.project_rows([row], options)}
        return super().call(uri, args, options)

@pytest.mark.parametrize('version', VERSIONS)
def test_missing_controller_preserves_public_read_and_refuses_loop_change(tmp_path, version):
    task = MusicTask(tmp_path, version)
    before = deepcopy(task.objects)
    code, read = task.run('query-object', '--exact-id', FIRST, '--include-field', 'LoopCount')
    assert code == 0, read
    assert read['agent_result'][0]['properties'] == {'LoopCount': 1}
    code, discovered = task.run('metadata', 'discover', '--exact-id', FIRST, '--meaning', 'LoopCount')
    assert code == 0, discovered
    assert discovered['agent_result']['dependency_closure_complete'] is False
    missing = discovered['agent_result']['unresolved_dependencies'][0]
    assert missing['reason'] == 'dependency-name-not-in-live-inventory'
    assert missing['dependency']['property'] == 'IsLoopingInfinite'
    declare(task, 'LoopCount', 3)
    code, checked = task.step('draft-check')
    assert code == 2, checked
    assert checked['error_code'] == 'INVALID_METADATA'
    assert checked['details']['field'] == 'LoopCount'
    assert checked['details']['controller'] == 'IsLoopingInfinite'
    assert checked['details']['reason'] == 'required_controller_metadata_unavailable'
    assert checked['details']['cause']['message'] == 'Field binding needs an exact live-discovered token.'
    assert checked['recovery']['project_write_outcome'] == 'no_project_write_in_this_invocation'
    assert task.objects == before
    assert not any(uri.endswith(('setProperty', 'setReference', 'object.set')) for uri, _, _ in task.calls)

@pytest.mark.parametrize('version', VERSIONS)
def test_exposed_supported_controller_keeps_the_normal_loop_change_path(tmp_path, version):
    task = MusicTask(tmp_path, version, exposed=True)
    before = deepcopy(task.objects[FIRST])
    declare(task, 'LoopCount', 3)
    _, _, verified, _ = finish(task)
    assert verified['verified'] is True
    assert task.objects[FIRST] == {**before, 'LoopCount': 3}

def test_other_music_fields_remain_writable_without_the_hidden_loop_controller(tmp_path):
    task = MusicTask(tmp_path, '2025.1')
    task.enabled = True  # The unrelated Weight field is independently applicable.
    before = deepcopy(task.objects[FIRST])
    declare(task, 'Weight', 75)
    finish(task)
    assert task.objects[FIRST] == {**before, 'Weight': 75}

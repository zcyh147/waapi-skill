"""Exercise the fixed collector and the real persisted ScenarioLifecycle finalizer."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from tests.unit.test_music_playlist_gateway import MusicPlaylistTask, FIRST, A, B, OLD, SECOND
from tests.destructive.support.music_playlist_diagnostic import run_diagnostic


class PlaylistActor:
    def __init__(self, root, *, fault=None):
        self.task = MusicPlaylistTask(root)
        self.task.old_snapshot = deepcopy(self.task.objects[OLD])
        old_child = '{DDDDDDDD-1111-1111-1111-111111111111}'
        self.task.objects[OLD]['children'] = [{'id': old_child}]
        self.task.objects[old_child] = {'id': old_child, 'name': '', 'type': 'MusicPlaylistItem', 'classId': 2359312,
            'path': r'\old-child', 'parent': {'id': OLD}, 'owner': None, 'notes': '', 'children': [],
            '@PlaylistItemType': 1, '@Segment': {'id': A}, '@PlayMode': 0}
        self.task.objects[FIRST]['children'] = [{'id': A}, {'id': B}]
        self.task.objects[A]['children'] = []
        self.task.objects[B]['children'] = []
        self.task.objects[SECOND]['path'] = r'\Containers\Default Work Unit'
        self.closed, self.fault, self.calls = False, fault, []

    def __call__(self, uri, args, options):
        self.calls.append((uri, deepcopy(args), deepcopy(options)))
        if self.fault == 'transport':
            raise RuntimeError('transport indeterminate')
        if uri.endswith('getInfo'):
            return {'isCommandLine': True, 'version': {'year': 2025, 'major': 1, 'minor': 7, 'build': 9143, 'displayName': '2025.1.7.9143'}}
        if uri.endswith('object.set') and args['objects'][0]['object'] == SECOND:
            return {'objects': [{'id': SECOND, 'name': 'Default Work Unit', 'children': [
                {'id': FIRST, 'name': 'GatewayPlaylist206', 'children': [{'id': A, 'name': 'SegmentA'}, {'id': B, 'name': 'SegmentB'}]}]}]}
        if uri.endswith('object.set'):
            args = deepcopy(args)
            args['objects'][0]['listMode'] = 'replaceAll'
            result = self.task.call(uri, args, options)
            for guid in list(self.task.objects):
                if guid == '{DDDDDDDD-1111-1111-1111-111111111111}':
                    del self.task.objects[guid]
            return result
        if uri.endswith('object.get') and args.get('transform'):
            parent = self.task.objects[args['from']['id'][0]]
            children = [self.task.objects[row['id']] for row in parent['children']]
            if self.fault == 'unordered-getter':
                children.reverse()
            return {'return': self.task.project_rows(children, options)}
        return self.task.call(uri, args, options)

    def close(self):
        self.closed = True
        if self.fault == 'close-error':
            raise RuntimeError('native disconnect failed')
        return True

    @property
    def fully_closed(self):
        return self.closed and self.fault != 'close-error'


@pytest.mark.parametrize('fault,expected', [(None, 'PASS'), ('unordered-getter', 'FAIL'), ('transport', 'FAIL'), ('shutdown', 'BLOCKED'), ('evidence-write', 'BLOCKED'), ('close-error', 'BLOCKED')])
def test_playlist_collector_reaches_existing_persisted_lifecycle_finalizer(monkeypatch, tmp_path, fault, expected):
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes
    from tests.destructive.test_music_playlist_diagnostic import make_playlist_lifecycle
    source, _ = _install_fakes(monkeypatch, tmp_path, shutdown_error=fault == 'shutdown', version='2025.1')
    original_bytes, original_mtime = source.read_bytes(), source.stat().st_mtime_ns
    actor_root = tmp_path / 'actor'
    actor_root.mkdir()
    actor = PlaylistActor(actor_root, fault=fault)
    root = tmp_path / 'scenario'
    lifecycle = make_playlist_lifecycle(root, live_environment={'WWISE_TEST_CONFIG': 'unused'})
    write = Path.write_bytes
    def write_evidence(path, content):
        if path == root / 'evidence/music-playlist-discriminator.json':
            assert not (root / 'evidence/lifecycle.json').exists()
            if fault == 'evidence-write':
                raise OSError('required evidence unavailable')
        return write(path, content)
    monkeypatch.setattr(Path, 'write_bytes', write_evidence)
    if fault is None:
        from tests.semantic.support import codex_heavy_project_runner_v3
        monkeypatch.setattr(codex_heavy_project_runner_v3, 'OwnedDirectWaapiCall', lambda **_: actor)
        run_diagnostic(lifecycle)
    else:
        with pytest.raises((AssertionError, OSError, RuntimeError)):
            run_diagnostic(lifecycle, actor_factory=lambda **_: actor)
    persisted = json.loads((root / 'evidence/lifecycle.json').read_text())
    assert persisted['final_status'] == expected and actor.closed
    assert source.read_bytes() == original_bytes and source.stat().st_mtime_ns == original_mtime
    if fault != 'evidence-write':
        evidence = json.loads((root / 'evidence/music-playlist-discriminator.json').read_text())
        assert evidence['status'] == 'PENDING'
        assert evidence['final_outcome'] == {'path': 'lifecycle.json', 'field': 'final_status'}
        assert len(evidence['native_calls']) <= evidence['bounds']['native_calls']
        assert evidence['public_gateway_pass'] is False and evidence['agent_semantic_pass'] is False
        if fault is None:
            assert evidence['ordered_getter_observed'] is True
            assert evidence['segments_before'] == evidence['segments_after']
            assert evidence['old_guid_lifetime']['survivors'] == []


def test_playlist_failed_start_preserves_authoritative_start_receipt(monkeypatch, tmp_path):
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle_v3
    from tests.destructive.test_music_playlist_diagnostic import make_playlist_lifecycle
    source, _ = _install_fakes(monkeypatch, tmp_path, version='2025.1')
    original, mtime = source.read_bytes(), source.stat().st_mtime_ns
    def fail_launch(sandbox, env, **kwargs):
        sandbox.metadata.process_cleanup_result = 'cleaned'
        raise RuntimeError('native launch unavailable')
    monkeypatch.setattr(lifecycle_v3, 'launch_sandboxed_wwise', fail_launch)
    lifecycle = make_playlist_lifecycle(tmp_path / 'scenario', live_environment={'WWISE_TEST_CONFIG': 'unused'})
    with pytest.raises(lifecycle_v3.ScenarioLifecycleStartError) as caught:
        run_diagnostic(lifecycle, actor_factory=lambda **_: pytest.fail('actor must not start'))
    receipt = json.loads(caught.value.evidence_path.read_text())
    assert 'native launch unavailable' in receipt['primary_error']
    assert receipt['source_hash_before'] == receipt['source_hash_after']
    assert source.read_bytes() == original and source.stat().st_mtime_ns == mtime
    assert lifecycle._lock_acquired is False

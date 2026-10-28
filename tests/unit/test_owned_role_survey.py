"""Representative fake collection reaches the existing persisted lifecycle writer."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from tests.destructive.support import owned_role_survey as survey

INSTANCE = '{11111111-1111-1111-1111-111111111111}'
RELATED = '{22222222-2222-2222-2222-222222222222}'


class SurveyActor:
    def __init__(self, *, fault=None):
        self.fault, self.closed, self.calls = fault, False, []

    def __call__(self, uri, args, options):
        self.calls.append((uri, deepcopy(args), deepcopy(options)))
        assert uri in survey.READ_ONLY_URIS
        if self.fault == 'transport':
            raise RuntimeError('owned transport failed')
        if uri == survey.INFO:
            return {'isCommandLine': True, 'sessionId': INSTANCE, 'apiVersion': 1,
                'displayName': 'Wwise', 'branch': '2025.1', 'copyright': 'Audiokinetic',
                'configuration': 'release', 'platform': 'x64', 'processId': 123,
                'processPath': 'C:\\WwiseConsole.exe',
                'directories': {key: 'C:\\Wwise' for key in ('install', 'authoring', 'bin', 'help', 'user')},
                'version': {'year': 2025, 'major': 1, 'minor': 7, 'nickname': '', 'schema': 1,
                    'build': 9142 if self.fault == 'wrong-build' else 9143, 'displayName': '2025.1.7.9143'}}
        if uri == survey.TYPES:
            return {'return': [row for row in survey.source_roster()['classes'] if row['name'] != 'MediaPoolQuery']}
        assert options == {'return': survey.FIELDS}
        if 'ofType' in args['from']:
            assert args['transform'] == [{'range': [0, 2]}]
            name = args['from']['ofType'][0]
            if name == 'MusicFade':
                from waapi import WaapiRequestFailed
                from autobahn.wamp.exception import ApplicationError
                raise WaapiRequestFailed(ApplicationError('ak.wwise.query.invalid_query', 'unqueryable exact type'))
            if name != 'Language':
                return {'return': []}
            row = {'id': INSTANCE, 'name': 'English(US)', 'type': name, 'classId': 4915216,
                'path': r'\Languages\English(US)', 'parent': {'id': RELATED}, 'owner': {'id': RELATED}}
            if self.fault == 'oversized-result':
                row['path'] = 'x' * survey.BOUNDS['bytes_per_result']
            return {'return': [row]}
        assert args == {'from': {'id': [RELATED]}}
        return {'return': [] if self.fault == 'missing-related' else [{'id': RELATED, 'name': 'Project',
            'type': 'Project', 'classId': 65552, 'path': '\\'}]}

    def close(self):
        self.closed = True
        if self.fault == 'close-error':
            raise RuntimeError('disconnect failed')
        return True

    @property
    def fully_closed(self):
        return self.closed and self.fault != 'close-error'


@pytest.mark.parametrize('fault,expected', [(None, 'PASS'), ('transport', 'FAIL'),
    ('wrong-build', 'FAIL'), ('oversized-result', 'FAIL'), ('missing-related', 'FAIL'),
    ('shutdown', 'BLOCKED'), ('evidence-write', 'BLOCKED'), ('close-error', 'BLOCKED')])
def test_survey_actual_persisted_finalizer(monkeypatch, tmp_path, fault, expected):
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes
    from tests.destructive.test_owned_role_survey import make_role_survey_lifecycle
    source, _ = _install_fakes(monkeypatch, tmp_path, shutdown_error=fault == 'shutdown', version='2025.1')
    before, mtime = source.read_bytes(), source.stat().st_mtime_ns
    actor = SurveyActor(fault=fault)
    root = tmp_path / 'scenario'
    lifecycle = make_role_survey_lifecycle(root, live_environment={'WWISE_TEST_CONFIG': 'unused'})
    original_write = Path.write_bytes
    def write(path, content):
        if path == root / 'evidence' / survey.EVIDENCE_FILE:
            assert actor.closed and not (root / 'evidence/lifecycle.json').exists()
            if fault == 'evidence-write':
                raise OSError('required survey evidence unavailable')
        return original_write(path, content)
    monkeypatch.setattr(Path, 'write_bytes', write)
    if fault is None:
        from tests.semantic.support import codex_heavy_project_runner_v3
        monkeypatch.setattr(codex_heavy_project_runner_v3, 'OwnedDirectWaapiCall', lambda **_: actor)
        survey.run_survey(lifecycle)
    else:
        with pytest.raises((AssertionError, RuntimeError, OSError)):
            survey.run_survey(lifecycle, actor_factory=lambda **_: actor)
    persisted = json.loads((root / 'evidence/lifecycle.json').read_text())
    assert persisted['final_status'] == expected and actor.closed
    assert source.read_bytes() == before and source.stat().st_mtime_ns == mtime
    assert persisted['source_hash_before'] == persisted['source_hash_after']
    assert persisted['source_mtime_before_ns'] == persisted['source_mtime_after_ns']
    if fault != 'evidence-write':
        raw = (root / 'evidence' / survey.EVIDENCE_FILE).read_bytes()
        evidence = json.loads(raw)
        assert len(raw) <= survey.BOUNDS['evidence_bytes']
        assert evidence['status'] == 'PENDING'
        assert evidence['final_outcome'] == {'path': 'lifecycle.json', 'field': 'final_status'}
        assert len(evidence['native_calls']) <= survey.BOUNDS['native_calls']
        assert {row['uri'] for row in evidence['native_calls']} <= survey.READ_ONLY_URIS
        assert evidence['constructor_proven'] is evidence['automatic_birth_proven'] is False
        if fault is None:
            findings = {row['class_name']: row for row in evidence['classes']}
            assert len(findings) == 17 and evidence['survey_completed'] is True
            assert findings['MediaPoolQuery']['finding'] == 'absent_class_in_live_getTypes'
            assert findings['MusicFade']['finding'] == 'registered_type_query_rejected'
            assert findings['MidiParameter']['finding'] == 'registered_no_instance_in_sample'
            assert findings['Language']['instance_ids'] == [INSTANCE]
            lookups = [row for row in actor.calls if 'id' in row[1].get('from', {})]
            assert len(lookups) == 1 and lookups[0][1] == {'from': {'id': [RELATED]}}
            assert len(actor.calls) == 19


def test_survey_failed_start_preserves_existing_start_receipt(monkeypatch, tmp_path):
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle_v3
    from tests.destructive.test_owned_role_survey import make_role_survey_lifecycle
    source, _ = _install_fakes(monkeypatch, tmp_path, version='2025.1')
    before, mtime = source.read_bytes(), source.stat().st_mtime_ns
    def fail_launch(sandbox, env, **kwargs):
        sandbox.metadata.process_cleanup_result = 'cleaned'
        raise RuntimeError('launch unavailable')
    monkeypatch.setattr(lifecycle_v3, 'launch_sandboxed_wwise', fail_launch)
    lifecycle = make_role_survey_lifecycle(tmp_path / 'scenario', live_environment={'WWISE_TEST_CONFIG': 'unused'})
    with pytest.raises(lifecycle_v3.ScenarioLifecycleStartError) as caught:
        survey.run_survey(lifecycle, actor_factory=lambda **_: pytest.fail('actor must not start'))
    receipt = json.loads(caught.value.evidence_path.read_text())
    assert 'launch unavailable' in receipt['primary_error']
    assert receipt['source_hash_before'] == receipt['source_hash_after']
    assert source.read_bytes() == before and source.stat().st_mtime_ns == mtime
    assert not lifecycle._lock_acquired

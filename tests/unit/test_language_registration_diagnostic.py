"""The one-shot candidate reaches the existing real persisted finalizer."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from waapi import WaapiRequestFailed

from tests.destructive.support import language_registration_diagnostic as probe
from tests.destructive.test_language_registration_diagnostic import make_language_lifecycle
from tests.unit.test_owned_role_survey import SurveyActor

PROJECT = '{11111111-1111-1111-1111-111111111111}'
OLD = '{22222222-2222-2222-2222-222222222222}'
NEW = '{33333333-3333-3333-3333-333333333333}'


class LanguageActor:
    def __init__(self, project, *, fault=None):
        self.project, self.fault, self.calls, self.closed = project, fault, [], False
        self.name, self.saved = None, False
        self._save()

    def _save(self):
        new = f'<Language Name="{self.name}" ID="{NEW}"/>' if self.name and self.fault != 'saved-missing' else ''
        default = self.name if self.name and self.fault == 'saved-default-drift' else 'English(US)'
        self.project.write_text(f'<WwiseDocument><ProjectInfo><Project Name="SampleProject" ID="{PROJECT}">'
            f'<LanguageList><Language Name="English(US)" ID="{OLD}"/>{new}</LanguageList>'
            f'<PropertyList><Property Name="DefaultLanguage" Type="string" Value="{default}"/>'
            '</PropertyList></Project></ProjectInfo></WwiseDocument>')

    def _languages(self, *, typed):
        rows = [{'id': OLD, 'name': 'English(US)'}]
        if self.name:
            rows.append({'id': NEW, 'name': self.name})
            if self.fault == 'lost-old':
                rows.pop(0)
        for index, row in enumerate(rows):
            if typed:
                row.update(type='Language', classId=4915216, path=row['name'])
            else:
                row['shortId'] = index + 1
        if typed and self.fault == 'baseline-overflow' and not self.name:
            rows *= probe.BOUNDS['language_rows'] + 1
        return rows

    def __call__(self, uri, args, options):
        self.calls.append((uri, deepcopy(args), deepcopy(options)))
        if uri == probe.INFO:
            return SurveyActor(fault='wrong-build' if self.fault == 'wrong-build' else None)(uri, args, options)
        if uri == probe.TYPES:
            return {'return': list(probe.source_pins()['classes'].values())}
        if uri == probe.PROJECT_INFO:
            path = str(self.project if self.fault != 'wrong-project' else self.project.parent / 'missing.wproj')
            return {'id': PROJECT, 'name': 'SampleProject', 'displayTitle': 'SampleProject',
                'path': path, 'isDirty': bool(self.name and not self.saved),
                'currentLanguageId': OLD, 'referenceLanguageId': OLD, 'currentPlatformId': PROJECT,
                'platforms': [], 'languages': self._languages(typed=False),
                'directories': {key: str(self.project.parent) for key in
                    ('root', 'cache', 'originals', 'soundBankOutputRoot', 'commands', 'properties')},
                'defaultConversion': {'id': PROJECT, 'name': 'Default Conversion'}}
        if uri == probe.CREATE:
            assert set(args) == {'parent', 'type', 'name', 'onNameConflict', 'autoAddToSourceControl'}
            assert args['parent'] == PROJECT and args['type'] == 'Language'
            assert args['onNameConflict'] == 'fail' and args['autoAddToSourceControl'] is False
            if self.fault == 'native-rejection':
                from waapi import WaapiRequestFailed
                from autobahn.wamp.exception import ApplicationError
                raise WaapiRequestFailed(ApplicationError('ak.wwise.core.object.create.failed', 'candidate rejected'))
            self.name = args['name']
            if self.fault == 'ambiguous-create':
                raise RuntimeError('create timed out after possible effect')
            if self.fault == 'already-saved':
                self._save()
                self.saved = True
            return {'id': NEW, 'name': self.name}
        if uri == probe.SAVE:
            assert args == {'autoCheckOutToSourceControl': False}
            self._save()
            self.saved = True
            if self.fault == 'ambiguous-save':
                raise TimeoutError('save timed out after possible effect')
            return {}
        assert uri == probe.GET
        if args.get('from', {}).get('ofType') == ['Language']:
            assert args['transform'] == [{'range': [0, probe.BOUNDS['language_rows'] + 1]}]
            return {'return': self._languages(typed=True)}
        if args.get('from', {}).get('id') == [NEW]:
            if self.fault == 'postwrite-read-timeout':
                raise TimeoutError('created identity read unavailable')
            row = {'id': NEW, 'name': self.name, 'type': 'Language', 'classId': 4915216, 'path': self.name}
            if self.fault == 'wrong-created-class':
                row['classId'] = 65552
            return {'return': [row]}
        assert args.get('from', {}).get('ofType') == ['Project'] or args.get('from', {}).get('id') == [PROJECT]
        row = {'id': PROJECT, 'name': 'SampleProject', 'type': 'Project', 'classId': 196624,
            'path': '\\', 'filePath': str(self.project), 'DefaultLanguage': 'English(US)', 'UseDefaultLanguage': True}
        if self.fault == 'missing-default':
            del row['UseDefaultLanguage']
        if self.fault == 'changed-default' and self.name:
            row['DefaultLanguage'] = self.name
        return {'return': [row]}

    def close(self):
        self.closed = True
        if self.fault == 'close-error':
            raise RuntimeError('disconnect failed')
        return True

    @property
    def fully_closed(self):
        return self.closed and self.fault != 'close-error'


@pytest.mark.parametrize('fault,expected', [(None, 'PASS'), ('already-saved', 'PASS'),
    ('wrong-build', 'FAIL'), ('wrong-project', 'FAIL'), ('baseline-overflow', 'FAIL'),
    ('missing-default', 'FAIL'), ('native-rejection', 'INDETERMINATE'), ('ambiguous-create', 'INDETERMINATE'),
    ('ambiguous-save', 'INDETERMINATE'), ('postwrite-read-timeout', 'INDETERMINATE'),
    ('saved-default-drift', 'FAIL'),
    ('wrong-created-class', 'FAIL'), ('lost-old', 'FAIL'), ('changed-default', 'FAIL'),
    ('saved-missing', 'FAIL'), ('shutdown', 'BLOCKED'), ('evidence-write', 'BLOCKED'), ('close-error', 'BLOCKED')])
def test_language_candidate_real_finalizer_and_single_dispatch(monkeypatch, tmp_path, fault, expected):
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes
    source, _ = _install_fakes(monkeypatch, tmp_path, shutdown_error=fault == 'shutdown', version='2025.1')
    before, mtime = source.read_bytes(), source.stat().st_mtime_ns
    root = tmp_path / 'scenario'
    lifecycle = make_language_lifecycle(root, live_environment={'WWISE_TEST_CONFIG': 'unused'})
    actors = []
    def factory(**_):
        actor = LanguageActor(lifecycle.runtime.sandbox.sandbox_project, fault=fault)
        actors.append(actor)
        return actor
    # Exercise the production default-factory import, without constructing a live client.
    from tests.semantic.support import codex_heavy_project_runner_v3
    monkeypatch.setattr(codex_heavy_project_runner_v3, 'OwnedDirectWaapiCall', factory)
    original_write = Path.write_bytes
    def write(path, content):
        if path == root / 'evidence' / probe.EVIDENCE_FILE:
            assert actors[0].closed and not (root / 'evidence/lifecycle.json').exists()
            if fault == 'evidence-write':
                raise OSError('required Language evidence unavailable')
        return original_write(path, content)
    monkeypatch.setattr(Path, 'write_bytes', write)
    if expected == 'PASS':
        probe.run_diagnostic(lifecycle)
    else:
        with pytest.raises((AssertionError, RuntimeError, OSError, ValueError, WaapiRequestFailed)):
            probe.run_diagnostic(lifecycle)
    actor = actors[0]
    receipt = json.loads((root / 'evidence/lifecycle.json').read_text())
    assert receipt['final_status'] == expected and actor.closed
    assert receipt['sandbox_retained'] is (expected != 'PASS')
    if expected != 'PASS':
        assert Path(receipt['quarantine_path']).exists()
    assert receipt['source_hash_before'] == receipt['source_hash_after']
    assert source.read_bytes() == before and source.stat().st_mtime_ns == mtime
    assert receipt['source_mtime_before_ns'] == receipt['source_mtime_after_ns']
    creates = [args for uri, args, _ in actor.calls if uri == probe.CREATE]
    saves = [args for uri, args, _ in actor.calls if uri == probe.SAVE]
    assert len(creates) <= 1 and len(saves) <= 1
    if fault in {'wrong-build', 'wrong-project', 'baseline-overflow', 'missing-default'}:
        assert not creates and not saves
    elif fault in {'native-rejection', 'ambiguous-create', 'postwrite-read-timeout', 'wrong-created-class', 'lost-old', 'changed-default'}:
        assert len(creates) == 1 and not saves
    elif fault in {'ambiguous-save', 'saved-default-drift'}:
        assert len(creates) == len(saves) == 1
    elif expected == 'PASS':
        assert len(creates) == 1 and len(saves) == (fault != 'already-saved')
    if fault != 'evidence-write':
        raw = (root / 'evidence' / probe.EVIDENCE_FILE).read_bytes()
        evidence = json.loads(raw)
        assert len(raw) <= probe.BOUNDS['evidence_bytes']
        assert evidence['status'] == 'PENDING' and evidence['final_outcome']['path'] == 'lifecycle.json'
        assert not evidence['public_gateway_pass'] and not evidence['agent_semantic_pass'] and not evidence['native_absence_claim']
        assert len(evidence['native_calls']) <= probe.BOUNDS['native_calls']
        assert {row['uri'] for row in evidence['native_calls']} <= probe.ALLOWED_URIS
        if expected == 'PASS':
            assert evidence['candidate_registration_observed']
            assert NEW in evidence['saved_project_after']['languages']
            assert evidence['before']['saved_project']['explicit_default_settings'] == evidence['saved_project_after']['explicit_default_settings']
        if expected == 'INDETERMINATE':
            uncertain = evidence['mutation_uncertainty']
            failed = evidence['native_calls'][uncertain['failed_call_index']]
            assert failed['error']
            mutations = [evidence['native_calls'][index] for index in uncertain['mutation_call_indices']]
            assert mutations and all(row['mutation']['attempted'] for row in mutations)
            if fault == 'ambiguous-create':
                assert failed['uri'] == probe.CREATE and failed['mutation'] == {
                    'attempted': True, 'acknowledged': False, 'result_validated': False}
            if fault == 'ambiguous-save':
                assert failed['uri'] == probe.SAVE and failed['mutation'] == {
                    'attempted': True, 'acknowledged': False, 'result_validated': False}
                assert mutations[0]['mutation'] == {'attempted': True, 'acknowledged': True, 'result_validated': True}
        if fault == 'native-rejection':
            assert evidence['native_calls'][-1]['error']['uri'] == 'ak.wwise.core.object.create.failed'
            assert evidence['native_calls'][-1]['response_kind'] == 'native_error'
        if fault == 'saved-default-drift':
            assert not evidence['candidate_registration_observed']
            assert 'Saved default-language settings changed' in evidence['error']['message']


def test_language_candidate_failed_start_keeps_existing_start_receipt(monkeypatch, tmp_path):
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes
    from tests.semantic.support import codex_scenario_lifecycle_v3 as lifecycle_v3
    source, _ = _install_fakes(monkeypatch, tmp_path, version='2025.1')
    before, mtime = source.read_bytes(), source.stat().st_mtime_ns
    def fail_launch(sandbox, env, **kwargs):
        sandbox.metadata.process_cleanup_result = 'cleaned'
        raise RuntimeError('owned launch unavailable')
    monkeypatch.setattr(lifecycle_v3, 'launch_sandboxed_wwise', fail_launch)
    lifecycle = make_language_lifecycle(tmp_path / 'scenario', live_environment={'WWISE_TEST_CONFIG': 'unused'})
    with pytest.raises(lifecycle_v3.ScenarioLifecycleStartError) as caught:
        probe.run_diagnostic(lifecycle, actor_factory=lambda **_: pytest.fail('actor must not start'))
    receipt = json.loads(caught.value.evidence_path.read_text())
    assert 'owned launch unavailable' in receipt['primary_error']
    assert receipt['source_hash_before'] == receipt['source_hash_after']
    assert source.read_bytes() == before and source.stat().st_mtime_ns == mtime
    assert not lifecycle._lock_acquired

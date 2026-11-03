"""Fake external execution; exercise default factories, conditional flow and final receipt."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from tests.destructive.support import music_fade_lifecycle as probe

FADE = '{11111111-1111-1111-1111-111111111111}'
REPO = Path(__file__).resolve().parents[2]


class ExternalWorld:
    def __init__(self, *, fault=None, birth='flag'):
        self.fault, self.birth = fault, birth
        self.value, self.closed, self.drafts, self.calls, self.executions = False, False, {}, [], []
        self.project = None

    def row(self, identity):
        names = {probe.OWNER: ('Stealth', 'MusicPlaylistContainer'), probe.ROOT: ('Root', 'MusicTransition'),
            probe.RULE: ('Transition', 'MusicTransition'), FADE: ('Source Fade-out', 'MusicFade')}
        name, kind = names[identity]
        row = {'id': identity, 'name': name, 'type': kind, 'path': 'Root\\' + name, 'classId': next(item['classId'] for item in probe.source_roster()['classes'] if item['name'] == kind) if kind in {'MusicFade', 'MusicTransition'} else 1966096}
        if identity == probe.RULE:
            row['parent'] = {'id': probe.ROOT}
        if identity == FADE:
            row['owner'] = {'id': probe.ROOT if self.fault == 'wrong-owner' else probe.RULE}
            row['parent'] = {'id': probe.OWNER}  # Deliberately not the owning rule.
        return row

    def __call__(self, uri, args, options):
        assert uri == probe.GET
        if self.fault == 'transport':
            raise RuntimeError('owned transport failed')
        return {'return': [self.row(identity) for identity in args['from']['id']]}

    def close(self):
        self.closed = True
        if self.fault == 'close-error':
            raise RuntimeError('disconnect failed')
        return True

    @property
    def fully_closed(self):
        return self.closed and self.fault != 'close-error'

    def save(self):
        if self.birth == 'none' or (self.birth == 'flag' and not self.value):
            return
        path = self.project.parent / probe.WWU
        document = ET.fromstring(path.read_bytes())
        rule = next(node for node in document.iter('MusicTransition') if node.get('ID') == probe.RULE)
        info = rule.find('TransitionInfo')
        if info.find('SourceFadeOut') is None:
            ET.SubElement(ET.SubElement(info, 'SourceFadeOut'), 'MusicFade', ID=FADE, Name='Source Fade-out')
        path.write_bytes(ET.tostring(document))

    def run(self, argv, *, environment, **kwargs):
        assert argv[1].endswith('/skills/waapi-skill/scripts/run.py') and argv[2] == 'gateway.py'
        assert str(environment['WAAPI_SKILL_CONFIG_PATH']).endswith('/owned/setup-config.json')
        command = argv[7:]
        self.calls.append(command)
        name = command[0]
        if self.fault == 'gateway-timeout' and name == 'status':
            import subprocess
            raise subprocess.TimeoutExpired(argv, 45, output='raw timeout diagnostic')
        payload = {'ok': True}
        if name in {'request-schema', 'query-schema'}:
            from tests.unit.test_waapi_gateway import waapi_gateway, gateway_env
            code, payload = waapi_gateway.execute_gateway(['--version', probe.VERSION, *command],
                env=gateway_env(self.project.parent / 'schema'),
                client_factory=lambda _: pytest.fail('schema must stay offline'))
            assert code == 0, payload
        elif name == 'status':
            payload.update(wwise={'isCommandLine': True, 'version': {'year': 2025, 'major': 1, 'minor': 7,
                'build': 9142 if self.fault == 'wrong-build' else 9143}},
                agent_result={'project': {'path': str(self.project)}})
        elif name == 'metadata':
            identity = command[command.index('--exact-id') + 1]
            names = ['TransitionRoot'] if identity == probe.OWNER else [probe.FIELD]
            if command[1] == 'list':
                payload['agent_result'] = {'fields': [{'name': n, 'selection': 'selection-' + n} for n in names],
                    'complete': True, 'total_count': len(names)}
            else:
                payload['agent_result'] = {'metadata': {'name': probe.FIELD, 'type': 'bool', 'default': False}, 'complete': True}
        elif name == 'query-object':
            if '--advanced-waql' in command:
                if self.fault == 'resolver-rejected':
                    payload.update(ok=False, error={'code': 'invalid_query', 'message': 'native query rejected'})
                else:
                    payload.update(status='ok', query_bound={'mode': 'gateway-appended-take', 'value': 2},
                        count=1, objects=[self.row(FADE)])
            else:
                identity = command[command.index('--exact-id') + 1]
                row = self.row(identity)
                row['class_id'] = row.pop('classId')
                if identity == probe.OWNER:
                    row['references'] = {'TransitionRoot': {'id': probe.ROOT}}
                if identity == probe.RULE:
                    row['properties'] = {probe.FIELD: self.value}
                payload.update(status='ok', count=1, query_bound={'mode': 'exact-object'}, objects=[row])
        elif name == 'draft-start':
            identity = 'draft-' + str(len(self.drafts))
            self.drafts[identity] = command[1]
            payload.update(draft={'draft_id': identity, 'revision': 1}, task_authority='authority')
        elif name == 'draft-bind-object':
            payload['bound_object'] = {'handle': 'object-handle'}
        elif name == 'draft-discover-fields':
            payload['meaning_results'] = [{'candidates': [{'handle': 'field-handle', 'field_kind': 'property', 'value_type': 'boolean'}]}]
        elif name in {'draft-declare-field-change', 'draft-declare-core-plan', 'draft-check'}:
            payload['draft'] = {'revision': 2}
        elif name == 'preview-from-draft':
            payload['transaction_id'] = command[1]
        elif name == 'transaction-show':
            tx = command[1]
            if self.drafts[tx] == 'object.setProperty':
                request = {'version': probe.VERSION, 'operation': 'object.setProperty', 'arguments': {
                    'object': {'kind': 'id', 'value': probe.RULE}, 'property': probe.FIELD, 'value': True}}
            else:
                request = {'version': probe.VERSION, 'operation': 'waapi.call', 'arguments': {
                    'api': 'ak.wwise.core.project.save', 'args': {'autoCheckOutToSourceControl': False}, 'options': {}}}
            if self.fault == 'wrong-preview' and self.drafts[tx] == 'object.setProperty':
                request['arguments']['property'] = 'FadeTime'
            artifact = {'request': {'contract': 'waapi-skill.operation-request/v1', **request}}
            payload.update(transaction_id=tx, state='awaiting_confirmation', artifact=artifact,
                artifact_hash=probe.canonical_digest(artifact), confirmation={'token': 'token-' + tx})
        elif name == 'confirm':
            payload['state'] = 'confirmed'
        elif name == 'execute':
            tx = command[1]
            assert tx not in self.executions
            self.executions.append(tx)
            if self.drafts[tx] == 'object.setProperty':
                self.value = True
                if self.fault == 'ambiguous-write':
                    payload.update(ok=False, error={'message': 'write outcome unknown'})
            else:
                self.save()
                if self.fault == 'ambiguous-save':
                    payload.update(ok=False, error={'message': 'save outcome unknown'})
            payload['state'] = 'executed_unverified'
        elif name == 'verify':
            prop = self.drafts[command[1]] == 'object.setProperty'
            payload.update(state='verified' if prop else 'result_schema_checked', verification={'business_state_verified': prop, 'status': 'verified' if prop else 'result_schema_checked'})
        else:
            assert name == 'config-set', command
        return SimpleNamespace(returncode=0 if payload['ok'] else 1, stdout=json.dumps(payload), stderr='')


def prepare(monkeypatch, tmp_path, *, fault=None, birth='flag'):
    from tests.semantic.test_codex_scenario_lifecycle_v3 import _install_fakes
    from tests.semantic.support import codex_scenario_lifecycle_v3 as life
    from tests.semantic.support import codex_heavy_project_runner_v3 as heavy
    from tests.semantic.support import codex_expansion_runtime as expansion
    from tests.destructive.test_owned_role_survey import make_role_survey_lifecycle
    source, _ = _install_fakes(monkeypatch, tmp_path, shutdown_error=fault == 'shutdown', version='2025.1')
    source_xml = source.parent / probe.WWU
    source_xml.parent.mkdir(parents=True)
    source_xml.write_bytes((REPO / 'tests/_org/2025.1' / probe.WWU).read_bytes())
    original_prepare = life.prepare_sample_project_sandbox
    world = ExternalWorld(fault=fault, birth=birth)
    def copy(*args, **kwargs):
        sandbox = original_prepare(*args, **kwargs)
        target = sandbox.sandbox_project.parent / probe.WWU
        target.parent.mkdir(parents=True)
        target.write_bytes((REPO / 'tests/_org/2025.1' / probe.WWU).read_bytes())
        world.project = sandbox.sandbox_project
        return sandbox
    monkeypatch.setattr(life, 'prepare_sample_project_sandbox', copy)
    monkeypatch.setattr(heavy, 'OwnedDirectWaapiCall', lambda **_: world)
    monkeypatch.setattr(expansion, 'run_owned_gateway', world.run)
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    root = tmp_path / 'scenario'
    lifecycle = make_role_survey_lifecycle(root, live_environment={'WWISE_TEST_CONFIG': 'unused'})
    return source, world, lifecycle, root


@pytest.mark.parametrize('birth,expected,count', [('default', 'default-materialized-role', 1),
    ('flag', 'flag-created-role', 3), ('none', 'no-saved-role', 3)])
def test_actual_default_factories_flow_to_persisted_lifecycle(monkeypatch, tmp_path, birth, expected, count):
    source, world, lifecycle, root = prepare(monkeypatch, tmp_path, birth=birth)
    original, mtime = source.read_bytes(), source.stat().st_mtime_ns
    result = probe.run_probe(lifecycle)
    receipt = json.loads((root / 'evidence/lifecycle.json').read_text())
    evidence = json.loads((root / 'evidence' / probe.EVIDENCE_FILE).read_text())
    assert receipt['final_status'] == 'PASS' and world.closed
    assert receipt['source_hash_before'] == receipt['source_hash_after']
    assert source.read_bytes() == original and source.stat().st_mtime_ns == mtime
    assert result['outcome'] == evidence['outcome'] == expected
    assert evidence['discriminator_completed'] and len(world.executions) == count
    assert evidence['status'] == 'PENDING' and evidence['final_outcome']['path'] == 'lifecycle.json'
    if birth != 'none':
        assert evidence['public_role_resolver']['status'] == 'resolved'
        assert evidence['independent_fade_identity']['parent']['id'] != probe.RULE
    assert sum(operation == 'object.setProperty' for operation in world.drafts.values()) == (birth != 'default')
    assert len(evidence['gateway_receipts']) < probe.LIMITS['gateway_calls']


@pytest.mark.parametrize('fault,expected', [('wrong-build', 'FAIL'), ('transport', 'FAIL'),
    ('wrong-preview', 'FAIL'), ('wrong-owner', 'FAIL'), ('ambiguous-write', 'INDETERMINATE'), ('ambiguous-save', 'INDETERMINATE'),
    ('gateway-timeout', 'FAIL'), ('shutdown', 'BLOCKED'), ('close-error', 'BLOCKED'), ('evidence-write', 'BLOCKED'), ('raw-receipt-write', 'BLOCKED')])
def test_failure_finalizers_preserve_partial_evidence_and_never_retry(monkeypatch, tmp_path, fault, expected):
    source, world, lifecycle, root = prepare(monkeypatch, tmp_path, fault=fault)
    original, mtime = source.read_bytes(), source.stat().st_mtime_ns
    original_write = Path.write_bytes
    def write(path, content):
        if (path == root / 'evidence' / probe.EVIDENCE_FILE and fault == 'evidence-write') or (
                path.parent.name == 'gateway-receipts' and fault == 'raw-receipt-write'):
            raise OSError('required evidence unavailable')
        return original_write(path, content)
    monkeypatch.setattr(Path, 'write_bytes', write)
    with pytest.raises((AssertionError, RuntimeError, OSError, subprocess.TimeoutExpired)):
        probe.run_probe(lifecycle)
    receipt = json.loads((root / 'evidence/lifecycle.json').read_text())
    assert receipt['final_status'] == expected and world.closed
    assert receipt['source_hash_before'] == receipt['source_hash_after']
    assert source.read_bytes() == original and source.stat().st_mtime_ns == mtime
    assert len(world.executions) == len(set(world.executions))
    if fault != 'evidence-write':
        evidence = json.loads((root / 'evidence' / probe.EVIDENCE_FILE).read_text())
        assert evidence['status'] == 'PENDING'
        if fault == 'gateway-timeout':
            raw_path = root / 'evidence' / evidence['gateway_receipts'][-1]['raw_receipt']
            assert json.loads(raw_path.read_text())['timeout_stdout']['excerpt'] == 'raw timeout diagnostic'
        if fault in {'ambiguous-write', 'ambiguous-save'}:
            assert evidence['outcome'] == 'indeterminate-dispatch-or-save'
            raw_path = root / 'evidence' / evidence['gateway_receipts'][-1]['raw_receipt']
            assert json.loads(raw_path.read_text())['payload']['ok'] is False
            assert len(world.executions) == (1 if fault == 'ambiguous-save' else 2)


def test_role_query_rejection_retains_allocation_separate_from_resolver(monkeypatch, tmp_path):
    _, _, lifecycle, root = prepare(monkeypatch, tmp_path, fault='resolver-rejected')
    probe.run_probe(lifecycle)
    evidence = json.loads((root / 'evidence' / probe.EVIDENCE_FILE).read_text())
    assert evidence['outcome'] == 'flag-created-role'
    assert evidence['public_role_resolver']['status'] == 'public-query-rejected'
    assert evidence['complete_fade_configuration_delivered'] is False


def test_failed_start_uses_original_lifecycle_start_receipt(monkeypatch, tmp_path):
    _, _, lifecycle, root = prepare(monkeypatch, tmp_path)
    from tests.semantic.support import codex_scenario_lifecycle_v3 as life
    def fail(sandbox, env, **kwargs):
        sandbox.metadata.process_cleanup_result = 'cleaned'
        raise RuntimeError('launch unavailable')
    monkeypatch.setattr(life, 'launch_sandboxed_wwise', fail)
    with pytest.raises(life.ScenarioLifecycleStartError) as caught:
        probe.run_probe(lifecycle, actor_factory=lambda **_: pytest.fail('actor cannot start'))
    receipt = json.loads(caught.value.evidence_path.read_text())
    assert 'launch unavailable' in receipt['primary_error']
    assert receipt['source_hash_before'] == receipt['source_hash_after']
    assert not lifecycle._lock_acquired and not (root / 'evidence' / probe.EVIDENCE_FILE).exists()


def test_exact_role_owner_name_query_passes_actual_public_compiler(tmp_path):
    from tests.unit.test_waapi_gateway import (FakeClient, gateway_env, live_info,
        set_gateway_config, waapi_gateway)
    expression = f'from type MusicFade where owner.id = "{probe.RULE}" and name = "Source Fade-out"'
    client = FakeClient({'ak.wwise.core.getInfo': live_info(year=2025),
        probe.GET: {'return': []}})
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=probe.VERSION)
    code, payload = waapi_gateway.execute_gateway(['query-object', '--advanced-waql', expression,
        '--max-results', '2', '--include', 'owner'], env=env, client_factory=lambda _: client)
    assert code == 0, payload
    assert client.calls[-1] == (probe.GET, {'waql': expression + ' take 2'},
        {'return': ['id', 'name', 'type', 'path', 'owner']})

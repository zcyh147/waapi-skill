from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tests.semantic.support.codex_music_oracle_probes import TRANSITION, TRANSITION_ROOT, xml_music_witness
from tests.semantic.support.codex_music_transition_goal import transition_xml_state, verify_transition_scalar_goal

ROOT = Path(__file__).resolve().parents[2]


def fixture(version):
    path = ROOT / 'tests/_org' / version / ('Interactive Music Hierarchy/Music.wwu' if version == '2022.1' else 'Containers/Music/Music.wwu')
    witness = xml_music_witness(path, version)
    raw = path.read_bytes()
    before = {**transition_xml_state(raw, witness), 'value': True, 'media': {'sample.wav': {'sha256': 'a' * 64}}}
    root = ET.fromstring(raw)
    target = next(node for node in root.iter('MusicTransition') if node.get('ID') == TRANSITION)
    ET.SubElement(target.find('PropertyList'), 'Property', Name='PlaySourcePostExit', Type='bool', Value='False')
    after = {**transition_xml_state(ET.tostring(root), witness), 'value': False, 'media': deepcopy(before['media'])}
    return witness, before, after, root


@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
def test_populated_transition_boolean_oracle_preserves_fifteen_rule_graph(version):
    witness, before, after, _ = fixture(version)
    assert len(before['rule_order']) == 15 and before['rule_order'][0] == TRANSITION
    assert all(verify_transition_scalar_goal(before, after, witness, default=True).values())


@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
@pytest.mark.parametrize('damage', ('wrong_value', 'wrong_field', 'sibling', 'order', 'reference', 'fade', 'media'))
def test_transition_oracle_rejects_any_delta_beyond_requested_boolean(version, damage):
    witness, before, after, root = fixture(version)
    if damage == 'wrong_value':
        after['value'] = after['saved_value'] = True
    elif damage == 'media':
        after['media']['sample.wav']['sha256'] = 'b' * 64
    else:
        target = next(node for node in root.iter('MusicTransition') if node.get('ID') == TRANSITION)
        owner = next(node for node in root.iter('MusicTransition') if node.get('ID') == TRANSITION_ROOT)
        if damage == 'wrong_field':
            target.find('PropertyList/Property[@Name="PlaySourcePostExit"]').set('Name', 'PlayDestinationPreEntry')
        elif damage == 'sibling':
            owner.findall('./ChildrenList/MusicTransition')[1].set('Name', 'Changed')
        elif damage == 'order':
            children = owner.find('ChildrenList')
            first = children[0]
            children.remove(first)
            children.append(first)
        elif damage == 'reference':
            next(root.iter('ObjectRef')).set('ID', '{11111111-1111-1111-1111-111111111111}')
        else:
            target.find('TransitionInfo/SourceFadeOut/MusicFade/PropertyList/Property[@Name="FadeTime"]').set('Value', '123')
        after.update(transition_xml_state(ET.tostring(root), witness))
    assert not all(verify_transition_scalar_goal(before, after, witness, default=True).values())


@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
def test_transition_preview_accepts_only_actual_boolean_request(version):
    from tests.semantic.support.codex_music_transition_goal import approve_transition_scalar_preview
    artifact = {'request': {'version': version, 'operation': 'object.setProperty', 'arguments':
        {'object': {'kind': 'id', 'value': TRANSITION}, 'property': 'PlaySourcePostExit', 'value': False}}}
    assert approve_transition_scalar_preview(artifact, version=version, value=False)
    for key, value in (('property', 'FadeTime'), ('value', 0), ('value', True), ('extra', True)):
        wrong = deepcopy(artifact)
        wrong['request']['arguments'][key] = value
        assert not approve_transition_scalar_preview(wrong, version=version, value=False)


@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
@pytest.mark.parametrize('wrong_preview', (False, True, 'save'))
def test_goal_uses_two_closed_once_executed_transactions_and_preserves_graph(tmp_path, monkeypatch, version, wrong_preview):
    # Import its pure transaction helper; never request its real lifecycle fixture.
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    from types import SimpleNamespace
    from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway
    from tests.semantic.support.codex_expansion_case_helpers import CaseBoundaryError
    from tests.semantic.support.codex_expansion_policy import canonical_digest
    from tests.semantic.support.codex_music_transition_goal import run_transition_scalar_goal, SAVE
    witness, before, after, _ = fixture(version)
    calls, current, drafts = [], {'value': True}, []
    def gateway(argv):
        calls.append(list(argv))
        command = argv[0]
        if command == 'request-schema':
            code, payload = waapi_gateway.execute_gateway(['--version', version, *argv], env=gateway_env(tmp_path),
                client_factory=lambda _url: pytest.fail('save schema must stay offline'))
            assert code == 0, payload
            return payload
        if command == 'draft-start':
            drafts.append(argv[1])
            return {'draft': {'draft_id': 'draft-' + str(len(drafts)), 'revision': 1}, 'task_authority': 'authority'}
        if command == 'draft-bind-object':
            assert argv[-2:] == ['--object-id', TRANSITION]
            return {'bound_object': {'handle': 'object-handle'}}
        if command == 'draft-discover-fields':
            return {'meaning_results': [{'candidates': [{'handle': 'field-handle', 'field_kind': 'property', 'value_type': 'boolean'}]}]}
        if command in {'draft-declare-field-change', 'draft-declare-core-plan', 'draft-check'}:
            return {'draft': {'revision': 2}}
        if command == 'preview-from-draft':
            return {'transaction_id': 'tx-property' if len(drafts) == 1 else 'tx-save'}
        if command == 'typed-zero-call':
            return {'transaction_id': 'tx-save'}
        if command == 'transaction-show':
            if argv[1] == 'tx-property':
                request = {'version': version, 'operation': 'object.setProperty', 'arguments': {
                    'object': {'kind': 'id', 'value': TRANSITION}, 'property': 'FadeTime' if wrong_preview is True else 'PlaySourcePostExit', 'value': False}}
            else:
                request = {'version': version, 'operation': 'waapi.call', 'arguments': {'api': SAVE,
                    'args': {} if version == '2022.1' else {'autoCheckOutToSourceControl': False}, 'options': {}}}
            if argv[1] == 'tx-save' and wrong_preview == 'save':
                request['arguments']['args'] = {'unrequested': True}
            artifact = {'request': request}
            return {'transaction_id': argv[1], 'state': 'awaiting_confirmation', 'artifact': artifact,
                'artifact_hash': canonical_digest(artifact), 'confirmation': {'token': 'token-' + argv[1]}}
        if command == 'confirm':
            assert argv[2:] == ['--confirmation-token', 'token-' + argv[1]]
            return {'state': 'confirmed'}
        if command == 'execute':
            if argv[1] == 'tx-property':
                current['value'] = False
            return {'state': 'executed_unverified'}
        if command == 'verify':
            state = 'verified' if argv[1] == 'tx-property' else 'result_schema_checked'
            return {'state': state, 'verification': {'status': state, 'business_state_verified': state == 'verified'}}
        if command == 'query-object':
            return {'status': 'ok', 'count': 1, 'query_bound': {'mode': 'exact-object'},
                'objects': [{'id': TRANSITION, 'parent': {'id': TRANSITION_ROOT}, 'properties': {'PlaySourcePostExit': current['value']}}]}
        if command == 'operation-schema':
            return {'ok': True}
        pytest.fail('unreviewed public command ' + repr(argv))
    snapshots = iter([before, before, after])
    ctx = SimpleNamespace(version=version, gateway=gateway)
    if wrong_preview is True:
        with pytest.raises(CaseBoundaryError, match='Preview'):
            run_transition_scalar_goal(ctx, witness, lambda: next(snapshots))
        assert not any(argv[0] in {'confirm', 'execute', 'verify', 'request-schema'} for argv in calls)
    elif wrong_preview == 'save':
        with pytest.raises(CaseBoundaryError, match='save Preview'):
            run_transition_scalar_goal(ctx, witness, lambda: next(snapshots))
        assert [argv[1] for argv in calls if argv[0] in {'execute', 'verify'}] == ['tx-property', 'tx-property']
    else:
        result = run_transition_scalar_goal(ctx, witness, lambda: next(snapshots))
        assert result['transaction_ids'] == ['tx-property', 'tx-save']
        assert result['scalar_maintenance_verified'] and result['complete_M04_verified'] is False
        assert all(result['assertions'].values())
        for command in ('confirm', 'execute', 'verify'):
            assert [argv[1] for argv in calls if argv[0] == command] == ['tx-property', 'tx-save']
        declaration = next(argv for argv in calls if argv[0] == 'draft-declare-field-change')
        assert declaration[-6:] == ['--object-handle', 'object-handle', '--field-handle', 'field-handle', '--business-value', 'false']


@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
def test_snapshot_ignores_public_row_order_but_retains_saved_rule_order_and_media(tmp_path, version):
    from types import SimpleNamespace
    from tests.semantic.support.codex_music_transition_goal import transition_scalar_snapshot
    witness, _, _, _ = fixture(version)
    source = ROOT / 'tests/_org' / version / ('Interactive Music Hierarchy/Music.wwu' if version == '2022.1' else 'Containers/Music/Music.wwu')
    path = tmp_path / 'Music.wwu'
    path.write_bytes(source.read_bytes())
    media = tmp_path / 'Originals/music.wav'
    media.parent.mkdir()
    media.write_bytes(b'owned-media')
    ids = [row['id'] for row in witness['transition']['rules']]
    def gateway(argv):
        if '--relationship' in argv:
            return {'status': 'ok', 'count': 15, 'query_bound': {'mode': 'take', 'value': 16},
                'objects': [{'id': identifier} for identifier in ids]}
        return {'status': 'ok', 'count': 1, 'query_bound': {'mode': 'exact-object'}, 'objects': [
            {'id': TRANSITION, 'parent': {'id': TRANSITION_ROOT}, 'properties': {'PlaySourcePostExit': True}}]}
    ctx = SimpleNamespace(project_path=tmp_path / 'SampleProject.wproj', version=version, gateway=gateway)
    first = transition_scalar_snapshot(ctx, path, witness)
    ids.reverse()
    second = transition_scalar_snapshot(ctx, path, witness)
    assert first == second
    assert first['rule_order'] == [row['id'] for row in witness['transition']['rules']]
    assert first['media']['music.wav']['sha256']


@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
@pytest.mark.parametrize('fails_before_result', (False, True))
def test_actual_maintenance_node_report_satisfies_real_category_finalizer(tmp_path, monkeypatch, version, fails_before_result):
    import json
    from types import SimpleNamespace
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    from tests.maintenance import probe_music_transition_scalar_goal as node
    from tests.destructive.support.category_evidence import append_category_evidence

    owned = tmp_path / 'project'
    relative = Path('Interactive Music Hierarchy/Music.wwu' if version == '2022.1' else 'Containers/Music/Music.wwu')
    path = owned / relative
    path.parent.mkdir(parents=True)
    path.write_bytes((ROOT / 'tests/_org' / version / relative).read_bytes())
    project = owned / 'SampleProject.wproj'
    project.write_bytes((ROOT / 'tests/_org' / version / 'SampleProject.wproj').read_bytes())
    runtime = SimpleNamespace(version=version, sandbox=SimpleNamespace(sandbox_path=owned, sandbox_project=project),
        category_results=[], raw_gateway=lambda argv: (0, {'ok': True, 'transaction_id': argv[1]}))
    def goal(ctx, _witness, _snapshot):
        ctx.gateway(['preview-from-draft', 'tx-property'])
        if fails_before_result:
            raise RuntimeError('bounded failure before goal result')
        ctx.gateway(['typed-zero-call', 'tx-save'])
        return {'status': 'PASS', 'transaction_ids': ['tx-property', 'tx-save'],
            'scalar_maintenance_verified': True, 'complete_M04_verified': False,
            'save_verifier_strength': 'result_schema_checked_plus_independent_owned_XML_readback'}
    monkeypatch.setattr(node, 'run_transition_scalar_goal', goal)
    if fails_before_result:
        with pytest.raises(RuntimeError, match='before goal result'):
            node.test_existing_transition_boolean_preserves_populated_rule_graph(runtime)
    else:
        node.test_existing_transition_boolean_preserves_populated_rule_graph(runtime)
    assert len(runtime.category_results) == 1
    report = runtime.category_results[0]
    assert report['status'] == ('FAIL' if fails_before_result else 'PASS')
    assert report['complete_M04_verified'] is False and report['agent_pass'] is False
    assert report['transaction_ids'] == (['tx-property'] if fails_before_result else ['tx-property', 'tx-save'])
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    append_category_evidence(repo_root=tmp_path, candidate='a' * 40, version=version,
        host={'display_name': 'fake-only'}, categories=runtime.category_results,
        source={'hash_before': 'same', 'hash_after': 'same'}, residual_state={'residual_processes': []})
    sealed = json.loads(target.read_text())['categories'][0]
    assert 'strong_scalar' in sealed['verifier_strength']
    assert 'saved_XML_media' in sealed['verifier_strength']
    assert 'save_result_schema_only' in sealed['verifier_strength']

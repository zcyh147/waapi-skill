"""One read-only 2021 Curve-points capability observation; no retry or setup writes."""
import copy
import json
import os
from pathlib import Path

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import workflow_sandbox_runtime, waapi_gateway
from tests.destructive.test_query_legacy_control_input import source_frame, REPO, RELATIVE, CURVE, RTPC
from tests.destructive.support.source_copy_fixture import read_file, sha, xml, _reject_symlink_chain
from wwise_waapi.canonical import canonical_sha256

pytestmark = [pytest.mark.live, pytest.mark.destructive,
    pytest.mark.skipif(os.environ.get('WWISE_VERSION') != '2021.1', reason='Selected legacy Curve representation is 2021.1')]
MAX_DISPATCHES = 4
MAX_PACKET_BYTES = 4 * 1024 * 1024


def test_exact_legacy_curve_points_capability(workflow_sandbox_runtime, monkeypatch):
    runtime = workflow_sandbox_runtime
    assert runtime.version == '2021.1'
    assert tuple(runtime.sandbox.metadata.get_info_version[key] for key in ('year','major','minor','build')) == (2021,1,14,8108)
    output = runtime.state_dir / 'query-legacy-curve-points.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_chain(output.parent, owned_input=runtime.state_dir, label='Curve observation')
    assert not output.exists() and not output.is_symlink()
    observation = {'candidate':runtime.candidate,'version':runtime.version,'read_only':True,'transaction_count':0,
        'invocation_count':0,'dispatch_count':0,'packet_bytes':0,'native_packets':[],
        'ordered_source_xy_verified':False,'business_effect_verified':False,
        'native_absence_proven':False,'interpolation_semantics_verified':False,
        'scope':'one exact legacy Curve points projection; property association and other contexts remain unresolved'}
    category = {'category':'query-legacy-curve-points','status':'FAIL','observation_path':str(output),
        'verifier_strength':'one_closed_exact_curve_native_public_ordered_xy_and_same_version_shape_postcondition'}
    runtime.category_results.append(category)
    status = 'FAIL'
    evidence_root = Path(runtime.env['WWISE_EVIDENCE_DIR'])
    packets = {}; calls = []
    original = waapi_gateway.WwiseDispatcher.dispatch

    def capture(dispatcher, api, **kwargs):
        assert observation['dispatch_count'] < MAX_DISPATCHES
        observation['dispatch_count'] += 1
        call = {'api':api, **copy.deepcopy({key:kwargs.get(key) for key in ('version','args','options')})}
        calls.append(call)
        result = original(dispatcher, api, **kwargs)
        call.update(ok=result['ok'],evidence_path=result.get('evidence_path'),result_sha256=canonical_sha256(result.get('result')))
        return result

    try:
        before = source_frame(runtime); observation['source_before'] = before
        tree = xml(read_file(runtime.sandbox.sandbox_path / RELATIVE, 4 * 1024 * 1024))
        curve, = [row for row in tree.iter('Curve') if row.get('ID') == CURVE]
        stored = curve.findall('PointList/Point')
        oracle = {'curve_id':CURVE,'owner_id':RTPC,
            'xy':[[float(row.findtext('XPos')),float(row.findtext('YPos'))] for row in stored],
            'stored_flags':[row.findtext('Flags') for row in stored],
            'numeric_comparison':{'relative_tolerance':2**-23,'absolute_tolerance':0,
                'scope':'serialized source XY versus native float32 representation only; count/order and native-public values stay exact'},
            'flags_interpretation':'uninterpreted; no interpolation decoder or mathematical claim'}
        assert oracle['xy'] == [[0.0,-5.67053],[1.0,0.0]] and oracle['stored_flags'] == ['21','53']
        observation['source_oracle'] = oracle
        argv = ['query-object','--exact-id',CURVE,'--max-results','1',
            '--include','class-id','--include','owner','--include','curve-points','--detail']
        observation.update(argv=argv,invocation_count=1,dispatch_calls=calls)
        paths_before = set(evidence_root.glob('*.json'))
        with monkeypatch.context() as patch:
            patch.setattr(waapi_gateway.WwiseDispatcher,'dispatch',capture)
            code, payload = runtime.raw_gateway(argv)
        observation.update(exit_code=code,payload=payload)
        for path in sorted(set(evidence_root.glob('*.json')) - paths_before):
            raw = read_file(path, 1024 * 1024)
            observation['packet_bytes'] += len(raw)
            assert observation['packet_bytes'] <= MAX_PACKET_BYTES
            observation['native_packets'].append({'path':str(path),'bytes':len(raw),'sha256':sha(raw)})
            packets[str(path)] = json.loads(raw)
        assert {call['evidence_path'] for call in calls} == set(packets)
        for call in calls:
            packet = packets[call['evidence_path']]
            assert packet['api'] == call['api'] == 'ak.wwise.core.object.get'
            assert call['version'] == runtime.version and packet['ok'] is call['ok']
            assert canonical_sha256(packet.get('result')) == call['result_sha256']
        assert len(calls) == 1, 'The candidate owns one value read, no alternate-token retries'
        assert calls[0]['args'] == {'waql':f'from object "{CURVE}" take 1'}
        assert calls[0]['options']['return'] == ['id','name','type','path','classId','owner','points']
        assert code == 0 and payload.get('ok') is True, payload
        assert list(payload)[-1] == 'agent_result' and isinstance(payload['agent_result'],list)
        row, = payload['agent_result']; observation['public_curve'] = row
        assert row['id'] == CURVE and row['type'] == 'Curve' and row['class_id'] == 917520 and row['owner']['id'] == RTPC
        native_row, = packets[calls[0]['evidence_path']]['result']['return']
        assert native_row['id'] == CURVE and native_row['classId'] == 917520 and native_row['owner']['id'] == RTPC
        assert 'points' in native_row and native_row['points'] is not None, 'Required points were omitted or null; no absence conclusion'
        assert row.get('curve_points') == native_row['points']
        # One float32 relative epsilon admits representation rounding of the
        # decimal fixture. Zero stays exact; this does not round native output.
        assert len(row['curve_points']) == len(oracle['xy'])
        for point, expected in zip(row['curve_points'], oracle['xy']):
            assert [point['x'],point['y']] == pytest.approx(expected, rel=2**-23, abs=0)
        observation.update(ordered_source_xy_verified=True,business_effect_verified=True)
        status = 'PASS'
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        try:
            observation['source_after'] = source_frame(runtime)
            assert observation['source_after'] == observation.get('source_before')
        except BaseException as exc:
            status = 'FAIL'
            observation.update(ordered_source_xy_verified=False,business_effect_verified=False,
                preservation_error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            body = json.dumps(observation,ensure_ascii=False,indent=2).encode()
            if len(body) > 8 * 1024 * 1024:
                status = 'FAIL'; observation.update(ordered_source_xy_verified=False,business_effect_verified=False,
                    finalization_error='Observation exceeded 8 MiB; retained without truncation')
                body = json.dumps(observation,ensure_ascii=False,indent=2).encode()
            with output.open('xb') as stream: stream.write(body)
            category.update(status=status,observation_sha256=sha(body),business_effect_verified=observation['business_effect_verified'])
            assert len(body) <= 8 * 1024 * 1024, 'Observation ceiling exceeded; no native PASS'

"""Exact 2021 fixed-accessor boundary and unchanged modern closed point outputs."""
import copy
import json
from pathlib import Path

import pytest

from tests.unit.test_object_query_result_pages import QueryTask, VERSIONS

CURVE = '{0B357DC6-5FE7-4E50-9C31-23CDE7F34307}'
RTPC = '{CE99046D-D354-422D-A7BB-F1305FF00B2F}'
POINTS = [{'x': 0.0, 'y': -5.67053, 'shape': 'Linear'}, {'x': 1.0, 'y': 0.0, 'shape': 'Linear'}]


def curve_task(tmp_path, version='2021.1'):
    task = QueryTask(tmp_path, version)
    task.row = {'id': CURVE, 'name': '', 'type': 'Curve', 'path': r'\opaque-curve',
        'classId': 917520, 'owner': {'id': RTPC}, 'points': copy.deepcopy(POINTS)}
    return task


def test_2021_fixed_points_rejection_is_disclosed_and_blocks_before_transport(tmp_path):
    task = curve_task(tmp_path)
    packet_path = Path(__file__).parents[1] / 'fixtures/query-legacy-curve-points/native-rejection-2021.original.json'
    raw = packet_path.read_bytes(); packet = json.loads(raw)
    import hashlib
    assert hashlib.sha256(raw).hexdigest() == 'f5f154606eab29977b856784fded6df949ae0f045c5d9406aab72184387f2513'
    assert packet['ok'] is False and packet['waapi_error_uri'] == 'ak.wwise.query.invalid_query'
    code, schema = task.run('query-schema', '--output', 'curve-points')
    assert code == 0, schema
    detail = schema['business_output']
    assert detail['available'] is False and detail['supported_versions'] == list(VERSIONS[1:])
    assert detail['native_accessor_rejection_proven'] is True and detail['native_absence_proven'] is False
    boundary = detail['native_boundary']
    assert boundary['scope'] == 'fixed object.get return accessor points on Curve; not all legacy Curve or RTPC reads'
    assert boundary['observation']['native_error_uri'] == packet['waapi_error_uri']
    assert boundary['observation']['native_error_details'] == packet['waapi_error_details']
    assert boundary['observation']['packet_sha256'] == hashlib.sha256(raw).hexdigest()
    assert boundary['observation']['original_verdict'] == 'FAIL'
    assert boundary['observation']['build'] == '2021.1.14.8108'
    assert boundary['source_delta']['2021']['named_points'] is False
    assert boundary['source_delta']['2022']['named_points'] is True
    assert detail['result_schema'] is None
    code, result = task.run('query-object', '--exact-id', CURVE, '--include', 'curve-points')
    assert code == 2 and result['error_code'] == 'GatewayInputError', result
    assert 'Unknown accessor points' in result['message'] and not task.calls


@pytest.mark.parametrize('version', VERSIONS[1:])
def test_modern_exact_curve_points_preserve_native_order_and_values(tmp_path, version):
    task = curve_task(tmp_path, version)
    code, result = task.run('query-object', '--exact-id', CURVE, '--max-results', '1', '--include', 'curve-points')
    assert code == 0, result
    row, = result['agent_result']
    assert row['id'] == CURVE and row['curve_points'] == POINTS
    assert list(result)[-1] == 'agent_result'
    reads = [(args, options) for uri, args, options in task.calls if uri.endswith('object.get')]
    assert reads == [({'waql': f'from object "{CURVE}" take 1'}, {'return':['id','name','type','path','points']})]


@pytest.mark.parametrize('version', ['2022.1', '2025.1'])
@pytest.mark.parametrize('value', [None, 'missing'])
def test_curve_candidate_preserves_missing_and_null_without_inventing_empty_points(tmp_path, value, version):
    task = curve_task(tmp_path, version)
    if value == 'missing': task.row.pop('points')
    else: task.row['points'] = value
    code, result = task.run('query-object', '--exact-id', CURVE, '--include', 'curve-points')
    assert code == 0, result
    row, = result['agent_result']
    if value == 'missing': assert 'curve_points' not in row and row['unavailable_fields'] == ['curve_points']
    else: assert row['curve_points'] is None


@pytest.mark.parametrize('version', VERSIONS[1:])
@pytest.mark.parametrize('fault', ['text', 'extra-field', 'missing-coordinate', 'boolean-coordinate', 'unknown-shape'])
def test_root_points_require_ordered_typed_values_and_keep_original_packet(tmp_path, version, fault):
    task = curve_task(tmp_path, version)
    if fault == 'text': task.row['points'] = 'points'
    elif fault == 'extra-field': task.row['points'][0]['unit'] = 'invented'
    elif fault == 'missing-coordinate': task.row['points'][0].pop('y')
    elif fault == 'boolean-coordinate': task.row['points'][0]['x'] = False
    else: task.row['points'][0]['shape'] = 'unknown'
    packets = tmp_path / 'native'; task.env['WWISE_EVIDENCE_DIR'] = str(packets)
    code, result = task.run('query-object', '--exact-id', CURVE, '--include', 'curve-points')
    assert code == 2 and result['error_code'] == 'RELATED_QUERY_CURVE_POINTS', result
    assert not result.get('agent_result')
    recorded = [json.loads(path.read_text()) for path in packets.glob('*.json')]
    value_packets = [packet for packet in recorded if packet['api'].endswith('object.get')]
    assert len(value_packets) == 1 and value_packets[0]['result']['return'][0]['points'] == task.row['points']


@pytest.mark.parametrize('source', [ ['--kind', 'all-sounds', '--max-results', '1'],
    ['--advanced-waql', 'from type Curve', '--max-results', '1'],
    ['--exact-id', CURVE, '--relationship', 'children', '--max-results', '1']])
def test_2021_fixed_points_boundary_also_blocks_other_query_contexts(tmp_path, source):
    task = curve_task(tmp_path)
    code, result = task.run('query-object', *source, '--include', 'curve-points')
    assert code == 2 and result['error_code'] == 'GatewayInputError', result
    assert not task.calls


def test_legacy_related_curve_scope_discloses_the_same_fixed_accessor_rejection(tmp_path):
    task = curve_task(tmp_path)
    code, result = task.run('query-schema')
    assert code == 0, result
    detail = result['related_outputs']['outputs']['curve-points']
    assert detail['available'] is False and detail['output_field'] == 'curve_points'
    assert 'Unknown accessor points' in detail['reason'] and 'other legacy Curve or RTPC reads are not excluded' in detail['reason']
    code, result = task.run('query-object', '--exact-id', CURVE, '--include-related', 'parent', 'curve-points')
    assert code == 2 and result['error_code'] == 'GatewayInputError' and not task.calls, result

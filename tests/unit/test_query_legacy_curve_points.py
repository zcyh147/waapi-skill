"""One fixed 2021 Curve-points candidate through the existing closed query seam."""
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


def test_exact_2021_curve_candidate_preserves_order_and_discloses_unproven_semantics(tmp_path):
    task = curve_task(tmp_path)
    code, result = task.run('query-object', '--exact-id', CURVE, '--max-results', '1',
        '--include', 'curve-points', '--detail')
    assert code == 0, result
    row, = result['agent_result']
    assert row['id'] == CURVE and row['curve_points'] == POINTS
    assert list(result)[-1] == 'agent_result'
    value_reads = [(args, options) for uri, args, options in task.calls if uri.endswith('object.get')]
    assert len(value_reads) == 1 and value_reads[0][0] == {'waql': f'from object "{CURVE}" take 1'}
    assert value_reads[0][1]['return'][-2:] == ['points', 'classId']
    code, schema = task.run('query-schema', '--output', 'curve-points')
    assert code == 0, schema
    detail = schema['business_output']
    assert detail['native_semantics_proven'] is False and detail['native_absence_proven'] is False
    assert detail['request_legality']['pointer'] == '/definitions/returnExpression/items/anyOf/1'
    assert detail['typed_postcondition']['uri'] == 'ak.wwise.core.object.getAttenuationCurve'
    assert detail['typed_postcondition']['semantic_equivalence_proven'] is False
    assert detail['result_schema'] is None


@pytest.mark.parametrize('value', [None, 'missing'])
def test_curve_candidate_preserves_missing_and_null_without_inventing_empty_points(tmp_path, value):
    task = curve_task(tmp_path)
    if value == 'missing': task.row.pop('points')
    else: task.row['points'] = value
    code, result = task.run('query-object', '--exact-id', CURVE, '--include', 'curve-points')
    assert code == 0, result
    row, = result['agent_result']
    if value == 'missing': assert 'curve_points' not in row and row['unavailable_fields'] == ['curve_points']
    else: assert row['curve_points'] is None


@pytest.mark.parametrize('version', VERSIONS)
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


@pytest.mark.parametrize('fault', ['class', 'boolean-class', 'type'])
def test_2021_candidate_cannot_borrow_another_native_class(tmp_path, fault):
    task = curve_task(tmp_path)
    task.row['classId' if fault != 'type' else 'type'] = {'class': 65552, 'boolean-class': True, 'type': 'Sound'}[fault]
    code, result = task.run('query-object', '--exact-id', CURVE, '--include', 'curve-points')
    assert code == 2 and result['error_code'] == 'QUERY_CURVE_POINTS_SCOPE', result


@pytest.mark.parametrize('source', [ ['--kind', 'all-sounds', '--max-results', '1'],
    ['--advanced-waql', 'from type Curve', '--max-results', '1'],
    ['--exact-id', CURVE, '--relationship', 'children', '--max-results', '1']])
def test_2021_candidate_does_not_open_unreviewed_query_contexts(tmp_path, source):
    task = curve_task(tmp_path)
    code, result = task.run('query-object', *source, '--include', 'curve-points')
    assert code == 2 and result['error_code'] == 'GatewayInputError', result
    assert not task.calls


def test_legacy_related_curve_scope_discloses_its_exact_root_alternative(tmp_path):
    task = curve_task(tmp_path)
    code, result = task.run('query-schema')
    assert code == 0, result
    detail = result['related_outputs']['outputs']['curve-points']
    assert detail['available'] is False and detail['output_field'] == 'curve_points'
    assert 'exact-ID root Curve' in detail['reason'] and 'unproven' in detail['reason']
    code, result = task.run('query-object', '--exact-id', CURVE, '--include-related', 'parent', 'curve-points')
    assert code == 2 and result['error_code'] == 'GatewayInputError' and not task.calls, result

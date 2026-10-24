"""Regression against the complete packet retained from the real r1 failure."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.destructive.support import integration_demo as demo
from tests.unit.test_integration_demo_observation import _installed

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/native-getinfo-schema-2025.1.11.9262.json'


def _reader(context, packet, expected_info):
    calls = []
    def call(argv):
        calls.append(argv)
        if argv == ['status']:
            return {'wwise': deepcopy(expected_info)}
        if argv[1] == 'ak.wwise.core.getInfo':
            return packet
        # Full documented public function-schema shape, independently of the
        # context's serialized comparison projection.
        return {'reflection_context': deepcopy(expected_info),
            'agent_result': deepcopy(demo.CapabilityCatalog().describe_for_profile(
                '2025.1', argv[1], profile='wwise-authoring-ui').schema)}
    return call, calls


def test_real_getinfo_schema_packet_retains_description_and_passes_exact_reflection(tmp_path):
    context = _installed(tmp_path)
    retained = json.loads(FIXTURE.read_bytes())
    packet = deepcopy(retained['payload'])
    assert retained['provenance']['exit_code'] == 0
    assert packet['agent_result']['description'] == 'Retrieve global Wwise information.'
    assert set(packet['agent_result']) == {'argsSchema', 'description', 'optionsSchema', 'resultSchema'}
    call, calls = _reader(context, packet, packet['reflection_context'])
    result = context.reflect(call, expected_info=packet['reflection_context'])
    assert [receipt['uri'] for receipt in result['schemas']] == list(demo.URIS)
    assert len(calls) == 14
    assert packet == retained['payload']  # Retain the complete native packet.


@pytest.mark.parametrize('fault', ['missing-argsSchema', 'missing-optionsSchema', 'missing-resultSchema',
    'missing-description', 'malformed-schema', 'schema-drift', 'description-drift', 'session', 'build'])
def test_real_schema_packet_still_rejects_incomplete_malformed_or_drifting_context(tmp_path, fault):
    context = _installed(tmp_path)
    packet = deepcopy(json.loads(FIXTURE.read_bytes())['payload'])
    expected_info = deepcopy(packet['reflection_context'])
    if fault.startswith('missing-'):
        del packet['agent_result'][fault.removeprefix('missing-')]
    elif fault == 'malformed-schema':
        packet['agent_result']['argsSchema'] = []
    elif fault == 'schema-drift':
        packet['agent_result']['resultSchema']['properties']['unreviewedField'] = {'type': 'string'}
    elif fault == 'description-drift':
        packet['agent_result']['description'] = 'Unreviewed schema description'
    elif fault == 'session':
        packet['reflection_context']['sessionId'] = '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'
    else:
        packet['reflection_context']['version']['build'] = 9263
    call, calls = _reader(context, packet, expected_info)
    with pytest.raises(ValueError, match='Scoped live schema/session mismatch'):
        context.reflect(call, expected_info=expected_info)
    assert calls == [['status'], ['waapi-schema', 'ak.wwise.core.getInfo', '--exclude-examples']]

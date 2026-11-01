"""Direct public Gateway behavior with injected native responses."""

from copy import deepcopy

import gzip

import json

import pytest

from tests.maintenance import branch_coverage_audit as audit

from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient

URI = 'ak.wwise.core.profiler.getLoadedMedia'
ROW = {'fileName': 'Ambience_40.wav', 'format': 'VORBIS', 'mediaId': 124871431, 'size': 160821, 'soundBank': 'Prepared'}

BUILDS = {'2023.1': '2023.1.19.8928', '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}

@pytest.mark.parametrize('version',('2021.1','2022.1'))
def test_loaded_media_unavailable_older_lanes_do_not_connect(tmp_path,version):
    code,payload = gateway.execute_gateway(['core-call',URI,'--profiler-position','0'],
        env=_env(tmp_path,version=version),client_factory=lambda _: pytest.fail('Unavailable version connected'))
    assert code == 2 and payload['ok'] is False

@pytest.mark.parametrize('version',('2023.1','2024.1','2025.1'))
def test_loaded_media_public_versioned_contract_and_rejections(tmp_path,version):
    env = _env(tmp_path,version=version)
    code,schema = gateway.execute_gateway(['request-schema',URI],env=env,
        client_factory=lambda _: pytest.fail('Offline schema connected'))
    assert code == 0
    declaration = schema['business_adapter']['declaration']
    assert declaration['required_fields'] == ['profiler_position']
    assert declaration['optional_fields'] == ['max_results']
    for flags in (['--profiler-position','not-a-position'],
                  ['--profiler-position','0','--max-results','0'],
                  ['--profiler-position','0','--max-results','1001'],
                  ['--profiler-position','0','--result-field','fileName']):
        code,rejected = gateway.execute_gateway(['core-call',URI,*flags],env=env,
            client_factory=lambda _: pytest.fail('Invalid declaration connected'))
        assert code == 2 and rejected['ok'] is False, rejected
    client = _RuntimeControlDraftClient(tmp_path,version=version)
    original = client.call
    client.call = lambda uri,args=None,options=None: ({'return':[{**ROW,'size':'not-bytes'}]}
        if uri == URI else original(uri,args,options))
    code,rejected = gateway.execute_gateway(['--state-dir',str(tmp_path/'malformed-state'),
        'core-call',URI,'--profiler-position','99328'],env=env,client_factory=lambda _: client)
    assert code == 2 and rejected['ok'] is False, rejected

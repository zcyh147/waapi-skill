"""Exact finalized Console observations retain their independent public data facts."""
import json
from pathlib import Path
from copy import deepcopy

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support.runtime_observation_evidence import write_json, write_program_receipt


def test_r125_finalized_console_profile_keeps_complete_report_and_exact_read():
    from tests.support.console_runtime_read_evidence import original_observation
    original = original_observation('2021.1', 'busses')
    assert original['context']['candidate'] == '0d56a083da7a7965d734df3e02c0fb5681a75c70'
    assert original['capture']['complete'] is True
    assert original['raw']['result']['return'][0]['objectGUID'] == '{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}'
    assert original['raw']['result']['return'][0]['gameObjectID'] == 18446744073709551614
    assert original['request']['args'] == {'time': 1898}


@pytest.fixture(scope='module')
def committed_tables():
    import gzip
    stored=json.loads((audit.ROOT/'docs/branch-coverage-inventory.json').read_bytes())
    packed=json.loads(gzip.decompress((audit.ROOT/'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    return stored,packed


def packet_case(tmp_path,version,key,tables,program_inputs=None,bundle_prefix=""):
    from tests.support import console_runtime_read_evidence as console
    from tests.unit.test_fixed_runtime_read_branch_evidence import public_fixed_read
    from tests.unit.test_rtpc_field_branch_evidence import public_rtpc_read
    from tests.unit.test_contribution_branch_evidence import public_contribution_flow
    original=console.original_observation(version,key);uri=original['reader']['uri'];ids=set(original['reader']['selectors'])
    route_id=next(iter(ids)).rsplit('|',1)[0];stored,packed=tables;rows=[]
    for encoded in packed['rows']:
        if encoded.get('route') is None or packed['routes'][encoded['route']]!=route_id:continue
        row=dict(encoded);row.update(packed['contexts'][row.pop('context')]);row.update(route=route_id,id=route_id+'|'+row['pointer'],shape_sha256=packed['shapes'][row.pop('shape')]);rows.append(row)
    route,=[r for r in stored['native_coverage']['routes'] if r['id']==route_id]
    inventory={'routes':[r for r in stored['routes'] if r['id']==route['public_route']],
        'native_coverage':{'candidate_sha256':'e'*64,'catalogs':stored['native_coverage']['catalogs'],'routes':[route],'obligations':rows}}
    if key=='rtpcs':
        receipt,native,context=public_rtpc_read(tmp_path/'public',version=version,host='wwise-console',
            position=str(original['profile']['time']),rows=original['raw']['result']['return']);extra={}
    elif key=='contributions_dry':
        c=original['capture'];seeds={suffix:c['outcomes'][name]['evidence']['agent_result']['return']
            for suffix,name in [('getVoices','voices'),('getBusses','busses')]}
        seeds={suffix:[{k:v for k,v in row.items() if k not in ['voice_instance_handle','bus_instance_handle']} for row in rows] for suffix,rows in seeds.items()}
        receipt,native,context,trace,calls,_=public_contribution_flow(tmp_path/'public',version,host='wwise-console',
            retained=(audit.ROOT/console.FIXTURE,original['receipt'],original['raw'],seeds))
        extra={'native_reads':trace,'public_calls':calls}
    else:
        receipt,native,context,trace=public_fixed_read(tmp_path/'public',version=version,host='wwise-console',
            uri=uri,position=str(original['profile']['time']),rows=original['raw']['result']['return'],original_argv=original['receipt']['argv'])
        extra={'native_reads':trace,'public_calls':[{'gateway':receipt,'native_start':0,'native_end':len(trace)}]}
    assert native['result']==original['raw']['result']
    if program_inputs is not None:
        program_inputs.update(gateway=receipt,native_call=native,source_context=context,**extra)
    capture=tmp_path/'program.json'
    write_program_receipt(capture,receipt,native,nodeid='r125-'+version+'-'+key,
        phase_reports=dict.fromkeys(('setup','call','teardown'),'passed'),source_context=context,**extra)
    index=console.write_bundle(tmp_path/'bundle',capture,inventory=inventory,version=version,key=key,name_prefix=bundle_prefix)
    policy=json.loads((index.parent/(bundle_prefix+'requirements.json')).read_bytes());document,base,_=audit.portable_binding_inputs(index,policy)
    return inventory,index,policy,document,base,ids


CASES=[(v,k) for v in ('2021.1','2022.1','2023.1','2024.1','2025.1')
    for k in ('busses','audio_objects','rtpcs','contributions_dry','game_objects','voices')
    if not (v=='2021.1' and k=='game_objects') and not (v!='2025.1' and k=='voices')]


@pytest.fixture(scope='module')
def packet_cache(tmp_path_factory,committed_tables):
    cases={}; inputs={}
    def get(version,key):
        if (version,key) not in cases:
            inputs[version,key]={}
            cases[version,key]=packet_case(tmp_path_factory.mktemp('r125-'+version+'-'+key),version,key,committed_tables,inputs[version,key])
        return cases[version,key]
    get.program_inputs=inputs
    return get


@pytest.mark.parametrize('version,key',CASES,ids=[v+'-'+k for v,k in CASES])
def test_r125_new106_anchors_use_25_complete_original_public_packets(packet_cache,version,key,request):
    inventory,index,policy,document,base,ids=packet_cache(version,key)
    import os
    directory=os.environ.get('WAAPI_CONSOLE_READER_CAPTURE_DIR')
    if directory:
        from tests.support.runtime_observation_evidence import register_runtime_program_output
        register_runtime_program_output(request.node,Path(directory)/(version+'-'+key+'.json'),**packet_cache.program_inputs[version,key])
    result=completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policy)
    observed=[r for r in result['obligations'] if r['id'] in ids]
    assert len(observed)==len(ids)
    assert all(r['state']=='verified' and r['requirements']==['native','program'] for r in observed),json.dumps(observed)
    print('R125_CONSOLE_NATIVE',version,key,len(observed))
    if (version, key) == ('2021.1', 'busses'):
        from tests.support import console_runtime_read_evidence as console
        identity = sorted(ids)[0]; binding = document['bindings'][identity]
        branch = next(row for row in inventory['native_coverage']['obligations'] if row['id'] == identity)
        proof = completion.read_sealed_artifact(binding['runtime_observation_attachment'], base)
        review = completion.read_sealed_artifact(proof['source_review'], base)
        for damage in ('wrong-pair', 'extra-file'):
            changed = deepcopy(review)
            if damage == 'wrong-pair':
                changed['changed_files']['skills/waapi-skill/wwise_waapi/profiler_meter_objects.py']['after'] = '0' * 64
            else:
                changed['changed_files']['skills/waapi-skill/scripts/run.py'] = {'before':'0' * 64, 'after':'1' * 64}
            descriptor = write_json(base / (damage + '-review.json'), changed)
            with pytest.raises(ValueError, match='R125 exact reviewed source'):
                console.validate_source_review(descriptor, review['historical_sources'], branch, audit.ROOT, base)
        native = completion.read_sealed_artifact(binding['evidence']['native'], base)
        equivalence = completion.read_sealed_artifact(binding['native_equivalence'], base)
        del equivalence['runtime_read_review']
        with pytest.raises(ValueError, match='equivalence relevant source changed'):
            completion.validate_equivalence(write_json(base / 'missing-review-marker.json', equivalence),
                native['native_runs'][0], {'candidate_sha256':equivalence['from_candidate'],
                    'relevant_sources':native['relevant_sources']}, branch,
                inventory['native_coverage']['candidate_sha256'], binding, base, audit.ROOT)
        unrelated = {**branch, 'route':branch['route'].replace('getBusses','getMeters'),
            'id':branch['id'].replace('getBusses','getMeters')}
        with pytest.raises(ValueError, match='exact106'):
            console.validate_source_review(proof['source_review'], review['historical_sources'], unrelated, audit.ROOT, base)


def test_r125_resealed_corruption_reuses_complete_packets(packet_cache):
    from tests.support import console_runtime_read_evidence as console
    inventory,index,policy,document,base,ids=packet_cache('2025.1','voices')
    target=next(i for i in ids if i.endswith('/priority'));original=deepcopy(document['bindings'][target])
    policy={'contract':policy['contract'],'branches':{target:policy['branches'][target]}}
    for damage in ('native-value','missing-attachment','time','source','empty','truncated','failed-phase','wrong-archive','wrong-finalization'):
        binding=deepcopy(original);proof=completion.read_sealed_artifact(binding['runtime_observation_attachment'],base)
        native=completion.read_sealed_artifact(binding['evidence']['native'],base)
        if damage=='native-value':
            native['branch_assertions'][target]['checks'][0]['equals']+=1
        elif damage=='missing-attachment':binding.pop('runtime_observation_attachment')
        elif damage=='wrong-archive':proof['archive']['sha256']='0'*64
        elif damage=='wrong-finalization':
            category=completion.read_sealed_artifact(proof['native_run'],base)
            category['invocation'].update(phase='prepared',outcome='PENDING')
            changed=write_json(base/'prepared-category.json',category)
            proof['native_run']={**changed,'nodeid':proof['native_run']['nodeid'],'observation_sha256':proof['native_run']['observation_sha256']}
            native['native_runs']=[proof['native_run']]
        else:
            program=completion.read_sealed_artifact(binding['evidence']['program'],base);capture=program['runtime_read_program']
            if damage=='time':program['native_call']['args']['time']+=1
            elif damage=='source':capture['source_context']['capture']['tests/support/console_runtime_read_evidence.py']='0'*64
            elif damage=='empty':program['native_call']['result']['return']=[]
            elif damage=='truncated':program['gateway']['payload']['agent_result'].update(complete=False,truncated=True)
            elif damage=='failed-phase':capture['phase_reports']['teardown']='failed'
            capture['native_call']=deepcopy(program['native_call']);capture['gateway']=deepcopy(program['gateway'])
            proof['program_capture']=write_json(base/(damage+'-capture.json'),capture)
            binding['evidence']['program'].update(write_json(base/(damage+'-program.json'),program))
        if 'runtime_observation_attachment' in binding:
            binding['runtime_observation_attachment']=write_json(base/(damage+'-proof.json'),proof)
        binding['evidence']['native'].update(write_json(base/(damage+'-native.json'),native))
        result=completion.evaluate_coverage(audit.ROOT,inventory,{'contract':'waapi-skill.branch-bindings/v1','bindings':{target:binding}},
            digest=audit.digest,evidence_base=base,requirements_document=policy)
        observed=next(r for r in result['obligations'] if r['id']==target)
        assert observed['state']!='verified',(damage,observed)
        if damage not in {'source','truncated','failed-phase'}:
            assert observed['evidence_results']['native']['outcome']=='missing',(damage,observed)
    # Original handles stay provenance. An expired original token cannot replace
    # the fresh public issuer retained in this same-frame contribution capture.
    inventory,index,policy,document,base,ids=packet_cache('2025.1','contributions_dry')
    target=next(i for i in ids if i.endswith('/properties/volume'));binding=deepcopy(document['bindings'][target])
    proof=completion.read_sealed_artifact(binding['runtime_observation_attachment'],base)
    program=completion.read_sealed_artifact(binding['evidence']['program'],base);capture=program['runtime_read_program']
    old=console.original_observation('2025.1','contributions_dry')['receipt']['argv'][-1]
    argv=program['gateway']['argv'];argv[argv.index('--voice-instance-handle')+1]=old
    capture['gateway']=deepcopy(program['gateway']);capture['public_calls'][-1]['gateway']=deepcopy(program['gateway'])
    binding['input']['gateway_argv']=deepcopy(argv);proof['program_capture']=write_json(base/'old-handle-capture.json',capture)
    binding['evidence']['program'].update(write_json(base/'old-handle-program.json',program))
    binding['runtime_observation_attachment']=write_json(base/'old-handle-proof.json',proof)
    result=completion.evaluate_coverage(audit.ROOT,inventory,{'contract':'waapi-skill.branch-bindings/v1','bindings':{target:binding}},
        digest=audit.digest,evidence_base=base,requirements_document=policy)
    assert next(r for r in result['obligations'] if r['id']==target)['state']!='verified'
    with pytest.raises(ValueError,match='provenance only'):
        console.original_observation('2024.1','voices')
    branch=next(r for r in inventory['native_coverage']['obligations'] if r['id']==target)
    for changed in ({**branch,'shape_sha256':'0'*64},{**branch,'route':branch['route'].replace('wwise-console','wwise-authoring')},
                    {**branch,'id':branch['id']+'/oneOf/1'}):
        with pytest.raises(ValueError,match='exact106|Exact R125'):
            console.profile_for_branch(changed)


def test_retained_packet_formal_output_waits_for_real_teardown_and_rechecks_source(tmp_path, monkeypatch):
    from tests import conftest
    from tests.support.runtime_observation_evidence import register_runtime_program_output
    from tests.unit.test_fixed_runtime_read_branch_evidence import public_fixed_read
    from tests.support.console_runtime_read_evidence import original_observation
    original = original_observation('2021.1', 'busses')
    receipt, native, context, trace = public_fixed_read(tmp_path / 'public', version='2021.1', host='wwise-console',
        uri=original['reader']['uri'], position='1898', rows=original['raw']['result']['return'], original_argv=original['receipt']['argv'])
    inputs = dict(gateway=receipt, native_call=native, source_context=context, native_reads=trace,
        public_calls=[{'gateway':receipt, 'native_start':0, 'native_end':len(trace)}])
    probe = tmp_path / 'test_formal_packet.py'
    probe.write_text('import pytest\n@pytest.mark.parametrize("damage", ["none", "teardown", "source"])\ndef test_packet(formal_packet, damage):\n    formal_packet(damage)\n')
    class Producer:
        @pytest.fixture
        def formal_packet(self, request):
            selected = {}
            def run(damage):
                selected['damage'] = damage
                selected['inputs'] = deepcopy(inputs)
                register_runtime_program_output(request.node, tmp_path / (damage + '.json'), **selected['inputs'])
                assert not (tmp_path / (damage + '.json')).exists()
            yield run
            if selected['damage'] == 'teardown': raise RuntimeError('actual retained-packet fixture teardown failure')
            if selected['damage'] == 'source':
                selected['inputs']['source_context']['capture']['tests/support/console_runtime_read_evidence.py'] = '0' * 64
    class Reports:
        pytest_runtest_makereport = staticmethod(conftest.pytest_runtest_makereport)
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    result = pytest.main([str(probe), '--rootdir', str(tmp_path), '-q', '-p', 'no:cacheprovider'], plugins=[Producer(), Reports()])
    assert int(result) == 1
    assert json.loads((tmp_path / 'none.json').read_bytes())['phase_reports'] == dict.fromkeys(('setup','call','teardown'), 'passed')
    assert not (tmp_path / 'teardown.json').exists() and not (tmp_path / 'source.json').exists()


def test_reviewed_log_message_source_delta_keeps_original_map_and_rejects_unlisted_changes(tmp_path, monkeypatch):
    """Exact reviewed successors never make arbitrary source drift eligible."""
    from tests.support import console_runtime_read_evidence as console
    from tests.support import runtime_observation_evidence as runtime
    from tests.support import source_copy_native_evidence as source
    original = json.loads((audit.ROOT / console.FIXTURE / 'r125-source-map.json').read_bytes())
    assert original['candidate'] == '0d56a083da7a7965d734df3e02c0fb5681a75c70'
    historical = original['sources']
    current = console.reviewed_source_context(historical)
    gateway = 'skills/waapi-skill/scripts/gateway.py'
    assert historical[gateway] == 'c8dfcff8ae13c9e5b192f4ca7f1e1cd7b52a9f20e5327b33bec15e8a1ecb0bc4'
    assert current[gateway] == 'eaac3a17e3ab76abe2cd0ec74e5b79e4e2281f7a7d65c8e3bf34f64b3c89763b'
    business='skills/waapi-skill/wwise_waapi/runtime_inspection_business.py'
    assert current[business]=='dcdfdaab82e8bd5faac9d762bd08ee917067dade291594c34e125a67be570712'
    for damaged in ({**historical, gateway: '0' * 64}, {**historical, 'unreviewed.py': '0' * 64}):
        with pytest.raises(ValueError, match='R125 exact reviewed source delta'):
            console.reviewed_source_context(damaged)
    from tests.support import fixed_runtime_read_evidence as fixed
    from tests.support import qualified_runtime_read_evidence as qualified
    from tests.support import loaded_media_runtime_evidence as loaded
    from tests.support import runtime_remaining_evidence as remaining
    from tests.support import runtime_log_retained_evidence as retained
    from tests.support import extra_runtime_read_evidence as extra
    endpoints={gateway:current[gateway],business:current[business]}
    for changes in (runtime.RTPC_REVIEWED_SOURCE_CHANGES,fixed.REVIEWED_CHANGES,
                    fixed.R118_CHANGES,fixed.R119_CHANGES,qualified.r104_source_review()[0]):
        assert {name:changes[name]['after']for name in endpoints}==endpoints
    positive=loaded.review();composite=loaded.composite_review();console_loaded=loaded.console_review()
    assert composite['positive_review_sha256']==console_loaded['positive_review_sha256']==loaded.REVIEW_SHA
    for changes in [positive['packaged_source_review']['changes'],console_loaded['packaged_source_changes'],
                    *[p['packaged_source_changes']for p in composite['profiles'].values()],
                    remaining.support()['packaged_source_changes'],
                    *[p['source_changes']for p in retained.review()['providers'].values()],
                    *[p['source_changes']for p in extra.review()['providers'].values()]]:
        assert {name:changes[name]['after']for name in endpoints}==endpoints
    for label in ('r128-2023','r128-2024'):
        provider=retained.review()['providers'][label]
        assert provider['source_changes']==runtime.CURSOR_OMISSION_SOURCE_CHANGES
        assert {name:provider['sources'][name]for name in endpoints}=={
            name:pair['before']for name,pair in runtime.CURSOR_OMISSION_SOURCE_CHANGES.items()}
    successor = source.successor_dependency_review()
    assert len(successor['current_sources']) == 619
    assert all(runtime.sha((audit.ROOT / name).read_bytes()) == seal
               for name, seal in successor['current_sources'].items())
    review = tmp_path / source.SUCCESSOR_REVIEW_PATH
    review.parent.mkdir(parents=True)
    review.write_text('{}')
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='Reviewed Source successor changed'):
        source.successor_dependency_review()

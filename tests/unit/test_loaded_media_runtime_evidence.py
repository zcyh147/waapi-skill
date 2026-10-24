"""The owned 9262 fact supports one exact pinned LoadedMedia route explicitly."""
from copy import deepcopy
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient

URI = 'ak.wwise.core.profiler.getLoadedMedia'
ROUTE = '2025.1|wwise-authoring|2025.1.7.9143|function|' + URI
ANCHOR = ROUTE + '|/resultSchema/properties/return/@cardinality/single'
ROW = {'fileName': 'Ambience_40.wav', 'format': 'VORBIS', 'mediaId': 124871431, 'size': 160821, 'soundBank': 'Prepared'}
FIXTURE = audit.ROOT / 'tests/fixtures/runtime-loaded-media'


def public_loaded_read(path, *, rows=None, position='99328'):
    path.mkdir(parents=True)
    context = runtime.program_source_context(flow=URI)
    client = _RuntimeControlDraftClient(path, version='2025.1')
    fallback, trace = client.call, []
    def call(uri, args=None, options=None):
        result = ({'return': deepcopy([ROW] if rows is None else rows)} if uri == URI else
                  {'return': 99328} if uri == 'ak.wwise.core.profiler.getCursorTime' else fallback(uri, args, options))
        if uri == 'ak.wwise.core.getInfo':
            result['version'].update(minor=7, build=9143, displayName='v2025.1.7.9143')
        trace.append({'ordinal': len(trace), 'uri': uri, 'args': deepcopy(args), 'options': deepcopy(options), 'result': deepcopy(result)})
        return result
    client.call = call
    argv = ['core-call', URI, '--profiler-position', position, '--max-results', '64']
    code, payload = gateway.execute_gateway(['--state-dir', str(path / 'state'), *argv],
        env=_env(path, version='2025.1'), client_factory=lambda _: client)
    assert code == 0, json.dumps(payload)
    receipt = {'argv': argv, 'exit_code': code, 'payload': payload}
    native = {key: trace[-1][key] for key in ('uri', 'args', 'options', 'result')}
    assert payload['agent_result']['return'] == ([ROW] if rows is None else rows)
    return receipt, native, context, trace


@pytest.fixture(scope='module')
def inventory():
    return audit.build_inventory()


def consume(index, inventory):
    policy = json.loads((index.parent / 'requirements.json').read_bytes())
    document, base, _ = audit.portable_binding_inputs(index, policy)
    result = completion.evaluate_coverage(audit.ROOT, inventory, document,
        digest=audit.digest, evidence_base=base, requirements_document=policy)
    return {r['id']: r for r in result['obligations'] if r['route'] == ROUTE}, document, base


def test_loaded_media_public_teardown_portable_consumer(request, tmp_path, inventory):
    # Each fake row family proves preservation only; solely the original native
    # single-row capture supplies semantic availability, with actual build9262.
    captures = []
    families = [(None, '99328'), ([], '0'), ([{**ROW, 'fileName': '', 'format': '', 'soundBank': ''}] * 2, '0'),
                (None, 'capture-latest'), (None, 'user-cursor')]
    for number, (rows, position) in enumerate(families):
        captures.append(public_loaded_read(tmp_path / str(number), rows=rows, position=position))
    assert captures[0][1] == {'uri': URI, 'args': {'time': 99328}, 'options': {}, 'result': {'return': [ROW]}}
    def finalize(phases):
        from tests.support.loaded_media_runtime_evidence import write_loaded_media_bundle
        paths = []
        for number, (receipt, native, context, trace) in enumerate(captures):
            path = tmp_path / f'capture-{number}.json'
            runtime.write_program_receipt(path, receipt, native, nodeid=request.node.nodeid,
                phase_reports=phases, source_context=context, native_reads=trace,
                public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
            paths.append(path)
        index = write_loaded_media_bundle(tmp_path / 'bundle', paths, inventory=inventory)
        rows, document, _ = consume(index, inventory)
        assert len(rows) == 31
        assert {row['state'] for row in rows.values()} == {'verified'}, json.dumps(rows)
        basis = rows[ANCHOR]['representative_native_support']
        assert basis == {'catalog_build': '2025.1.7.9143', 'observed_build': '2025.1.11.9262',
                         'basis': 'exact_reviewed_representative_support'}
        assert rows[ANCHOR]['evidence_results']['native']['outcome'] == 'passed'
        assert all(row['requirements'] == ['program'] for identity, row in rows.items() if identity != ANCHOR)
        assert all(row['runtime_native_anchor_status'] == 'passed' for identity, row in rows.items() if identity != ANCHOR)
        assert len([b for b in document['bindings'].values() if 'native' in b['evidence']]) == 1
    register_exact_evidence_finalizer(request.node, finalize)


@pytest.fixture(scope='module')
def corruption_inputs(tmp_path_factory, inventory):
    """Synthetic controls only; the positive above owns reported-teardown proof."""
    path = tmp_path_factory.mktemp('loaded-media-corruption-controls')
    captures = []
    for number, (rows, position) in enumerate([(None,'99328'),([], '0'),
            ([{**ROW,'fileName':'','format':'','soundBank':''}]*2,'0'),(None,'capture-latest'),(None,'user-cursor')]):
        receipt,native,context,trace = public_loaded_read(path/str(number),rows=rows,position=position)
        target=path/f'capture-{number}.json'
        runtime.write_program_receipt(target,receipt,native,nodeid='synthetic-corruption-control',
            phase_reports=dict.fromkeys(('setup','call','teardown'),'passed'),source_context=context,native_reads=trace,
            public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
        captures.append(target)
    from tests.support.loaded_media_runtime_evidence import write_loaded_media_bundle
    index=write_loaded_media_bundle(path/'bundle',captures,inventory=inventory)
    policy=json.loads((index.parent/'requirements.json').read_bytes())
    document,base,_=audit.portable_binding_inputs(index,policy)
    return document,base,policy


def evaluate_control(document, base, policy, inventory):
    result=completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,
        evidence_base=base,requirements_document=policy)
    return {r['id']:r for r in result['obligations'] if r['route']==ROUTE}


def reseal_program(document, base, edit):
    """Refresh transport seals so semantic corruption is the actual rejection."""
    binding=document['bindings'][ANCHOR]
    record=completion.read_sealed_artifact(binding['evidence']['program'],base)
    captured=record['runtime_read_program']
    edit(captured)
    record['gateway']=deepcopy(captured['gateway']);record['native_call']=deepcopy(captured['native_call'])
    captured['public_calls'][0]['gateway']=deepcopy(captured['gateway'])
    for identity,assertion in record['branch_assertions'].items():
        for check in assertion['checks']:
            if 'equals' in check:
                try:check['equals']=completion.pointer_value(record,check['pointer'])
                except KeyError:pass  # Keep the independently expected missing-field assertion.
    original_sha=binding['evidence']['program']['sha256']
    replacement=runtime.write_json(base/'changed-program.json',record)
    for b in document['bindings'].values():
        if b['evidence']['program']['sha256']==original_sha:
            b['evidence']['program'].update(replacement)
            b['input']['gateway_argv']=deepcopy(record['gateway']['argv'])
    proof=completion.read_sealed_artifact(binding['runtime_observation_attachment'],base)
    proof['program_capture']=runtime.write_json(base/'changed-capture.json',captured)
    binding['runtime_observation_attachment']=runtime.write_json(base/'changed-proof.json',proof)
    eq=completion.read_sealed_artifact(binding['native_equivalence'],base)
    eq['binding_semantics_sha256']=audit.digest(completion.binding_semantics(binding))
    binding['native_equivalence']=runtime.write_json(base/'changed-equivalence.json',eq)


def test_loaded_media_rejects_extra_raw_read(tmp_path,inventory,corruption_inputs):
    import shutil
    document,source,policy=corruption_inputs;document=deepcopy(document)
    base=tmp_path/'bundle';shutil.copytree(source,base)
    def duplicate(captured):
        captured['native_reads'].append(deepcopy(captured['native_reads'][-1]))
        captured['native_reads'][-1]['ordinal']=len(captured['native_reads'])-1
        captured['public_calls'][0]['native_end']=len(captured['native_reads'])
    reseal_program(document,base,duplicate)
    rows=evaluate_control(document,base,policy,inventory)
    assert rows[ANCHOR]['state']!='verified', json.dumps(rows[ANCHOR])
    assert rows[ANCHOR]['evidence_results']['program']['outcome']=='missing'
    assert all(row['state']!='verified' for row in rows.values())


@pytest.mark.parametrize('damage',('partial','missing-field','changed-codec','changed-time','missing-attachment','missing-review','missing-anchor'))
def test_loaded_media_portable_consumer_fails_closed(tmp_path,inventory,corruption_inputs,damage):
    import shutil
    document,source,policy=corruption_inputs;document=deepcopy(document)
    base=tmp_path/'bundle';shutil.copytree(source,base)
    binding=document['bindings'][ANCHOR]
    if damage in {'partial','missing-field','changed-codec','changed-time'}:
        def change(captured):
            public=captured['gateway']['payload']['agent_result']
            if damage=='partial':public['complete']=False
            elif damage=='missing-field':del public['return'][0]['fileName']
            else:
                if damage=='changed-codec':
                    public['return'][0]['format']='PCM'
                    captured['native_call']['result']['return'][0]['format']='PCM'
                    captured['native_reads'][-1]['result']['return'][0]['format']='PCM'
                else:
                    public['profiler_position']='99329'
                    captured['gateway']['argv'][3]='99329'
                    captured['gateway']['payload']['business_request']['profiler_position']='99329'
                    captured['native_call']['args']['time']=99329
                    captured['native_reads'][-1]['args']['time']=99329
                public['snapshot_sha256']=audit.digest({'profiler_position':public['profiler_position'],
                    'return':public['return'],'returned_count':1,'truncated':False})
        reseal_program(document,base,change)
    elif damage=='missing-attachment':binding.pop('runtime_observation_attachment')
    elif damage=='missing-review':(base/'support-review.json').unlink()
    else:binding['evidence'].pop('native')
    rows=evaluate_control(document,base,policy,inventory)
    assert rows[ANCHOR]['state']!='verified',json.dumps(rows[ANCHOR])
    assert all(row['state']!='verified' for row in rows.values())
    if damage in {'changed-codec','changed-time'}:
        # A wholly consistent synthetic current response still cannot replace
        # the one independently observed native semantic anchor.
        assert rows[ANCHOR]['evidence_results']['program']['outcome']=='passed',json.dumps(rows[ANCHOR])
        assert rows[ANCHOR]['evidence_results']['native']['outcome']=='missing'


@pytest.mark.parametrize('damage',('missing-artifact','changed-raw-row','prepared-only','wrong-build','failed-cleanup'))
def test_loaded_media_original_closure_rejects_resealed_corruption(tmp_path,inventory,corruption_inputs,damage):
    import base64
    import gzip
    import shutil
    document,source,policy=corruption_inputs;document=deepcopy(document)
    base=tmp_path/'bundle';shutil.copytree(source,base)
    binding=document['bindings'][ANCHOR]
    proof=completion.read_sealed_artifact(binding['runtime_observation_attachment'],base)
    if damage in {'missing-artifact','changed-raw-row'}:
        archive_path=base/'r124-originals.json.gz'
        archive=json.loads(gzip.decompress(archive_path.read_bytes()))
        name=proof['mapping']['raw_original_path']
        if damage=='missing-artifact':archive['files'].pop(name)
        else:
            raw=json.loads(base64.b64decode(archive['files'][name]));raw['result']['return'][0]['size']=0
            archive['files'][name]=base64.b64encode(json.dumps(raw).encode()).decode()
        archive_path.write_bytes(gzip.compress(json.dumps(archive).encode(),mtime=0))
        proof['archive']['sha256']=runtime.sha(archive_path.read_bytes())
    else:
        path=base/'r124-category.json';category=json.loads(path.read_bytes())
        if damage=='prepared-only':
            from tests.support.loaded_media_runtime_evidence import PREFIX
            read=runtime.archive_reader(proof['archive'],base)
            category=json.loads(read(PREFIX+'categories.jsonl').splitlines()[0])
        elif damage=='wrong-build':category['host']['version']['build']=9263
        else:category['residual_state']['process_cleanup']='failed'
        descriptor=runtime.write_json(path,category)
        native=completion.read_sealed_artifact(binding['evidence']['native'],base)
        native['native_runs'][0].update(descriptor);proof['native_run'].update(descriptor)
        binding['evidence']['native'].update(runtime.write_json(base/'changed-native.json',native))
    binding['runtime_observation_attachment']=runtime.write_json(base/'changed-proof.json',proof)
    eq=completion.read_sealed_artifact(binding['native_equivalence'],base)
    eq['binding_semantics_sha256']=audit.digest(completion.binding_semantics(binding))
    binding['native_equivalence']=runtime.write_json(base/'changed-equivalence.json',eq)
    rows=evaluate_control(document,base,policy,inventory)
    assert rows[ANCHOR]['evidence_results']['native']['outcome']=='missing',json.dumps(rows[ANCHOR])
    assert all(row['state']!='verified' for row in rows.values())


def test_loaded_media_fact_does_not_support_other_catalog_routes(inventory,corruption_inputs):
    document,base,_=corruption_inputs
    binding=document['bindings'][ANCHOR]
    # Genuine existing catalog rows, rather than a caller-supplied build flag.
    branches=inventory['native_coverage']['obligations']
    candidates=[next(b for b in branches if b['pointer']=='/resultSchema/properties/return/@cardinality/single'
        and b['route'].split('|')[:2]==scope and b['route'].endswith('|'+uri))
        for scope,uri in [(['2024.1','wwise-authoring'],URI),
                          (['2025.1','wwise-console'],URI),
                          (['2025.1','wwise-authoring'],'ak.wwise.core.profiler.getStreamedMedia')]]
    for branch in candidates:
        outcome,reason=completion.evidence_result(binding['evidence']['native'],branch,
            inventory['native_coverage']['candidate_sha256'],'native','product',base,binding,audit.ROOT)
        assert outcome=='missing', (branch['id'],outcome,reason)

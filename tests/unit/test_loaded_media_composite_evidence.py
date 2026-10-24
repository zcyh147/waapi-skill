"""Older API availability and9262 semantic support retain separate attribution."""
from copy import deepcopy
import gzip
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
from tests.unit.test_loaded_media_runtime_evidence import ROW, URI

BUILDS = {'2023.1': '2023.1.19.8928', '2024.1': '2024.1.13.9056', '2025.1': '2025.1.7.9143'}


def public_read(path, version, rows, position):
    path.mkdir(parents=True)
    context = runtime.program_source_context(flow=URI)
    client = _RuntimeControlDraftClient(path, version=version)
    fallback, trace = client.call, []
    def call(uri, args=None, options=None):
        result = ({'return': deepcopy(rows)} if uri == URI else
                  {'return': 99328} if uri.endswith('.getCursorTime') else fallback(uri, args, options))
        if uri == 'ak.wwise.core.getInfo':
            year, major, minor, build = map(int, BUILDS[version].split('.'))
            result['version'].update(year=year, major=major, minor=minor, build=build,
                                     displayName='v' + BUILDS[version])
        trace.append({'ordinal': len(trace), 'uri': uri, 'args': deepcopy(args),
                      'options': deepcopy(options), 'result': deepcopy(result)})
        return result
    client.call = call
    argv = ['core-call', URI, '--profiler-position', position, '--max-results', '64']
    code, payload = gateway.execute_gateway(['--state-dir', str(path / 'state'), *argv],
        env=_env(path, version=version), client_factory=lambda _: client)
    assert code == 0, payload
    assert payload['agent_result']['return'] == rows
    return {'argv': argv, 'exit_code': code, 'payload': payload}, {
        key: trace[-1][key] for key in ('uri', 'args', 'options', 'result')}, context, trace


@pytest.fixture(scope='module')
def inventory():
    stored = json.loads((audit.ROOT / 'docs/branch-coverage-inventory.json').read_bytes())
    packed = json.loads(gzip.decompress((audit.ROOT / 'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    routes = [r for r in stored['native_coverage']['routes'] if r['version'] in BUILDS
              and r['host'] == 'wwise-authoring' and r['uri'] == URI]
    ids = {r['id'] for r in routes}
    rows = []
    for encoded in packed['rows']:
        if encoded.get('route') is None or packed['routes'][encoded['route']] not in ids:
            continue
        row = dict(encoded)
        row.update(packed['contexts'][row.pop('context')])
        route = packed['routes'][row['route']]
        row.update(route=route, id=route + '|' + row['pointer'],
                   shape_sha256=packed['shapes'][row.pop('shape')])
        rows.append(row)
    return {'routes': [r for r in stored['routes'] if r['id'] in {route['public_route'] for route in routes}],
            'native_coverage': {'candidate_sha256': 'f' * 64, 'catalogs': stored['native_coverage']['catalogs'],
                                'routes': routes, 'obligations': rows}}


@pytest.fixture(scope='module')
def published_packets():
    return []


@pytest.mark.parametrize('version', ('2023.1', '2024.1', '2025.1'))
def test_older_loaded_media_composite_public_teardown_consumer(request, tmp_path, inventory, version, published_packets):
    families = [([ROW], '99328'), ([], '0'),
                ([{**ROW, 'fileName': '', 'format': '', 'soundBank': ''}] * 2, '0'),
                ([ROW], 'capture-latest'), ([ROW], 'user-cursor')]
    captures = [public_read(tmp_path / str(i), version, rows, position)
                for i, (rows, position) in enumerate(families)]
    def finalize(phases):
        from tests.support.loaded_media_runtime_evidence import write_composite_bundle, write_loaded_media_bundle, BASIS
        paths = []
        for i, (receipt, native, context, trace) in enumerate(captures):
            path = tmp_path / ('capture-' + str(i) + '.json')
            runtime.write_program_receipt(path, receipt, native, nodeid=request.node.nodeid,
                phase_reports=phases, source_context=context, native_reads=trace,
                public_calls=[{'gateway': receipt, 'native_start': 0, 'native_end': len(trace)}])
            paths.append(path)
        index = (write_loaded_media_bundle(tmp_path / 'bundle',paths,inventory=inventory,name_prefix='lm-2025-')
                 if version == '2025.1' else
                 write_composite_bundle(tmp_path / 'bundle', paths, inventory=inventory, version=version))
        policies = json.loads((index.with_name(index.name.replace('index.json','requirements.json'))).read_bytes())
        document, base, _ = audit.portable_binding_inputs(index, policies)
        result = completion.evaluate_coverage(audit.ROOT, inventory, document, digest=audit.digest,
            evidence_base=base, requirements_document=policies)
        rows = [r for r in result['obligations'] if r['route'].startswith(version + '|')]
        assert len(rows) == 31
        assert {r['state'] for r in rows} == {'verified'}, json.dumps(rows)
        anchor = next(r for r in rows if r['id'].endswith('/@cardinality/single'))
        assert anchor['representative_native_support'] == (BASIS if version == '2025.1' else {
            'catalog_build': BUILDS[version], 'availability_build': BUILDS[version],
            'observed_build': '2025.1.11.9262', 'basis': 'exact_reviewed_cross_version_composite_support',
            'older_nonempty_native_execution': False, 'older_parent_outcome': 'BLOCKED'})
        published_packets.append((index,policies))
        if version != '2025.1':
            composite_damage_controls(tmp_path,inventory,document,base,policies,anchor['id'])
        else:
            # All three publishers create their own namespace; no recursive
            # descriptor rewriting is needed at a shared portable artifact base.
            import shutil
            common = tmp_path / 'common'
            common.mkdir()
            joined = {'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[],
                      'runtime_observation_attachments':[]}
            combined = {'contract':policies['contract'],'branches':{}}
            assert len(published_packets) == 3
            for packet, policy in published_packets:
                for source in packet.parent.iterdir():
                    assert not (common / source.name).exists(), source.name
                    shutil.copyfile(source,common / source.name)
                source_index = json.loads(packet.read_bytes())
                joined['entries'].extend(source_index['entries'])
                joined['runtime_observation_attachments'].extend(source_index['runtime_observation_attachments'])
                combined['branches'].update(policy['branches'])
            runtime.write_json(common / 'combined-index.json',joined)
            joined_doc,joined_base,_ = audit.portable_binding_inputs(common / 'combined-index.json',combined)
            joined_result = completion.evaluate_coverage(audit.ROOT,inventory,joined_doc,digest=audit.digest,
                evidence_base=joined_base,requirements_document=combined)
            assert len(joined_result['obligations']) == 93
            assert {row['state'] for row in joined_result['obligations']} == {'verified'}
    register_exact_evidence_finalizer(request.node, finalize)


def composite_damage_controls(tmp_path,inventory,document,base,policies,identity):
    import shutil
    copied = tmp_path / 'damage-controls'
    shutil.copytree(base,copied)
    base = copied
    from tests.support.loaded_media_runtime_evidence import composite_branch
    anchor = next(row for row in inventory['native_coverage']['obligations'] if row['id'] == identity)
    one = {**inventory,'native_coverage':{**inventory['native_coverage'],'obligations':[anchor]}}
    policy = {'contract':policies['contract'],'branches':{identity:policies['branches'][identity]}}
    for damage in ('availability','session','older-source','positive','current-replay','current-source','duplicate-read','attachment'):
        binding = deepcopy(document['bindings'][identity])
        proof = completion.read_sealed_artifact(binding['runtime_observation_attachment'],base)
        bridge = completion.read_sealed_artifact(proof['source_review'],base)
        if damage == 'availability': bridge['availability_archive']['artifact'] = 'missing-older-availability.json.gz'
        elif damage == 'session': bridge['availability_context']['live']['sessionId'] = '{00000000-0000-0000-0000-000000000000}'
        elif damage == 'older-source':
            # Remove the older original source map and reseal transport. The
            # source-owned whole-archive pin must still reject the substitute.
            import base64
            archive = json.loads(gzip.decompress((base/bridge['availability_archive']['artifact']).read_bytes()))
            name = next(name for name in archive['files'] if name.endswith('/d87a1375cafae330c7be7f7f.json'))
            node = json.loads(base64.b64decode(archive['files'][name]))
            node['source_context']['sources'].pop('skills/waapi-skill/scripts/gateway.py')
            archive['files'][name] = base64.b64encode(json.dumps(node).encode()).decode()
            path = base / ('damaged-'+damage+'.json.gz')
            path.write_bytes(gzip.compress(json.dumps(archive).encode(),mtime=0))
            bridge['availability_archive'] = {'artifact':path.name,'sha256':runtime.sha(path.read_bytes())}
        elif damage == 'positive': proof['archive']['artifact'] = 'missing-r124-originals.json.gz'
        elif damage == 'current-replay': proof['program_capture']['artifact'] = 'missing-current-replay.json'
        elif damage in {'current-source','duplicate-read'}:
            captured = completion.read_sealed_artifact(proof['program_capture'],base)
            if damage == 'current-source': captured['source_context']['packaged']['skills/waapi-skill/scripts/gateway.py'] = '0'*64
            else:
                captured['native_reads'].append(deepcopy(captured['native_reads'][-1]))
                captured['native_reads'][-1]['ordinal'] += 1
                captured['public_calls'][0]['native_end'] += 1
            proof['program_capture'] = runtime.write_json(base/('damaged-'+damage+'-capture.json'),captured)
        proof['source_review'] = runtime.write_json(base/('damaged-'+damage+'-bridge.json'),bridge)
        binding['runtime_observation_attachment'] = runtime.write_json(base/('damaged-'+damage+'-proof.json'),proof)
        equivalence = completion.read_sealed_artifact(binding['native_equivalence'],base)
        equivalence['loaded_media_source_review'] = proof['source_review']
        equivalence['binding_semantics_sha256'] = audit.digest(completion.binding_semantics(binding))
        binding['native_equivalence'] = runtime.write_json(base/('damaged-'+damage+'-equivalence.json'),equivalence)
        if damage == 'attachment': binding.pop('runtime_observation_attachment')
        result = completion.evaluate_coverage(audit.ROOT,one,
            {'contract':document['contract'],'bindings':{identity:binding}},digest=audit.digest,
            evidence_base=base,requirements_document=policy)
        row, = result['obligations']
        assert row['evidence_results']['native']['outcome'] == 'missing',(damage,row)
        assert row['state'] != 'verified',(damage,row)
    missing = deepcopy(document)
    missing['bindings'][identity]['evidence'].pop('native')
    result = completion.evaluate_coverage(audit.ROOT,inventory,missing,digest=audit.digest,
        evidence_base=base,requirements_document=policies)
    assert all(row['state'] != 'verified' for row in result['obligations'] if row['route'] == anchor['route'])
    for changed in ({**anchor,'route':anchor['route'].replace('wwise-authoring','wwise-console')},
                    {**anchor,'route':anchor['route'].replace('getLoadedMedia','getStreamedMedia')},
                    {**anchor,'id':anchor['id']+'/unlisted'}, {**anchor,'shape_sha256':'0'*64}):
        with pytest.raises(ValueError,match='exact reviewed older Authoring'):
            composite_branch(changed)


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

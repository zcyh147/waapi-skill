"""Exact Console availability and9262 meaning are independent mandatory facts."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
from tests.unit.test_runtime_business_gateway import gateway, _env, _RuntimeControlDraftClient
from tests.unit.test_loaded_media_runtime_evidence import ROW, URI

BUILDS = {'2023.1':'2023.1.19.8928', '2024.1':'2024.1.13.9056', '2025.1':'2025.1.7.9143'}


@pytest.fixture(scope='module')
def inventory():
    stored=json.loads((audit.ROOT/'docs/branch-coverage-inventory.json').read_bytes())
    packed=json.loads(gzip.decompress((audit.ROOT/'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    routes=[r for r in stored['native_coverage']['routes'] if r['uri']==URI and r['host']=='wwise-console' and r['version'] in BUILDS]
    selected={r['id'] for r in routes}; rows=[]
    for encoded in packed['rows']:
        if encoded.get('route') is None or packed['routes'][encoded['route']] not in selected:continue
        row=deepcopy(encoded); row.update(packed['contexts'][row.pop('context')])
        route=packed['routes'][row['route']]
        row.update(route=route,id=route+'|'+row['pointer'],shape_sha256=packed['shapes'][row.pop('shape')]); rows.append(row)
    assert len(rows)==93 and len(routes)==3
    return {'routes':[r for r in stored['routes'] if r['id'] in {route['public_route']for route in routes}],
        'native_coverage':{'candidate_sha256':'f'*64,'catalogs':stored['native_coverage']['catalogs'],'routes':routes,'obligations':rows}}


def public_read(path,version,rows,position):
    path.mkdir();context=runtime.program_source_context(flow=URI)
    client=_RuntimeControlDraftClient(path,version=version); fallback=client.call; trace=[]
    def call(uri,args=None,options=None):
        result=({'return':deepcopy(rows)}if uri==URI else {'return':99328}if uri.endswith('.getCursorTime')else fallback(uri,args,options))
        if uri=='ak.wwise.core.getInfo':
            year,major,minor,build=map(int,BUILDS[version].split('.'))
            result['version'].update(year=year,major=major,minor=minor,build=build,displayName='v'+BUILDS[version]);result['isCommandLine']=True
        trace.append({'ordinal':len(trace),'uri':uri,'args':deepcopy(args),'options':deepcopy(options),'result':deepcopy(result)})
        return result
    client.call=call;argv=['core-call',URI,'--profiler-position',position,'--max-results','64']
    code,payload=gateway.execute_gateway(['--state-dir',str(path/'state'),*argv],env=_env(path,version=version),client_factory=lambda _:client)
    assert code==0,payload
    assert payload['is_command_line'] is True and payload['agent_result']['return']==rows
    return {'argv':argv,'exit_code':code,'payload':payload},{k:trace[-1][k]for k in ('uri','args','options','result')},context,trace


@pytest.fixture(scope='module')
def published():return []


@pytest.mark.parametrize('version',('2023.1','2024.1','2025.1'))
def test_console_loaded_media_public_teardown_portable_consumer(request,tmp_path,inventory,version,published):
    # Import before public dispatch: the initial missing-adapter RED creates no
    # throwaway positive captures or duplicate Gateway transactions.
    from tests.support.loaded_media_runtime_evidence import write_console_bundle, console_review, console_basis
    profile=console_review()['profiles'][version]
    families=[([ROW],'99328'),([],str(profile['time'])),
        ([{**ROW,'fileName':'','format':'','soundBank':''}]*2,'0'),([ROW],'capture-latest'),([ROW],'user-cursor')]
    captures=[public_read(tmp_path/str(i),version,rows,position)for i,(rows,position)in enumerate(families)]
    def finalize(phases):
        paths=[]
        for i,(receipt,native,context,trace)in enumerate(captures):
            path=tmp_path/('capture-'+str(i)+'.json')
            runtime.write_program_receipt(path,receipt,native,nodeid=request.node.nodeid,phase_reports=phases,
                source_context=context,native_reads=trace,public_calls=[{'gateway':receipt,'native_start':0,'native_end':len(trace)}])
            paths.append(path)
        index=write_console_bundle(tmp_path/'bundle',paths,inventory=inventory,version=version)
        policies=json.loads(index.with_name(index.name.replace('index.json','requirements.json')).read_bytes())
        document,base,_=audit.portable_binding_inputs(index,policies)
        result=completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=policies)
        rows=[r for r in result['obligations']if r['route']==profile['route']]
        assert len(rows)==31 and {r['state']for r in rows}=={'verified'},json.dumps(rows)
        root=next(r for r in rows if r['id']==profile['gate'])
        assert root['requirements']==['program','native'] and root['representative_native_support']==console_basis(profile)
        assert all(r['requirements']==['program'] and r['runtime_native_anchor_status']=='passed'for r in rows if r['id']!=profile['gate'])
        assert sum('native'in b['evidence']for b in document['bindings'].values())==1
        if version=='2023.1':
            damage_controls(tmp_path,inventory,document,base,policies,profile)
            for damage in ('failed-phase','stale-source'):
                changed=json.loads(paths[0].read_bytes())
                if damage=='failed-phase':changed['phase_reports']['teardown']='failed'
                else:changed['source_context']['packaged']['skills/waapi-skill/scripts/gateway.py']='0'*64
                damaged=tmp_path/(damage+'.json');runtime.write_json(damaged,changed)
                destination=tmp_path/('rejected-'+damage)
                with pytest.raises(ValueError):
                    write_console_bundle(destination,[damaged,*paths[1:]],inventory=inventory,version=version)
                assert not(destination/('lm-console-'+version[:4]+'-index.json')).exists()
        published.append((index,policies))
        if version=='2025.1':
            assert len(published)==3
            common=tmp_path/'common';common.mkdir()
            joined={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[],'runtime_observation_attachments':[]}
            combined={'contract':policies['contract'],'branches':{}}
            for packet,policy in published:
                for source in packet.parent.iterdir():
                    assert not(common/source.name).exists();shutil.copyfile(source,common/source.name)
                source_index=json.loads(packet.read_bytes());joined['entries']+=source_index['entries'];joined['runtime_observation_attachments']+=source_index['runtime_observation_attachments']
                assert not(set(combined['branches'])&set(policy['branches']));combined['branches'].update(policy['branches'])
            runtime.write_json(common/'combined-index.json',joined)
            document,base,_=audit.portable_binding_inputs(common/'combined-index.json',combined)
            result=completion.evaluate_coverage(audit.ROOT,inventory,document,digest=audit.digest,evidence_base=base,requirements_document=combined)
            assert len(result['obligations'])==93 and {r['state']for r in result['obligations']}=={'verified'}
    register_exact_evidence_finalizer(request.node,finalize)


def damage_controls(tmp_path,inventory,document,base,policies,profile):
    original_binding=document['bindings'][profile['gate']]
    one={**inventory,'native_coverage':{**inventory['native_coverage'],'obligations':[r for r in inventory['native_coverage']['obligations']if r['id']==profile['gate']]}}
    policy={'contract':policies['contract'],'branches':{profile['gate']:policies['branches'][profile['gate']]}}
    copied=tmp_path/'damage';shutil.copytree(base,copied);base=copied
    for damage in ('availability','session','positive','current-replay','current-source','current-host','duplicate-read','public-row','phase','attachment','native-root'):
        binding=deepcopy(original_binding);proof=completion.read_sealed_artifact(binding['runtime_observation_attachment'],base)
        bridge=completion.read_sealed_artifact(proof['source_review'],base)
        if damage=='availability':bridge['availability_archive']['artifact']='missing-availability.json.gz'
        elif damage=='session':bridge['availability_context']['live']['sessionId']='{00000000-0000-0000-0000-000000000000}'
        elif damage=='positive':bridge['positive_archive']['artifact']='missing-positive.json.gz'
        elif damage=='current-replay':proof['program_capture']['artifact']='missing-current.json'
        elif damage in {'current-source','current-host','duplicate-read','public-row','phase'}:
            captured=completion.read_sealed_artifact(proof['program_capture'],base)
            if damage=='current-source':captured['source_context']['packaged']['skills/waapi-skill/scripts/gateway.py']='0'*64
            elif damage=='current-host':next(r for r in captured['native_reads']if r['uri']=='ak.wwise.core.getInfo')['result']['isCommandLine']=False
            elif damage=='duplicate-read':
                captured['native_reads'].append(deepcopy(captured['native_reads'][-1]));captured['native_reads'][-1]['ordinal']+=1;captured['public_calls'][0]['native_end']+=1
            elif damage=='public-row':captured['gateway']['payload']['agent_result']['return'][0]['size']+=1
            else:captured['phase_reports']['teardown']='failed'
            proof['program_capture']=runtime.write_json(base/('damaged-'+damage+'-capture.json'),captured)
        proof['source_review']=runtime.write_json(base/('damaged-'+damage+'-bridge.json'),bridge)
        binding['runtime_observation_attachment']=runtime.write_json(base/('damaged-'+damage+'-proof.json'),proof)
        equivalence=completion.read_sealed_artifact(binding['native_equivalence'],base)
        equivalence['loaded_media_source_review']=proof['source_review'];equivalence['binding_semantics_sha256']=audit.digest(completion.binding_semantics(binding))
        binding['native_equivalence']=runtime.write_json(base/('damaged-'+damage+'-equivalence.json'),equivalence)
        if damage=='attachment':binding.pop('runtime_observation_attachment')
        if damage=='native-root':binding['evidence'].pop('native')
        result=completion.evaluate_coverage(audit.ROOT,one,{'contract':document['contract'],'bindings':{profile['gate']:binding}},digest=audit.digest,evidence_base=base,requirements_document=policy)
        row,=result['obligations'];assert row['state']!='verified',(damage,row)
    missing=deepcopy(document);missing['bindings'][profile['gate']]['evidence'].pop('native')
    result=completion.evaluate_coverage(audit.ROOT,inventory,missing,digest=audit.digest,evidence_base=base,requirements_document=policies)
    assert all(r['state']!='verified'for r in result['obligations']if r['route']==profile['route'])


def test_console_loaded_media_exact_scope_and_canonical_parent_policy(inventory):
    from tests.support.loaded_media_runtime_evidence import console_branch,console_review
    from tests.support import runtime_remaining_evidence as remaining
    review=console_review();roots=[]
    for branch in inventory['native_coverage']['obligations']:
        _,profile,entry=console_branch(branch)
        assert entry==remaining.exact_entry(branch) and entry['family']=='console_loaded_media'
        if branch['pointer']=='/resultSchema':
            assert entry['categories']==['program','native'] and entry['required_native_anchor_ids']==[];roots.append(branch['id'])
        else:assert entry['categories']==['program'] and entry['required_native_anchor_ids']==[profile['gate']]
    assert len(roots)==3 and len(review['entries'])==93
    branch=inventory['native_coverage']['obligations'][0]
    for damaged in ({**branch,'route':branch['route'].replace('wwise-console','wwise-authoring')},
                    {**branch,'id':branch['id']+'/unlisted'}, {**branch,'shape_sha256':'0'*64},
                    {**branch,'owner_issue':187}):
        with pytest.raises(ValueError,match='exact reviewed Console'):
            console_branch(damaged)

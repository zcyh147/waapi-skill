"""Exact finalized R125 Console packets through the existing runtime observation transport."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support import fixed_runtime_read_evidence as fixed

FIXTURE = 'tests/fixtures/runtime-console-reads'
PROFILE_SHA = '7364ac3de8bcae4cea1b41bf45d9744fc0fb19df69a5659ad56d85865b72d0ca'
CANDIDATE = '0d56a083da7a7965d734df3e02c0fb5681a75c70'


def profiles(root=audit.ROOT):
    raw = (root / FIXTURE / 'r125-profiles.json').read_bytes()
    if runtime.sha(raw) != PROFILE_SHA:
        raise ValueError('Exact R125106-ID profile changed')
    return json.loads(raw)


def selected(identity, root=audit.ROOT):
    return identity in profiles(root)['selectors']


def profile_for_branch(branch, root=audit.ROOT):
    scope = profiles(root)
    for version, profile in scope['profiles'].items():
        for key, reader in profile['readers'].items():
            entry = reader['selectors'].get(branch['id'])
            if entry is not None:
                route = f"{version}|wwise-console|{profile['build']}|function|{reader['uri']}"
                if branch['route'] != route or branch['shape_sha256'] != entry['shape_sha256']:
                    raise ValueError('Exact R125 native route/host/version/build/shape differs')
                return version, key, profile, reader
    raise ValueError('Only exact106 new R125 selectors are eligible')


def reviewed_source_context(sources, root=audit.ROOT):
    current = runtime.program_source_context(root)['packaged']
    changes = {name:{'before':sources.get(name),'after':current.get(name)}
        for name in sources.keys() | current.keys() if sources.get(name) != current.get(name)}
    if (len(sources) != 413 or len(current) != 413
            or changes != {runtime.METER_SOURCE:runtime.METER_SOURCE_CHANGE, **runtime.LOG_MESSAGE_SOURCE_CHANGES}):
        return runtime.retained_runtime_sources(sources, root)
    return current


def original_observation(version, key, originals=None, root=audit.ROOT):
    scope = profiles(root); profile = scope['profiles'][version]; reader = profile['readers'][key]
    if not reader['selectors']:
        raise ValueError('Older Voices packets are provenance only; no redundant selector publication')
    base = Path(originals) if originals is not None else root / FIXTURE
    descriptor = {'artifact': version + '-original.json.gz', 'sha256': profile['archive_sha256']}
    read = runtime.archive_reader(descriptor, base)
    # The exact gzip seal covers the complete original node directory, not selected rows.
    import gzip
    encoded = json.loads(gzip.decompress((base / descriptor['artifact']).read_bytes()))['files']
    if len(encoded) != profile['archive_files'] or audit.digest(encoded) != profile['archive_decoded_map_sha256']:
        raise ValueError('R125 complete decoded original closure differs')
    category_descriptor = {'artifact': version + '-category.json', 'sha256': profile['category_sha256'], 'nodeid': scope['nodeid']}
    context = completion.read_category_run(category_descriptor, base)
    final = context['record']; capture_raw = read(profile['report']); capture = json.loads(capture_raw)
    history_raw = read(profile['root'] + '/evidence/category.jsonl')
    history = [json.loads(line) for line in history_raw.splitlines()]
    if (runtime.sha(history_raw) != profile['category_history_sha256'] or history[-1] != final
            or context['candidate'] != CANDIDATE or context['version'] != version
            or context['host'] != 'wwise-console' or context['build'] != profile['build']
            or final['invocation']['selected_test_nodeids'] != [scope['nodeid']]
            or final['invocation']['node_outcomes'] != [{'nodeid': scope['nodeid'], 'outcome': 'PASS'}]
            or [(x['category'],x['status']) for x in final['categories']] != [('console-runtime-read-batch','PASS'),('authoring-ui','blocked')]
            or final['categories'][0]['observation_path'] != profile['report']
            or final['categories'][0]['observation_sha256'] != profile['report_sha256']
            or runtime.sha(capture_raw) != profile['report_sha256']
            or final['residual_state']['sandbox'] != 'deleted' or final['residual_state']['residual_processes'] != []
            or final['source']['hash_before'] != final['source']['hash_after']
            or final['source']['mtime_before_ns'] != final['source']['mtime_after_ns']):
        raise ValueError('R125 original exact finalized node/host/source/cleanup differs')
    decision = json.loads(read(profile['root'] + '/decision.json'))
    if (decision['candidate'] != CANDIDATE or decision['version'] != version or decision['attempts'] != 1
            or decision['config_sha256'] != runtime.sha(read(profile['root'] + '/isolated-live-environment.json'))
            or capture['candidate'] != CANDIDATE or capture['version'] != version or capture['complete'] is not True
            or capture['errors'] != [] or capture['cleanup']['complete'] is not True or capture['cleanup']['errors'] != []
            or capture['fixture_before'] != capture['fixture_after'] or capture['capture_position']['position_ms'] != profile['time']):
        raise ValueError('R125 original complete read/config/preservation facts differ')
    source_raw = (root / FIXTURE / 'r125-source-map.json').read_bytes()
    if runtime.sha(source_raw) != scope['source_map_sha256']:
        raise ValueError('R125 original source map differs')
    source = json.loads(source_raw); sources = source['sources']
    if source['candidate'] != CANDIDATE:
        raise ValueError('R125 original full413 source candidate differs')
    reviewed_source_context(sources, root)
    outcome = capture['outcomes'][key]; evidence = outcome['evidence']; gateway = evidence['gateway_result']
    receipt, = [r for r in capture['calls'] if r['payload'] == gateway]
    raw = json.loads(read(reader['raw_path']))
    if (outcome['outcome'] != 'PASS' or evidence['complete'] is not True or evidence['nonempty'] is not True
            or evidence['owned_identity_observed'] is not True or evidence['position_ms'] != profile['time']
            or receipt['exit_code'] != 0 or receipt['argv'] != reader['public_argv']
            or gateway['call']['evidence_path'] != reader['raw_path'] or gateway['is_command_line'] is not True
            or gateway['ok'] is not True or runtime.sha(read(reader['raw_path'])) != reader['raw_sha256']
            or raw['api'] != reader['uri'] or raw['ok'] is not True or raw['version'] != version
            or raw['dry_run'] is not False or raw['error_code'] is not None):
        raise ValueError('R125 exact independent owned public/native read differs')
    voice = capture['outcomes']['voices']['evidence']['agent_result']['return'][0]
    if (voice['objectGUID'] != capture['fixture_before']['sound']['id']
            or voice['objectGUID'] != capture['transport_association']['object']
            or voice['gameObjectID'] != capture['transport_association']['gameObject']):
        raise ValueError('R125 independently queried owned Sound/transport association differs')
    data = raw['result']['return']; public = evidence['agent_result']
    if key in {'voices','busses','audio_objects','rtpcs'}:
        if (fixed.row_data(public['return']) != data or public['complete'] is not True
                or public['truncated'] is not False or public['total_count'] != len(data)):
            raise ValueError('R125 complete nontruncated native/public array differs')
        issuer = json.loads(read(reader['issuer_path']))
        if (runtime.sha(read(reader['issuer_path'])) != reader['issuer_sha256']
                or audit.digest({k:v for k,v in issuer.items() if k != 'sha256'}) != issuer['sha256']
                or issuer['plan']['request'] != reader['request']
                or audit.digest(issuer['plan']['result']) != public['snapshot_sha256']):
            raise ValueError('R125 exact original issued snapshot/request differs')
    if key == 'busses' and not all(data[i]['gameObjectID'] == voice['gameObjectID'] for i in evidence['owned_row_indexes']):
        raise ValueError('R125 owned runtime Bus association differs')
    if key == 'audio_objects':
        busses = capture['outcomes']['busses']['evidence']['agent_result']['return']
        if not all(any(row['gameObjectID']==b['gameObjectID']==voice['gameObjectID'] and row['busGUID']==b['objectGUID']
                and row['busPipelineID']==b['pipelineID'] for b in busses) for row in data):
            raise ValueError('R125 same-frame AudioObject/runtime Bus association differs')
    if key == 'rtpcs':
        rpm = capture['game_parameter']
        if rpm['type'] != 'GameParameter' or not any(r['id']==rpm['id'] and r['name']==rpm['name']
                and r['gameObjectId']==voice['gameObjectID'] for r in data):
            raise ValueError('R125 independently queried object-scoped RTPC identity differs')
    if key == 'game_objects':
        if not any(r['id']==voice['gameObjectID'] for r in data):
            raise ValueError('R125 owned GameObject identity differs')
    if key == 'contributions_dry':
        if (gateway['semantic_preview']['args'] != reader['request']['args'] or public['objects'] != data['objects']
                or evidence['selected_observed_voice']['objectGUID'] != voice['objectGUID']
                or reader['request']['args'] != {'voicePipelineID':voice['pipelineID'],'bussesPipelineID':[],'time':profile['time']}):
            raise ValueError('R125 owned voice/default dry-path contribution differs')
    return dict(profile=profile,reader=reader,context=context,capture=capture,capture_raw=capture_raw,
        read=read,raw=raw,raw_path=reader['raw_path'],request=reader['request'],receipt=receipt,
        sources=sources,archive=descriptor,category_descriptor=category_descriptor)


def write_bundle(output, program_path, *, inventory, version, key, name_prefix=""):
    """Add one exact finalized packet to an ordinary existing program bundle."""
    runtime.validate_runtime_file_prefix(name_prefix)
    original = original_observation(version,key); captured = json.loads(Path(program_path).read_bytes())
    selected_ids = set(original['reader']['selectors']); uri = original['reader']['uri']
    route, = [r for r in inventory['native_coverage']['routes'] if r['version']==version and r['host']=='wwise-console' and r['uri']==uri]
    if uri in fixed.URIS:
        mappings = fixed.mappings(inventory,captured,route,selected=selected_ids)
    elif uri == runtime.RTPC_URI:
        mappings = [{'branch':b,'reference_chain':[]} for b in inventory['native_coverage']['obligations'] if b['id'] in selected_ids]
    else:
        _,mappings = runtime.contribution_field_mappings(inventory,captured,version=version,host='wwise-console',selected=selected_ids)
    for mapping in mappings:
        mapping['program_pointer'] = '/native_call' + original['reader']['selectors'][mapping['branch']['id']]['native_pointer']
    if {m['branch']['id'] for m in mappings} != selected_ids:
        raise ValueError('Every selected R125 occurrence must be independently mapped')
    output = Path(output)
    if uri in fixed.URIS:
        index = fixed.write_fixed_bundle(output,program_path,None,inventory=inventory,selected=selected_ids,mappings=mappings,name_prefix=name_prefix)
    elif uri == runtime.RTPC_URI:
        index = runtime.write_field_bundle(output,program_path,None,inventory=inventory,version=version,host='wwise-console',mode='data',mappings=mappings,name_prefix=name_prefix)
    else:
        index = runtime.write_read_bundle(output,program_path,None,inventory=inventory,version=version,host='wwise-console',mode='r125-data',mappings=mappings,name_prefix=name_prefix)
    index_doc = json.loads(index.read_bytes())
    if uri not in fixed.URIS:
        for entry in index_doc['entries']: entry['id']=name_prefix+entry['id']
    bindings = completion.read_sealed_artifact(index_doc['entries'][0]['bindings'],output)['bindings']
    for filename in (version+'-original.json.gz',version+'-category.json'):
        shutil.copyfile(audit.ROOT/FIXTURE/filename,output/filename)
    def filename(name): return name_prefix+name
    def emit(name,value): return runtime.write_json(output/filename(name),value)
    def descriptor(name): return {'artifact':filename(name),'sha256':runtime.sha((output/filename(name)).read_bytes())}
    (output/filename('original-capture.json')).write_bytes(original['capture_raw'])
    (output/filename('original-raw.json')).write_bytes(original['read'](original['raw_path']))
    capture_descriptor = descriptor('original-capture.json'); raw_descriptor = descriptor('original-raw.json')
    native_run = {**original['category_descriptor'],'observation_sha256':[capture_descriptor['sha256'],raw_descriptor['sha256']]}
    native = {'candidate_sha256':inventory['native_coverage']['candidate_sha256'],'scope_kind':'product',
        'evidence_kind':'native_execution','relevant_sources':original['sources'],'native_runs':[native_run],
        'invocation':original['context']['record']['invocation'],
        'observation_artifacts':{'capture':capture_descriptor,'raw':raw_descriptor},'branch_assertions':{}}
    source_review = emit('r127-source-review.json', {
        'contract':'waapi-skill.runtime-read-source-review/v1', 'historical_candidate':CANDIDATE,
        'historical_sources':original['sources'], 'current_sources':captured['source_context']['packaged'],
        'changed_files':{runtime.METER_SOURCE:runtime.METER_SOURCE_CHANGE, **runtime.LOG_MESSAGE_SOURCE_CHANGES},
        'changed_symbols':{runtime.METER_SOURCE:runtime.METER_SOURCE_SYMBOLS, **runtime.LOG_MESSAGE_SOURCE_SYMBOLS},
        'scope':{'version':version,'key':key,'route':route['id']},
        'archive':original['archive'],'original_capture':capture_descriptor,
        'program_replay':index_doc['entries'][0]['origin']['capture']})
    attachments=[]
    for n,mapping in enumerate(mappings):
        branch=mapping['branch']; identity=branch['id'];binding=deepcopy(bindings[identity])
        native_pointer='/observations/raw'+original['reader']['selectors'][identity]['native_pointer']
        value=completion.pointer_value(original['raw'],original['reader']['selectors'][identity]['native_pointer'])
        checks=[{'pointer':native_pointer,'equals':value}]
        native['branch_assertions'][identity]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],'checks':checks}
        proof={'contract':'waapi-skill.runtime-observation-proof/v1','branch_id':identity,'native_shape_sha256':branch['shape_sha256'],
            'mapping':{'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'program_pointer':mapping['program_pointer'],
                'native_pointer':native_pointer,'reference_chain':mapping['reference_chain'],'native_checks':checks,
                'raw_observation':raw_descriptor,'raw_original_path':original['raw_path']},
            'native_run':native_run,'archive':original['archive'],'capture':capture_descriptor,
            'capture_original_path':original['profile']['report'],'program_capture':index_doc['entries'][0]['origin']['capture'],
            'relevant_sources':original['sources'],'source_review':source_review}
        proof_descriptor=emit(f'r125-proof-{n}.json',proof)
        binding.update(runtime_observation_attachment=proof_descriptor,program_observation_pointer=mapping['program_pointer'],
            observation_pointer=native_pointer,native_observations_sha256={'capture':capture_descriptor['sha256'],'raw':raw_descriptor['sha256']})
        equivalence={'contract':'waapi-skill.branch-evidence-equivalence/v1','from_candidate':CANDIDATE,
            'to_candidate':inventory['native_coverage']['candidate_sha256'],'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],
            'native_route':branch['route'],'evidence_sha256':native_run['sha256'],
            'binding_semantics_sha256':audit.digest(completion.binding_semantics(binding)),
            'reviewed_reason':'Exact finalized R125 Console read; complete current public replay and exact meter-only reviewed source delta;412 packaged paths unchanged; no control effect or rich44 claim',
            'sources':original['sources'],'runtime_read_review':source_review}
        attachments.append({'identity':identity,'proof':proof_descriptor,'equivalence':emit(f'r125-equivalence-{n}.json',equivalence)})
    nd={**emit('r125-native.json',native),'nodeid':native_run['nodeid']}
    index_doc['runtime_observation_attachments']=[emit(f'r125-attachment-{n}.json',{
        'contract':'waapi-skill.runtime-observation-attachment/v1','branch_id':a['identity'],
        'proof':a['proof'],'evidence':nd,'native_equivalence':a['equivalence']}) for n,a in enumerate(attachments)]
    runtime.write_json(index,index_doc)
    return index


def validate_evidence(record,binding,branch,category,base,root,edges):
    version,key,profile,reader=profile_for_branch(branch,root)
    proof=runtime._proof(binding,base); mapping=proof['mapping']; captured=completion.read_sealed_artifact(proof['program_capture'],base)
    if (category not in {'program','native'} or proof['branch_id']!=branch['id'] or proof['native_shape_sha256']!=branch['shape_sha256']
            or mapping['branch_id']!=branch['id'] or mapping['native_shape_sha256']!=branch['shape_sha256']
            or binding['observation_pointer']!=mapping['native_pointer'] or binding['program_observation_pointer']!=mapping['program_pointer']
            or mapping['reference_chain']!=binding['reference_chain']):
        raise ValueError('Exact R125 branch/reference observation binding differs')
    completion.exact_observation_pointer(branch,{**binding,'observation_pointer':mapping['program_pointer']},'/native_call','result',edges)
    completion.exact_observation_pointer(branch,binding,'/observations/raw','result',edges)
    if category=='program':
        if audit.digest(record['runtime_read_program'])!=audit.digest(captured):
            raise ValueError('R125 attached current program capture differs')
        if reader['uri'] in fixed.URIS: fixed.validate_program(record,binding,branch,root,edges)
        elif reader['uri']==runtime.RTPC_URI: runtime.validate_rtpc_program(record,binding,branch,root,edges)
        else: runtime.validate_contribution_program(record,binding,branch,root,edges)
        return
    original=original_observation(version,key,base,root)
    retained = runtime.retained_runtime_native(binding, branch, root, base)
    if retained:
        if original['sources'] != retained['sources']:
            raise ValueError('R125 retained original source map differs')
        runtime.retained_runtime_sources(original['sources'], root)
        if proof.get('source_review'):
            runtime.retained_runtime_source_review(proof['source_review'], original['sources'], branch, root, base)
    else:
        validate_source_review(proof.get('source_review', {}), original['sources'], branch, root, base)
    pointer=reader['selectors'][branch['id']]['native_pointer'];expected_native='/observations/raw'+pointer
    if (proof['archive']!=original['archive'] or proof['native_run']!=record['native_runs'][0] or len(record['native_runs'])!=1
            or proof['capture_original_path']!=profile['report'] or proof['relevant_sources']!=original['sources']
            or (base/proof['capture']['artifact']).read_bytes()!=original['capture_raw']
            or (base/mapping['raw_observation']['artifact']).read_bytes()!=original['read'](original['raw_path'])
            or record['observation_artifacts']!={'capture':proof['capture'],'raw':mapping['raw_observation']}
            or mapping['raw_original_path']!=original['raw_path'] or mapping['native_pointer']!=expected_native
            or mapping['program_pointer']!='/native_call'+pointer
            or record['branch_assertions'][branch['id']]['checks']!=[{'pointer':expected_native,'equals':completion.pointer_value(original['raw'],pointer)}]
            or mapping['native_checks']!=record['branch_assertions'][branch['id']]['checks']):
        raise ValueError('R125 exact whole original packet/owned occurrence differs')
    if runtime.retained_runtime_native(binding, branch, root, base):
        # Native-only origins retain the actual archived capture. Current code
        # support is selected separately; no current fake replay is reconstructed.
        return
    expected={'uri':reader['uri'],'args':original['request']['args'],'options':original['request']['options'],'result':original['raw']['result']}
    if audit.digest(captured['native_call'])!=audit.digest(expected):
        raise ValueError('R125 complete original request/options/array must survive current public replay')
    if key!='contributions_dry' and captured['gateway']['argv']!=original['receipt']['argv']:
        raise ValueError('R125 original public argv/time differs')
    if key=='contributions_dry':
        original_argv=original['receipt']['argv'];argv=captured['gateway']['argv'];position=argv.index('--voice-instance-handle')+1
        if argv[:position]!=original_argv[:position] or argv[position+1:]!=original_argv[position+1:] or argv[position]==original_argv[position]:
            raise ValueError('R125 dry path must reissue current same-frame Gateway voice authority')


def validate_source_review(descriptor, sources, branch, root, base):
    """Only exact106 R125 identities may bridge the reviewed meter and log-message deltas."""
    version,key,profile,reader = profile_for_branch(branch,root)
    runtime._portable_descriptor(descriptor,base)
    try:
        return runtime.retained_runtime_source_review(descriptor, sources, branch, root, base)
    except (ValueError, FileNotFoundError):
        pass
    review = completion.read_sealed_artifact(descriptor,base)
    current = reviewed_source_context(sources,root)
    expected = {'contract','historical_candidate','historical_sources','current_sources',
        'changed_files','changed_symbols','scope','archive','original_capture','program_replay'}
    if (set(review) != expected or review['contract'] != 'waapi-skill.runtime-read-source-review/v1'
            or review['historical_candidate'] != CANDIDATE or review['historical_sources'] != sources
            or review['current_sources'] != current
            or review['changed_files'] != {runtime.METER_SOURCE:runtime.METER_SOURCE_CHANGE, **runtime.LOG_MESSAGE_SOURCE_CHANGES}
            or review['changed_symbols'] != {runtime.METER_SOURCE:runtime.METER_SOURCE_SYMBOLS, **runtime.LOG_MESSAGE_SOURCE_SYMBOLS}
            or review['scope'] != {'version':version,'key':key,'route':branch['route']}):
        raise ValueError('R125 exact reviewed source/branch closure differs')
    original = original_observation(version,key,base,root)
    for name in ('archive','original_capture','program_replay'):
        runtime._portable_descriptor(review[name],base)
    replay = completion.read_sealed_artifact(review['program_replay'],base)
    if (sources != original['sources'] or review['archive'] != original['archive']
            or (base/review['original_capture']['artifact']).read_bytes() != original['capture_raw']
            or runtime.sha(original['capture_raw']) != review['original_capture']['sha256']
            or replay.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or replay.get('phase_reports') != dict.fromkeys(('setup','call','teardown'),'passed')
            or replay.get('source_unchanged') is not True
            or replay.get('source_context') != runtime.program_source_context(root,flow=reader['uri'])
            or replay['gateway']['exit_code'] != 0 or replay['gateway']['payload'].get('ok') is not True
            or replay['gateway']['payload'].get('is_command_line') is not True
            or audit.digest(replay['native_call']) != audit.digest({'uri':reader['uri'],
                'args':original['request']['args'],'options':original['request']['options'],'result':original['raw']['result']})):
        raise ValueError('R125 exact reviewed source complete current/original replay differs')

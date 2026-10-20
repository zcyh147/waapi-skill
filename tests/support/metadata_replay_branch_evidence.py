"""Current public replays of closed original R51/R54/R55 metadata observations.

Original native execution and current injected replay retain separate identities.
The existing shared finalizer publishes current product evidence only at teardown.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tests.maintenance import branch_coverage_audit as audit
from tests.support.metadata_read_branch_evidence import source_seals as metadata_source_seals
from tests.support.media_pool_branch_evidence import public_read_observation

ORIGINAL = '90c1089b77e9a9d5695224d312bff9a3ab8b5c18'
OBJECT = '{CE99046D-D354-422D-A7BB-F1305FF00B2F}'
URI = 'ak.wwise.core.object.getPropertyInfo'
NODE = 'tests/unit/test_metadata_discovery_gateway.py::test_original_r51_metadata_default_replays_through_current_public_gateway'
CASES = {'Color': 'Color-0', 'ControlInput': 'ControlInput-None', 'OverrideColor': 'OverrideColor-False'}
R54_ORIGINAL = '8a8d5f8e006fd56dd5c78ebe6429ee24450abf26'
R54_SOURCE_MAP_SHA256 = 'd747725b40ad86c1c7fbaa515f441b7b3b8137b6845faf0983a1282783d9a929'
R54_NODE = 'tests/unit/test_metadata_discovery_gateway.py::test_original_r54_class_metadata_replays_through_current_public_gateway'


R55_ORIGINAL = '860965d3368a92032061e5b3045c9a916d185b4b'
R55_SOURCE_MAP_SHA256 = 'b2226e4baef9518c7fd19e3b105ba08179e83c11035a227329424401a429d927'
R55_NODE = 'tests/unit/test_metadata_discovery_gateway.py::test_original_r55_class_metadata_replays_through_current_public_gateway'
R55_ORIGINAL_SEALS = {
    '2021.1':'430198f804dbbcfef95974b2e08b4982f24ad9fab3a642bcedf8ffe0dc7855c4',
    '2022.1':'26db7b59adb38a1ea5ae40b16c554cceb4795e3893870e9ecb31bb48caec39b2',
    '2023.1':'f7d964a60d23d364ca292e3dd89af129fa536d28d47a505b4caf799e22fe937e',
    '2024.1':'bb0588f23f9af5a8df9ce33c1dc8c1b903affa3dd5e2558fb629380ed8bb574b'}


def class_original_profile(cohort):
    if cohort not in ('r54','r55'):raise ValueError('Unreviewed original class cohort')
    return {'candidate':R54_ORIGINAL if cohort=='r54' else R55_ORIGINAL,
        'source_count':560 if cohort=='r54' else 561,
        'source_digest':R54_SOURCE_MAP_SHA256 if cohort=='r54' else R55_SOURCE_MAP_SHA256,
        'node':R54_NODE if cohort=='r54' else R55_NODE,'cases':16 if cohort=='r54' else 6,
        'branches':41 if cohort=='r54' else 10,
        'versions':('2021.1','2022.1','2023.1','2024.1','2025.1') if cohort=='r54' else tuple(R55_ORIGINAL_SEALS),
        'bridge_contract':'waapi-skill.'+cohort+'-class-metadata-leaf-replay/v1',
        'capture_contract':'waapi-skill.'+cohort+'-metadata-replay-context/v1'}


def class_original_reads(cohort,index_path=None,*,originals=None):
    """Two closed identities; portable anchors first, explicit preparatory inputs only."""
    import os
    from tests.maintenance import branch_audit_completion as completion
    from tests.maintenance.collect_class_metadata import metadata_descriptors,collection_plan
    profile=class_original_profile(cohort)
    path=Path(index_path) if index_path else audit.ROOT/'docs/branch-coverage-evidence-index.json'
    index=audit.load(path);base=(path.parent/index['base']).resolve();roots={}
    def register(original,base):
        original=deepcopy(original);root=(base/original['root']).resolve()
        seal=completion.read_sealed_artifact(original['seal'],base)
        entry,=[row for row in seal['files'] if row['path']=='plan.json'];raw=(root/'plan.json').read_bytes()
        if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('Original index-bound plan seal changed')
        plan=json.loads(raw)
        if plan['repositories'][0]['commit']!=profile['candidate']:return
        if plan.get('cohort','r54')!=cohort:raise ValueError('Closed original class native cohort changed')
        if cohort=='r55' and original['seal']['sha256']!=R55_ORIGINAL_SEALS.get(plan['version']):
            raise ValueError('Original accepted R55 seal anchor changed')
        original['root']=str(root);original['seal']['artifact']=str((base/original['seal']['artifact']).resolve())
        if root in roots:
            if original['seal']!=roots[root]['seal']:raise ValueError('Conflicting original index-bound seal')
        else:
            completion.read_metadata_run(original,base,historical_class=True);roots[root]=original
    if originals is None:
        for desc in index.get('metadata_attachments',[]):
            item=completion.read_sealed_artifact(desc,base)
            if item['contract']!='waapi-skill.class-metadata-attachment/v1':continue
            record=completion.read_sealed_artifact(item['evidence'],base);register(record['metadata_run'],base)
        # Transitional source-only input; committed portable originals win and
        # no historical absolute location is followed implicitly on other hosts.
        preparatory=os.environ.get('WAAPI_R55_CLASS_METADATA_ORIGINALS') if cohort=='r55' and index_path is None else None
        if not roots and preparatory:originals=json.loads(Path(preparatory).read_bytes())
    if originals is not None:
        for descriptor in originals.values():register(descriptor,audit.ROOT)
    found={}
    for root,original in sorted(roots.items()):
        for case,descriptor in metadata_descriptors(root).items():
            descriptor['seal']=deepcopy(original['seal'])
            if case in found:raise ValueError('Duplicate original class/field occurrence')
            found[case]=descriptor
    expected={v+'|'+scope+'|'+field for v in profile['versions']
        for scope,fields in collection_plan(v,cohort=cohort)['targets'].items() for field in fields}
    if set(found)!=expected or len(found)!=profile['cases']:
        raise ValueError('Complete closed original '+cohort+' class reads required')
    return found


def r54_original_reads(index_path=None):
    return class_original_reads('r54',index_path)


def r55_original_reads(index_path=None,*,originals=None):
    return class_original_reads('r55',index_path,originals=originals)


def validate_class_original_sources(candidate,sources,cohort):
    profile=class_original_profile(cohort)
    digest=hashlib.sha256(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if (candidate!=profile['candidate'] or len(sources)!=profile['source_count'] or digest!=profile['source_digest']
            or git_source_seals(candidate,sources)!=sources):
        raise ValueError('Exact full original '+cohort+' Git/source map changed')


def validate_r54_original_sources(candidate,sources):
    validate_class_original_sources(candidate,sources,'r54')


def r55_replay_case(case,descriptor=None,*,base=None):
    return r54_replay_case(case,descriptor,base=base,cohort='r55')


def r54_replay_case(case,descriptor=None,*,base=None,cohort='r54'):
    """Raw original response objects only, never normalized public reconstruction."""
    from tests.maintenance import branch_audit_completion as completion
    base=Path(base) if base else audit.ROOT
    descriptor=deepcopy(descriptor or class_original_reads(cohort)[case])
    context=completion.read_metadata_run(descriptor,base,historical_class=True)
    if context['cohort']!=cohort or case!='|'.join((context['version'],context['class_name'],context['field'])):
        raise ValueError('Exact original R54 class/field occurrence changed')
    root=Path(descriptor['root']);root=root if root.is_absolute() else base/root
    seal=completion.read_sealed_artifact(descriptor['seal'],base)
    entries={row['path']:row for row in seal['files']}
    def read(name):
        raw=(root/name).read_bytes();entry=entries[name]
        if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('Original R54 replay dependency digest/size changed')
        return json.loads(raw)
    target=read('targets.json')[descriptor['target_index']]
    listed=read(target['list_receipt']+'.stdout')
    name_dispatch,=[row for row in listed['calls'] if row['api']=='ak.wwise.core.object.getPropertyAndReferenceNames']
    packets={};hashes={}
    for name in entries:
        if not name.startswith('dispatcher-evidence/'):continue
        packet=read(name);api=packet['api']
        if api not in {'ak.wwise.core.getInfo','ak.wwise.core.getProjectInfo','ak.wwise.core.object.get',
                'ak.wwise.core.object.getTypes','ak.wwise.core.object.getPropertyAndReferenceNames'}:continue
        if api=='ak.wwise.core.object.getPropertyAndReferenceNames' and packet['evidence_path']!=name_dispatch['evidence_path']:continue
        if api not in packets:
            packets[api]=packet;hashes[api]=entries[name]['sha256']
    if ('ak.wwise.core.getInfo' not in packets or 'ak.wwise.core.object.getTypes' not in packets
            or 'ak.wwise.core.object.getPropertyAndReferenceNames' not in packets
            or context['field'] not in packets['ak.wwise.core.object.getPropertyAndReferenceNames']['result']['return']):
        raise ValueError('Original raw host/class/field replay inputs missing')
    return {'context':context,'packets':packets,'packet_sha256s':hashes,'descriptor':descriptor}


def r54_current_sources():
    from tests.maintenance.collect_class_metadata import source_links,collection_source_map,REPO
    return collection_source_map(source_links('',{})[1],REPO)


def make_r54_replay_receipt(capture,case,observed,reports):
    from tests.support.metadata_read_branch_evidence import _witness
    outcome='PASS' if all(reports.get(p)=='passed' for p in ('setup','call','teardown')) else 'FAIL'
    record={'candidate_sha256':capture['candidate_sha256'],'scope_kind':capture.get('scope_kind','product'),
        'evidence_kind':'injected_client_program','git_candidate':capture['git_candidate'],
        'relevant_sources':deepcopy(capture['relevant_sources']),
        'invocation':{'phase':'final','outcome':outcome,'node_outcomes':[{'nodeid':class_original_profile(capture.get('cohort','r54'))['node']+'['+case+']','outcome':outcome}]},
        **deepcopy(observed),'branch_assertions':{}}
    bindings={}
    for branch in capture['branches']:
        if branch['id'] not in capture['case_branch_ids'][case]:continue
        witness=_witness(branch,observed['native_call']['result'],capture['edges'])
        if witness is None:raise ValueError('Current replay did not observe original R54 leaf')
        public=witness['observation_pointer'].replace('/native_call/result','/gateway/payload/agent_result/metadata',1)
        record['branch_assertions'][branch['id']]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],
            'checks':[witness['check'],{**witness['check'],'pointer':public},
                {'pointer':'/gateway/payload/agent_result','equals':deepcopy(observed['gateway']['payload']['agent_result'])}]}
        bindings[branch['id']]={'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],
            'input':{'gateway_argv':deepcopy(observed['gateway']['argv']),'selector':'original_'+capture.get('cohort','r54')+'_class_field_replay'},
            'dispatch_pointer':'/native_call','observation_pointer':witness['observation_pointer'],
            'gateway_observation_pointer':public,'reference_chain':witness['reference_chain']}
    return record,bindings


def make_r54_attachment_record(capture,case,replay_descriptor,replay_record,replay_bindings,*,base):
    from tests.maintenance import branch_audit_completion as completion
    context=completion.read_metadata_run(capture['originals'][case],base,historical_class=True)
    profile=class_original_profile(capture.get('cohort','r54'))
    if context['cohort']!=capture.get('cohort','r54'):raise ValueError('Original/current class cohort differs')
    record={'candidate_sha256':capture['candidate_sha256'],'scope_kind':capture.get('scope_kind','product'),
        'evidence_kind':'historical_class_metadata_current_program_replay','metadata_run':deepcopy(capture['originals'][case]),
        'invocation':deepcopy(replay_record['invocation']),'replay':deepcopy(replay_descriptor),
        'replay_bindings':deepcopy(replay_bindings),'source_bridge':{'contract':profile['bridge_contract'],
            'attribution':'historical_native_current_program_not_current_native','historical_candidate':profile['candidate'],
            'historical_sources':deepcopy(capture['historical_sources']),'current_sources':deepcopy(capture['relevant_sources']),
            'changed_files':source_changes(capture['historical_sources'],capture['relevant_sources'])},
        'branch_assertions':{},'category_inputs':{'historical':context['gateway']['argv'],'replay':replay_record['gateway']['argv']}}
    for branch in capture['branches']:
        if branch['id'] not in replay_bindings:continue
        record['branch_assertions'][branch['id']]={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],
            'checks':[{'pointer':replay_bindings[branch['id']]['gateway_observation_pointer'],
                'equals':deepcopy(context['native_result']['default'])},
                {'pointer':'/gateway/payload/agent_result','equals':deepcopy(context['gateway']['payload']['agent_result'])}]}
    return record


def replay_case(field):
    if field not in CASES:
        raise ValueError('Unreviewed R51 replay field')
    return json.loads((audit.ROOT / 'tests/support/metadata_replay_cases.json').read_text())


def source_seals():
    sources = metadata_source_seals()
    for name in ('tests/support/metadata_replay_cases.json', 'tests/support/metadata_replay_branch_evidence.py',
                 'tests/unit/test_metadata_replay_attachments.py', 'docs/branch-coverage-requirements.json'):
        sources[name] = hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest()
    return dict(sorted(sources.items()))


def replay_observation(argv, code, payload, client, field, list_argv, listed):
    packet = replay_case(field)['packets'][field]['native']
    calls = [(uri, args, options) for uri, args, options in client.calls if uri == URI]
    if len(calls) != 1:
        raise ValueError('Replay needs one exact getPropertyInfo dispatch')
    uri, args, options = calls[0]
    return {**public_read_observation(gateway_argv=argv, exit_code=code, payload=payload,
        uri=uri, args=args, options=options, result=packet['result']),
        'discovery': {'argv': deepcopy(list_argv), 'payload': deepcopy(listed)},
        'client_disconnected': client.disconnected, 'replayed_original_native_sha256': replay_case(field)['packets'][field]['original_sha256']}


def _descriptor(path, **extra):
    return {'artifact': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(), **extra}


def original_read(root, field):
    """Describe preserved R51 bytes; never repair, copy, or regrade originals."""
    if field not in CASES:
        raise ValueError('Unreviewed R51 replay field')
    root = Path(root)
    category = root / 'category.jsonl'
    rows = category.read_bytes().splitlines()
    final = json.loads(rows[-1])
    observation = next(row for row in final['categories'] if row['category'] == 'legacy-original-source-owned-read')
    body_path = Path(observation['observation_path'])
    body = json.loads(body_path.read_bytes())
    calls = [(i, row) for i, row in enumerate(body['calls']) if row['argv'][:4] == ['metadata', 'detail', '--exact-id', OBJECT]
             and json.loads(Path(row['reply']['path']).read_bytes())['agent_result']['metadata']['name'] == field]
    (index, call), = calls
    reply = json.loads(Path(call['reply']['path']).read_bytes())
    native_path = next(row['evidence_path'] for row in reply['calls'] if row['api'] == URI)
    native = next(row for row in body['native_evidence'] if row['native_path'] == native_path)
    return {'contract': 'waapi-skill.r51-metadata-read/v1',
        'category': _descriptor(category, record_index=len(rows)-1, nodeid=final['invocation']['node_outcomes'][0]['nodeid']),
        'observation': _descriptor(body_path), 'status': _descriptor(Path(body['calls'][0]['reply']['path'])),
        'identity': _descriptor(Path(body['calls'][3]['reply']['path'])),
        'reply': _descriptor(Path(call['reply']['path'])), 'native': _descriptor(Path(native['path'])), 'call_index': index}


def portable_original_reads(index_path=None):
    """Resolve committed sealed transport, without following historical host paths.

    Original/source-freeze Git objects are still required by the later full
    source bridge; portable receipt transport does not imply shallow support.
    """
    from tests.maintenance import branch_audit_completion as completion
    index_path = Path(index_path) if index_path else audit.ROOT/'docs/branch-coverage-evidence-index.json'
    requirements = audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    bindings,base,_ = audit.portable_binding_inputs(index_path,requirements)
    originals = {}
    for identity,binding in bindings['bindings'].items():
        evidence = binding.get('evidence',{}).get('live_metadata')
        if identity not in selected_ids() or evidence is None:
            continue
        record = completion.read_sealed_artifact(evidence,base)
        descriptor = deepcopy(record['metadata_run'])
        context = completion.read_metadata_run(descriptor,base)
        field = context['native_result']['name']
        for role in ('category','observation','status','identity','reply','native'):
            descriptor[role]['artifact'] = str((base/descriptor[role]['artifact']).resolve())
        if field in originals and originals[field] != descriptor:
            raise ValueError('Conflicting portable original metadata read')
        originals[field] = descriptor
    return originals


def selected_ids():
    prefix = '2021.1|wwise-console|2021.1.14.8108|function|' + URI + '|'
    definition = '/resultSchema/@definition/waapi_definitions.json/definitions/propertyValue'
    pointers = ['/resultSchema/properties/default/@presence/present', '/resultSchema/properties/default',
        '/resultSchema/properties/default/$ref', definition, definition+'/anyOf/0', definition+'/anyOf/0/@nullable',
        definition+'/anyOf/2', definition+'/anyOf/3', definition+'/anyOf/3/@boolean/false']
    return {prefix+p for p in pointers}


def selected_branches(inventory):
    rows = [row for row in inventory['native_coverage']['obligations'] if row['id'] in selected_ids()]
    if len(rows) != 9:
        raise ValueError('Exact nine R51 default obligations changed')
    return rows


def branch_case(branch):
    pointer = branch['pointer']
    return 'ControlInput' if '/anyOf/0' in pointer else 'OverrideColor' if '/anyOf/3' in pointer else 'Color'


def git_source_seals(candidate, names):
    import subprocess
    names = list(names)
    result = subprocess.run(['git', 'cat-file', '--batch'], cwd=audit.ROOT, check=True,
        input=''.join(candidate+':'+name+'\n' for name in names).encode(), stdout=subprocess.PIPE).stdout
    position, sources = 0, {}
    for name in names:
        end = result.index(b'\n', position)
        header = result[position:end].decode()
        if header.endswith(' missing'):
            raise ValueError('Full committed metadata source closure unavailable')
        count = int(header.rsplit(' ', 1)[1]); position = end+1
        sources[name] = hashlib.sha256(result[position:position+count]).hexdigest(); position += count+1
    return dict(sorted(sources.items()))


def historical_sources():
    names = metadata_source_seals()
    # These exact reviewed Source-copy modules did not exist in R51. Keep
    # both explicit absences in source_changes; never invent historical hashes.
    for name in ('source_copy_observations.py','source_copy_proof.py'):
        names.pop('skills/waapi-skill/wwise_waapi/'+name,None)
    return git_source_seals(ORIGINAL, names)

def source_changes(before, after):
    return {name: {'before': before.get(name), 'after': after.get(name)} for name in sorted(set(before)|set(after))
            if before.get(name) != after.get(name)}


def make_replay_receipt(capture, field, observed, reports):
    from tests.support.metadata_read_branch_evidence import _witness
    outcome = 'PASS' if all(reports.get(phase) == 'passed' for phase in ('setup', 'call', 'teardown')) else 'FAIL'
    record = {'candidate_sha256': capture['candidate_sha256'], 'scope_kind': capture.get('scope_kind', 'product'),
        'evidence_kind': 'injected_client_program', 'git_candidate': capture['git_candidate'],
        'relevant_sources': deepcopy(capture['relevant_sources']), 'invocation': {'phase': 'final', 'outcome': outcome,
            'node_outcomes': [{'nodeid': NODE+'['+CASES[field]+']', 'outcome': outcome}]},
        **deepcopy(observed), 'branch_assertions': {}}
    bindings = {}
    for branch in capture['branches']:
        if branch_case(branch) != field:
            continue
        witness = _witness(branch, observed['native_call']['result'], capture['edges'])
        if witness is None:
            raise ValueError('Actual current replay did not observe the selected branch')
        public_pointer = witness['observation_pointer'].replace('/native_call/result','/gateway/payload/agent_result/metadata',1)
        checks = [witness['check'], {**deepcopy(witness['check']), 'pointer': public_pointer},
            {'pointer':'/gateway/payload/agent_result','equals':deepcopy(observed['gateway']['payload']['agent_result'])}]
        record['branch_assertions'][branch['id']] = {'native_shape_sha256':branch['shape_sha256'], 'native_route':branch['route'], 'checks':checks}
        bindings[branch['id']] = {'branch_id':branch['id'], 'native_shape_sha256':branch['shape_sha256'],
            'input':{'gateway_argv':deepcopy(observed['gateway']['argv']), 'selector':'original_R51_exact_object_field_replay'},
            'dispatch_pointer':'/native_call', 'observation_pointer':witness['observation_pointer'],
            'gateway_observation_pointer':public_pointer, 'reference_chain':witness['reference_chain']}
    return record, bindings


def make_attachment_record(capture, field, replay_descriptor, replay_record, replay_bindings, *, base):
    from tests.maintenance import branch_audit_completion as completion
    context = completion.read_metadata_run(capture['originals'][field], base)
    record = {'candidate_sha256':capture['candidate_sha256'], 'scope_kind':capture.get('scope_kind','product'),
        'evidence_kind':'historical_metadata_current_program_replay', 'metadata_run':deepcopy(capture['originals'][field]),
        'invocation':deepcopy(replay_record['invocation']), 'replay':deepcopy(replay_descriptor),
        'replay_bindings':deepcopy(replay_bindings), 'source_bridge':{'contract':'waapi-skill.r51-metadata-leaf-replay/v1',
            'attribution':'historical_native_current_program_not_current_native',
            'historical_candidate':ORIGINAL, 'historical_sources':deepcopy(capture['historical_sources']),
            'current_sources':deepcopy(capture['relevant_sources']),
            'changed_files':source_changes(capture['historical_sources'],capture['relevant_sources'])},
        'branch_assertions':{}, 'category_inputs':{'historical':context['gateway']['argv'], 'replay':replay_record['gateway']['argv']}}
    for branch in capture['branches']:
        if branch['id'] not in replay_bindings:
            continue
        pointer = replay_bindings[branch['id']]['gateway_observation_pointer']
        record['branch_assertions'][branch['id']] = {'native_shape_sha256':branch['shape_sha256'], 'native_route':branch['route'],
            'checks':[{'pointer':pointer,'equals':deepcopy(context['gateway']['payload']['agent_result']['metadata']['default'])},
                {'pointer':'/gateway/payload/agent_result','equals':deepcopy(context['gateway']['payload']['agent_result'])}]}
    return record


def prepare_capture(root, original_root):
    """After source approval only: one fresh context, three selected public nodes."""
    import subprocess
    import shutil
    import gzip
    from tests.maintenance import branch_audit_completion as completion
    from tests.support.media_pool_branch_evidence import _git_candidate, _write
    if subprocess.check_output(['git','status','--porcelain'],cwd=audit.ROOT,text=True).strip():
        raise ValueError('Product metadata replay needs a clean committed source')
    root = Path(root).resolve()
    root.mkdir(parents=True,exist_ok=False)
    (root/'originals').mkdir()
    inventory = audit.build_inventory()
    rows = selected_branches(inventory)
    policy = audit.load(audit.ROOT/'docs/branch-coverage-requirements.json')
    assigned = {identity for identity,p in policy['branches'].items() if '|wwise-console|' in identity
        and '|function|'+URI+'|' in identity and p['categories'] == ['program','live_metadata']}
    if len(assigned) != 65 or not {row['id'] for row in rows} <= assigned:
        raise ValueError('Original65 default requirements changed')
    for row in rows:
        if policy['branches'][row['id']]['native_shape_sha256'] != row['shape_sha256']:
            raise ValueError('Exact original default requirement shape changed')
    originals = {}
    for field in CASES:
        original = original_read(original_root,field)
        completion.read_metadata_run(original,root.parent)
        for role in ('category','observation','status','identity','reply','native'):
            desc = original[role]
            name = role+'.original.json' if role in ('category','observation','status','identity') else field+'-'+role+'.original.json'
            dest = root/'originals'/name
            raw = Path(desc['artifact']).read_bytes()
            if dest.exists():
                if dest.read_bytes() != raw:
                    raise ValueError('Conflicting original metadata archive')
            else:
                shutil.copyfile(desc['artifact'],dest)
                if dest.read_bytes() != raw:
                    raise ValueError('Original metadata copy differs')
            desc['artifact'] = root.name+'/originals/'+name
        originals[field] = original
    context = {'contract':'waapi-skill.r51-metadata-replay-context/v1','root':str(root),
        'candidate_sha256':inventory['native_coverage']['candidate_sha256'],'git_candidate':_git_candidate(),
        'relevant_sources':source_seals(),'historical_sources':historical_sources(), 'originals':originals,
        'branches':rows,'edges':{r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'
            and r['route'] == rows[0]['route']},
        'assigned_unobserved_branch_ids':sorted(assigned-{row['id'] for row in rows})}
    with gzip.open(root/'frozen-inventory.json.gz','wt',encoding='utf-8') as stream:
        json.dump(inventory,stream,separators=(',',':'))
    _write(root/'context.json',context)
    return root/'context.json'


def load_capture(path, nodeid, field):
    from tests.support.media_pool_branch_evidence import _git_candidate
    context = json.loads(Path(path).read_bytes())
    if (context['contract'] != 'waapi-skill.r51-metadata-replay-context/v1' or field not in CASES
            or nodeid != NODE+'['+CASES[field]+']' or context['git_candidate'] != _git_candidate()
            or context['relevant_sources'] != source_seals() or context['historical_sources'] != historical_sources()):
        raise ValueError('Prepared current replay node or full source closure changed')
    return context


def finish_capture(capture, reports, observed):
    from tests.support.media_pool_branch_evidence import _git_candidate, _write
    field = observed['native_call']['result']['name']
    root = Path(capture['root'])
    unchanged = capture['git_candidate'] == _git_candidate() and capture['relevant_sources'] == source_seals()
    replay,bindings = make_replay_receipt(capture,field,observed,reports if unchanged else {})
    dest = root/field;dest.mkdir(exist_ok=False)
    program = _write(dest/'program.json',replay)
    program['artifact'] = root.name+'/'+field+'/program.json'
    program['nodeid'] = NODE+'['+CASES[field]+']'
    record = make_attachment_record(capture,field,program,replay,bindings,base=root.parent)
    receipt = _write(dest/'live-metadata.json',record)
    receipt['artifact'] = root.name+'/'+field+'/live-metadata.json'
    receipt['nodeid'] = program['nodeid']
    attachments = []
    for branch in capture['branches']:
        if branch['id'] not in bindings:
            continue
        item = {'contract':'waapi-skill.r51-metadata-attachment/v1','branch_id':branch['id'],
            'native_shape_sha256':branch['shape_sha256'],'category_inputs':record['category_inputs'],'evidence':receipt}
        descriptor = _write(dest/('attachment-'+str(len(attachments))+'.json'),item)
        descriptor['artifact'] = root.name+'/'+field+'/'+Path(descriptor['artifact']).name
        attachments.append(descriptor)
    _write(dest/'attachments.json',{'metadata_attachments':attachments})
    _write(dest/'capture.json',{'outcome':replay['invocation']['outcome'],'source_unchanged':unchanged,
        'phase_reports':reports,'observed_branch_ids':sorted(bindings),
        'attribution':'historical_native_current_program_not_current_native'})



def r54_case_assignments(branches,edges,contexts):
    from tests.support.metadata_read_branch_evidence import _witness
    used=set();owners={}
    for case,context in contexts.items():
        owned=[r['id'] for r in branches if r['id'] not in used and r['route'].split('|')[0]==context['version']
            and _witness(r,context['native_result'],edges) is not None]
        owners[case]=owned;used.update(owned)
    if used!={r['id'] for r in branches}:raise ValueError('Original R54 facts do not witness all exact assigned leaves')
    return owners


def prepare_r54_capture(root,*,cohort='r54',source_originals=None):
    """After review: same finalizer/transport, sixteen R54 or six R55 public nodes."""
    import subprocess,shutil,gzip
    from tests.maintenance import branch_audit_completion as completion
    from tests.maintenance.collect_class_metadata import collection_plan
    from tests.support.media_pool_branch_evidence import _git_candidate,_write
    if subprocess.check_output(['git','status','--porcelain'],cwd=audit.ROOT,text=True).strip():
        raise ValueError('Current R54 replay requires a clean source pin')
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    profile=class_original_profile(cohort)
    inventory=audit.build_inventory();source_originals=class_original_reads(cohort,originals=source_originals);originals={};contexts={}
    copied={}
    for case,descriptor in source_originals.items():
        context=completion.read_metadata_run(descriptor,audit.ROOT,historical_class=True);contexts[case]=context
        original_root=Path(descriptor['root'])
        if original_root not in copied:
            dest=root/'originals'/original_root.name;dest.mkdir(parents=True,exist_ok=False)
            seal=completion.read_sealed_artifact(descriptor['seal'],audit.ROOT)
            for entry in seal['files']:
                path=original_root/entry['path'];raw=path.read_bytes()
                if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                    raise ValueError('Original R54 archive changed before replay preparation')
                target=dest/entry['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            shutil.copyfile(original_root/'evidence-seal.json',dest/'evidence-seal.json');copied[original_root]=dest
        item=deepcopy(descriptor);item['root']=root.name+'/originals/'+original_root.name
        item['seal']['artifact']=item['root']+'/evidence-seal.json';originals[case]=item
    assigned=set().union(*(set(collection_plan(v,cohort=cohort)['eligible_branch_ids']) for v in profile['versions']))
    branches=[r for r in inventory['native_coverage']['obligations'] if r['id'] in assigned]
    if len(branches)!=profile['branches']:raise ValueError('Closed original class requirement set changed')
    edges={r['id']:r for r in inventory['native_coverage']['obligations'] if r['kind']=='reference'}
    owners=r54_case_assignments(branches,edges,contexts)
    context={'contract':profile['capture_contract'],'cohort':cohort,'root':str(root),
        'candidate_sha256':inventory['native_coverage']['candidate_sha256'],'git_candidate':_git_candidate(),
        'relevant_sources':r54_current_sources(),'historical_sources':next(iter(contexts.values()))['relevant_sources'],
        'originals':originals,'case_branch_ids':owners,'branches':branches,'edges':edges}
    with gzip.open(root/'frozen-inventory.json.gz','wt',encoding='utf-8') as stream:json.dump(inventory,stream)
    _write(root/'context.json',context);return root/'context.json'


def load_r54_capture(path,nodeid,case):
    from tests.support.media_pool_branch_evidence import _git_candidate
    capture=json.loads(Path(path).read_bytes())
    profile=class_original_profile(capture.get('cohort','r54'))
    if (capture['contract']!=profile['capture_contract'] or case not in capture['originals']
            or nodeid!=class_original_profile(capture.get('cohort','r54'))['node']+'['+case+']' or capture['git_candidate']!=_git_candidate()
            or capture['relevant_sources']!=r54_current_sources()):
        raise ValueError('Current R54 public replay source/node changed')
    validate_class_original_sources(profile['candidate'],capture['historical_sources'],capture.get('cohort','r54'))
    return capture


def finish_r54_capture(capture,reports,case,observed):
    from tests.support.media_pool_branch_evidence import _git_candidate,_write
    root=Path(capture['root']);unchanged=capture['git_candidate']==_git_candidate() and capture['relevant_sources']==r54_current_sources()
    program,bindings=make_r54_replay_receipt(capture,case,observed,reports if unchanged else {})
    dest=root/('case-'+str(list(capture['originals']).index(case)));dest.mkdir(exist_ok=False)
    descriptor=_write(dest/'program.json',program);descriptor.update(artifact=root.name+'/'+dest.name+'/program.json',nodeid=class_original_profile(capture.get('cohort','r54'))['node']+'['+case+']')
    record=make_r54_attachment_record(capture,case,descriptor,program,bindings,base=root.parent)
    evidence=_write(dest/'live-metadata.json',record);evidence.update(artifact=root.name+'/'+dest.name+'/live-metadata.json',nodeid=descriptor['nodeid'])
    attachments=[]
    for branch in capture['branches']:
        if branch['id'] not in bindings:continue
        item={'contract':'waapi-skill.class-metadata-attachment/v1','branch_id':branch['id'],
            'native_shape_sha256':branch['shape_sha256'],'category_inputs':record['category_inputs'],'evidence':evidence}
        desc=_write(dest/('attachment-'+str(len(attachments))+'.json'),item)
        desc['artifact']=root.name+'/'+dest.name+'/'+Path(desc['artifact']).name;attachments.append(desc)
    _write(dest/'attachments.json',{'metadata_attachments':attachments})
    _write(dest/'capture.json',{'outcome':program['invocation']['outcome'],'source_unchanged':unchanged,
        'phase_reports':reports,'observed_branch_ids':sorted(bindings),'attribution':'historical_native_current_program_not_current_native'})

"""Three current public replays of original R51 native metadata packets.

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
    # This explicitly reviewed Source-copy module did not exist in R51. Keep
    # its absence in source_changes(before, current); never invent an old hash.
    names.pop('skills/waapi-skill/wwise_waapi/source_copy_observations.py',None)
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

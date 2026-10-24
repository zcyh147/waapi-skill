"""One reviewed 9262 LoadedMedia fact; no alternate-build execution mechanism."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime
from tests.support import fixed_runtime_read_evidence as fixed

URI = 'ak.wwise.core.profiler.getLoadedMedia'
ROUTE = '2025.1|wwise-authoring|2025.1.7.9143|function|' + URI
ANCHOR = ROUTE + '|/resultSchema/properties/return/@cardinality/single'
FIXTURE = 'tests/fixtures/runtime-loaded-media'
REVIEW_SHA = 'b0c96141eb54a2ff058bde6e846a03d91f33def3a8ff010bdcd054fc2a8ae2c3'
ORIGINAL_CANDIDATE = '7289081b552c5f428013ba0b6bacaf7d05843481'
PREFIX = '/private/tmp/waapi-r122-demo-native-r4/evidence/'
CATEGORY = 'profiler-loaded-media-observation'
BASIS = {'catalog_build': '2025.1.7.9143', 'observed_build': '2025.1.11.9262',
         'basis': 'exact_reviewed_representative_support'}


def review(root=audit.ROOT):
    path = root / FIXTURE / 'support-review.json'
    if runtime.sha(path.read_bytes()) != REVIEW_SHA:
        raise ValueError('Exact LoadedMedia support descriptor missing or changed')
    result = json.loads(path.read_bytes())
    if (result['route'] != ROUTE or result['anchor_id'] != ANCHOR or len(result['entries']) != 31
            or any(result[key] != value for key, value in BASIS.items())):
        raise ValueError('Exact LoadedMedia representative scope differs')
    baseline = result['prior_policy_absent']
    import subprocess
    original_blob = subprocess.run(['git', 'show', baseline['candidate'] + ':' + baseline['path']],
        cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    original = original_blob.stdout
    if (original_blob.returncode or runtime.sha(original) != baseline['sha256']
            or set(result['entries']) & set(json.loads(original)['branches'])):
        raise ValueError('LoadedMedia prior-policy absence baseline changed')
    published = json.loads((root / baseline['path']).read_bytes())['branches']
    if any(identity in published and published[identity] != policy(entry)
            for identity, entry in result['entries'].items()):
        raise ValueError('Unreviewed published LoadedMedia policy differs')
    for name, seal in result['files'].items():
        if runtime.sha((root / FIXTURE / name).read_bytes()) != seal:
            raise ValueError('Original LoadedMedia source-owned closure changed: ' + name)
    # Primary installed documentation states the selected business meaning; the
    # reflected description alone is not used as a behavioral compatibility rule.
    text = (root / FIXTURE / 'documented-api.html').read_text()
    if not all(token in text for token in ('loaded media at a specific profiler capture time', 'PrepareEvent()', 'PrepareGameSyncs()', 'size (in bytes)')):
        raise ValueError('Selected LoadedMedia documented business meaning differs')
    return result


def exact_branch(branch, root=audit.ROOT):
    r = review(root); entry = r['entries'].get(branch['id'])
    if not entry or any(branch.get(key) != entry[key] for key in ('route', 'pointer', 'kind', 'shape_sha256', 'owner_issue', 'parent_issue', 'blocks_issue')):
        raise ValueError('LoadedMedia requires one exact reviewed catalog branch/shape')
    return r, entry


def policy(entry):
    return {'native_shape_sha256': entry['shape_sha256'], 'categories': entry['categories'],
            'reason': ('Exact actual9262 prepared-media semantic anchor; no9143 execution or arbitrary patch equivalence'
                       if entry['categories'] == ['program', 'native'] else
                       'SPEC section5 deterministic LoadedMedia request/field/collection preservation; conditional on exact actual9262 semantic anchor; no native codec/value occurrence claim')}


def preservation_gates(root, policies, obligations):
    selected = [b for b in obligations if b['route'] == ROUTE and b['id'] in policies]
    if not selected: return {}
    r = review(root)
    return {b['id']: ([ANCHOR] if b['id'] != ANCHOR else []) if policies[b['id']] == policy(r['entries'][b['id']])
            and b['shape_sha256'] == r['entries'][b['id']]['shape_sha256'] else None
            for b in selected}


def original_observation(originals=None, *, root=audit.ROOT):
    """Recheck the complete strict-PASS archive, not a manufactured native row."""
    r = review(root); base = Path(originals) if originals is not None else root / FIXTURE
    def descriptor(name): return {'artifact': name, 'sha256': r['files'][name]}
    read = runtime.archive_reader(descriptor('r124-originals.json.gz'), base)
    context = completion.read_category_run({**descriptor('r124-category.json'), 'nodeid': r['nodeid']}, base)
    if {key: context[key] for key in ('version', 'host', 'build', 'candidate')} != {
            'version': '2025.1', 'host': 'wwise-authoring', 'build': BASIS['observed_build'], 'candidate': ORIGINAL_CANDIDATE}:
        raise ValueError('Exact original LoadedMedia actual9262 Authoring context required')
    run = context['record']
    completion.validate_authoring_batch_finalization(run, base, read_bytes=read)
    if (len(run['categories']) != 1 or run['categories'][0]['category'] != CATEGORY
            or run['categories'][0]['observation_build'] != BASIS['observed_build']
            or run['categories'][0]['preparation_or_streaming_control_effect_verified'] is not False):
        raise ValueError('Original LoadedMedia finalized reader/effect boundary differs')
    seal = json.loads(read(run['categories'][0]['batch_finalization']['artifact']))
    node_path = seal['observations'][r['nodeid']]['path']; node_raw = read(node_path); node = json.loads(node_raw)
    sources = node['source_context']['sources']
    if (runtime.sha(node_raw) != r['node_sha256'] or len(sources) != r['original_source_count']
            or audit.digest(sources) != r['original_sources_sha256']
            or completion.historical_source_seals(root, ORIGINAL_CANDIDATE, sources) != sources):
        raise ValueError('Original LoadedMedia complete620-source Git closure differs')
    archived = {PurePosixPath(g['path']).joinpath(f['path']).as_posix(): f for g in node['artifacts'].values() for f in g['files']}
    if len(archived) != 97 or sum(v['bytes'] for v in archived.values()) != 1053616:
        raise ValueError('Original LoadedMedia complete97-artifact closure differs')
    capture_path, = [name for name in archived if name.endswith('/profiler-capture.json')]
    capture_raw = read(capture_path); capture = json.loads(capture_raw)
    outcome = capture['outcomes'][CATEGORY]
    if (outcome['outcome'] != 'PASS' or capture['complete'] is not True or capture['errors']
            or capture['cleanup']['complete'] is not True or capture['capture_position']['position_ms'] != r['time']
            or outcome['evidence']['attributed_rows'] != r['native_result']['return']
            or outcome['evidence']['unrelated_rows'] != []
            or outcome['evidence']['preparation_or_streaming_control_effect_verified'] is not False):
        raise ValueError('Original LoadedMedia attributed positive/cleanup/time differs')
    argv = ['core-call', URI, '--profiler-position', str(r['time']), '--max-results', '64']
    receipt, = [item for item in node['receipts'] if item['argv'] == argv]
    raw_path, = [name for name in archived if name.endswith('/' + receipt['payload']['call']['evidence_path'].rsplit('/', 1)[1])]
    raw = json.loads(read(raw_path))
    plans = [json.loads(read(name)) for name in archived if '/runtime-inspection-observations-v1/rto1-' in name]
    issuer, = [p for p in plans if p['plan']['request']['api'] == URI]
    request = {'api': URI, 'args': {'time': r['time']}, 'options': {}}
    public = receipt['payload']['agent_result']
    if (raw['api'] != URI or raw['version'] != '2025.1' or raw['ok'] is not True or raw['dry_run'] is not False
            or raw['error_code'] is not None or audit.digest(raw['result']) != audit.digest(r['native_result'])
            or issuer['plan']['request'] != request or audit.digest({k:v for k,v in issuer.items() if k != 'sha256'}) != issuer['sha256']
            or issuer['plan']['result']['return'] != r['native_result']['return']
            or audit.digest(issuer['plan']['result']) != r['snapshot_sha256']
            or receipt['exit_code'] != 0 or receipt['payload']['ok'] is not True
            or public['return'] != r['native_result']['return'] or public['complete'] is not True or public['truncated'] is not False
            or public['snapshot_sha256'] != r['snapshot_sha256']):
        raise ValueError('Original LoadedMedia exact request/issuer/full-array snapshot differs')
    from wwise_waapi.native_catalog import load_native_catalog
    catalog = load_native_catalog('2025.1', 'wwise-authoring', root=root / 'skills/waapi-skill/resources/native-catalog')
    schema_receipt, = [item for item in node['receipts'] if item['argv'] == ['waapi-schema', URI, '--exclude-examples']]
    schema = schema_receipt['payload']['agent_result']
    definitions = json.loads((root/FIXTURE/'selected-definitions.json').read_bytes())
    reflected_files = {name:seal for name,seal,_ in capture['reflection']['source_files']}
    if (definitions['source_sha256'] != reflected_files[definitions['source']]
            or definitions['definitions'] != {k:catalog['definitions']['documents']['waapi_definitions.json']['definitions'][k] for k in ('cursorTime','profilerCursor')}
            or schema_receipt['payload']['reflection_context']['sessionId'] != issuer['context']['live']['sessionId']):
        raise ValueError('LoadedMedia matching selected definition/session parity differs')
    if audit.digest(schema) != r['selected_schema_sha256'] or audit.digest(catalog['schemas'][URI]) != r['selected_schema_sha256']:
        raise ValueError('LoadedMedia selected documented schema parity differs')
    # The whole source-owned archive includes all twelve scoped reflection reads,
    # matching source definition hashes and ready/action/PNG/lifecycle history.
    if len([i for i in node['receipts'] if i['argv'][0] == 'waapi-schema']) != 12:
        raise ValueError('LoadedMedia complete twelve-schema gate missing')
    if read(PREFIX + 'categories.jsonl').splitlines()[-1] != (base / 'r124-category.json').read_bytes().strip():
        raise ValueError('LoadedMedia final category detached from prepared/final history')
    historical = {k:v for k,v in sources.items() if k.startswith('skills/waapi-skill/')}
    current = runtime.program_source_context(root, flow=URI)['packaged']
    source_review = r['packaged_source_review']
    differences = {name: {'before': historical.get(name), 'after': current.get(name)}
                   for name in historical.keys() | current.keys() if historical.get(name) != current.get(name)}
    if (len(historical) != source_review['packaged_source_count']
            or len(current) != source_review['packaged_source_count']
            or len(historical) - len(differences) != source_review['unchanged_source_count']
            or differences != source_review['changes']):
        raise ValueError('LoadedMedia exact reviewed packaged source delta differs')
    return dict(context=context, node=node, read=read, capture=capture, capture_raw=capture_raw, capture_path=capture_path,
                raw=raw, raw_path=raw_path, request=request, receipt=receipt, historical_sources=historical,
                archive=descriptor('r124-originals.json.gz'), category_descriptor=descriptor('r124-category.json'))



def _cursor_source(captured, choice):
    trace = captured['native_reads']
    cursors = [r for r in trace if r['uri'] == 'ak.wwise.core.profiler.getCursorTime']
    dependents = [r for r in trace if r['uri'] == URI]
    enum = {'capture-latest':'capture','user-cursor':'user'}[choice]
    time = cursors[0]['result'].get('return') if len(cursors) == 1 else None
    if (type(time) is not int or time < 0 or len(dependents) != 1
            or cursors[0]['args'] != {'cursor':enum} or cursors[0]['options'] != {}
            or cursors[0]['result'] != {'return':time} or dependents[0]['args'] != {'time':time}
            or cursors[0]['ordinal'] >= dependents[0]['ordinal']):
        raise ValueError('LoadedMedia exact ordered typed cursor snapshot differs')
    return cursors[0]


def _mappings(inventory,captured,route):
    # Reuse existing exact occurrence/predicate machinery. Its fixed-reader
    # cursor dispatcher intentionally excludes LoadedMedia, so this one closed
    # reader binds its own two-read cursor chain without broadening that lane.
    view = {**inventory,'native_coverage':{**inventory['native_coverage'],'obligations':[
        b for b in inventory['native_coverage']['obligations'] if b['pointer'] not in runtime.CONTRIBUTION_CURSOR_POINTERS]}}
    mapped = fixed.mappings(view,captured,route)
    position = captured['gateway']['argv'][3]
    if position in {'capture-latest','user-cursor'}:
        source = _cursor_source(captured,position)
        branches = [b for b in inventory['native_coverage']['obligations'] if b['route']==ROUTE]
        edges = {b['id']:b for b in branches if b['kind']=='reference'}
        for b in branches:
            if b['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS and fixed.predicate(b,fixed.schema_node(b),source['args']['cursor']):
                mapped.append({'branch':b,'program_pointer':f"/runtime_read_program/native_reads/{source['ordinal']}/args/cursor",
                    'reference_chain':runtime._contribution_chains(b,edges)[0],'categories':['program']})
    return mapped


def validate_program(record, binding, branch, root, edges=None):
    exact_branch(branch, root)
    captured = record.get('runtime_read_program', {}); gateway = record['gateway']; native = record['native_call']
    payload = gateway['payload']; trace = captured.get('native_reads', [])
    if (captured.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_unchanged') is not True or captured.get('source_context') != runtime.program_source_context(root, flow=URI)
            or record.get('relevant_sources') != captured['source_context']['packaged']
            or audit.digest(captured.get('gateway')) != audit.digest(gateway) or audit.digest(captured.get('native_call')) != audit.digest(native)
            or gateway['exit_code'] != 0 or payload.get('ok') is not True or payload.get('is_command_line') is not False
            or gateway['argv'] != binding['input']['gateway_argv'] or native['uri'] != URI
            or any(payload['schema_validation'][s]['version'] != '2025.1' for s in ('request', 'result'))):
        raise ValueError('LoadedMedia exact public capture/phases/source/context differs')
    if (not 1 <= len(trace) <= 16 or any(set(row) != {'ordinal','uri','args','options','result'} or type(row['ordinal']) is not int or row['ordinal'] != i for i,row in enumerate(trace))
            or captured.get('public_calls') != [{'gateway':gateway, 'native_start':0, 'native_end':len(trace)}]
            or audit.digest({k:trace[-1][k] for k in ('uri','args','options','result')}) != audit.digest(native)):
        raise ValueError('LoadedMedia ordered public/native trace differs')
    if len([row for row in trace if row['uri'] == URI]) != 1:
        raise ValueError('LoadedMedia public span requires exactly one native reader call')
    info, = [row['result'] for row in trace if row['uri'] == 'ak.wwise.core.getInfo']
    if completion.native_host_context(info, 'isCommandLine') != {'version':'2025.1','host':'wwise-authoring','build':BASIS['catalog_build']}:
        raise ValueError('LoadedMedia public program must retain pinned9143 fake host identity')
    argv = gateway['argv']; position = argv[argv.index('--profiler-position') + 1]
    if argv != ['core-call',URI,'--profiler-position',position,'--max-results','64']:
        raise ValueError('LoadedMedia requires its exact bounded public declaration')
    from wwise_waapi.runtime_inspection_business import materialize_runtime_inspection_business_request, normalize_runtime_inspection_result
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    request, _, business = materialize_runtime_inspection_business_request(URI, '2025.1', profiler_position=position, max_results=64, log_channel=None)
    if position in {'capture-latest','user-cursor'}:
        cursor = _cursor_source(captured, position); request['args']['time'] = cursor['result']['return']
    if audit.digest(request) != audit.digest({'api':URI,'args':native['args'],'options':native['options']}):
        raise ValueError('LoadedMedia controlled request differs')
    validate_resolved_semantic_result(URI, native['result'], version='2025.1')
    expected = normalize_runtime_inspection_result(URI,native['result'],business_request=business,max_results=64)
    actual = payload['agent_result']
    if (audit.digest(actual['return']) != audit.digest(native['result']['return']) or actual.get('complete') is not True
            or actual['truncated'] is not False or actual['total_count'] != len(native['result']['return'])
            or actual['profiler_position'] != position or actual['snapshot_sha256'] != audit.digest(expected)
            or payload['business_request'] != {'operation':URI, **business,'max_results':64}):
        raise ValueError('LoadedMedia complete native/public full-array preservation differs')
    pointer = binding.get('program_observation_pointer', binding['observation_pointer'])
    if binding['gateway_observation_pointer'] != fixed.public_pointer(branch,pointer,record):
        raise ValueError('LoadedMedia corresponding exact public occurrence differs')
    if branch['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS:
        # Same closed cursor-chain validator/predicate used by existing readers.
        first = ROUTE + '|/argsSchema/properties/time/$ref'
        second = ROUTE + '|/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime/oneOf/1/$ref'
        chain = [first] if 'definitions/cursorTime/' in branch['pointer'] else [first,second]
        completion.exact_observation_pointer(branch,{**binding,'observation_pointer':'/native_call/args/time'},'/native_call','args',edges or {})
        cursor = _cursor_source(captured,position)
        if binding['reference_chain'] != chain or pointer != f"/runtime_read_program/native_reads/{cursor['ordinal']}/args/cursor":
            raise ValueError('LoadedMedia exact cursor reference occurrence differs')
        value = cursor['args']['cursor']
        normalized = {'branch_id':branch['id'],'observation_pointer':pointer}
    else:
        value = completion.pointer_value(record,pointer); normalized = None
    if not fixed.predicate(branch,fixed.schema_node(branch,root),value,root):
        raise ValueError('LoadedMedia exact pinned branch predicate failed')
    return normalized


def validate_evidence(record,binding,branch,category,base,root,edges):
    r,_ = exact_branch(branch,root)
    if branch['id'] != ANCHOR or category not in {'program','native'}:
        raise ValueError('Only exact LoadedMedia semantic anchor accepts original native support')
    proof = runtime._proof(binding,base); mapping = proof['mapping']
    if (proof['branch_id'] != ANCHOR or proof['native_shape_sha256'] != branch['shape_sha256']
            or proof['source_review']['sha256'] != REVIEW_SHA or completion.read_sealed_artifact(proof['source_review'],base) != r
            or binding['reference_chain'] != [] or mapping['program_pointer'] != '/native_call/result/return'
            or mapping['native_pointer'] != '/observations/raw/result/return'
            or binding['observation_pointer'] != mapping['native_pointer'] or binding['program_observation_pointer'] != mapping['program_pointer']):
        raise ValueError('LoadedMedia exact reviewed original anchor mapping differs')
    captured = completion.read_sealed_artifact(proof['program_capture'],base)
    if category == 'program':
        if audit.digest(record.get('runtime_read_program')) != audit.digest(captured):
            raise ValueError('LoadedMedia attached program capture differs')
        return validate_program(record,binding,branch,root,edges)
    original = original_observation(base,root=root)
    if (proof['native_run'] != record['native_runs'][0] or len(record['native_runs']) != 1
            or proof['archive'] != original['archive'] or proof['capture_original_path'] != original['capture_path']
            or original['capture_raw'] != (base/proof['capture']['artifact']).read_bytes()
            or proof['relevant_sources'] != original['historical_sources']
            or record['observation_artifacts'] != {'capture':proof['capture'],'raw':mapping['raw_observation']}
            or mapping['raw_original_path'] != original['raw_path']
            or original['read'](original['raw_path']) != (base/mapping['raw_observation']['artifact']).read_bytes()
            or audit.digest(captured['native_call']) != audit.digest({'uri':URI,'args':original['request']['args'],'options':{},'result':original['raw']['result']})
            or captured['gateway']['payload']['agent_result']['snapshot_sha256'] != r['snapshot_sha256']
            or record.get('representative_native_support') != BASIS):
        raise ValueError('LoadedMedia strict original request/result/current replay differs')


def validate_source_equivalence(proof, sources, branch, binding, root, base):
    """Only the exact original anchor may use its pinned one-file source review."""
    r, _ = exact_branch(branch, root)
    if (branch['id'] != ANCHOR or proof['from_candidate'] != ORIGINAL_CANDIDATE
            or not binding.get('runtime_observation_attachment')):
        raise ValueError('LoadedMedia source bridge requires exact original anchor/attachment')
    attached = runtime._proof(binding, base)
    if (proof['loaded_media_source_review'] != attached['source_review']
            or attached['source_review']['sha256'] != REVIEW_SHA
            or completion.read_sealed_artifact(attached['source_review'], base) != r):
        raise ValueError('LoadedMedia source bridge requires pinned source-owned review')
    original = original_observation(base, root=root)
    captured = completion.read_sealed_artifact(attached['program_capture'], base)
    if (sources != original['historical_sources'] or attached['relevant_sources'] != sources
            or audit.digest(captured['native_call']) != audit.digest({'uri': URI,
                'args': original['request']['args'], 'options': {}, 'result': original['raw']['result']})):
        raise ValueError('LoadedMedia source bridge requires original sources and complete current replay')
    validate_program({'gateway': captured['gateway'], 'native_call': captured['native_call'],
        'runtime_read_program': captured, 'relevant_sources': captured['source_context']['packaged']},
        binding, branch, root)


def accepts_native_context(context,branch,binding,record,base,root):
    """No generic patch fallback: this original profile and anchor alone qualify."""
    exact_branch(branch,root)
    if (branch['id'] != ANCHOR or context['version'] != '2025.1' or context['host'] != 'wwise-authoring'
            or context['build'] != BASIS['observed_build'] or context['candidate'] != ORIGINAL_CANDIDATE
            or record.get('representative_native_support') != BASIS):
        raise ValueError('Unreviewed LoadedMedia native host/build/branch support')
    # The prior attachment validation already checked the full immutable original
    # plus current replay; removal of that attachment never enables build reuse.
    if not binding.get('runtime_observation_attachment'):
        raise ValueError('LoadedMedia representative support requires original attachment')
    return True


def write_loaded_media_bundle(output,captures,*,inventory,originals=None):
    """Publish the closed31-branch slice through the existing portable importer."""
    r=review(); original=original_observation(originals); output=Path(output);output.mkdir(parents=True,exist_ok=False)
    original_base=Path(originals) if originals is not None else audit.ROOT/FIXTURE
    for name in ('r124-originals.json.gz','r124-category.json','support-review.json'):
        shutil.copyfile(original_base/name,output/name)
    def write(name,value):return runtime.write_json(output/name,value)
    def desc(name):return {'artifact':name,'sha256':runtime.sha((output/name).read_bytes())}
    (output/'original-capture.json').write_bytes(original['capture_raw'])
    (output/'original-raw.json').write_bytes(original['read'](original['raw_path']))
    route,=[row for row in inventory['native_coverage']['routes'] if row['id']==ROUTE]
    public,=[row for row in inventory['routes'] if row['id']==route['public_route']]
    candidate=inventory['native_coverage']['candidate_sha256']; sources=original['historical_sources']
    index={'contract':'waapi-skill.branch-evidence-index/v1','base':'.','entries':[]}
    requirements={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}}
    selected=set();attachment=None
    for number,path in enumerate(captures):
        captured=json.loads(Path(path).read_bytes())
        mapped=_mappings(inventory,captured,route)
        mapped=[m for m in mapped if m['branch']['id'] not in selected]
        if not mapped:continue
        prefix=f'flow-{number}-'
        cp=write(prefix+'capture.json',captured)
        program={'candidate_sha256':candidate,'scope_kind':'product','relevant_sources':captured['source_context']['packaged'],
            'gateway':captured['gateway'],'native_call':captured['native_call'],'runtime_read_program':captured,
            'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':captured['nodeid'],'outcome':'PASS'}]},'branch_assertions':{}}
        document={'contract':'waapi-skill.branch-bindings/v1','bindings':{}}
        policies={'contract':'waapi-skill.branch-evidence-requirements/v1','branches':{}}
        for mapping in mapped:
            branch=mapping['branch'];identity=branch['id'];exact_branch(branch);pointer=mapping['program_pointer']
            pp=fixed.public_pointer(branch,pointer,program)
            check=({'pointer':pointer,'cardinality':branch['value']} if branch['kind']=='collection_cardinality' else
                   {'pointer':pointer,'equals':completion.pointer_value(program,pointer)})
            assertion={'native_shape_sha256':branch['shape_sha256'],'native_route':ROUTE}
            program['branch_assertions'][identity]={**assertion,'checks':[check,{'pointer':pp,'equals':completion.pointer_value(program,pp)}]}
            binding={'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],
                'public_route_sha256':audit.digest(public),'input':{'gateway_argv':captured['gateway']['argv'],'selector':pointer},
                'dispatch_pointer':'/native_call','observation_pointer':pointer,'gateway_observation_pointer':pp,
                'reference_chain':mapping['reference_chain'],'relevant_sources':sorted(sources),'evidence':{},
                **{key:{'source':source,'selector':branch['pointer']} for key,source in (
                    ('construction','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#materialize_runtime_inspection_business_request'),
                    ('validation','skills/waapi-skill/wwise_waapi/builders/schema.py#validate_resolved_semantic_result'),
                    ('verifier','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#normalize_runtime_inspection_result'))}}
            validate_program(program,binding,branch,audit.ROOT,{b['id']:b for b in inventory['native_coverage']['obligations'] if b['kind']=='reference'})
            document['bindings'][identity]=binding;policies['branches'][identity]=policy(r['entries'][identity]);selected.add(identity)
            if identity==ANCHOR:
                if audit.digest(captured['native_call'])!=audit.digest({'uri':URI,'args':original['request']['args'],'options':{},'result':original['raw']['result']}):
                    raise ValueError('LoadedMedia semantic anchor requires exact original full-array public replay')
                native_run={**desc('r124-category.json'),'nodeid':r['nodeid'],
                            'observation_sha256':[desc('original-capture.json')['sha256'],desc('original-raw.json')['sha256']]}
                native_check={'pointer':'/observations/raw/result/return','cardinality':'single'}
                native={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'native_execution',
                    'relevant_sources':sources,'invocation':original['context']['record']['invocation'],'native_runs':[native_run],
                    'observation_artifacts':{'capture':desc('original-capture.json'),'raw':desc('original-raw.json')},
                    'representative_native_support':BASIS,'branch_assertions':{identity:{**assertion,'checks':[native_check,
                        {'pointer':'/observations/raw/result','equals':r['native_result']}]}}}
                nd={**write('native.json',native),'nodeid':r['nodeid']}
                mapping={k:v for k,v in mapping.items() if k!='branch'}
                mapping.update(categories=['program','native'],branch_id=identity,native_shape_sha256=branch['shape_sha256'],
                    category=CATEGORY,native_pointer='/observations/raw/result/return',native_result_parent='/observations/raw',
                    native_checks=native['branch_assertions'][identity]['checks'],raw_observation=desc('original-raw.json'),raw_original_path=original['raw_path'])
                proof=write('proof.json',{'contract':'waapi-skill.runtime-observation-proof/v1','branch_id':identity,
                    'native_shape_sha256':branch['shape_sha256'],'mapping':mapping,'native_run':native_run,'archive':original['archive'],
                    'capture':desc('original-capture.json'),'capture_original_path':original['capture_path'],'program_capture':cp,
                    'relevant_sources':sources,'source_review':desc('support-review.json')})
                attached=deepcopy(binding);attached.update(runtime_observation_attachment=proof,program_observation_pointer=pointer,
                    observation_pointer=mapping['native_pointer'],native_observations_sha256={k:v['sha256']for k,v in native['observation_artifacts'].items()})
                eq=write('native-equivalence.json',{'contract':'waapi-skill.branch-evidence-equivalence/v1','from_candidate':ORIGINAL_CANDIDATE,
                    'to_candidate':candidate,'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'native_route':ROUTE,
                    'evidence_sha256':native_run['sha256'],'binding_semantics_sha256':audit.digest(completion.binding_semantics(attached)),
                    'reviewed_reason':'Exact reviewed actual9262 semantic support and complete current public replay; only reviewed Gateway exception-finish host-context delta; all other412 packaged sources exact; no9143 native execution',
                    'sources':sources,'loaded_media_source_review':desc('support-review.json')})
                attachment=write('attachment.json',{'contract':'waapi-skill.runtime-observation-attachment/v1','branch_id':identity,
                    'proof':proof,'evidence':nd,'native_equivalence':eq})
        pd={**write(prefix+'program.json',program),'nodeid':captured['nodeid']}
        for binding in document['bindings'].values():binding['evidence']['program']=deepcopy(pd)
        bd=write(prefix+'bindings.json',document);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':'loaded-media-'+str(number),'bindings':bd,'origin':{'bindings':bd,'program':desc(prefix+'program.json'),'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if selected!=set(r['entries']) or attachment is None:
        raise ValueError('LoadedMedia bundle requires every exact31 branch plus complete semantic anchor')
    index['runtime_observation_attachments']=[attachment]
    write('requirements.json',requirements);write('index.json',index)
    return output/'index.json'

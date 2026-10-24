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
REVIEW_SHA = '6d01288485ea78648bfaf65b48ee39697280828629257f72a1ff1e25dcf7044c'
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


def original_observation(originals=None, *, root=audit.ROOT, copied_prefix=''):
    """Recheck the complete strict-PASS archive, not a manufactured native row."""
    if copied_prefix not in ('','lm-2025-','lm-composite-2023-','lm-composite-2024-'):
        raise ValueError('LoadedMedia copied closure requires its closed family/version namespace')
    r = review(root); base = Path(originals) if originals is not None else root / FIXTURE
    def descriptor(name): return {'artifact': copied_prefix + name, 'sha256': r['files'][name]}
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
    if read(PREFIX + 'categories.jsonl').splitlines()[-1] != (base / (copied_prefix + 'r124-category.json')).read_bytes().strip():
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
        branches = [b for b in inventory['native_coverage']['obligations'] if b['route']==route['id']]
        edges = {b['id']:b for b in branches if b['kind']=='reference'}
        for b in branches:
            if b['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS and fixed.predicate(b,fixed.schema_node(b),source['args']['cursor']):
                mapped.append({'branch':b,'program_pointer':f"/runtime_read_program/native_reads/{source['ordinal']}/args/cursor",
                    'reference_chain':runtime._contribution_chains(b,edges)[0],'categories':['program']})
    return mapped


def validate_program(record, binding, branch, root, edges=None):
    if branch['route'] in COMPOSITE_ROUTES.values():
        return validate_composite_program(record,binding,branch,root,edges)
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
    if branch['route'] in COMPOSITE_ROUTES.values():
        return validate_composite_evidence(record,binding,branch,category,base,root,edges)
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
    original = _positive_from_proof(proof,base,root)
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
    if branch['route'] in COMPOSITE_ROUTES.values():
        return validate_composite_source(proof,sources,branch,binding,root,base)
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
    original = _positive_from_proof(attached,base,root)
    captured = completion.read_sealed_artifact(attached['program_capture'], base)
    if (sources != original['historical_sources'] or attached['relevant_sources'] != sources
            or audit.digest(captured['native_call']) != audit.digest({'uri': URI,
                'args': original['request']['args'], 'options': {}, 'result': original['raw']['result']})):
        raise ValueError('LoadedMedia source bridge requires original sources and complete current replay')
    validate_program({'gateway': captured['gateway'], 'native_call': captured['native_call'],
        'runtime_read_program': captured, 'relevant_sources': captured['source_context']['packaged']},
        binding, branch, root)


def accepts_native_context(context,branch,binding,record,base,root):
    if branch['route'] in COMPOSITE_ROUTES.values():
        _, profile, _ = composite_branch(branch,root)
        if (branch['id'] != profile['anchor'] or context['candidate'] != ORIGINAL_CANDIDATE
                or context['version'] != '2025.1' or context['host'] != 'wwise-authoring'
                or context['build'] != BASIS['observed_build'] or not binding.get('runtime_observation_attachment')
                or record.get('representative_native_support') != composite_basis(profile)):
            raise ValueError('LoadedMedia exact older composite native context differs')
        return True
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


def write_loaded_media_bundle(output,captures,*,inventory,originals=None,name_prefix=''):
    """Publish the closed31-branch slice through the existing portable importer."""
    if name_prefix not in ('','lm-2025-'):
        raise ValueError('LoadedMedia publisher accepts only its closed2025 namespace')
    r=review(); original=original_observation(originals); output=Path(output);output.mkdir(parents=True,exist_ok=False)
    original_base=Path(originals) if originals is not None else audit.ROOT/FIXTURE
    for name in ('r124-originals.json.gz','r124-category.json','support-review.json'):
        shutil.copyfile(original_base/name,output/(name_prefix+name))
    def write(name,value):return runtime.write_json(output/(name_prefix+name),value)
    def desc(name):return {'artifact':name_prefix+name,'sha256':runtime.sha((output/(name_prefix+name)).read_bytes())}
    (output/(name_prefix+'original-capture.json')).write_bytes(original['capture_raw'])
    (output/(name_prefix+'original-raw.json')).write_bytes(original['read'](original['raw_path']))
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
                    'native_shape_sha256':branch['shape_sha256'],'mapping':mapping,'native_run':native_run,'archive':desc('r124-originals.json.gz'),
                    'capture':desc('original-capture.json'),'capture_original_path':original['capture_path'],'program_capture':cp,
                    'relevant_sources':sources,'source_review':desc('support-review.json')})
                attached=deepcopy(binding);attached.update(runtime_observation_attachment=proof,program_observation_pointer=pointer,
                    observation_pointer=mapping['native_pointer'],native_observations_sha256={k:v['sha256']for k,v in native['observation_artifacts'].items()})
                eq=write('native-equivalence.json',{'contract':'waapi-skill.branch-evidence-equivalence/v1','from_candidate':ORIGINAL_CANDIDATE,
                    'to_candidate':candidate,'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'native_route':ROUTE,
                    'evidence_sha256':native_run['sha256'],'binding_semantics_sha256':audit.digest(completion.binding_semantics(attached)),
                    'reviewed_reason':'Exact reviewed actual9262 semantic support and complete current public replay; exact reviewed Gateway host-context and meter-only allowlist deltas; all other411 packaged sources exact; no9143 native execution',
                    'sources':sources,'loaded_media_source_review':desc('support-review.json')})
                attachment=write('attachment.json',{'contract':'waapi-skill.runtime-observation-attachment/v1','branch_id':identity,
                    'proof':proof,'evidence':nd,'native_equivalence':eq})
        pd={**write(prefix+'program.json',program),'nodeid':captured['nodeid']}
        for binding in document['bindings'].values():binding['evidence']['program']=deepcopy(pd)
        bd=write(prefix+'bindings.json',document);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':name_prefix+'loaded-media-'+str(number),'bindings':bd,'origin':{'bindings':bd,'program':desc(prefix+'program.json'),'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if selected!=set(r['entries']) or attachment is None:
        raise ValueError('LoadedMedia bundle requires every exact31 branch plus complete semantic anchor')
    index['runtime_observation_attachments']=[attachment]
    write('requirements.json',requirements);write('index.json',index)
    return output/(name_prefix+'index.json')


COMPOSITE_REVIEW_SHA = 'c778e6dbd69b56de353c5d79d2ff4797cbce1e844e295f6642465aa429f9e613'
COMPOSITE_ROUTES = {
    '2023.1': '2023.1|wwise-authoring|2023.1.19.8928|function|' + URI,
    '2024.1': '2024.1|wwise-authoring|2024.1.13.9056|function|' + URI,
}
R104_CANDIDATE = 'a5884dcbb655d03a4537ed1e3553ac01e1d2fdb8'


def _resolved_loaded_schema(version, root):
    from wwise_waapi.native_catalog import load_native_catalog
    catalog = load_native_catalog(version, 'wwise-authoring', root=root / 'skills/waapi-skill/resources/native-catalog')
    documents = catalog['definitions']['documents']
    def resolve(value):
        if isinstance(value, list): return [resolve(item) for item in value]
        if not isinstance(value, dict): return value
        if '$ref' in value:
            document, pointer = value['$ref'].split('#')
            target = completion.pointer_value(documents[document or 'waapi_definitions.json'], pointer)
            value = {**target, **{k:v for k,v in value.items() if k != '$ref'}}
        return {k:resolve(v) for k,v in value.items()}
    schema = catalog['schemas'][URI]
    return schema, {key:resolve(schema[key]) for key in ('argsSchema','optionsSchema','resultSchema')}


def composite_policy(entry):
    return {'native_shape_sha256':entry['shape_sha256'], 'categories':entry['categories'],
        'reason': ('Exact older successful empty API availability plus actual9262 common prepared-media semantic anchor and current whole-array replay; no older nonempty native execution'
                   if entry['categories'] == ['program','native'] else
                   'Exact older LoadedMedia declaration/field/collection preservation; conditional on reviewed composite anchor; no older native value occurrence')}


def composite_review(root=audit.ROOT):
    path = root / FIXTURE / 'composite-review.json'
    if runtime.sha(path.read_bytes()) != COMPOSITE_REVIEW_SHA:
        raise ValueError('Exact older LoadedMedia composite descriptor differs')
    result = json.loads(path.read_bytes())
    if (len(result['entries']) != 62 or set(result['profiles']) != set(COMPOSITE_ROUTES)
            or result['positive_review_sha256'] != REVIEW_SHA):
        raise ValueError('Exact older LoadedMedia composite scope differs')
    positive_schema = _resolved_loaded_schema('2025.1',root)[1]
    if positive_schema != result['positive_resolved_schema']:
        raise ValueError('LoadedMedia positive resolved schema differs')
    for version, profile in result['profiles'].items():
        schema, resolved = _resolved_loaded_schema(version,root)
        if (profile['route'] != COMPOSITE_ROUTES[version] or schema != profile['catalog_schema']
                or resolved != profile['resolved_schema']):
            raise ValueError('Exact older LoadedMedia schema/reference mapping differs')
        # Only this exact documented punctuation transition is admitted. All
        # other resolved keys, descriptions, alternatives and fields stay equal.
        changed = deepcopy(resolved)
        field = changed['resultSchema']['properties']['return']['items']['properties']['mediaId']
        if field['description'] != result['exact_resolved_difference']['older']:
            raise ValueError('LoadedMedia reviewed older field meaning differs')
        field['description'] = result['exact_resolved_difference']['positive']
        if changed != positive_schema:
            raise ValueError('LoadedMedia resolved semantic difference is unreviewed')
        for name, document in profile['documents'].items():
            raw = (root / FIXTURE / name).read_bytes()
            if runtime.sha(raw) != document['sha256']:
                raise ValueError('LoadedMedia older primary documentation differs')
        text = (root / FIXTURE / next(n for n in profile['documents'] if n.endswith('-api.html'))).read_text()
        if not all(t in text for t in ('loaded media at a specific profiler capture time','PrepareEvent()','PrepareGameSyncs()','size (in bytes)')):
            raise ValueError('LoadedMedia older documented business meaning differs')
    import subprocess
    baseline = result['prior_policy_absent']
    prior = subprocess.check_output(['git','show',baseline['candidate']+':'+baseline['path']],cwd=root)
    if runtime.sha(prior) != baseline['sha256'] or set(result['entries']) & set(json.loads(prior)['branches']):
        raise ValueError('Older LoadedMedia immutable policy-absence baseline differs')
    published = json.loads((root / baseline['path']).read_bytes())['branches']
    if any(identity in published and published[identity] != composite_policy(entry)
           for identity,entry in result['entries'].items()):
        raise ValueError('Unreviewed published older LoadedMedia policy differs')
    return result


def composite_branch(branch, root=audit.ROOT):
    reviewed = composite_review(root)
    entry = reviewed['entries'].get(branch['id'])
    if not entry or any(branch.get(key) != entry[key] for key in
            ('route','pointer','kind','shape_sha256','owner_issue','parent_issue','blocks_issue')):
        raise ValueError('Only exact reviewed older Authoring LoadedMedia branch/shape is eligible')
    return reviewed, reviewed['profiles'][branch['route'].split('|')[0]], entry


def composite_basis(profile):
    return {'catalog_build':profile['build'], 'availability_build':profile['build'],
        'observed_build':BASIS['observed_build'], 'basis':'exact_reviewed_cross_version_composite_support',
        'older_nonempty_native_execution':False, 'older_parent_outcome':'BLOCKED'}


def availability_observation(version, *, root=audit.ROOT, base=None, descriptor=None):
    profile = composite_review(root)['profiles'][version]
    path = root / profile['archive_path']
    base = Path(base) if base is not None else path.parent
    descriptor = descriptor or {'artifact':path.name,'sha256':profile['archive_sha256']}
    if descriptor['sha256'] != profile['archive_sha256']:
        raise ValueError('LoadedMedia exact older availability archive differs')
    read = runtime.archive_reader(descriptor,base)
    import gzip
    encoded = json.loads(gzip.decompress((base / descriptor['artifact']).read_bytes()))['files']
    if len(encoded) != profile['archive_files'] or audit.digest(encoded) != profile['archive_decoded_sha256']:
        raise ValueError('LoadedMedia complete older availability closure differs')
    node_raw = read(profile['node_path']); node = json.loads(node_raw); sources = node['source_context']['sources']
    if (runtime.sha(node_raw) != profile['node_sha256'] or node['candidate'] != R104_CANDIDATE
            or node['source_context']['candidate'] != R104_CANDIDATE
            or len(sources) != profile['source_count'] or audit.digest(sources) != profile['source_sha256']
            or completion.historical_source_seals(root,R104_CANDIDATE,sources) != sources):
        raise ValueError('LoadedMedia complete original older source context differs')
    for group in node['artifacts'].values():
        for item in group['files']:
            raw = read(group['path']+'/'+item['path'])
            if runtime.sha(raw) != item['sha256'] or len(raw) != item['bytes']:
                raise ValueError('LoadedMedia complete older artifact manifest differs')
    historical = {k:v for k,v in sources.items() if k.startswith('skills/waapi-skill/')}
    current = runtime.program_source_context(root,flow=URI)['packaged']
    differences = {k:{'before':historical.get(k),'after':current.get(k)}
        for k in historical.keys() | current.keys() if historical.get(k) != current.get(k)}
    if len(historical) != 413 or len(current) != 413 or differences != profile['packaged_source_changes']:
        raise ValueError('LoadedMedia exact older/current packaged source delta differs')
    original_root = profile['original_root']
    load = lambda relative: json.loads(read(original_root+'/'+relative))
    capture = load('evidence/authoring-node-observations/d87a1375cafae330c7be7f7f-native-evidence/profiler-capture.json')
    start = load('evidence/start.json'); lifecycle = load('evidence/lifecycle.json')
    issuer_raw = read(profile['issuer_path']); issuer = json.loads(issuer_raw)
    raw_bytes = read(profile['raw_path']); raw = json.loads(raw_bytes)
    receipt, = [r for r in node['receipts'] if r['payload'].get('call',{}).get('evidence_path') == raw['evidence_path']]
    info = capture['host']; observed = capture['outcomes'][CATEGORY]
    if (completion.native_host_context(info,'isCommandLine') != {'version':version,'host':'wwise-authoring','build':profile['build']}
            or start['get_info'] != info or issuer['context'] != profile['availability_context']
            or issuer['context']['live'] != {k:info[k] for k in ('version','sessionId','processId')}
            or runtime.sha(issuer_raw) != profile['issuer_sha256'] or runtime.sha(raw_bytes) != profile['raw_sha256']
            or issuer['plan']['request'] != profile['request'] or raw['api'] != URI or raw['version'] != version
            or raw['ok'] is not True or raw['dry_run'] is not False or raw['error_code'] is not None
            or raw['result'] != {'return':[]} or receipt['exit_code'] != 0 or receipt['payload']['ok'] is not True
            or receipt['payload']['agent_result']['return'] != [] or receipt['payload']['agent_result']['complete'] is not True
            or receipt['argv'] != ['core-call',URI,'--profiler-position',str(profile['request']['args']['time']),'--max-results','64']
            or observed['outcome'] != 'BLOCKED' or observed['evidence']['observation_status'] != 'PASS'
            or observed['evidence']['nonempty'] is not False or observed['evidence']['complete'] is not True
            or capture['cleanup']['complete'] is not True or capture['errors'] != [] or capture['complete'] is not False
            or lifecycle['final_status'] != 'BLOCKED' or lifecycle['errors'] != []
            or lifecycle['source_hash_before'] != lifecycle['source_hash_after']
            or lifecycle['source_mtime_before_ns'] != lifecycle['source_mtime_after_ns']):
        raise ValueError('LoadedMedia exact older successful empty availability/session/BLOCKED attribution differs')
    return profile


def _composite_bridge(proof, branch, root, base):
    reviewed, profile, _ = composite_branch(branch,root)
    bridge = completion.read_sealed_artifact(proof['source_review'],base)
    if (set(bridge) != {'contract','version','review','availability_archive','availability_context','positive_review'}
            or bridge['contract'] != 'waapi-skill.loaded-media-composite-source/v1'
            or bridge['version'] != branch['route'].split('|')[0]
            or bridge['review']['sha256'] != COMPOSITE_REVIEW_SHA
            or completion.read_sealed_artifact(bridge['review'],base) != reviewed
            or bridge['positive_review']['sha256'] != REVIEW_SHA
            or completion.read_sealed_artifact(bridge['positive_review'],base) != review(root)
            or bridge['availability_context'] != profile['availability_context']):
        raise ValueError('LoadedMedia composite review/availability session binding differs')
    availability_observation(bridge['version'],root=root,base=base,descriptor=bridge['availability_archive'])
    return profile


def validate_composite_evidence(record,binding,branch,category,base,root,edges):
    _, profile, _ = composite_branch(branch,root)
    proof = runtime._proof(binding,base); mapping = proof['mapping']
    if (proof['branch_id'] != branch['id'] or proof['native_shape_sha256'] != branch['shape_sha256']
            or binding['program_observation_pointer'] != mapping['program_pointer']
            or binding['observation_pointer'] != mapping['native_pointer'] or binding['reference_chain'] != []):
        raise ValueError('LoadedMedia composite exact branch/observation binding differs')
    captured = completion.read_sealed_artifact(proof['program_capture'],base)
    if category == 'program':
        if audit.digest(record['runtime_read_program']) != audit.digest(captured):
            raise ValueError('LoadedMedia composite current capture differs')
        return validate_composite_program(record,binding,branch,root,edges)
    if category != 'native' or branch['id'] != profile['anchor']:
        raise ValueError('Only exact older composite anchor accepts representative native support')
    _composite_bridge(proof,branch,root,base)
    original = _positive_from_proof(proof,base,root)
    if (proof['archive'] != original['archive'] or proof['native_run'] != record['native_runs'][0] or len(record['native_runs']) != 1
            or proof['capture_original_path'] != original['capture_path'] or proof['relevant_sources'] != original['historical_sources']
            or (base/proof['capture']['artifact']).read_bytes() != original['capture_raw']
            or (base/mapping['raw_observation']['artifact']).read_bytes() != original['read'](original['raw_path'])
            or mapping['raw_original_path'] != original['raw_path']
            or record['observation_artifacts'] != {'capture':proof['capture'],'raw':mapping['raw_observation']}
            or mapping['native_pointer'] != '/observations/raw/result/return'
            or mapping['program_pointer'] != '/native_call/result/return'
            or record.get('representative_native_support') != composite_basis(profile)
            or audit.digest(captured['native_call']) != audit.digest({'uri':URI,'args':original['request']['args'],
                'options':{},'result':original['raw']['result']})):
        raise ValueError('LoadedMedia composite original9262 full-array/current replay differs')
    validate_composite_program({'gateway':captured['gateway'],'native_call':captured['native_call'],
        'runtime_read_program':captured,'relevant_sources':captured['source_context']['packaged']},binding,branch,root,edges)


def validate_composite_source(proof,sources,branch,binding,root,base):
    _, profile, _ = composite_branch(branch,root)
    if branch['id'] != profile['anchor'] or proof['from_candidate'] != ORIGINAL_CANDIDATE or not binding.get('runtime_observation_attachment'):
        raise ValueError('LoadedMedia composite source bridge requires exact original9262 anchor attachment')
    attached = runtime._proof(binding,base)
    if proof['loaded_media_source_review'] != attached['source_review']:
        raise ValueError('LoadedMedia composite source bridge differs')
    _composite_bridge(attached,branch,root,base)
    if sources != _positive_from_proof(attached,base,root)['historical_sources'] or attached['relevant_sources'] != sources:
        raise ValueError('LoadedMedia composite original9262 source map differs')


def validate_composite_program(record, binding, branch, root, edges=None):
    _, profile, _ = composite_branch(branch,root)
    version = branch['route'].split('|')[0]
    captured = record.get('runtime_read_program', {}); gateway = record['gateway']; native = record['native_call']
    payload = gateway['payload']; trace = captured.get('native_reads', [])
    if (captured.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_unchanged') is not True or captured.get('source_context') != runtime.program_source_context(root, flow=URI)
            or record.get('relevant_sources') != captured['source_context']['packaged']
            or audit.digest(captured.get('gateway')) != audit.digest(gateway) or audit.digest(captured.get('native_call')) != audit.digest(native)
            or gateway['exit_code'] != 0 or payload.get('ok') is not True or payload.get('is_command_line') is not False
            or gateway['argv'] != binding['input']['gateway_argv'] or native['uri'] != URI
            or any(payload['schema_validation'][s]['version'] != version for s in ('request', 'result'))):
        raise ValueError('LoadedMedia exact public capture/phases/source/context differs')
    if (not 1 <= len(trace) <= 16 or any(set(row) != {'ordinal','uri','args','options','result'} or type(row['ordinal']) is not int or row['ordinal'] != i for i,row in enumerate(trace))
            or captured.get('public_calls') != [{'gateway':gateway, 'native_start':0, 'native_end':len(trace)}]
            or audit.digest({k:trace[-1][k] for k in ('uri','args','options','result')}) != audit.digest(native)):
        raise ValueError('LoadedMedia ordered public/native trace differs')
    if len([row for row in trace if row['uri'] == URI]) != 1:
        raise ValueError('LoadedMedia public span requires exactly one native reader call')
    info, = [row['result'] for row in trace if row['uri'] == 'ak.wwise.core.getInfo']
    if completion.native_host_context(info, 'isCommandLine') != {'version':version,'host':'wwise-authoring','build':profile['build']}:
        raise ValueError('LoadedMedia public program must retain pinned9143 fake host identity')
    argv = gateway['argv']; position = argv[argv.index('--profiler-position') + 1]
    if argv != ['core-call',URI,'--profiler-position',position,'--max-results','64']:
        raise ValueError('LoadedMedia requires its exact bounded public declaration')
    from wwise_waapi.runtime_inspection_business import materialize_runtime_inspection_business_request, normalize_runtime_inspection_result
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    request, _, business = materialize_runtime_inspection_business_request(URI, version, profiler_position=position, max_results=64, log_channel=None)
    if position in {'capture-latest','user-cursor'}:
        cursor = _cursor_source(captured, position); request['args']['time'] = cursor['result']['return']
    if audit.digest(request) != audit.digest({'api':URI,'args':native['args'],'options':native['options']}):
        raise ValueError('LoadedMedia controlled request differs')
    validate_resolved_semantic_result(URI, native['result'], version=version)
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
        first = profile['route'] + '|/argsSchema/properties/time/$ref'
        second = profile['route'] + '|/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime/oneOf/1/$ref'
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



def write_composite_bundle(output,captures,*,inventory,version):
    """Publish the closed31-branch slice through the existing portable importer."""
    name_prefix='lm-composite-'+version[:4]+'-'
    reviewed=composite_review(); profile=availability_observation(version); r=review(); original=original_observation()
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    original_base=audit.ROOT/FIXTURE
    for name in ('r124-originals.json.gz','r124-category.json','support-review.json'):
        shutil.copyfile(original_base/name,output/(name_prefix+name))
    shutil.copyfile(audit.ROOT/profile['archive_path'],output/(name_prefix+Path(profile['archive_path']).name))
    shutil.copyfile(audit.ROOT/FIXTURE/'composite-review.json',output/(name_prefix+'composite-review.json'))
    def write(name,value):return runtime.write_json(output/(name_prefix+name),value)
    def desc(name):return {'artifact':name_prefix+name,'sha256':runtime.sha((output/(name_prefix+name)).read_bytes())}
    (output/(name_prefix+'original-capture.json')).write_bytes(original['capture_raw'])
    (output/(name_prefix+'original-raw.json')).write_bytes(original['read'](original['raw_path']))
    route,=[row for row in inventory['native_coverage']['routes'] if row['id']==profile['route']]
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
            branch=mapping['branch'];identity=branch['id'];composite_branch(branch);pointer=mapping['program_pointer']
            pp=fixed.public_pointer(branch,pointer,program)
            check=({'pointer':pointer,'cardinality':branch['value']} if branch['kind']=='collection_cardinality' else
                   {'pointer':pointer,'equals':completion.pointer_value(program,pointer)})
            assertion={'native_shape_sha256':branch['shape_sha256'],'native_route':profile['route']}
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
            document['bindings'][identity]=binding;policies['branches'][identity]=composite_policy(reviewed['entries'][identity]);selected.add(identity)
            if identity==profile['anchor']:
                if audit.digest(captured['native_call'])!=audit.digest({'uri':URI,'args':original['request']['args'],'options':{},'result':original['raw']['result']}):
                    raise ValueError('LoadedMedia semantic anchor requires exact original full-array public replay')
                native_run={**desc('r124-category.json'),'nodeid':r['nodeid'],
                            'observation_sha256':[desc('original-capture.json')['sha256'],desc('original-raw.json')['sha256']]}
                native_check={'pointer':'/observations/raw/result/return','cardinality':'single'}
                native={'candidate_sha256':candidate,'scope_kind':'product','evidence_kind':'native_execution',
                    'relevant_sources':sources,'invocation':original['context']['record']['invocation'],'native_runs':[native_run],
                    'observation_artifacts':{'capture':desc('original-capture.json'),'raw':desc('original-raw.json')},
                    'representative_native_support':composite_basis(profile),'branch_assertions':{identity:{**assertion,'checks':[native_check,
                        {'pointer':'/observations/raw/result','equals':r['native_result']}]}}}
                nd={**write('native.json',native),'nodeid':r['nodeid']}
                mapping={k:v for k,v in mapping.items() if k!='branch'}
                mapping.update(categories=['program','native'],branch_id=identity,native_shape_sha256=branch['shape_sha256'],
                    category=CATEGORY,native_pointer='/observations/raw/result/return',native_result_parent='/observations/raw',
                    native_checks=native['branch_assertions'][identity]['checks'],raw_observation=desc('original-raw.json'),raw_original_path=original['raw_path'])
                proof=write('proof.json',{'contract':'waapi-skill.runtime-observation-proof/v1','branch_id':identity,
                    'native_shape_sha256':branch['shape_sha256'],'mapping':mapping,'native_run':native_run,'archive':desc('r124-originals.json.gz'),
                    'capture':desc('original-capture.json'),'capture_original_path':original['capture_path'],'program_capture':cp,
                    'relevant_sources':sources,'source_review':write('composite-source-review.json',
                        {'contract':'waapi-skill.loaded-media-composite-source/v1','version':version,
                         'review':desc('composite-review.json'),'availability_archive':desc(Path(profile['archive_path']).name),
                         'availability_context':profile['availability_context'],'positive_review':desc('support-review.json')})})
                attached=deepcopy(binding);attached.update(runtime_observation_attachment=proof,program_observation_pointer=pointer,
                    observation_pointer=mapping['native_pointer'],native_observations_sha256={k:v['sha256']for k,v in native['observation_artifacts'].items()})
                eq=write('native-equivalence.json',{'contract':'waapi-skill.branch-evidence-equivalence/v1','from_candidate':ORIGINAL_CANDIDATE,
                    'to_candidate':candidate,'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'native_route':profile['route'],
                    'evidence_sha256':native_run['sha256'],'binding_semantics_sha256':audit.digest(completion.binding_semantics(attached)),
                    'reviewed_reason':'Exact older successful empty API availability plus reviewed actual9262 common semantic support and current whole-array replay; older parent stays BLOCKED; no older nonempty native execution',
                    'sources':sources,'loaded_media_source_review':desc('composite-source-review.json')})
                attachment=write('attachment.json',{'contract':'waapi-skill.runtime-observation-attachment/v1','branch_id':identity,
                    'proof':proof,'evidence':nd,'native_equivalence':eq})
        pd={**write(prefix+'program.json',program),'nodeid':captured['nodeid']}
        for binding in document['bindings'].values():binding['evidence']['program']=deepcopy(pd)
        bd=write(prefix+'bindings.json',document);rd=write(prefix+'requirements.json',policies)
        index['entries'].append({'id':name_prefix+'loaded-media-'+str(number),'bindings':bd,'origin':{'bindings':bd,'program':desc(prefix+'program.json'),'requirements':rd,'capture':cp}})
        requirements['branches'].update(policies['branches'])
    if selected!={i for i,e in reviewed['entries'].items() if e['route']==profile['route']} or attachment is None:
        raise ValueError('LoadedMedia bundle requires every exact31 branch plus complete semantic anchor')
    index['runtime_observation_attachments']=[attachment]
    write('requirements.json',requirements);write('index.json',index)
    return output/(name_prefix+'index.json')



def composite_preservation_gates(root, policies, obligations):
    selected = [b for b in obligations if b['route'] in COMPOSITE_ROUTES.values() and b['id'] in policies]
    if not selected: return {}
    reviewed = composite_review(root)
    gates = {}
    for branch in selected:
        entry = reviewed['entries'].get(branch['id'])
        profile = reviewed['profiles'][branch['route'].split('|')[0]]
        gates[branch['id']] = ([] if branch['id'] == profile['anchor'] else [profile['anchor']]) if (
            entry and entry['shape_sha256'] == branch['shape_sha256'] and policies[branch['id']] == composite_policy(entry)) else None
    return gates


def _positive_from_proof(proof, base, root):
    artifact = proof['archive']['artifact']
    suffix = 'r124-originals.json.gz'
    if not artifact.endswith(suffix):
        raise ValueError('LoadedMedia exact positive archive locator differs')
    return original_observation(base,root=root,copied_prefix=artifact[:-len(suffix)])

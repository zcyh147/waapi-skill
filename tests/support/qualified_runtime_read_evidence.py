"""Exact retained R105 read facts; never a successful lifecycle wrapper.

Eligibility is source owned, including the complete immutable original closure.
The ordinary finalized-PASS reader is deliberately not involved in this path.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime

NODE = 'd6e9da42fb2f751cbc535eeb'
CANDIDATE = runtime.RTPC_ORIGINAL_CANDIDATE
ORIGINAL_BASE = '/Users/xiye/Documents/Git/waapi-skills/.waapi-skill-state/full-coverage'
PROFILES = {
    '2021.1': {'build': '2021.1.14.8108', 'time': 24202, 'manifest_count': 172,
        'archive': 'd3fd223608b347e205e9151aeae8ba6820ce478825bcb384b19c426979b53105'},
    '2023.1': {'build': '2023.1.19.8928', 'time': 28746,
        'archive': '74a6e9ad14e924d41d60e75b780daa577752adb8c505a047deba9b0ee69a97aa'},
    '2024.1': {'build': '2024.1.13.9056', 'time': 30069,
        'archive': '91cb35808f25dc24e20e25d1453654bffa0c72450d3449470d117fa2d36147ea'},
}
CATEGORIES = {'profiler-rtpcs-observation': runtime.RTPC_URI,
              'profiler-contributions-bus-observation': runtime.CONTRIBUTION_URI,
              'profiler-voices-seed': 'ak.wwise.core.profiler.getVoices',
              'profiler-busses-seed': 'ak.wwise.core.profiler.getBusses'}
ANCHOR_SELECTORS = 'tests/fixtures/runtime-qualified-reads/r124-native-anchor-selectors.json'
ANCHOR_SELECTORS_SHA = '2d78aef3d8cc69e7acf519004edbf1ac7f542fa4809b21ff745bc4ad3e81bf4d'


def anchor_profile(version, category):
    raw = (audit.ROOT / ANCHOR_SELECTORS).read_bytes()
    if runtime.sha(raw) != ANCHOR_SELECTORS_SHA:
        raise ValueError('Exact43 retained native anchor scope differs')
    return json.loads(raw)['profiles'].get(version + '|' + category)
ERROR = 'post-teardown:SandboxFixtureError:Wwise WAAPI port 0.0.0.0:8080 remained occupied after the 15-second release wait'


def lifecycle_obligations(version=None):
    return [{'issue': 186, 'version': version, 'original_root': original_root(version),
             'obligation': 'owned-Authoring post-teardown port-release/lifecycle', 'status': 'BLOCKED'}
            for version in (('2021.1', '2023.1', '2024.1') if version == '2021.1' else ('2023.1', '2024.1'))]


def original_root(version):
    return ORIGINAL_BASE + '/r105-missing-profiler-native-' + version[:4] + '-r1'


def fixture_path(version, root=audit.ROOT):
    return root / f'tests/fixtures/runtime-qualified-reads/{version}-original.json.gz'


R104_CANDIDATE = 'a5884dcbb655d03a4537ed1e3553ac01e1d2fdb8'
R104_NODE = 'd87a1375cafae330c7be7f7f'
R104_SELECTORS = 'tests/fixtures/runtime-qualified-reads/r125-r104-native-anchor-selectors.json'
R104_SELECTORS_SHA = '59826bc255917de26fdd9a70a228d724941b8c125756195d55045d5ae8f83c68'


def r104_profile(version, category):
    raw = (audit.ROOT / R104_SELECTORS).read_bytes()
    if runtime.sha(raw) != R104_SELECTORS_SHA:
        raise ValueError('Exact22 R104 retained native anchor scope differs')
    profile = json.loads(raw)['profiles'].get(version + '|' + category)
    if profile is None:
        raise ValueError('Only exact22 assessed R104 read profiles are eligible')
    return profile


def r104_fixture_path(version, root=audit.ROOT):
    return root / f'tests/fixtures/runtime-qualified-reads/r104-{version}-original.json.gz'


def r104_source_review():
    # R104 differs from the reviewed R105 packaged basis only at this alias repair.
    changes = deepcopy(runtime.RTPC_REVIEWED_SOURCE_CHANGES)
    changes['skills/waapi-skill/wwise_waapi/builders/stable_reads.py']['before'] = '74e37957692c6748f6c7f8f6c4dd795dc31c10b78ba0d30500a90d59b818412d'
    symbols = deepcopy(runtime.RTPC_REVIEWED_SOURCE_SYMBOLS)
    symbols['skills/waapi-skill/wwise_waapi/builders/stable_reads.py'] = ['normalize_profiler_game_objects_result: accept actual registerTime/unregisterTime and reflected registrationTime/unregistrationTime; preserve ID/name/time values']
    return changes, symbols


def retained_r104_read(version, category, descriptor=None, base=None):
    """Exact failed R104 roots, independently assessed read facts and actual cleanup."""
    import base64
    import gzip
    profile = r104_profile(version, category)
    if descriptor is None:
        path = r104_fixture_path(version)
        base, descriptor = path.parent, {'artifact': path.name, 'sha256': runtime.sha(path.read_bytes())}
    if descriptor['sha256'] != profile['archive']:
        raise ValueError('Exact R104 whole original closure differs')
    read = runtime.archive_reader(descriptor, base)
    encoded = json.loads(gzip.decompress((base / descriptor['artifact']).read_bytes()))['files']
    if len(encoded) != profile['files'] or audit.digest(encoded) != profile['decoded_files_sha256']:
        raise ValueError('Exact R104 decoded whole archive map differs')
    root = profile['original_root']
    def load(relative): return json.loads(read(root + '/' + relative))
    node = load(f'evidence/authoring-node-observations/{R104_NODE}.json')
    sources = node['source_context']['sources']
    if (node['candidate'] != R104_CANDIDATE or node['source_context']['candidate'] != R104_CANDIDATE
            or node['nodeid'] != 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_profiler_capture_reads'
            or len(sources) != 616 or audit.digest(sources) != 'ea923adf89f880842b4fcaff20fc22ec7478fedd9b62c5e2128990a12e45e42b'):
        raise ValueError('Exact R104 candidate/full source context differs')
    manifest = {}
    for name, group in node['artifacts'].items():
        if group['path'] != root + f'/evidence/authoring-node-observations/{R104_NODE}-' + name:
            raise ValueError('Exact R104 manifest group differs')
        for item in group['files']:
            path = group['path'] + '/' + item['path']
            if Path(item['path']).is_absolute() or '..' in Path(item['path']).parts or path in manifest:
                raise ValueError('Exact R104 manifest path differs')
            raw = read(path)
            if runtime.sha(raw) != item['sha256'] or len(raw) != item['bytes']:
                raise ValueError('Exact R104 manifest artifact differs')
            manifest[path] = raw
    if len(manifest) != profile['manifest_count']:
        raise ValueError('Complete R104 original native manifest required')
    capture = json.loads(manifest[root + f'/evidence/authoring-node-observations/{R104_NODE}-native-evidence/profiler-capture.json'])
    life, quarantine, start = (load('evidence/' + n + '.json') for n in ('lifecycle', 'quarantine', 'start'))
    review = load('root-review.json')
    if (life['final_status'] != 'BLOCKED' or life['requested_status'] != 'BLOCKED'
            or life['errors'] != [] or life['sandbox_retained'] is not True
            or life['source_hash_before'] != life['source_hash_after']
            or life['source_mtime_before_ns'] != life['source_mtime_after_ns']
            or quarantine['status'] != 'BLOCKED' or quarantine['never_reuse'] is not True or quarantine['errors'] != []
            or review['candidate'] != R104_CANDIDATE or review['version'] != version
            or review['exit_code'] != 1 or review['formal_outcome'] != 'BLOCKED'
            or review['source_context_files_checked'] != 616 or review['archive_files_checked'] != len(manifest)
            or review['integrity_errors'] != [] or review['lifecycle_errors'] != []
            or any(review[k] is not True for k in ('source_unchanged', 'cleanup_complete', 'fixture_preserved', 'post_terminal_port_8080_bindable'))
            or review['post_terminal_owned_processes'] != []):
        raise ValueError('R104 original blocked workflow/completed physical cleanup facts differ')
    if (capture['candidate'] != R104_CANDIDATE or capture['version'] != version
            or capture['host']['isCommandLine'] is not False or start['get_info'] != capture['host']
            or start['authoring_build'] != profile['build'] or start['version'] != version
            or capture['complete'] is not False or capture['capture_read_batch'] is not True or capture['errors'] != []
            or capture['fixture_before'] != capture['fixture_after']
            or capture['capture_position']['position_ms'] != profile['time']
            or capture['cleanup']['complete'] is not True or capture['cleanup']['errors'] != []
            or capture['cleanup']['transport_stopped_observation']['state'] != 'stopped'):
        raise ValueError('R104 actual host/time/preservation/collector cleanup differs')
    receipt, = [r for r in node['receipts'] if r['argv'] == profile['public_argv']]
    raw = json.loads(manifest[profile['raw_path']])
    if (runtime.sha(manifest[profile['raw_path']]) != profile['raw_sha256'] or raw['api'] != profile['uri']
            or raw['version'] != version or raw['ok'] is not True or raw['dry_run'] is not False or raw['error_code'] is not None
            or receipt['exit_code'] != profile['public_exit_code']):
        raise ValueError('Exact R104 native packet/original public outcome differs')
    # Every selected read is tied to the independently observed Soundcaster at the same T.
    game_id = capture['transport_association']['gameObject']
    audio = capture['outcomes']['profiler-audio-objects-observation']
    ae = audio['evidence']
    if (game_id != 18446744073709551614 or audio['outcome'] != 'PASS'
            or ae['owned_identity_observed'] is not True or ae['complete'] is not True or ae['nonempty'] is not True
            or ae['identity_ties'] != {'sound_row_indexes': [], 'bus_row_indexes': [], 'transport_game_object_row_indexes': [0, 1]}
            or any(row['gameObjectID'] != game_id or row['busGUID'] != '{1514A4D8-1DA6-412A-A17E-75CA0C2149F3}' for row in ae['agent_result']['return'])):
        raise ValueError('R104 actual owned Soundcaster/runtime Bus association differs')
    from tests.support.fixed_runtime_read_evidence import row_data
    rows = raw['result']['return']
    facts = {'original_workflow_outcome': 'BLOCKED', 'original_finalization': 'BLOCKED',
        'original_public_exit_code': receipt['exit_code'], 'physical_cleanup_complete': True,
        'post_terminal_port_8080_bindable': True, 'post_terminal_owned_processes': [],
        'cleanup_credit_transferred': False, 'original_read_outcome': 'PASS',
        'qualified_scope': 'owned Soundcaster/runtime Bus association; no Cars mixing-Bus effect'}
    if category == 'r104-object-rtpcs-observation':
        outcome = capture['outcomes']['profiler-rtpcs-observation']; evidence = outcome['evidence']
        if (outcome['outcome'] != 'BLOCKED' or evidence['observation_status'] != 'PASS'
                or evidence['owned_identity_observed'] is not False or evidence['rpm_stimulus_row_indexes'] != []
                or evidence['owned_game_object_row_indexes'] != [0, 1] or evidence['attribution_scope'] != 'controlled-global-rtpc'
                or capture['fixture_before']['rpm']['id'] != rows[0]['id'] or capture['fixture_before']['rpm']['name'] != rows[0]['name']
                or [(r['name'], r['gameObjectId'], r['value']) for r in rows] != [('RPM', game_id, 1000.0), ('Engine_Load', game_id, 1.0)]):
            raise ValueError('R104 object-specific RTPC fact/global-effect failure boundary differs')
        facts.update(original_read_outcome='BLOCKED', collector_owned_identity_observed=False,
            qualified_scope='object-specific read facts only; global setter effect unverified')
        if receipt['payload']['agent_result'] != evidence['agent_result']:
            raise ValueError('Original R104 complete RTPC public result differs')
    elif category == 'r104-game-objects-observation':
        if len(rows) != 1 or rows[0]['id'] != game_id or rows[0]['name'] != 'Transport/Soundcaster':
            raise ValueError('R104 GameObject raw identity differs')
        facts['qualified_scope'] = 'actual owned Soundcaster GameObject ID; current timestamp-alias replay'
        if version == '2022.1':
            if receipt['payload'].get('error_code') != 'INVALID_STABLE_READ_RESULT' or receipt['payload'].get('ok') is not False:
                raise ValueError('R104 original public alias-normalization failure must remain')
            facts['original_read_outcome'] = 'FAIL'
        elif receipt['payload']['ok'] is not True:
            raise ValueError('Original R104 successful public GameObject read required')
    elif audit.digest(row_data(ae['agent_result']['return'])) != audit.digest(rows) or len(rows) != 2:
        raise ValueError('R104 complete original AudioObject native/public array differs')
    if receipt['exit_code'] == 0 and profile['uri'] != 'ak.wwise.core.profiler.getGameObjects':
        public = receipt['payload']['agent_result']
        if public['complete'] is not True or public['truncated'] is not False or audit.digest(row_data(public['return'])) != audit.digest(rows):
            raise ValueError('Complete nontruncated R104 original public result required')
    request = {'args': {'time': profile['time']}, 'options': {}}
    if category == 'r104-audio-objects-observation':
        issuers = [json.loads(data) for name, data in manifest.items()
            if '/runtime-inspection-observations-v1/rto1-' in name]
        issuer, = [item for item in issuers if item['plan']['request']['api'] == profile['uri']
            and item['plan']['request']['args'] == request['args']]
        if audit.digest(row_data(issuer['plan']['result']['return'])) != audit.digest(rows):
            raise ValueError('R104 exact original AudioObject request issuer/result differs')
        request = issuer['plan']['request']
    return {'node': node, 'capture': capture, 'receipt': receipt, 'raw': raw, 'manifest': manifest,
            'sources': sources, 'profile': profile, 'request': request, 'facts': facts}


def retained_read(version, category, descriptor=None, base=None):
    """Read exactly one immutable closure, resolving only archived manifest paths."""
    if category.startswith('r104-'):
        return retained_r104_read(version, category, descriptor, base)
    profile = PROFILES[version]
    selected_profile = anchor_profile(version, category)
    if category not in CATEGORIES or (version == '2021.1' and selected_profile is None):
        raise ValueError('Only exact retained read categories are eligible')
    if descriptor is None:
        path = fixture_path(version)
        base, descriptor = path.parent, {'artifact': path.name, 'sha256': runtime.sha(path.read_bytes())}
    if descriptor['sha256'] != profile['archive']:
        raise ValueError('Exact retained original closure differs')
    read = runtime.archive_reader(descriptor, base)
    root = original_root(version)
    def load(relative):
        return json.loads(read(root + '/' + relative))
    node = load(f'evidence/authoring-node-observations/{NODE}.json')
    sources = node['source_context']['sources']
    if (node['candidate'] != CANDIDATE or node['source_context']['candidate'] != CANDIDATE
            or len(sources) != 616
            or audit.digest(sources) != '41d79c2ea620cb9b75859365e2f66346e1c57ec52485978898fbce421b215dca'):
        raise ValueError('Exact original full source context differs')
    manifest = {}
    for name, group in node['artifacts'].items():
        directory = group['path']
        expected = root + f'/evidence/authoring-node-observations/{NODE}-' + name
        if directory != expected:
            raise ValueError('Original archived group identity differs')
        for item in group['files']:
            path = directory + '/' + item['path']
            if Path(item['path']).is_absolute() or '..' in Path(item['path']).parts or path in manifest:
                raise ValueError('Original archived manifest path differs')
            raw = read(path)
            if len(raw) != item['bytes'] or runtime.sha(raw) != item['sha256']:
                raise ValueError('Original manifest artifact differs')
            manifest[path] = raw
    if len(manifest) != profile.get('manifest_count', 168):
        raise ValueError('Complete original native manifest required')
    capture = json.loads(manifest[root + f'/evidence/authoring-node-observations/{NODE}-native-evidence/profiler-capture.json'])
    failure, release = load('evidence/authoring-batch-finalization-error.json'), load('evidence/lifecycle-release-error.json')
    lifecycle, quarantine, start = (load('evidence/' + name + '.json') for name in ('lifecycle', 'quarantine', 'start'))
    if (failure != {'outcome': 'BLOCKED', 'error': {'type': 'ScenarioLifecycleError', 'message': ERROR}}
            or release != {'error': ERROR, 'phase': 'post-teardown', 'status': 'BLOCKED'}
            or lifecycle['final_status'] != 'PREPARED' or lifecycle['requested_status'] != 'PASS'
            or lifecycle['cleanup_deferred'] is not True or lifecycle['sandbox_retained'] is not True
            or lifecycle['errors'] != [] or lifecycle['source_hash_before'] != lifecycle['source_hash_after']
            or lifecycle['source_mtime_before_ns'] != lifecycle['source_mtime_after_ns']
            or quarantine['status'] != 'PREPARED' or quarantine['never_reuse'] is not True
            or quarantine['errors'] != []):
        raise ValueError('Exact retained BLOCKED lifecycle/quarantine required')
    if (capture['candidate'] != CANDIDATE or capture['version'] != version
            or capture['host']['isCommandLine'] is not False or start['get_info'] != capture['host']
            or start['authoring_build'] != profile['build'] or start['version'] != version
            or capture['complete'] is not True or capture['capture_read_batch'] is not True
            or capture['missing_only'] is not True or capture['errors'] != []
            or capture['fixture_before'] != capture['fixture_after']
            or capture['capture_position']['position_ms'] != profile['time']
            or capture['cleanup']['complete'] is not True or capture['cleanup']['errors'] != []
            or capture['cleanup']['transport_stopped_observation']['state'] != 'stopped'):
        raise ValueError('Original read context/completeness differs')
    outcome = (capture['seed_observations'][category.replace('-seed', '-observation')]
        if category.endswith('-seed') else capture['outcomes'][category])
    evidence = outcome['evidence']
    if (outcome['outcome'] != 'PASS' or evidence['observation_status'] != 'PASS'
            or evidence['owned_identity_observed'] is not True or evidence['complete'] is not True):
        raise ValueError('Original exact read observation did not pass')
    uri = CATEGORIES[category]
    receipts = [row for row in node['receipts'] if
        (row['argv'][:2] == ['core-call', uri] if uri == runtime.RTPC_URI else
         row['argv'][:2] == ['core-call', uri] if category.endswith('-seed') else
         row['argv'][0] == 'profiler-voice-contributions' and '--bus-instance-handle' in row['argv'])]
    receipt, = receipts
    logical = receipt['payload']['call']['evidence_path']
    prefix = root + f'/owned/authoring-nodes/{NODE}/native-evidence/'
    if not logical.startswith(prefix) or '/' in logical[len(prefix):]:
        raise ValueError('Original public native artifact link differs')
    raw_path = root + f'/evidence/authoring-node-observations/{NODE}-native-evidence/' + logical[len(prefix):]
    raw = json.loads(manifest[raw_path])
    if (raw['api'] != uri or raw['version'] != version or raw['ok'] is not True
            or raw['dry_run'] is not False or raw['error_code'] is not None
            or receipt['exit_code'] != 0 or receipt['payload']['ok'] is not True):
        raise ValueError('Successful original public/native read required')
    request = None
    if selected_profile is not None:
        if (raw_path != selected_profile['raw_path'] or runtime.sha(manifest[raw_path]) != selected_profile['raw_sha256']
                or receipt['argv'] != selected_profile['public_argv']
                or receipt['payload']['is_command_line'] is not False
                or receipt['payload']['agent_result'] != evidence['agent_result']):
            raise ValueError('Exact assessed native anchor packet/public receipt differs')
    if category.endswith('-seed'):
        from tests.support.fixed_runtime_read_evidence import row_data
        public = receipt['payload']['agent_result']
        kind = 'voice' if uri.endswith('getVoices') else 'bus'
        if (public['complete'] is not True or public['truncated'] is not False
                or len(raw['result']['return']) != 1
                or audit.digest(raw['result']['return']) != audit.digest(row_data(public['return']))
                or evidence['nonempty'] is not True):
            raise ValueError('Complete nonempty original seed native/public array required')
        handle = 'rto1-' + public['return'][0][kind + '_instance_handle'][5:].rsplit('-', 1)[0]
        plan_path, = [name for name in manifest if name.endswith('/runtime-inspection-observations-v1/' + handle + '.json')]
        plan = json.loads(manifest[plan_path]); request = plan['plan']['request']
        contribution, = [r for r in node['receipts'] if r['argv'][0] == 'profiler-voice-contributions' and '--bus-instance-handle' in r['argv']]
        args = contribution['payload']['semantic_preview']['args']
        selected = [args['voicePipelineID']] if kind == 'voice' else args['bussesPipelineID']
        if (plan['handle'] != handle or request['api'] != uri or request['args'] != {'time': profile['time']}
                or args['time'] != profile['time'] or [r['pipelineID'] for r in raw['result']['return']] != selected
                or audit.digest(row_data(plan['plan']['result']['return'])) != audit.digest(raw['result']['return'])):
            raise ValueError('Original seed issuer/owned contribution identity/time differs')
    return {'node': node, 'capture': capture, 'receipt': receipt, 'raw': raw,
            'manifest': manifest, 'sources': sources, 'profile': profile, 'request': request}


def retained_contribution_inputs(version):
    """Feed the existing public fake seam the original complete read and identities."""
    retained = retained_read(version, 'profiler-contributions-bus-observation')
    args = retained['receipt']['payload']['semantic_preview']['args']
    rows = {}
    for suffix, identities in (('getVoices', [args['voicePipelineID']]),
                               ('getBusses', args['bussesPipelineID'])):
        matches = []
        for name, raw in retained['manifest'].items():
            if name.endswith('-ak_wwise_core_profiler_' + suffix + '.json'):
                packet = json.loads(raw)
                result = packet['result']['return']
                if packet['ok'] is True and all(sum(row.get('pipelineID') == identity
                    for row in result) == 1 for identity in identities):
                    matches.append(result)
        if not matches:
            raise ValueError('Original unique voice/Bus seed identity missing')
        rows[suffix] = [deepcopy(next(row for row in matches[-1] if row['pipelineID'] == identity))
                        for identity in identities]
    return fixture_path(version), retained['receipt'], retained['raw'], rows


def selected_mappings(inventory, captured, version, category):
    if category.startswith('r104-'):
        profile = r104_profile(version, category)
        route = next(r for r in inventory['native_coverage']['routes'] if r['id'] == profile['route'])
        allowed = {r['id'] for r in profile['selectors']}
        if category == 'r104-object-rtpcs-observation':
            mappings = [{'branch': b, 'program_pointer': '/native_call/result/return/0/' + b['pointer'].rsplit('/', 1)[1], 'reference_chain': []}
                for b in inventory['native_coverage']['obligations'] if b['id'] in allowed]
        else:
            from tests.support.fixed_runtime_read_evidence import mappings as fixed_mappings
            mappings = fixed_mappings(inventory, captured, route, selected=allowed)
        return route, mappings
    if category.endswith('-seed'):
        from tests.support.fixed_runtime_read_evidence import mappings as fixed_mappings
        route = next(r for r in inventory['native_coverage']['routes'] if r['id'] == anchor_profile(version, category)['route'])
        mappings = fixed_mappings(inventory, captured, route)
    elif category == 'profiler-rtpcs-observation':
        route, mappings = runtime.rtpc_field_mappings(inventory, version=version, host='wwise-authoring', mode='data')
        for mapping in mappings:
            mapping['program_pointer'] = mapping['program_pointer'].replace('/return/1/', '/return/7/')
    else:
        route, mappings = runtime.contribution_field_mappings(inventory, captured, version=version, host='wwise-authoring')
        mappings = [row for row in mappings if row['categories'] == ['program', 'native']
                    and row['branch']['pointer'].startswith('/resultSchema')]
    profile = anchor_profile(version, category)
    if profile is not None:
        allowed = {r['id']: r['shape_sha256'] for r in profile['selectors']}
        mappings = [r for r in mappings if r['branch']['id'] in allowed and r['branch']['shape_sha256'] == allowed[r['branch']['id']]]
    return route, mappings


def write_qualified_read_bundle(output, program_path, original, *, inventory, version, category, selected=None, name_prefix=""):
    """Add one retained observation to ordinary shared per-branch program output."""
    runtime.validate_runtime_file_prefix(name_prefix)
    is_r104 = category.startswith('r104-')
    original_fixture = r104_fixture_path(version) if is_r104 else fixture_path(version)
    root_locator = r104_profile(version, category)['original_root'] if is_r104 else original_root(version)
    if Path(original) != Path(root_locator) and Path(original) != original_fixture:
        raise ValueError('Exact retained original locator required')
    retained = retained_read(version, category)
    captured = json.loads(Path(program_path).read_bytes())
    route, mappings = selected_mappings(inventory, captured, version, category)
    if selected is not None:
        mappings = [row for row in mappings if row['branch']['id'] in selected]
        if {row['branch']['id'] for row in mappings} != selected:
            raise ValueError('Selected branch has no independently observed native result fact')
    if not mappings:
        raise ValueError('No qualified result mappings')
    output = Path(output)
    if category.endswith('-seed') or (is_r104 and category != 'r104-object-rtpcs-observation'):
        from tests.support.fixed_runtime_read_evidence import write_fixed_bundle
        index_path = write_fixed_bundle(output, program_path, None, inventory=inventory, selected={r['branch']['id'] for r in mappings}, name_prefix=name_prefix)
    elif category in {'profiler-rtpcs-observation', 'r104-object-rtpcs-observation'}:
        index_path = runtime.write_field_bundle(output, program_path, None, inventory=inventory,
            version=version, host='wwise-authoring', mode='data', mappings=mappings, name_prefix=name_prefix)
    else:
        index_path = runtime.write_read_bundle(output, program_path, None, inventory=inventory,
            version=version, host='wwise-authoring', mode='qualified-data', mappings=mappings, name_prefix=name_prefix)
    index = json.loads(index_path.read_bytes())
    if not (category.endswith('-seed') or (is_r104 and category != 'r104-object-rtpcs-observation')):
        for entry in index['entries']: entry['id']=name_prefix+entry['id']
    def filename(name): return name_prefix + name
    def write(name, value): return runtime.write_json(output / filename(name), value)
    shutil.copyfile(original_fixture, output / filename('qualified-original.json.gz'))
    assessment = {'contract': 'waapi-skill.qualified-retained-read-assessment/v1',
        'version': version, 'category': category, 'original_candidate': R104_CANDIDATE if is_r104 else CANDIDATE,
        'original_workflow_outcome': 'BLOCKED', 'original_finalization': 'BLOCKED',
        'successful_finalization': False, 'qualified_read_fact': 'PASS',
        'lifecycle_obligations': [] if is_r104 else lifecycle_obligations(version),
        'archive': {'artifact': filename('qualified-original.json.gz'), 'sha256': retained['profile']['archive']},
        'program_capture': index['entries'][0]['origin']['capture'],
        'source_changes': runtime.RTPC_REVIEWED_SOURCE_CHANGES,
        'changed_symbols': runtime.RTPC_REVIEWED_SOURCE_SYMBOLS}
    if is_r104:
        assessment['source_changes'], assessment['changed_symbols'] = r104_source_review()
        assessment['retained_facts'] = retained['facts']
    assessment_descriptor = write('qualified-assessment.json', assessment)
    bindings = completion.read_sealed_artifact(index['entries'][0]['bindings'], output)['bindings']
    attachments = []
    for number, mapping in enumerate(mappings):
        branch = mapping['branch']; identity = branch['id']; pointer = mapping['program_pointer']
        native = {'contract': 'waapi-skill.qualified-retained-read-fact/v1',
            'assessment_sha256': assessment_descriptor['sha256'], 'branch_id': identity,
            'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
            'program_pointer': pointer, 'reference_chain': mapping['reference_chain'],
            'observed': completion.pointer_value(retained['raw'], pointer.removeprefix('/native_call'))}
        descriptor = write(f'qualified-native-{number}.json', native)
        attachments.append(write(f'qualified-attachment-{number}.json', {
            'contract': 'waapi-skill.qualified-retained-read-attachment/v1', 'branch_id': identity,
            'assessment': assessment_descriptor, 'evidence': descriptor}))
    index['qualified_runtime_read_attachments'] = attachments
    runtime.write_json(index_path, index)
    return index_path


def attach_qualified_reads(descriptors, bindings, read, requirements, captures):
    if not isinstance(descriptors, list):
        raise ValueError('Qualified retained read attachments must be a list')
    attached = set()
    for descriptor in descriptors:
        item = read(descriptor)
        if set(item) != {'contract', 'branch_id', 'assessment', 'evidence'} or item['contract'] != 'waapi-skill.qualified-retained-read-attachment/v1':
            raise ValueError('Closed qualified retained read attachment required')
        identity = item['branch_id']; binding = bindings[identity]
        assessment = read(item['assessment'])
        if (identity in attached or set(binding['evidence']) != {'program'}
                or requirements['branches'][identity]['categories'] != ['program', 'native']
                or captures[identity] != read(assessment['program_capture'])):
            raise ValueError('Qualified retained read needs exact existing program/native policy and capture')
        attached.add(identity)
        binding['qualified_runtime_read_attachment'] = item['assessment']
        binding['evidence']['native'] = item['evidence']


def qualified_read_result(descriptor, branch, candidate, scope_kind, base, binding, root, edges, historical_sources):
    assessment = completion.read_sealed_artifact(binding['qualified_runtime_read_attachment'], base)
    if assessment.get('contract') == 'waapi-skill.retained-owned-control-assessment/v1':
        from tests.support.runtime_owned_control_evidence import qualified_result
        return qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges)
    if assessment.get('contract') == 'waapi-skill.retained-capture-control-assessment/v1':
        from tests.support.runtime_capture_control_evidence import qualified_result
        return qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges)
    if assessment.get('contract') == 'waapi-skill.retained-cursor-assessment/v1':
        from tests.support.runtime_cursor_evidence import qualified_result
        return qualified_result(descriptor,assessment,branch,candidate,scope_kind,base,binding,root,edges)
    if assessment.get('contract') == 'waapi-skill.meter-runtime-read-assessment/v1':
        from tests.support.meter_runtime_read_evidence import qualified_result
        return qualified_result(descriptor, assessment, branch, candidate, scope_kind, base, binding, root, edges)
    if assessment.get('contract') == 'waapi-skill.extra-runtime-read-assessment/v1':
        from tests.support.extra_runtime_read_evidence import qualified_result
        return qualified_result(descriptor, assessment, branch, candidate, scope_kind, base, binding, root, edges)
    if assessment.get('contract') == 'waapi-skill.retained-log-assessment/v1':
        from tests.support.runtime_log_retained_evidence import qualified_result
        return qualified_result(descriptor, assessment, branch, candidate, scope_kind, base, binding, root, edges)
    is_r104 = assessment['category'].startswith('r104-')
    profile = r104_profile(assessment['version'], assessment['category']) if is_r104 else PROFILES[assessment['version']]
    original_candidate = R104_CANDIDATE if is_r104 else CANDIDATE
    if assessment['lifecycle_obligations'] != ([] if is_r104 else lifecycle_obligations(assessment['version'])):
        raise ValueError('All exact lifecycle obligations remain BLOCKED on #186')
    version, host, build, kind, uri = branch['route'].split('|')
    if (scope_kind != 'product' or (not is_r104 and version not in PROFILES) or host != 'wwise-authoring'
            or build != profile['build'] or kind != 'function'
            or (profile['uri'] if is_r104 else CATEGORIES.get(assessment['category'])) != uri or assessment['version'] != version
            or not branch['pointer'].startswith('/resultSchema')):
        raise ValueError('Qualified retained read exact route/result scope differs')
    selected_profile = profile if is_r104 else anchor_profile(version, assessment['category'])
    if selected_profile is not None and not any(r['id'] == branch['id'] and r['shape_sha256'] == branch['shape_sha256'] for r in selected_profile['selectors']):
        raise ValueError('Only exact43 approved native anchor selectors are eligible')
    expected = {'contract', 'version', 'category', 'original_candidate', 'original_workflow_outcome',
        'original_finalization', 'successful_finalization', 'qualified_read_fact', 'lifecycle_obligations',
        'archive', 'program_capture', 'source_changes', 'changed_symbols'}
    if is_r104:
        expected.add('retained_facts')
    if (set(assessment) != expected or assessment['contract'] != 'waapi-skill.qualified-retained-read-assessment/v1'
            or assessment['original_candidate'] != original_candidate or assessment['original_workflow_outcome'] != 'BLOCKED'
            or assessment['original_finalization'] != 'BLOCKED' or assessment['successful_finalization'] is not False
            or assessment['qualified_read_fact'] != 'PASS'):
        raise ValueError('Qualified assessment must preserve original BLOCKED finalization')
    retained = retained_read(version, assessment['category'], assessment['archive'], base)
    if is_r104 and assessment['retained_facts'] != retained['facts']:
        raise ValueError('Exact R104 qualified scope/original failures/actual cleanup facts differ')
    sources = retained['sources']
    if completion.historical_source_seals(root, original_candidate, sources, historical_sources) != sources:
        raise ValueError('Original full 616-file candidate source map differs')
    before = {key: value for key, value in sources.items() if key.startswith('skills/waapi-skill/')}
    current = runtime.program_source_context(root, flow=uri)['packaged']
    changes = {key: {'before': before.get(key), 'after': current.get(key)}
               for key in before.keys() | current.keys() if before.get(key) != current.get(key)}
    expected_changes, expected_symbols = r104_source_review() if is_r104 else (runtime.RTPC_REVIEWED_SOURCE_CHANGES, runtime.RTPC_REVIEWED_SOURCE_SYMBOLS)
    if (len(before) != 413 or assessment['source_changes'] != expected_changes
            or changes != expected_changes or assessment['changed_symbols'] != expected_symbols):
        raise ValueError('Exact reviewed five-file source transition differs')
    runtime._portable_descriptor(assessment['program_capture'], base)
    capture = completion.read_sealed_artifact(assessment['program_capture'], base)
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    record = completion.read_sealed_artifact(descriptor, base)
    pointer = binding['observation_pointer']
    if (record != {'contract': 'waapi-skill.qualified-retained-read-fact/v1',
            'assessment_sha256': binding['qualified_runtime_read_attachment']['sha256'],
            'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
            'program_pointer': pointer, 'reference_chain': binding.get('reference_chain', []),
            'observed': completion.pointer_value(retained['raw'], pointer.removeprefix('/native_call'))}
            or program.get('candidate_sha256') != candidate or program.get('scope_kind') != 'product'
            or audit.digest(program.get('runtime_read_program')) != audit.digest(capture)):
        raise ValueError('Qualified exact original branch occurrence/program binding differs')
    completion.exact_observation_pointer(branch, binding, '/native_call', 'result', edges)
    if uri == runtime.RTPC_URI:
        allowed = {'/resultSchema/properties/return/@cardinality/multiple'}
        for field in ('id', 'name', 'gameObjectId', 'value'):
            parent = '/resultSchema/properties/return/items/properties/' + field
            allowed.update((parent, parent + '/$ref', parent + '/@presence/present'))
            edge = edges.get(branch['route'] + '|' + parent + '/$ref')
            if edge:
                allowed.add(edge['reference']['target'].split('|', 5)[5])
        if branch['pointer'] not in allowed:
            raise ValueError('Only existing observed RTPC data branches are eligible')
        runtime.validate_rtpc_program(program, binding, branch, root, edges)
        if audit.digest(capture['native_call']['result']) != audit.digest(retained['raw']['result']):
            raise ValueError('Complete original RTPC array must survive current public replay')
        if capture['gateway']['argv'] != retained['receipt']['argv']:
            raise ValueError('Original RTPC request/time differs')
    elif assessment['category'].endswith('-seed') or is_r104:
        from tests.support.fixed_runtime_read_evidence import validate_program
        validate_program(program, binding, branch, root, edges)
        expected = {'uri': uri, 'args': retained['request']['args'], 'options': retained['request']['options'], 'result': retained['raw']['result']}
        if (audit.digest(capture['native_call']) != audit.digest(expected) or capture['gateway']['argv'] != retained['receipt']['argv']):
            raise ValueError('Complete original seed request/array must survive current public replay')
    else:
        node = runtime._contribution_node(branch, root)
        if runtime._contribution_categories(branch, node) != ['program', 'native']:
            raise ValueError('Only existing observed contribution data branches are eligible')
        runtime.validate_contribution_program(program, binding, branch, root, edges)
        if (audit.digest(capture['native_call']['result']) != audit.digest(retained['raw']['result'])
                or audit.digest(capture['native_call']['args']) != audit.digest(retained['receipt']['payload']['semantic_preview']['args'])
                or audit.digest(capture['gateway']['payload']['agent_result']) != audit.digest(retained['receipt']['payload']['agent_result'])):
            raise ValueError('Complete original contribution/path must survive current public replay')
    if type(capture['native_call']['args']['time']) is not int or capture['native_call']['args']['time'] != profile['time']:
        raise ValueError('Exact original read time differs')
    value = completion.pointer_value(capture, pointer)
    if audit.digest(value) != audit.digest(record['observed']):
        raise ValueError('Same exact native/public scalar type and occurrence required')
    check = ({'pointer': pointer, 'cardinality': branch['value']} if branch['kind'] == 'collection_cardinality'
             else {'pointer': pointer, 'equals': value})
    if not completion.proves_alternative(check, branch):
        raise ValueError('Exact observed value does not prove branch semantics')
    return 'passed', None

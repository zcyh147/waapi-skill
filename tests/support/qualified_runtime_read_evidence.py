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


def retained_read(version, category, descriptor=None, base=None):
    """Read exactly one immutable closure, resolving only archived manifest paths."""
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


def write_qualified_read_bundle(output, program_path, original, *, inventory, version, category, selected=None):
    """Add one retained observation to ordinary shared per-branch program output."""
    if Path(original) != Path(original_root(version)) and Path(original) != fixture_path(version):
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
    if category.endswith('-seed'):
        from tests.support.fixed_runtime_read_evidence import write_fixed_bundle
        index_path = write_fixed_bundle(output, program_path, None, inventory=inventory, selected={r['branch']['id'] for r in mappings})
    elif category == 'profiler-rtpcs-observation':
        index_path = runtime.write_field_bundle(output, program_path, None, inventory=inventory,
            version=version, host='wwise-authoring', mode='data', mappings=mappings)
    else:
        index_path = runtime.write_read_bundle(output, program_path, None, inventory=inventory,
            version=version, host='wwise-authoring', mode='qualified-data', mappings=mappings)
    index = json.loads(index_path.read_bytes())
    shutil.copyfile(fixture_path(version), output / 'qualified-original.json.gz')
    assessment = {'contract': 'waapi-skill.qualified-retained-read-assessment/v1',
        'version': version, 'category': category, 'original_candidate': CANDIDATE,
        'original_workflow_outcome': 'BLOCKED', 'original_finalization': 'BLOCKED',
        'successful_finalization': False, 'qualified_read_fact': 'PASS',
        'lifecycle_obligations': lifecycle_obligations(version),
        'archive': {'artifact': 'qualified-original.json.gz', 'sha256': retained['profile']['archive']},
        'program_capture': index['entries'][0]['origin']['capture'],
        'source_changes': runtime.RTPC_REVIEWED_SOURCE_CHANGES,
        'changed_symbols': runtime.RTPC_REVIEWED_SOURCE_SYMBOLS}
    assessment_descriptor = runtime.write_json(output / 'qualified-assessment.json', assessment)
    bindings = completion.read_sealed_artifact(index['entries'][0]['bindings'], output)['bindings']
    attachments = []
    for number, mapping in enumerate(mappings):
        branch = mapping['branch']; identity = branch['id']; pointer = mapping['program_pointer']
        native = {'contract': 'waapi-skill.qualified-retained-read-fact/v1',
            'assessment_sha256': assessment_descriptor['sha256'], 'branch_id': identity,
            'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
            'program_pointer': pointer, 'reference_chain': mapping['reference_chain'],
            'observed': completion.pointer_value(retained['raw'], pointer.removeprefix('/native_call'))}
        descriptor = runtime.write_json(output / f'qualified-native-{number}.json', native)
        attachments.append(runtime.write_json(output / f'qualified-attachment-{number}.json', {
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
    if assessment['lifecycle_obligations'] != lifecycle_obligations(assessment['version']):
        raise ValueError('All exact lifecycle obligations remain BLOCKED on #186')
    version, host, build, kind, uri = branch['route'].split('|')
    if (scope_kind != 'product' or version not in PROFILES or host != 'wwise-authoring'
            or build != PROFILES[version]['build'] or kind != 'function'
            or CATEGORIES.get(assessment['category']) != uri or assessment['version'] != version
            or not branch['pointer'].startswith('/resultSchema')):
        raise ValueError('Qualified retained read exact route/result scope differs')
    selected_profile = anchor_profile(version, assessment['category'])
    if selected_profile is not None and not any(r['id'] == branch['id'] and r['shape_sha256'] == branch['shape_sha256'] for r in selected_profile['selectors']):
        raise ValueError('Only exact43 approved native anchor selectors are eligible')
    expected = {'contract', 'version', 'category', 'original_candidate', 'original_workflow_outcome',
        'original_finalization', 'successful_finalization', 'qualified_read_fact', 'lifecycle_obligations',
        'archive', 'program_capture', 'source_changes', 'changed_symbols'}
    if (set(assessment) != expected or assessment['contract'] != 'waapi-skill.qualified-retained-read-assessment/v1'
            or assessment['original_candidate'] != CANDIDATE or assessment['original_workflow_outcome'] != 'BLOCKED'
            or assessment['original_finalization'] != 'BLOCKED' or assessment['successful_finalization'] is not False
            or assessment['qualified_read_fact'] != 'PASS'):
        raise ValueError('Qualified assessment must preserve original BLOCKED finalization')
    retained = retained_read(version, assessment['category'], assessment['archive'], base)
    sources = retained['sources']
    if completion.historical_source_seals(root, CANDIDATE, sources, historical_sources) != sources:
        raise ValueError('Original full 616-file candidate source map differs')
    before = {key: value for key, value in sources.items() if key.startswith('skills/waapi-skill/')}
    current = runtime.program_source_context(root, flow=uri)['packaged']
    changes = {key: {'before': before.get(key), 'after': current.get(key)}
               for key in before.keys() | current.keys() if before.get(key) != current.get(key)}
    if (len(before) != 413 or assessment['source_changes'] != runtime.RTPC_REVIEWED_SOURCE_CHANGES
            or changes != runtime.RTPC_REVIEWED_SOURCE_CHANGES
            or assessment['changed_symbols'] != runtime.RTPC_REVIEWED_SOURCE_SYMBOLS):
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
    elif assessment['category'].endswith('-seed'):
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
    if type(capture['native_call']['args']['time']) is not int or capture['native_call']['args']['time'] != PROFILES[version]['time']:
        raise ValueError('Exact original read time differs')
    value = completion.pointer_value(capture, pointer)
    if audit.digest(value) != audit.digest(record['observed']):
        raise ValueError('Same exact native/public scalar type and occurrence required')
    check = ({'pointer': pointer, 'cardinality': branch['value']} if branch['kind'] == 'collection_cardinality'
             else {'pointer': pointer, 'equals': value})
    if not completion.proves_alternative(check, branch):
        raise ValueError('Exact observed value does not prove branch semantics')
    return 'passed', None

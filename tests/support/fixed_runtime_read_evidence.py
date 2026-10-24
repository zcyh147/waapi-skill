"""Source-owned fixed Profiler rows using the existing runtime evidence transport."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import shutil

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import runtime_observation_evidence as runtime

URIS = frozenset('ak.wwise.core.profiler.' + name for name in ('getVoices', 'getBusses', 'getAudioObjects', 'getGameObjects'))
ORIGINAL_CANDIDATE = '4e5eb44bff9b2d173b97559c9d70ff5f7d78d2f3'
NODEID = 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_2025_profiler_readers'
ARCHIVE_SHA = '91324beb53f122fb2348a07e39e7f803f81130824b47ad9955cb842b3ffdf495'
CATEGORY_SHA = '87a77cd2960e890145ad21ccffaa2aa10f65ac374a37515bdc0e50b0431859d4'
CAPTURE_SHA = '6df34044156629b39a414a41e392c41e7c40b425e8e6f6f548c1605e3028ce5f'
CATEGORIES = frozenset(('profiler-voices-observation', 'profiler-busses-observation', 'profiler-audio-objects-observation',
    'profiler-game-objects-observation', 'profiler-voice-instance-filter', 'profiler-bus-instance-filter', 'profiler-audio-objects-bus-filter'))


R118_CANDIDATE = '6e0fb16a53466ab9dd57ea647fc21fb02c0c22e1'
R118_NODEID = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::test_console_owned_2025_transport_profiler_diagnostic'
R118_CATEGORY = 'console-transport-profiler-probe'
R118_CATEGORY_SHA = 'efbbc0487f9473d6b390d9620965b353a5992b84333338f1df67a005d90c7917'
R118_ARCHIVE_SHA = '6fb48b4582a02968ca8cce07714c756bbaf5c2d581a26eecf0ff6f296754eaa5'
R118_CAPTURE_SHA = 'caa3e3aa450a6982438f4ff050c22bc18aa586fc1cbda8155d57c536041d631f'
R118_MAP_SHA = '848d75fa50d2f1f8fb620abe87bf74b0a41a18f676c3cb152aaf280edf22b5c6'
R118_CHANGES = {
    runtime.UNICODE_CONTEXT_SOURCE: runtime.UNICODE_CONTEXT_SOURCE_CHANGE,
    'skills/waapi-skill/scripts/gateway.py': {
        'before': '118f9a62be178b2ad10d9f8525163582f0a1996ec2c2aee4c0856d71ee75c963',
        'after': 'c8dfcff8ae13c9e5b192f4ca7f1e1cd7b52a9f20e5327b33bec15e8a1ecb0bc4'},
    'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': {
        'before': 'c66426240e65d05559c1266ca32b52b3fd2caad08cf0309b37a892373747291d',
        'after': 'f93e41345477d0e3346230c12ebc056511b4c348ee253cb3df33c91d8bd4658d'},
    'skills/waapi-skill/wwise_waapi/operation_registry.py': {
        'before': 'f96a2233a98e03dd62de261a24b3f81876284af28f0973758cf1f8a805b5dd5a', 'after': '3b298a11c9326d47b968783e536d09d290a8fff4a5a7080b5f5f99d5e7c2734d'},
    'skills/waapi-skill/wwise_waapi/runtime_log_effects.py': {
        'before': '62c28fc9bb92ccd8e8efb3ccbfe5b187d6df1d3086c2def79e1d11dbc81ddfe8', 'after': '1f03a038ba77a0ab62fba014329eeeb6962de86902f14fcb60cbfb4de19dea00'}}
R118_SYMBOLS = {
    'wwise_waapi/business_declarations.py': ['BusinessHandleRegistry._require_context: exact UTF-8 byte comparison; no normalization'],
    'scripts/gateway.py': ['_execute_gateway_unconstrained: retain only already-attested getInfo bool in missing finish host context; preserve exact agent_result last; no additional call or successful read request/result change', 'runtime_authoring_host_required_payload: message only', 'runtime_log_observation_support import; live_log_topic_boundary; dispatch_command/dispatch_topic_stream: exact log Topic guard', 'dispatch_offline_command/dispatch_runtime_inspection_business_read: exact log disclosure only', '_dispatch_transaction_command_with_execution_lease: exact log observation-plan drift/event selection only'],
    'wwise_waapi/runtime_inspection_business_contracts.py': [
        'runtime_inspection_business_catalog_rows: remove pending development status and expose matching registered Console transport versions',
        'runtime_transport_requires_authoring: docstring and matching registered Console transport admission only', 'runtime_log_observation_support/CONSOLE_LOG_ADD_OBSERVER; runtime_inspection_business_catalog_rows/runtime_inspection_business_contract_data: exact log metadata only'],
    'wwise_waapi/operation_registry.py': ['prepare_operation/verify_prepared_operation: exact log observation plan, verifier selection and message only'],
    'wwise_waapi/runtime_log_effects.py': ['compare_channel: exact Console log observation guard only']}


R119_CANDIDATE = '301a2235f51b1721fb113a1e01311bc59ab67f87'
R119_CHANGES = {runtime.UNICODE_CONTEXT_SOURCE: runtime.UNICODE_CONTEXT_SOURCE_CHANGE,
    'skills/waapi-skill/scripts/gateway.py': {
        'before': 'cd8367bee13c94d59e4880994468fd2cfd7cc1119969f65c881cfd7739785388', 'after': 'c8dfcff8ae13c9e5b192f4ca7f1e1cd7b52a9f20e5327b33bec15e8a1ecb0bc4'},
    'skills/waapi-skill/wwise_waapi/operation_registry.py': {
        'before': 'f96a2233a98e03dd62de261a24b3f81876284af28f0973758cf1f8a805b5dd5a', 'after': '3b298a11c9326d47b968783e536d09d290a8fff4a5a7080b5f5f99d5e7c2734d'},
    'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': {
        'before': '8f8aa5ce579dc9a0c895341b9c835e4e93060ea4c30f1525f0d2a31fc28883c1', 'after': 'f93e41345477d0e3346230c12ebc056511b4c348ee253cb3df33c91d8bd4658d'},
    'skills/waapi-skill/wwise_waapi/runtime_log_effects.py': {
        'before': '62c28fc9bb92ccd8e8efb3ccbfe5b187d6df1d3086c2def79e1d11dbc81ddfe8', 'after': '1f03a038ba77a0ab62fba014329eeeb6962de86902f14fcb60cbfb4de19dea00'}}
R119_SYMBOLS = {'wwise_waapi/business_declarations.py': [
    'BusinessHandleRegistry._require_context: exact UTF-8 byte comparison; no normalization'],
    'scripts/gateway.py': ['_execute_gateway_unconstrained: retain only already-attested getInfo bool in missing finish host context; preserve exact agent_result last; no additional call or successful read request/result change', 'runtime_log_observation_support import; live_log_topic_boundary; dispatch_command/dispatch_topic_stream: exact log Topic guard', 'dispatch_offline_command/dispatch_runtime_inspection_business_read: exact log disclosure only', '_dispatch_transaction_command_with_execution_lease: exact log observation-plan drift/event selection only'],
    'wwise_waapi/runtime_inspection_business_contracts.py': ['runtime_log_observation_support/CONSOLE_LOG_ADD_OBSERVER; runtime_inspection_business_catalog_rows/runtime_inspection_business_contract_data: exact log metadata only'],
    'wwise_waapi/operation_registry.py': ['prepare_operation/verify_prepared_operation: exact log observation plan, verifier selection and message only'],
    'wwise_waapi/runtime_log_effects.py': ['compare_channel: exact Console log observation guard only']}
R119_NODEID = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::test_console_owned_older_transport_profiler_diagnostic'
R119_MAP_SHA = 'f9afa45f46d2d7e193a7d6ad825c008ace08a85dfd711d9b696d52bcd85a8aab'
R119_PROFILES = {'2021.1': {'name': 'r119-2021',
            'version': '2021.1',
            'build': '2021.1.14.8108',
            'time': 5077,
            'category_sha': '1c427d8ac5c282f400376437bd7073923ab388bcc6f9fb88cb03d03361b85b12',
            'archive_sha': '384df9af9fded495af429350c40ac52006d020d87d071adaa19c3da1f19bec71',
            'capture_sha': '25d3cb0c6038944391b440dbb97dc04df0d554c3cc77d59ddd475d959ac81811',
            'category_file': 'r119-2021-category.json',
            'archive_file': 'r119-2021-originals.json.gz'},
 '2022.1': {'name': 'r119-2022',
            'version': '2022.1',
            'build': '2022.1.19.8584',
            'time': 5280,
            'category_sha': '0ccfcf947b8f28bb6afe067a030e19a125bd50b790fb15a91aac1f29b7dcfff6',
            'archive_sha': 'd6c59a51f5b0d82937fba7272089592ee3a81cf03fba7ecaf1f3d4162fa7f43a',
            'capture_sha': '87ba75235f9156ef27e61b62cc92753acc0cc227ef5355890b1de3365c462119',
            'category_file': 'r119-2022-category.json',
            'archive_file': 'r119-2022-originals.json.gz'},
 '2023.1': {'name': 'r119-2023',
            'version': '2023.1',
            'build': '2023.1.19.8928',
            'time': 6005,
            'category_sha': '6b77899fb75f0cc572bbb048fa39b35734f8b4494e7066c3a33254e805fd4d6a',
            'archive_sha': 'eb3e95c21acbfaeb26f1b00cd25f757d07f73a6d9f68cc3e84fbd4e9ba2e3ef7',
            'capture_sha': 'ea3f7cf21002c347974b2521e73a32d41bfc12f601ba6cf82ec6c1332a1fb421',
            'category_file': 'r119-2023-category.json',
            'archive_file': 'r119-2023-originals.json.gz'},
 '2024.1': {'name': 'r119-2024',
            'version': '2024.1',
            'build': '2024.1.13.9056',
            'time': 5781,
            'category_sha': '82880810123ab6412f09be6d339e5d199da4a80b1d597fd9f22ed0c4b7723ee4',
            'archive_sha': 'e6d9e068317da00910187ff5073594badc54b96bab717da7bad18fe3c2340df0',
            'capture_sha': '55cd97478a40dc78fcceaecb66500617dd887d09129300416e090bb7a91d9d9c',
            'category_file': 'r119-2024-category.json',
            'archive_file': 'r119-2024-originals.json.gz'}}



R105_SEED_NODEID = 'tests/destructive/test_authoring_ui_business_live.py::test_runtime_owned_missing_profiler_reads'
R105_SEED_CATEGORY_SHA = '46f35b09db3c1f298d4c29cc6869ce965db56eccf6a120c548e1e4aa0713626c'
R105_SEED_ARCHIVE_SHA = '6f1c7f297bfad4ae0130b40d84d15c7bedd8208e6f45cbf3e236d94fb17f3b79'
R105_SEED_PACKETS = {
    'ak.wwise.core.profiler.getVoices': {
        'packet_sha': '40fb0be8d36926860cf5127a0b8abd5b266993eb71d7bc433df8c46837117e22',
        'packet_name': '1792791903159220000-782fe5d33901410490fa1dd332822376-ak_wwise_core_profiler_getVoices.json'},
    'ak.wwise.core.profiler.getBusses': {
        'packet_sha': '5df8e04334f736b31b6991d78be22b4a55c4371c351a3640bb4ae84c4c03cb61',
        'packet_name': '1792791903758373000-1de386c7e0cc40fa9b7786c4b43757d5-ak_wwise_core_profiler_getBusses.json'}}
R105_SEED_SOURCE_FILES = {'r105-2022-category.json': 'original-category.json',
    'r105-2022-originals.json.gz': 'original-closure.json.gz'}


def native_profile(branch):
    """Eligibility is owned by exact route identities, never optional markers."""
    version, host, build, kind, uri = branch['route'].split('|')
    if (version in R119_PROFILES and host == 'wwise-console' and kind == 'function'
            and uri == 'ak.wwise.core.profiler.getVoices' and build == R119_PROFILES[version]['build']):
        pinned = R119_PROFILES[version]
        return dict(pinned, candidate=R119_CANDIDATE, nodeid=R119_NODEID,
            files=(pinned['category_file'], pinned['archive_file'], 'r119-source-map.json'),
            map_file='r119-source-map.json', map_sha=R119_MAP_SHA, category=R118_CATEGORY,
            changes=R119_CHANGES, symbols=R119_SYMBOLS,
            reason='Reviewed attested-host finish metadata only; successful read request/result unchanged. Exact original R119 Console version/build complete twenty-field Voices at its fixed T; exact five-file log-only observation policy and UTF-8 context comparator delta preserves original successful ASCII equality and Profiler behavior; 408 packaged paths unchanged; no native non-ASCII or other reader/data/effect/Topic credit')
    if (version == '2022.1' and host == 'wwise-authoring' and build == '2022.1.19.8584'
            and kind == 'function' and uri in R105_SEED_PACKETS):
        return dict(R105_SEED_PACKETS[uri], name='r105-2022-seed', uri=uri,
            candidate=runtime.RTPC_ORIGINAL_CANDIDATE, nodeid=R105_SEED_NODEID,
            category_sha=R105_SEED_CATEGORY_SHA, archive_sha=R105_SEED_ARCHIVE_SHA,
            capture_sha=runtime.RTPC_ORIGINALS['2022.1'][1], category='r105-seed-' + uri.rsplit('.',1)[1],
            category_file='r105-2022-category.json', archive_file='r105-2022-originals.json.gz',
            files=tuple(R105_SEED_SOURCE_FILES), source_files=R105_SEED_SOURCE_FILES,
            changes=runtime.RTPC_REVIEWED_SOURCE_CHANGES, symbols=runtime.RTPC_REVIEWED_SOURCE_SYMBOLS,
            reason='Exact finalized-PASS R1052022 Authoring node, original complete paired seed diagnostics at T23637; same reviewed R105 eight-file source delta/current complete original-array replay; independent result selectors only; no new category PASS or standalone contribution/lifecycle/effect claim')
    if version != '2025.1' or build != '2025.1.7.9143' or kind != 'function':
        raise ValueError('No qualified fixed-reader native profile for this exact route')
    if host == 'wwise-authoring' and uri in URIS:
        return dict(name='r103', candidate=ORIGINAL_CANDIDATE, nodeid=NODEID,
            category_sha=CATEGORY_SHA, archive_sha=ARCHIVE_SHA, capture_sha=CAPTURE_SHA,
            category_file='r103-category.json', archive_file='r103-originals.json.gz',
            files=('r103-category.json','r103-originals.json.gz'), changes=REVIEWED_CHANGES, symbols=REVIEWED_SYMBOLS,
            reason='Reviewed attested-host finish metadata only; successful read request/result unchanged. Exact reviewed R103 nine-file read scope; exact log-only observation policy/Topic/transaction/metadata guards leave Profiler reads unchanged; UTF-8 context comparator preserves original successful ASCII equality; registered-version Console transport predicate/catalog delta leaves fixed reads unchanged; full original request/array/current projection; no lifecycle or mutation effect credit')
    if host == 'wwise-console' and uri == 'ak.wwise.core.profiler.getVoices':
        return dict(name='r118', candidate=R118_CANDIDATE, nodeid=R118_NODEID,
            category_sha=R118_CATEGORY_SHA, archive_sha=R118_ARCHIVE_SHA, capture_sha=R118_CAPTURE_SHA,
            category_file='r118-category.json', archive_file='r118-originals.json.gz',
            files=('r118-category.json','r118-originals.json.gz','r118-source-map.json'), changes=R118_CHANGES, symbols=R118_SYMBOLS,
            version='2025.1', build='2025.1.7.9143', time=6016, category=R118_CATEGORY, map_file='r118-source-map.json', map_sha=R118_MAP_SHA,
            reason='Reviewed attested-host finish metadata only; successful read request/result unchanged. Exact reviewed R118 five-file UTF-8 context comparator/presentation, registered-version Console transport predicate/catalog and exact log-only observation policy/Topic/transaction/metadata source transition; Profiler reads unchanged; original successful ASCII context equality preserved without native non-ASCII credit; fixed reads and Console2025 transport unchanged; original Console2025 complete identity Voices at T6016; current issued observation/handle; no other native data/effect/Topic credit')
    raise ValueError('No qualified fixed-reader native profile for this exact route')


def console_original_observation(originals, category, *, profile):
    """Original finalized PASS/report/dispatch/retained record, plus Git bridge metadata."""
    base = Path(originals)
    archive = {'artifact':profile['archive_file'],'sha256':runtime.sha((base/profile['archive_file']).read_bytes())}
    descriptor = {'artifact':profile['category_file'],'sha256':runtime.sha((base/profile['category_file']).read_bytes()),'nodeid':profile['nodeid']}
    source_raw = (base/profile['map_file']).read_bytes()
    if (category != profile['category'] or archive['sha256'] != profile['archive_sha']
            or descriptor['sha256'] != profile['category_sha'] or runtime.sha(source_raw) != profile['map_sha']):
        raise ValueError('Exact original Console profile closure/category/immutable Git source map required')
    source_map = json.loads(source_raw)
    if source_map['candidate'] != profile['candidate'] or len(source_map['sources']) != 413:
        raise ValueError('Original Console profile immutable Git source context differs')
    read = runtime.archive_reader(archive, base)
    context = completion.read_category_run(descriptor, base)
    run = context['record']
    if (context['candidate'] != profile['candidate'] or context['version'] != profile['version']
            or context['host'] != 'wwise-console' or context['build'] != profile['build']
            or run['invocation']['selected_test_nodeids'] != [profile['nodeid']]
            or run['invocation']['node_outcomes'] != [{'nodeid':profile['nodeid'],'outcome':'PASS'}]
            or [(row['category'],row['status']) for row in run['categories']] != [(profile['category'],'PASS'),('authoring-ui','blocked')]):
        raise ValueError('Original Console profile exact final PASS/node/category/host differs')
    capture_path = run['categories'][0]['observation_path']
    capture_raw = read(capture_path)
    if runtime.sha(capture_raw) != profile['capture_sha']: raise ValueError('Original Console profile report differs')
    capture = json.loads(capture_raw)
    if (capture['candidate'] != profile['candidate'] or capture['version'] != profile['version'] or capture['complete'] is not True
            or capture['errors'] or capture['cleanup']['complete'] is not True or capture['cleanup']['errors']
            or capture['outcomes']['voices']['outcome'] != 'PASS'
            or capture['outcomes']['voices']['evidence']['complete'] is not True
            or capture['outcomes']['voices']['evidence']['owned_voice_observed'] is not True):
        raise ValueError('Original Console profile complete owned Voices/preservation/cleanup differs')
    receipt, = [row for row in capture['calls'] if row['argv'][:2] == ['core-call','ak.wwise.core.profiler.getVoices']]
    raw_path = receipt['payload']['call']['evidence_path']; raw = json.loads(read(raw_path))
    handle = receipt['payload']['agent_result']['return'][0]['voice_instance_handle']
    observation_path = str(PurePosixPath(capture_path).parent / 'runtime-inspection-observations-v1' / ('rto1-'+handle[5:].rsplit('-',1)[0]+'.json'))
    observation = json.loads(read(observation_path)); request = observation['plan']['request']
    unsigned = {key:value for key,value in observation.items() if key != 'sha256'}
    if (raw['api'] != 'ak.wwise.core.profiler.getVoices' or raw['ok'] is not True or raw['dry_run'] is not False
            or raw['error_code'] is not None or len(raw['result']['return']) != 1
            or request['args'] != {'time':profile['time']} or request['api'] != raw['api']
            or audit.digest(unsigned) != observation['sha256']
            or audit.digest(observation['plan']['result']) != receipt['payload']['agent_result']['snapshot_sha256']
            or receipt['payload']['agent_result'] != capture['outcomes']['voices']['evidence']['agent_result']):
        raise ValueError('Original Console profile exact raw/retained Voices observation differs')
    return dict(context=context, read=read, capture=capture, capture_raw=capture_raw,
        capture_path=capture_path, raw=raw, raw_path=raw_path, request=request, receipt=receipt,
        category_descriptor=descriptor, archive=archive, historical_sources=source_map['sources'])


def schema_node(branch, root=audit.ROOT):
    return runtime._contribution_node({**branch, 'pointer': branch['pointer'].split('/@boolean/')[0]}, root)


def categories(branch, node):
    if not branch['pointer'].startswith('/resultSchema'):
        return ['program']
    if (branch['kind'] in {'constraint', 'empty_object', 'empty_string'}
            or branch['kind'] == 'optional_presence' and branch['value'] == 'absent'
            or branch['kind'] == 'collection_cardinality' and branch['value'] in {'empty', 'single'}
            or branch['kind'] == 'schema' and (node is False or isinstance(node, dict) and node.get('type') in {'object', 'array'})):
        return ['program']
    return ['program', 'native']


def predicate(branch, node, value, root=audit.ROOT):
    if branch['kind'] == 'boolean_value':
        return type(value) is bool and value is branch['value']
    if branch['kind'] == 'schema' and isinstance(node, dict) and node.get('type') == 'boolean':
        return type(value) is bool
    return runtime._contribution_predicate(branch, node, value, root=root)


def row_data(rows):
    return [{key: value for key, value in row.items() if key not in {'voice_instance_handle', 'bus_instance_handle'}} for row in rows]


def public_pointer(branch, pointer, record=None):
    if branch['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS and not branch['route'].endswith('|ak.wwise.core.profiler.getGameObjects'):
        return '/gateway/payload/agent_result/profiler_position'
    if (record is not None and branch['route'].split('|')[:2] == ['2025.1', 'wwise-console']
            and branch['route'].endswith('|ak.wwise.core.profiler.getVoices')
            and record['gateway']['payload'].get('business_request', {}).get('result_view') == 'identity'
            and branch.get('value') != 'absent'):
        import re
        match = re.fullmatch(r'/native_call/result/return/(0|[1-9][0-9]*)/pipelineID', pointer)
        if match:
            return '/gateway/payload/agent_result/return/' + match[1] + '/voice_instance_handle'
    if pointer.startswith('/native_call/result/return'):
        if branch['route'].endswith('|ak.wwise.core.profiler.getGameObjects'):
            pointer = pointer.replace('/native_call/result/return', '/gateway/payload/agent_result/game_objects', 1)
            for old, new in (('registrationTime', 'register_time'), ('unregistrationTime', 'unregister_time'),
                             ('registerTime', 'register_time'), ('unregisterTime', 'unregister_time')):
                if pointer.endswith('/' + old): pointer = pointer[:-len(old)] + new
            return pointer
        public = pointer.replace('/native_call/result', '/gateway/payload/agent_result', 1)
        return public.rsplit('/', 1)[0] if branch['kind'] == 'optional_presence' and branch['value'] == 'absent' else public
    return '/gateway/payload/agent_result'


def validate_issued_voice_handle(record, native_pointer, public_pointer):
    """Current public authority comes from this read's actual retained issuer."""
    from wwise_waapi.runtime_inspection_observations import (
        RuntimeInspectionObservationStore, observation_pipeline_handle, pipeline_key, validate_pipeline_handle)
    from wwise_waapi.runtime_inspection_business import normalize_runtime_inspection_result
    gateway, native = record['gateway'], record['native_call']
    public = gateway['payload']['agent_result']
    retained = gateway.get('retained_observation')
    if not isinstance(retained, dict) or set(retained) != {'context','contract','expires_at','handle','plan','sha256'}:
        raise ValueError('Exact current Gateway-written issuer observation is required')
    unsigned = {key:value for key,value in retained.items() if key != 'sha256'}
    RuntimeInspectionObservationStore.validate_handle(retained['handle'])
    plan = retained['plan']
    RuntimeInspectionObservationStore.validate_plan(plan)
    business = gateway['payload']['business_request']
    expected = normalize_runtime_inspection_result(native['uri'], native['result'], business_request=business,
        max_results=max(1,len(native['result']['return'])))
    if (retained['contract'] != RuntimeInspectionObservationStore.CONTRACT
            or audit.digest(unsigned) != retained['sha256'] or audit.digest(plan['result']) != public['snapshot_sha256']
            or type(retained['expires_at']) is not int or type(public['expires_at']) is not int or retained['expires_at'] != public['expires_at']
            or plan['operation'] != native['uri'] or plan['page_size'] != 64
            or audit.digest(plan['request']) != audit.digest({'api':native['uri'],'args':native['args'],'options':native['options']})
            or audit.digest(plan['result']) != audit.digest(expected)):
        raise ValueError('Current issued observation hash/snapshot/request/full projection differs')
    trace = record['runtime_read_program']['native_reads']
    final_trace = trace[record['runtime_read_program']['public_calls'][-1]['native_start']:]
    info, = [row['result'] for row in final_trace if row['uri'] == 'ak.wwise.core.getInfo']
    project, = [row['result'] for row in final_trace if row['uri'] == 'ak.wwise.core.getProjectInfo']
    context = retained['context']
    endpoint = gateway['payload']['endpoint']
    configuration = context['configuration']
    if (set(context) != {'configuration','endpoint','live','project'}
            or audit.digest(context['endpoint']) != audit.digest(endpoint)
            or audit.digest(context['live']) != audit.digest({key:info.get(key) for key in ('version','sessionId','processId')})
            or audit.digest(context['project']) != audit.digest({key:project.get(key) for key in ('id','path','filePath')})
            or configuration['waapi_host'] != endpoint['host'] or configuration['waapi_port'] != endpoint['port']
            or configuration['wwise_version'] != gateway['payload']['detected_version']):
        raise ValueError('Current issued observation live/project/configuration context differs')
    index = int(native_pointer.split('/')[4]); value = completion.pointer_value(record,native_pointer)
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError('Current issued voice requires exact native uint32')
    handle = completion.pointer_value(record,public_pointer)
    validate_pipeline_handle(handle)
    raw = native['result']['return'][index]
    matching_indexes = [i for i,row in enumerate(native['result']['return']) if type(row.get('pipelineID')) is int and row['pipelineID'] == value]
    expected_binding = {'kind':'voice','native_id':value,'time':native['args']['time'],
        'identity':{key:raw[key] for key in ('objectGUID','gameObjectID')},'row_indexes':matching_indexes}
    if (handle != observation_pipeline_handle(retained['handle'],kind='voice',native_id=value)
            or audit.digest(plan['pipeline_bindings'].get(pipeline_key('voice',value))) != audit.digest(expected_binding)
            or 'pipelineID' in public['return'][index]):
        raise ValueError('Exact same-row current issued voice handle differs')


def _validate_capture(record, binding, branch, root):
    """The exact mapped route, never optional markers, owns capture eligibility."""
    from wwise_waapi.builders.schema import validate_resolved_semantic_result
    from wwise_waapi.runtime_inspection_business import normalize_runtime_inspection_result, materialize_runtime_inspection_business_request
    version, host, build, kind, uri = branch['route'].split('|')
    captured = record.get('runtime_read_program', {})
    gateway, native = record['gateway'], record['native_call']
    payload = gateway['payload']
    if (uri not in URIS or kind != 'function' or captured.get('contract') != 'waapi-skill.runtime-read-program/v1'
            or captured.get('phase_reports') != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
            or captured.get('source_unchanged') is not True
            or captured.get('source_context') != runtime.program_source_context(root, flow=uri)
            or record.get('relevant_sources') != captured['source_context']['packaged']
            or audit.digest(captured.get('gateway')) != audit.digest(gateway)
            or audit.digest(captured.get('native_call')) != audit.digest(native)
            or gateway['argv'] != binding['input']['gateway_argv'] or gateway['exit_code'] != 0
            or payload.get('ok') is not True or payload.get('is_command_line') != (host == 'wwise-console')
            or any(payload['schema_validation'][section]['version'] != version for section in ('request', 'result'))
            or native['uri'] != uri):
        raise ValueError('Fixed-row proof needs exact current public capture/phases/host/version')
    trace = captured['native_reads']
    if (not 1 <= len(trace) <= 128 or any(type(row['ordinal']) is not int or row['ordinal'] != index
        or set(row) != {'ordinal', 'uri', 'args', 'options', 'result'} for index, row in enumerate(trace))):
        raise ValueError('Fixed-row ordered native trace differs')
    calls = captured.get('public_calls')
    if not isinstance(calls, list) or not 1 <= len(calls) <= 2:
        raise ValueError('Fixed-row exact public call spans required')
    end = 0
    for call in calls:
        if (set(call) != {'gateway', 'native_start', 'native_end'} or type(call['native_start']) is not int
                or type(call['native_end']) is not int or call['native_start'] != end
                or not end < call['native_end'] <= len(trace) or call['gateway']['exit_code'] != 0
                or call['gateway']['payload'].get('ok') is not True):
            raise ValueError('Fixed-row ordered public/native call spans differ')
        end = call['native_end']
    if end != len(trace) or audit.digest(calls[-1]['gateway']) != audit.digest(gateway):
        raise ValueError('Fixed-row final public/native call span differs')
    final_trace = trace[calls[-1]['native_start']:]
    info, = [row['result'] for row in final_trace if row['uri'] == 'ak.wwise.core.getInfo']
    if completion.native_host_context(info, 'isCommandLine') != {'version': version, 'host': host, 'build': build}:
        raise ValueError('Fixed-row actual public host/build differs')
    final = trace[-1]
    if audit.digest({key: final[key] for key in ('uri', 'args', 'options', 'result')}) != audit.digest(native):
        raise ValueError('Fixed-row final trace/request/result differs')
    if uri.endswith('.getGameObjects'):
        from wwise_waapi.builders.stable_reads import normalize_profiler_game_objects_result, build_profiler_game_objects_request
        argv = gateway['argv']
        if argv[0] != 'profiler-game-objects' or len(calls) != 1 or [r['uri'] for r in final_trace if r['uri'] in URIS] != [uri]:
            raise ValueError('Fixed GameObjects requires its exact dedicated command')
        if '--capture-ms' in argv:
            time = argv[argv.index('--capture-ms') + 1]
        else:
            choice = argv[argv.index('--capture') + 1]
            time = {'latest': 'capture', 'user-cursor': 'user'}[choice]
        request = build_profiler_game_objects_request(version=version, time=time)
        if (audit.digest({'api': uri, 'args': native['args'], 'options': native['options']}) !=
                audit.digest({'api': request.uri, 'args': request.args, 'options': request.options})
                or audit.digest(payload['semantic_preview']) != audit.digest(request.as_dict())):
            raise ValueError('Fixed GameObjects exact controlled request/options differs')
        expected = normalize_profiler_game_objects_result(version=version, result=native['result'])
        if audit.digest(expected) != audit.digest(payload['agent_result']):
            raise ValueError('Program must preserve complete native/public fixed-row projection')
    else:
        argv = gateway['argv']
        if argv[:2] != ['core-call', uri] or '--profiler-position' not in argv:
            raise ValueError('Fixed-row exact public route/position missing')
        position = argv[argv.index('--profiler-position') + 1]
        fields = [argv[index + 1] for index, token in enumerate(argv[:-1]) if token == '--result-field']
        view = argv[argv.index('--result-view') + 1] if '--result-view' in argv else None if fields else 'summary'
        pipeline_bindings = filtered_binding(captured, branch, root)
        request, _, business = materialize_runtime_inspection_business_request(uri, version,
            profiler_position=position, result_view=view, result_fields=fields or None, max_results=64, log_channel=None,
            voice_instance_handle=next((value for value, item in pipeline_bindings.items() if item['kind'] == 'voice'), None),
            bus_instance_handle=next((value for value, item in pipeline_bindings.items() if item['kind'] == 'bus'), None),
            pipeline_bindings=pipeline_bindings)
        if view in {'summary', 'identity', 'diagnostics'}:
            identity_fields = ['busGUID', 'gameObjectID'] if uri.endswith('.getAudioObjects') else ['objectGUID', 'gameObjectID']
            request['options'] = {'return': list(dict.fromkeys([*request['options']['return'], *identity_fields]))}
        if position in {'capture-latest', 'user-cursor'}:
            cursor = cursor_source(captured, uri, position)
            request['args']['time'] = cursor['result']['return']
        if type(native['args'].get('time')) is not int or native['args']['time'] < 0:
            raise ValueError('Fixed-row time requires its exact public construction')
        if payload['business_request'] != {'operation': uri, **business, 'max_results': 64}:
            raise ValueError('Fixed-row reported public construction differs')
        if audit.digest({'api': uri, 'args': native['args'], 'options': native['options']}) != audit.digest(request):
            raise ValueError('Fixed-row exact controlled request/options differs')
        validate_resolved_semantic_result(uri, native['result'], version=version)
        expected = normalize_runtime_inspection_result(uri, native['result'], business_request=business,
            max_results=max(1, len(native['result']['return'])))
        actual = payload['agent_result']
        if (audit.digest(row_data(actual['return'])) != audit.digest(expected['return'])
                or actual.get('complete') is not True or actual['total_count'] != len(native['result']['return'])
                or actual['profiler_position'] != position):
            raise ValueError('Program must preserve complete native/public fixed-row projection')



def filtered_binding(captured, branch, root):
    """A public seed and same-T identity read own the one selected pipeline."""
    from wwise_waapi.runtime_inspection_observations import pipeline_key, validate_pipeline_handle
    uri = captured['native_call']['uri']
    argv = captured['gateway']['argv']
    flags = [flag for flag in ('--voice-instance-handle', '--bus-instance-handle') if flag in argv]
    calls, trace = captured['public_calls'], captured['native_reads']
    final_trace = trace[calls[-1]['native_start']:]
    relevant = [row for row in final_trace if row['uri'] in URIS]
    if not flags:
        if len(calls) != 1 or len(relevant) != 1 or relevant[0]['ordinal'] != len(trace) - 1:
            raise ValueError('Fixed-row unfiltered read has extra dependent calls')
        return {}
    if len(flags) != 1 or len(calls) != 2 or len(relevant) != 2:
        raise ValueError('Fixed-row filtered seed/revalidation trace differs')
    flag, = flags
    kind = 'voice' if flag == '--voice-instance-handle' else 'bus'
    handle = argv[argv.index(flag) + 1]
    validate_pipeline_handle(handle)
    seed_uri = 'ak.wwise.core.profiler.' + ('getVoices' if kind == 'voice' else 'getBusses')
    seed = calls[0]['gateway']
    seed_trace = trace[:calls[0]['native_end']]
    checked, final = relevant
    time = captured['native_call']['args']['time']
    if (seed['argv'][:2] != ['core-call', seed_uri] or checked['uri'] != seed_uri or final['uri'] != uri
            or checked['args'] != {'time': time}
            or checked['options'] != {'return': ['pipelineID', 'gameObjectID', 'objectGUID', 'objectName', 'gameObjectName']}
            or any(token in seed['argv'] for token in ('--voice-instance-handle', '--bus-instance-handle'))
            or type(seed_trace[-1]['args'].get('time')) is not int or seed_trace[-1]['args']['time'] != time):
        raise ValueError('Fixed-row same-time identity revalidation differs')
    seed_native = {key: seed_trace[-1][key] for key in ('uri', 'args', 'options', 'result')}
    seed_capture = {**captured, 'gateway': seed, 'native_call': seed_native, 'native_reads': seed_trace,
        'public_calls': [calls[0]]}
    seed_branch = {**branch, 'route': branch['route'].rsplit('|', 1)[0] + '|' + seed_uri}
    _validate_capture({'gateway': seed, 'native_call': seed_native, 'runtime_read_program': seed_capture,
        'relevant_sources': captured['source_context']['packaged']}, {'input': {'gateway_argv': seed['argv']}}, seed_branch, root)
    for api in ('ak.wwise.core.getInfo', 'ak.wwise.core.object.get'):
        first = [{k:r[k] for k in ('uri','args','options','result')} for r in seed_trace if r['uri'] == api]
        second = [{k:r[k] for k in ('uri','args','options','result')} for r in final_trace if r['uri'] == api]
        if audit.digest(first) != audit.digest(second):
            raise ValueError('Fixed-row seed project/host context differs')
    public, = [row for row in seed['payload']['agent_result']['return'] if row.get(kind + '_instance_handle') == handle]
    native_id = captured['native_call']['args'][kind + 'PipelineID']
    original, = [row for row in seed_native['result']['return'] if row.get('pipelineID') == native_id]
    revalidated, = [row for row in checked['result']['return'] if row.get('pipelineID') == native_id]
    identity = {key: original[key] for key in ('objectGUID', 'gameObjectID')}
    if (type(native_id) is not int or not 0 <= native_id <= 0xffffffff
            or handle.rsplit('-', 1)[1] != pipeline_key(kind, native_id)
            or audit.digest(identity) != audit.digest({key: revalidated.get(key) for key in identity})
            or any(audit.digest(public.get(key)) != audit.digest(value) for key, value in identity.items())):
        raise ValueError('Fixed-row issued handle identity differs from exact revalidation')
    return {handle: {'handle': handle, 'kind': kind, 'native_id': native_id}}

def cursor_source(captured, uri, choice):
    """One source-owned moving cursor snapshot before every dependent read."""
    trace = captured['native_reads'][captured['public_calls'][-1]['native_start']:]
    cursors = [row for row in trace if row['uri'] == 'ak.wwise.core.profiler.getCursorTime']
    source_time = cursors[0]['result'].get('return') if len(cursors) == 1 and type(cursors[0]['result']) is dict else None
    enum = {'capture-latest': 'capture', 'user-cursor': 'user'}[choice]
    dependents = [row for row in trace if row['uri'] in URIS]
    if (len(cursors) != 1 or type(source_time) is not int or source_time < 0
            or cursors[0]['args'] != {'cursor': enum} or cursors[0]['options'] != {}
            or cursors[0]['result'] != {'return': source_time} or not 1 <= len(dependents) <= 2
            or dependents[-1]['uri'] != uri or any(row['ordinal'] <= cursors[0]['ordinal']
                or type(row['args'].get('time')) is not int or row['args']['time'] != source_time for row in dependents)):
        raise ValueError('Fixed-row exact ordered typed cursor snapshot differs')
    return cursors[0]


def validate_program(record, binding, branch, root, reference_edges=None):
    _validate_capture(record, binding, branch, root)
    pointer = binding.get('program_observation_pointer') if binding.get('runtime_observation_attachment') else binding['observation_pointer']
    if binding['gateway_observation_pointer'] != public_pointer(branch, pointer, record):
        raise ValueError('Fixed-row corresponding exact public occurrence differs')
    if binding['gateway_observation_pointer'].endswith('/voice_instance_handle'):
        validate_issued_voice_handle(record, pointer, binding['gateway_observation_pointer'])
    node = schema_node(branch, root)
    if branch['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS and not branch['route'].endswith('.getGameObjects'):
        edges = reference_edges or {}
        first = branch['route'] + '|/argsSchema/properties/time/$ref'
        second = branch['route'] + '|/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime/oneOf/1/$ref'
        chain = [first] if 'definitions/cursorTime/' in branch['pointer'] else [first, second]
        completion.exact_observation_pointer(branch, {**binding, 'observation_pointer': '/native_call/args/time'},
            '/native_call', 'args', edges)
        if (binding.get('reference_chain') != chain
                or edges[first]['reference']['target'] != branch['route'] + '|/argsSchema/@definition/waapi_definitions.json/definitions/cursorTime'
                or edges[second]['reference']['target'] != branch['route'] + '|/argsSchema/@definition/waapi_definitions.json/definitions/profilerCursor'
                or branch['shape_sha256'] != audit.digest(node)):
            raise ValueError('Fixed-row exact cursor branch/ref/shape differs')
        argv = record['gateway']['argv']
        source = cursor_source(record['runtime_read_program'], record['native_call']['uri'], argv[argv.index('--profiler-position') + 1])
        expected = f"/runtime_read_program/native_reads/{source['ordinal']}/args/cursor"
        if pointer != expected or not predicate(branch, node, source['args']['cursor'], root):
            raise ValueError('Fixed-row exact cursor branch/occurrence differs')
        return {'branch_id': branch['id'], 'observation_pointer': expected}
    if branch['kind'] == 'optional_presence' and branch['value'] == 'absent':
        parent = completion.pointer_value(record, pointer.rsplit('/', 1)[0])
        if type(parent) is not dict or pointer.rsplit('/', 1)[1] in parent:
            raise ValueError('Fixed-row omission requires existing exact parent and missing field')
        value = runtime._CONTRIBUTION_ABSENT
    else:
        value = completion.pointer_value(record, pointer)
    if not predicate(branch, node, value, root):
        raise ValueError('Fixed-row exact pinned branch predicate failed')


def r105_seed_original_observation(originals, category, *, profile):
    """Read successful seed packets inside the untouched finalized PASS node.

    The original capture has RTPC/contribution outcome categories only. These
    exact seed URI selectors never fabricate a Voices/Busses category verdict.
    """
    base = Path(originals)
    if category != profile['category'] or profile['uri'] not in R105_SEED_PACKETS:
        raise ValueError('Exact R105 seed URI/profile selector required')
    archive = {'artifact':profile['archive_file'], 'sha256':runtime.sha((base/profile['archive_file']).read_bytes())}
    descriptor = {'artifact':profile['category_file'], 'sha256':runtime.sha((base/profile['category_file']).read_bytes()), 'nodeid':profile['nodeid']}
    if archive['sha256'] != R105_SEED_ARCHIVE_SHA or descriptor['sha256'] != R105_SEED_CATEGORY_SHA:
        raise ValueError('Exact R105 seed original archive/category required')
    read = runtime.archive_reader(archive,base)
    context = completion.read_category_run(descriptor,base)
    completion.validate_authoring_batch_finalization(context['record'],base,read_bytes=read)
    if (context['candidate'] != runtime.RTPC_ORIGINAL_CANDIDATE or context['host'] != 'wwise-authoring'
            or context['version'] != '2022.1' or context['build'] != '2022.1.19.8584'
            or {r['category'] for r in context['record']['categories']} != {'profiler-rtpcs-observation','profiler-contributions-bus-observation'}):
        raise ValueError('Exact R105 seed finalized context/real category roster differs')
    seal = json.loads(read(context['record']['categories'][0]['batch_finalization']['artifact']))
    node = json.loads(read(seal['observations'][R105_SEED_NODEID]['path']))
    sources = node['source_context']['sources']
    if (node['candidate'] != runtime.RTPC_ORIGINAL_CANDIDATE
            or node['source_context']['candidate'] != runtime.RTPC_ORIGINAL_CANDIDATE
            or len(sources) != 616 or audit.digest(sources) != '41d79c2ea620cb9b75859365e2f66346e1c57ec52485978898fbce421b215dca'):
        raise ValueError('Exact R105 seed complete original source context differs')
    archived = {PurePosixPath(g['path']).joinpath(f['path']).as_posix():f for g in node['artifacts'].values() for f in g['files']}
    capture_path, = [name for name in archived if name.endswith('/profiler-capture.json')]
    capture_raw = read(capture_path)
    if runtime.sha(capture_raw) != profile['capture_sha']:
        raise ValueError('Exact R105 seed original capture differs')
    capture = json.loads(capture_raw)
    if (capture['outcomes']['profiler-contributions-bus-observation']['outcome'] != 'PASS'
            or capture['capture_position']['position_ms'] != 23637 or capture['errors']):
        raise ValueError('Original R105 contribution context/time did not pass')
    uri = profile['uri']
    argv = ['core-call',uri,'--profiler-position','23637','--result-view','diagnostics','--max-results','64']
    receipt, = [r for r in node['receipts'] if r['argv'] == argv]
    raw_path, = [name for name in archived if name.endswith('/'+profile['packet_name'])]
    raw_bytes = read(raw_path);raw=json.loads(raw_bytes)
    public = receipt['payload']
    if (runtime.sha(raw_bytes) != profile['packet_sha'] or raw['api'] != uri or raw['version'] != '2022.1'
            or raw['ok'] is not True or raw['dry_run'] is not False or raw['error_code'] is not None
            or receipt['exit_code'] != 0 or public['ok'] is not True or public['is_command_line'] is not False
            or any(public['schema_validation'][section]['version'] != '2022.1' for section in ('request','result'))
            or not public['call']['evidence_path'].endswith('/'+profile['packet_name'])
            or public['agent_result']['complete'] is not True or public['agent_result']['truncated'] is not False
            or len(raw['result']['return']) != 1
            or audit.digest(raw['result']['return']) != audit.digest(row_data(public['agent_result']['return']))):
        raise ValueError('Exact successful complete R105 seed native/public packet differs')
    # The expired original handle is only an archive identity, never current
    # authority. Current public replay issues and validates its own handles.
    kind = 'voice' if uri.endswith('getVoices') else 'bus'
    old_handle = public['agent_result']['return'][0][kind+'_instance_handle']
    handle = 'rto1-'+old_handle[5:].rsplit('-',1)[0]
    plan_path, = [name for name in archived if name.endswith('/runtime-inspection-observations-v1/'+handle+'.json')]
    plan = json.loads(read(plan_path));request=plan['plan']['request']
    if (plan['handle'] != handle or audit.digest(row_data(plan['plan']['result']['return'])) != audit.digest(raw['result']['return'])):
        raise ValueError('Exact original R105 seed issuer/full array differs')
    if (request['api'] != uri or request['args'] != {'time':23637}
            or str(public['agent_result']['profiler_position']) != '23637'):
        raise ValueError('Exact R105 seed stored original request/time differs')
    contribution, = [r for r in node['receipts'] if r['argv'][0] == 'profiler-voice-contributions' and '--bus-instance-handle' in r['argv']]
    args = contribution['payload']['semantic_preview']['args']
    selected = [args['voicePipelineID']] if uri.endswith('getVoices') else args['bussesPipelineID']
    if args['time'] != 23637 or [r['pipelineID'] for r in raw['result']['return']] != selected:
        raise ValueError('Original R105 seed identity/contribution time relation differs')
    return dict(context=context,read=read,node=node,capture=capture,capture_raw=capture_raw,capture_path=capture_path,
        raw=raw,raw_path=raw_path,request=request,receipt=receipt,category_descriptor=descriptor,archive=archive,
        historical_sources={p:h for p,h in sources.items() if p.startswith('skills/waapi-skill/')})


def original_observation(originals, category, *, profile=None):
    """Use strict original PASS; all archive paths are inert logical identities."""
    if profile is not None and profile['name'] == 'r105-2022-seed':
        return r105_seed_original_observation(originals,category,profile=profile)
    if profile is not None and (profile['name'] == 'r118' or profile['name'].startswith('r119-')):
        return console_original_observation(originals, category, profile=profile)
    originals = Path(originals)
    archive = {'artifact': 'r103-originals.json.gz', 'sha256': runtime.sha((originals / 'r103-originals.json.gz').read_bytes())}
    category_descriptor = {'artifact': 'r103-category.json', 'sha256': runtime.sha((originals / 'r103-category.json').read_bytes()), 'nodeid': NODEID}
    if archive['sha256'] != ARCHIVE_SHA or category_descriptor['sha256'] != CATEGORY_SHA or category not in CATEGORIES:
        raise ValueError('Exact original R103 archive/category scope required')
    read = runtime.archive_reader(archive, originals)
    context = completion.read_category_run(category_descriptor, originals)
    completion.validate_authoring_batch_finalization(context['record'], originals, read_bytes=read)
    run = context['record']
    if (context['candidate'] != ORIGINAL_CANDIDATE or context['host'] != 'wwise-authoring'
            or context['version'] != '2025.1' or context['build'] != '2025.1.7.9143'
            or {row['category'] for row in run['categories']} != CATEGORIES):
        raise ValueError('Original R103 exact seven-category roster/context differs')
    seal = json.loads(read(run['categories'][0]['batch_finalization']['artifact']))
    node = json.loads(read(seal['observations'][NODEID]['path']))
    archived = {PurePosixPath(group['path']).joinpath(item['path']).as_posix(): item for group in node['artifacts'].values() for item in group['files']}
    capture_path, = [name for name in archived if name.endswith('/profiler-capture.json')]
    capture_raw = read(capture_path)
    if runtime.sha(capture_raw) != CAPTURE_SHA: raise ValueError('Original fixed-row capture differs')
    capture = json.loads(capture_raw)
    if capture['outcomes'][category]['outcome'] != 'PASS': raise ValueError('Original fixed-row category did not pass')
    uri = ('ak.wwise.core.profiler.getGameObjects' if category == 'profiler-game-objects-observation' else
        'ak.wwise.core.profiler.getAudioObjects' if 'audio-objects' in category else
        'ak.wwise.core.profiler.getBusses' if 'bus' in category else 'ak.wwise.core.profiler.getVoices')
    filtered = 'filter' in category
    receipt, = [r for r in node['receipts'] if (r['argv'][0] == 'profiler-game-objects' if uri.endswith('.getGameObjects') else r['argv'][:2] == ['core-call', uri])
        and any(flag in r['argv'] for flag in ('--voice-instance-handle', '--bus-instance-handle')) == filtered]
    raw_path, = [name for name in archived if name.endswith('/' + receipt['payload']['call']['evidence_path'].rsplit('/', 1)[1])]
    raw = json.loads(read(raw_path))
    plans = [(name, json.loads(read(name))) for name in archived if '/runtime-inspection-observations-v1/rto1-' in name]
    if uri.endswith('.getGameObjects'):
        request = receipt['payload']['semantic_preview']
        request = {'api': uri, 'args': request['args'], 'options': request['options']}
    else:
        _, plan = next((name, plan) for name, plan in plans if plan['plan']['request']['api'] == uri
            and ('voicePipelineID' in plan['plan']['request']['args']) == ('--voice-instance-handle' in receipt['argv'])
            and ('busPipelineID' in plan['plan']['request']['args']) == ('--bus-instance-handle' in receipt['argv']))
        request = plan['plan']['request']
    if raw['api'] != uri or raw['ok'] is not True or raw['dry_run'] is not False or raw['error_code'] is not None:
        raise ValueError('Original successful fixed-row raw read required')
    return dict(context=context, read=read, node=node, capture=capture, capture_raw=capture_raw,
        capture_path=capture_path, raw=raw, raw_path=raw_path, request=request, receipt=receipt,
        category_descriptor=category_descriptor, archive=archive,
        historical_sources={k:v for k,v in node['source_context']['sources'].items() if k.startswith('skills/waapi-skill/')})


def mappings(inventory, captured, route, selected=None):
    branches = [b for b in inventory['native_coverage']['obligations'] if b['route'] == route['id']]
    edges = {b['id']: b for b in branches if b['kind'] == 'reference'}
    found = []
    for branch in branches:
        if selected is not None and branch['id'] not in selected: continue
        node = schema_node(branch)
        if branch['pointer'] in runtime.CONTRIBUTION_CURSOR_POINTERS and not route['uri'].endswith('.getGameObjects'):
            argv = captured['gateway']['argv']; position = argv[argv.index('--profiler-position') + 1]
            if position in {'capture-latest', 'user-cursor'}:
                source = cursor_source(captured, route['uri'], position)
                if predicate(branch, node, source['args']['cursor']):
                    found.append({'branch': branch, 'program_pointer': f"/runtime_read_program/native_reads/{source['ordinal']}/args/cursor",
                        'reference_chain': runtime._contribution_chains(branch, edges)[0], 'categories': ['program']})
            continue
        for chain in runtime._contribution_chains(branch, edges):
            hit = next(((pointer, value) for pointer, value in runtime._contribution_occurrences(captured,
                runtime._contribution_pattern(branch, chain, edges)) if predicate(branch, node, value)), None)
            if hit:
                found.append({'branch': branch, 'program_pointer': hit[0], 'reference_chain': chain, 'categories': categories(branch, node)})
                break
    if selected is not None and {r['branch']['id'] for r in found} != selected:
        raise ValueError('Every selected fixed-row branch needs an exact independently observed predicate')
    return found


REVIEWED_CHANGES = {runtime.UNICODE_CONTEXT_SOURCE: runtime.UNICODE_CONTEXT_SOURCE_CHANGE, 'skills/waapi-skill/scripts/gateway.py': {'before': '9ea8d1c0c79c9323c8ee0e48b8cb9444c54c8d73f9f7330ed827563f31f42f03', 'after': 'c8dfcff8ae13c9e5b192f4ca7f1e1cd7b52a9f20e5327b33bec15e8a1ecb0bc4'}, 'skills/waapi-skill/wwise_waapi/builders/schema.py': {'before': '4a1ac5146edc65eb8e58defd689051f79a198bafb2d5d2134d912bd9a862fd6d', 'after': 'cd11309c557b68ea7bcb7d82c2bcbc1a448d08f8e283fab50a0424555fc4f8f2'}, 'skills/waapi-skill/wwise_waapi/builders/stable_reads.py': {'before': '74e37957692c6748f6c7f8f6c4dd795dc31c10b78ba0d30500a90d59b818412d', 'after': 'ea1c39a5480afc5720f99a0acb85015c7c7d028d8ee53eb1937ff079fce9d7d8'}, 'skills/waapi-skill/wwise_waapi/operation_registry.py': {'before': '691d93149f80e619539c40db64d1b9d34b86771b0660740eb948356c92a034e1', 'after': '3b298a11c9326d47b968783e536d09d290a8fff4a5a7080b5f5f99d5e7c2734d'}, 'skills/waapi-skill/wwise_waapi/runtime_inspection_business.py': {'before': '62e4ed3eca63a62637e7b8e1ab4c5c55c18ceffb49d91d4e318cecec44ce116c', 'after': '06442176e0aa4f5862feb0c66ef9878221494145755d700c02029353641e9f4d'}, 'skills/waapi-skill/wwise_waapi/runtime_inspection_business_contracts.py': {'before': 'd3ebc12976ef6d8976cf8d136ded7dbcd08cc0728ed365b4a0d70e9420fe2c12', 'after': 'f93e41345477d0e3346230c12ebc056511b4c348ee253cb3df33c91d8bd4658d'}, 'skills/waapi-skill/wwise_waapi/transport_action.py': {'before': '3f9828a964b75ce04cc683b8cf0479d4d82b4eddd05c7d26bb4cde6e0b096ec4', 'after': 'f1dfed2fc9e2697d37e022262d440a7d3ace7005d4f5e57b939d7550d7efa2a5'},
    'skills/waapi-skill/wwise_waapi/runtime_log_effects.py': {
        'before': '62c28fc9bb92ccd8e8efb3ccbfe5b187d6df1d3086c2def79e1d11dbc81ddfe8', 'after': '1f03a038ba77a0ab62fba014329eeeb6962de86902f14fcb60cbfb4de19dea00'}}
REVIEWED_SYMBOLS = {
    'wwise_waapi/business_declarations.py': ['BusinessHandleRegistry._require_context: exact UTF-8 byte comparison; no normalization'],
    'scripts/gateway.py': ['_execute_gateway_unconstrained: retain only already-attested getInfo bool in missing finish host context; preserve exact agent_result last; no additional call or successful read request/result change', 'dispatch_runtime_inspection_business_read', 'dispatch_command:profiler-game-objects', 'fixed_command_route_payload', 'stable-read constant imports', 'build_parser', 'preflight_core_business_input', 'runtime_authoring_host_required_payload', 'dispatch_offline_command',
        'dispatch_business_runtime_control_plan', 'transport-host helper import; fixed readers unaffected', 'runtime_log_observation_support import; live_log_topic_boundary; dispatch_command/dispatch_topic_stream: exact log Topic guard', 'dispatch_offline_command/dispatch_runtime_inspection_business_read: exact log disclosure only', '_dispatch_transaction_command_with_execution_lease: exact log observation-plan drift/event selection only'],
    'wwise_waapi/builders/schema.py': ['validate_resolved_semantic_result', '_validate_resolved_sections', '_runtime_result_reference_schema'],
    'wwise_waapi/builders/stable_reads.py': ['normalize_profiler_game_objects_result'],
    'wwise_waapi/runtime_inspection_business.py': ['RTPC-only guard/disclosure', 'Sequence/field-contract imports', 'materialize_runtime_inspection_business_request', 'normalize_runtime_inspection_result'],
    'wwise_waapi/runtime_inspection_business_contracts.py': ['transport-only earlier delta', 'field ceiling', 'profiler_result_field_choices', 'three row declarations', 'runtime_inspection_business_contract_data', 'runtime_transport_requires_authoring',
        'runtime_inspection_business_catalog_rows: exact registered-version Console transport admission and metadata-only finalization', 'runtime_log_observation_support/CONSOLE_LOG_ADD_OBSERVER; runtime_inspection_business_catalog_rows/runtime_inspection_business_contract_data: exact log metadata only'],
    'wwise_waapi/transport_action.py': ['expected_state; unrelated to fixed reads'],
    'wwise_waapi/operation_registry.py': ['verify_prepared_operation transport message; unrelated to fixed reads', 'prepare_operation/verify_prepared_operation: exact log observation plan, verifier selection and message only'],
    'wwise_waapi/runtime_log_effects.py': ['compare_channel: exact Console log observation guard only'],
}


def validate_source_review(descriptor, historical, branch, root, base):
    review = completion.read_sealed_artifact(descriptor, base)
    version, host, build, _, uri = branch['route'].split('|')
    profile = native_profile(branch)
    current = runtime.program_source_context(root, flow=uri)['packaged']
    changes = {key: {'before': historical.get(key), 'after': current.get(key)}
        for key in historical.keys() | current.keys() if historical.get(key) != current.get(key)}
    if (not branch['pointer'].startswith('/resultSchema') or categories(branch, schema_node(branch, root)) != ['program', 'native']
            or set(review) != {'contract', 'historical_candidate', 'historical_sources', 'current_sources', 'changed_files', 'changed_symbols', 'category', 'archive', 'program_replay'}
            or review['contract'] != 'waapi-skill.fixed-row-source-review/v1'
            or review['historical_candidate'] != profile['candidate'] or len(historical) != 413
            or review['historical_sources'] != historical or review['current_sources'] != current
            or review['changed_files'] != profile['changes'] or changes != profile['changes']
            or review['changed_symbols'] != profile['symbols']):
        raise ValueError('Fixed-row exact reviewed native-profile source/branch closure differs')
    runtime._portable_descriptor(review['program_replay'], base)
    replay = completion.read_sealed_artifact(review['program_replay'], base)
    original = original_observation(base, review['category'], profile=profile)
    if (review['archive'] != original['archive'] or historical != original['historical_sources']
            or audit.digest(replay['native_call']) != audit.digest({'uri': uri, 'args': original['request']['args'],
                'options': original['request']['options'], 'result': original['raw']['result']})):
        raise ValueError('Fixed-row complete original native request/array replay differs')
    provisional = {'gateway': replay['gateway'], 'native_call': replay['native_call'], 'runtime_read_program': replay,
                   'relevant_sources': replay['source_context']['packaged']}
    _validate_capture(provisional, {'input': {'gateway_argv': replay['gateway']['argv']}}, branch, root)


def validate_evidence(record, binding, branch, category, base, root, edges):
    profile = native_profile(branch)
    proof = runtime._proof(binding, base); mapping = proof['mapping']; chain = mapping['reference_chain']
    if (category not in {'program', 'native'} or proof['branch_id'] != branch['id'] or proof['native_shape_sha256'] != branch['shape_sha256']
            or mapping['branch_id'] != branch['id'] or mapping['native_shape_sha256'] != branch['shape_sha256']
            or binding['observation_pointer'] != mapping['native_pointer'] or binding['program_observation_pointer'] != mapping['program_pointer']
            or binding['reference_chain'] != chain or not branch['pointer'].startswith('/resultSchema')):
        raise ValueError('Fixed-row exact original branch/reference mapping differs')
    completion.exact_observation_pointer(branch, {'observation_pointer': mapping['program_pointer'], 'reference_chain': chain}, '/native_call', 'result', edges)
    completion.exact_observation_pointer(branch, {'observation_pointer': mapping['native_pointer'], 'reference_chain': chain}, '/observations/raw', 'result', edges)
    captured = completion.read_sealed_artifact(proof['program_capture'], base)
    if category == 'program':
        if audit.digest(record.get('runtime_read_program')) != audit.digest(captured):
            raise ValueError('Fixed-row attached public capture differs')
        validate_program({**record, 'runtime_read_program': captured}, binding, branch, root, edges)
        return
    original = original_observation(base, mapping['category'], profile=profile)
    historical = original['historical_sources']
    if (proof['native_run']['sha256'] != profile['category_sha'] or proof['native_run']['nodeid'] != profile['nodeid']
            or proof['archive'] != original['archive'] or proof['relevant_sources'] != historical
            or proof['capture']['sha256'] != profile['capture_sha'] or proof['capture_original_path'] != original['capture_path']
            or mapping['raw_original_path'] != original['raw_path']
            or original['read'](mapping['raw_original_path']) != (base / mapping['raw_observation']['artifact']).read_bytes()
            or original['capture_raw'] != (base / proof['capture']['artifact']).read_bytes()
            or record['native_runs'] != [proof['native_run']]
            or record['observation_artifacts'] != {'capture': proof['capture'], 'raw': mapping['raw_observation']}
            or audit.digest(captured['native_call']) != audit.digest({'uri': original['raw']['api'], 'args': original['request']['args'],
                'options': original['request']['options'], 'result': original['raw']['result']})):
        raise ValueError('Fixed-row original strict-PASS observation/request/replay differs')
    validate_source_review(proof['source_review'], historical, branch, root, base)
    if record['branch_assertions'][branch['id']]['checks'] != mapping['native_checks']:
        raise ValueError('Fixed-row exact native branch assertion differs')


def write_fixed_bundle(output, program_path, originals, *, inventory, selected=None, name_prefix='', mappings=None):
    """Publish independent assertions through the existing runtime attachment."""
    captured = json.loads(Path(program_path).read_bytes()); uri = captured['native_call']['uri']
    payload = captured['gateway']['payload']; version = payload['schema_validation']['result']['version']
    host = 'wwise-console' if payload['is_command_line'] else 'wwise-authoring'
    route = next(r for r in inventory['native_coverage']['routes'] if r['uri'] == uri and r['version'] == version and r['host'] == host)
    public = next(r for r in inventory['routes'] if r['id'] == route['public_route'])
    mapped = globals()['mappings'](inventory, captured, route, selected) if mappings is None else mappings
    if selected is not None and {m['branch']['id'] for m in mapped} != selected:
        raise ValueError('Every selected fixed-row branch needs its explicit mapped occurrence')
    profile = native_profile({'route':route['id']}) if originals is not None else None
    if name_prefix and (not name_prefix.endswith('-') or '/' in name_prefix or '..' in name_prefix):
        raise ValueError('Fixed flow prefix must be a simple filename prefix')
    output = Path(output);output.mkdir(parents=True, exist_ok=bool(name_prefix))
    def filename(name):
        if name == 'original-capture.json': return profile['name']+'-capture.json'
        return name if name.startswith(('r103-','r118-','r119-')) else name_prefix + name
    def write(name, value): return runtime.write_json(output / filename(name), value)
    shutil.copyfile(program_path, output / filename('program-capture.json'))
    def descriptor(name):return {'artifact': filename(name), 'sha256': runtime.sha((output / filename(name)).read_bytes())}
    sources = captured['source_context']['packaged']; candidate = inventory['native_coverage']['candidate_sha256']
    program = {'candidate_sha256': candidate, 'scope_kind': 'product', 'relevant_sources': sources,
        'gateway': captured['gateway'], 'native_call': captured['native_call'], 'runtime_read_program': captured,
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': captured['nodeid'], 'outcome': 'PASS'}]}, 'branch_assertions': {}}
    document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {}}
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    native = original = source_review = None
    if originals is not None:
        if any(m['categories'] != ['program', 'native'] for m in mapped):
            raise ValueError('Original native attachment only accepts independently observed data branches')
        category = ('profiler-voices-observation' if uri.endswith('.getVoices') else 'profiler-busses-observation' if uri.endswith('.getBusses')
            else 'profiler-audio-objects-observation' if uri.endswith('.getAudioObjects') else 'profiler-game-objects-observation')
        if '--voice-instance-handle' in captured['gateway']['argv']: category = 'profiler-voice-instance-filter'
        elif '--bus-instance-handle' in captured['gateway']['argv']:
            category = 'profiler-audio-objects-bus-filter' if uri.endswith('.getAudioObjects') else 'profiler-bus-instance-filter'
        if profile['name'] in {'r118','r105-2022-seed'} or profile['name'].startswith('r119-'): category = profile['category']
        for name in profile['files']:
            source = (Path(originals) / profile.get('source_files',{}).get(name,name)).read_bytes()
            if (output / name).exists():
                if (output / name).read_bytes() != source: raise ValueError('Fixed stage original closure changed')
            else: (output / name).write_bytes(source)
        original = original_observation(output, category, profile=profile)
        (output / filename('original-capture.json')).write_bytes(original['capture_raw'])
        (output / filename('original-raw.json')).write_bytes(original['read'](original['raw_path']))
        historical = original['historical_sources']
        native_run = {**descriptor(profile['category_file']), 'nodeid': profile['nodeid'],
            'observation_sha256': [descriptor('original-capture.json')['sha256'], descriptor('original-raw.json')['sha256']]}
        source_review = write('source-review.json', {'contract': 'waapi-skill.fixed-row-source-review/v1',
            'historical_candidate': profile['candidate'], 'historical_sources': historical, 'current_sources': sources,
            'changed_files': profile['changes'], 'changed_symbols': profile['symbols'], 'category': category,
            'archive': descriptor(profile['archive_file']), 'program_replay': descriptor('program-capture.json')})
        native = {'candidate_sha256': candidate, 'scope_kind': 'product', 'evidence_kind': 'native_execution',
            'relevant_sources': historical, 'invocation': original['context']['record']['invocation'], 'native_runs': [native_run],
            'observation_artifacts': {'capture': descriptor('original-capture.json'), 'raw': descriptor('original-raw.json')}, 'branch_assertions': {}}
    for mapping in mapped:
        branch, pointer = mapping['branch'], mapping['program_pointer']; identity=branch['id']; public_path=public_pointer(branch,pointer,program)
        check = ({'pointer': pointer, 'absent': True} if branch['kind'] == 'optional_presence' and branch['value'] == 'absent' else
            {'pointer': pointer, 'cardinality': branch['value']} if branch['kind'] == 'collection_cardinality' else
            {'pointer': pointer, 'equals': completion.pointer_value(program, pointer)})
        assertion={'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route']}
        program['branch_assertions'][identity]={**assertion,'checks':[check,{'pointer':public_path,'equals':completion.pointer_value(captured,public_path)}]}
        binding={'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
            'input':{'gateway_argv':captured['gateway']['argv'],'selector':pointer},'dispatch_pointer':'/native_call','observation_pointer':pointer,
            'gateway_observation_pointer':public_path,'reference_chain':mapping['reference_chain'],'relevant_sources':sorted(sources),'evidence':{},
            **{key:{'source':source,'selector':branch['pointer']} for key,source in (
                ('construction','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#materialize_runtime_inspection_business_request'),
                ('validation','skills/waapi-skill/wwise_waapi/builders/schema.py#validate_resolved_semantic_result'),
                ('verifier','skills/waapi-skill/wwise_waapi/runtime_inspection_business.py#normalize_runtime_inspection_result'))}}
        if uri.endswith('.getGameObjects'):
            binding['construction']['source'] = 'skills/waapi-skill/wwise_waapi/builders/stable_reads.py#build_profiler_game_objects_request'
            binding['validation']['source'] = 'skills/waapi-skill/wwise_waapi/builders/schema.py#validate_semantic_result'
            binding['verifier']['source'] = 'skills/waapi-skill/wwise_waapi/builders/stable_reads.py#normalize_profiler_game_objects_result'
        document['bindings'][identity]=binding
        policy['branches'][identity]={'native_shape_sha256':branch['shape_sha256'],'categories':mapping['categories'],
            'reason':'Exact reported fixed-reader data/reference/present/boolean/multiple occurrence; independent native fact required' if mapping['categories']==['program','native'] else
            'SPEC section5 exact deterministic fixed-reader construction/predicate/shape preservation; no actual native occurrence/data/effect claim'}
        if native is not None:
            native_pointer=pointer.replace('/native_call','/observations/raw',1)
            native_value=completion.pointer_value({'observations':{'raw':original['raw']}},native_pointer)
            native_check={'pointer':native_pointer,'cardinality':branch['value']} if branch['kind']=='collection_cardinality' else {'pointer':native_pointer,'equals':native_value}
            native['branch_assertions'][identity]={**assertion,'checks':[native_check]}
            mapping.update(branch_id=identity,native_shape_sha256=branch['shape_sha256'],native_pointer=native_pointer,
                native_result_parent='/observations/raw',native_checks=[native_check],category=category,
                raw_observation=descriptor('original-raw.json'),raw_original_path=original['raw_path'])
    pd={**write('program.json',program),'nodeid':captured['nodeid']}
    for binding in document['bindings'].values():binding['evidence']['program']=deepcopy(pd)
    bd=write('bindings.json',document);rd=write('requirements.json',policy);attachments=[]
    if native is not None:
        nd={**write('native.json',native),'nodeid':profile['nodeid']}
        for number,mapping in enumerate(mapped):
            branch=mapping['branch'];identity=branch['id'];binding=deepcopy(document['bindings'][identity])
            proof={'contract':'waapi-skill.runtime-observation-proof/v1','branch_id':identity,'native_shape_sha256':branch['shape_sha256'],
                'mapping':{k:v for k,v in mapping.items() if k!='branch'},'native_run':native_run,'archive':descriptor(profile['archive_file']),
                'capture':descriptor('original-capture.json'),'capture_original_path':original['capture_path'],'program_capture':descriptor('program-capture.json'),
                'relevant_sources':historical,'source_review':source_review}
            proof_descriptor=write(f'proof-{number}.json',proof)
            binding.update(runtime_observation_attachment=proof_descriptor,program_observation_pointer=mapping['program_pointer'],
                observation_pointer=mapping['native_pointer'],native_observations_sha256={'capture':descriptor('original-capture.json')['sha256'],'raw':descriptor('original-raw.json')['sha256']})
            equivalence={'contract':'waapi-skill.branch-evidence-equivalence/v1','from_candidate':profile['candidate'],'to_candidate':candidate,
                'branch_id':identity,'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],'evidence_sha256':native_run['sha256'],
                'binding_semantics_sha256':audit.digest(completion.binding_semantics(binding)),
                'reviewed_reason':profile['reason'],
                'sources':historical,'runtime_read_review':source_review}
            ed=write(f'equivalence-{number}.json',equivalence)
            attachments.append(write(f'attachment-{number}.json',{'contract':'waapi-skill.runtime-observation-attachment/v1','branch_id':identity,
                'proof':proof_descriptor,'evidence':nd,'native_equivalence':ed}))
    write('index.json',{'contract':'waapi-skill.branch-evidence-index/v1','base':'.',
        'entries':[{'id':name_prefix+'fixed-'+version+'-'+host,'bindings':bd,'origin':{'bindings':bd,'program':descriptor('program.json'),'requirements':rd,'capture':descriptor('program-capture.json')}}],
        **({'runtime_observation_attachments':attachments} if attachments else {})})
    return output/filename('index.json')


def write_fixed_stage(output, captures, *, inventory, route_ids=None, selected_ids=None, original_captures=None, originals=None, r118_capture=None, r118_originals=None, r119_captures=None, r119_originals=None):
    """Select each exact branch once from independent shared public flows."""
    routes = [r for r in inventory['native_coverage']['routes'] if r['uri'] in URIS
        and (route_ids is None or r['id'] in route_ids)]
    if route_ids is not None and {r['id'] for r in routes} != set(route_ids):
        raise ValueError('Fixed stage only accepts existing exact fixed-reader routes')
    wanted = {b['id'] for b in inventory['native_coverage']['obligations'] if b['route'] in {r['id'] for r in routes}}
    if selected_ids is not None:
        if not set(selected_ids) <= wanted: raise ValueError('Fixed stage selected identities escape exact mapped routes')
        wanted = set(selected_ids)
    selected = set()
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': []}
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    def append_flow(flow, fresh):
        document = json.loads(flow.read_bytes())
        index['entries'].extend(document['entries'])
        if document.get('runtime_observation_attachments'):
            index.setdefault('runtime_observation_attachments', []).extend(document['runtime_observation_attachments'])
        flow_policy = completion.read_sealed_artifact(document['entries'][0]['origin']['requirements'], output)
        if policy['branches'].keys() & flow_policy['branches'].keys():
            raise ValueError('Fixed stage duplicates an exact branch')
        policy['branches'].update(flow_policy['branches'])
        selected.update(fresh)
    def captured_route(captured):
        payload = captured['gateway']['payload']
        version = payload['schema_validation']['result']['version']
        host = 'wwise-console' if payload['is_command_line'] else 'wwise-authoring'
        route, = [r for r in routes if r['uri'] == captured['native_call']['uri'] and r['version'] == version and r['host'] == host]
        return route
    if originals is not None or original_captures:
        if originals is None or set(original_captures or {}) != CATEGORIES:
            raise ValueError('Fixed native stage requires all exact seven original public replays')
        # Filtered receipts own one matching result branch each; unfiltered
        # receipts own the remaining independent data witnesses. No ID repeats.
        for category in sorted(CATEGORIES, key=lambda name: ('filter' not in name, name)):
            path = original_captures[category]
            captured = json.loads(Path(path).read_bytes())
            route = captured_route(captured)
            mapped = mappings(inventory, captured, route)
            fresh = {m['branch']['id'] for m in mapped if m['categories'] == ['program', 'native']} & wanted - selected
            if 'filter' in category:
                fresh = set(sorted(fresh)[:1])
            if not fresh:
                raise ValueError('Each original fixed receipt needs an independently matching unique data branch')
            flow = write_fixed_bundle(output, path, originals, inventory=inventory, selected=fresh,
                name_prefix='original-' + category + '-')
            proof = completion.read_sealed_artifact(json.loads(flow.read_bytes())['runtime_observation_attachments'][0], output)
            observed = completion.read_sealed_artifact(proof['proof'], output)
            if observed['mapping']['category'] != category:
                raise ValueError('Fixed original category does not match actual public filter')
            append_flow(flow, fresh)
    if r118_capture is not None or r118_originals is not None:
        if r118_capture is None or r118_originals is None:
            raise ValueError('R118 stage needs its separate exact original closure and current capture')
        captured = json.loads(Path(r118_capture).read_bytes())
        route = captured_route(captured)
        if native_profile({'route':route['id']})['name'] != 'r118':
            raise ValueError('R118 stage is only exact Console2025 identity Voices')
        fresh = {m['branch']['id'] for m in mappings(inventory,captured,route)
            if m['categories'] == ['program','native']} & wanted - selected
        if not fresh:
            raise ValueError('R118 stage needs independently witnessed unique result selectors')
        flow = write_fixed_bundle(output,r118_capture,r118_originals,inventory=inventory,selected=fresh,name_prefix='r118-identity-')
        append_flow(flow,fresh)
    if r119_captures or r119_originals is not None:
        if not r119_captures or r119_originals is None or not set(r119_captures) <= R119_PROFILES.keys():
            raise ValueError('R119 stage needs exact registered original Console profiles and current captures')
        for version, path in sorted(r119_captures.items()):
            captured = json.loads(Path(path).read_bytes())
            route = captured_route(captured)
            if native_profile({'route':route['id']})['name'] != R119_PROFILES[version]['name']:
                raise ValueError('R119 stage capture must match its exact original version/build Console Voices profile')
            fresh = {m['branch']['id'] for m in mappings(inventory,captured,route)
                if m['categories'] == ['program','native']} & wanted - selected
            if not fresh:
                raise ValueError('R119 stage needs independently witnessed unique result selectors')
            flow = write_fixed_bundle(output,path,r119_originals,inventory=inventory,selected=fresh,
                name_prefix=R119_PROFILES[version]['name']+'-')
            append_flow(flow,fresh)
    for number, path in enumerate(captures):
        captured = json.loads(Path(path).read_bytes())
        route = captured_route(captured)
        mapped = mappings(inventory, captured, route)
        fresh = ({m['branch']['id'] for m in mapped} & wanted) - selected
        if not fresh:
            continue
        flow = write_fixed_bundle(output, path, None, inventory=inventory, selected=fresh, name_prefix=f'flow-{number}-')
        append_flow(flow, fresh)
    if selected != wanted:
        raise ValueError('Fixed stage unproved exact branches: ' + repr(sorted(wanted - selected)))
    runtime.write_json(output / 'index.json', index)
    runtime.write_json(output / 'requirements.json', policy)
    return output / 'index.json'

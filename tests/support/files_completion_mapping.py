"""Exact #183/#184 input/result correspondence, independent of execution credit.

Only ten pinned native catalogs define the roster. Accepted weak verification
and historical failures survive; no native behavior is inferred from mapping.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tests.maintenance.branch_coverage_audit import digest, schema_branches
from tests.support.topic_completion_mapping import _path

LIB = 'skills/waapi-skill/wwise_waapi/'
GATEWAY = 'skills/waapi-skill/scripts/gateway.py'
BASE = 'tests/fixtures/branch-evidence/product/files-195-r1/'
POLICY = 'docs/plans/full-waapi-coverage/SPEC.md'
TICKETS = ['docs/plans/full-waapi-coverage/tickets/' + name for name in (
    '09-complete-soundbank-definition-conversion-and-build-options.md',
    '10-complete-console-project-and-file-operation-alternatives.md')]
OWNERS = {
    **{'ak.wwise.cli.' + name: 184 for name in ('addNewPlatform', 'createNewProject', 'dumpObjects',
        'migrate', 'moveMediaIdsToSingleFile', 'moveMediaIdsToWorkUnits', 'updateMediaIdsInSingleFile', 'verify')},
    **{'ak.wwise.console.project.' + name: 184 for name in ('close', 'create', 'open')},
    **{'ak.wwise.cli.' + name: 183 for name in ('convertExternalSource', 'generateSoundbank')},
    **{'ak.wwise.core.soundbank.' + name: 183 for name in ('convertExternalSources', 'generate',
        'getInclusions', 'processDefinitionFiles', 'setInclusions')},
    **{'ak.wwise.core.audio.' + name: 183 for name in ('convert', 'setConversionPlugin')},
}


def discover_files(root):
    """Expand reachable definitions; retain every host/version and reference site."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root)
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    if {key.split('|', 1)[1]: value['owner_issue'] for key, value in owners.items()
            if value['owner_issue'] in (183, 184)} != OWNERS:
        raise ValueError('Files exact #183/#184 ownership roster changed')
    routes, rows, catalogs, locations = [], {}, {}, defaultdict(list)
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            graph = DefinitionGraph(**{k: catalog['definitions'][k] for k in
                ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
            # No assumption that Authoring and Console or version rosters agree.
            for uri in sorted(set(catalog['functions']) & set(OWNERS)):
                native = f'{version}|{host}|{build}|function|{uri}'
                routes.append({'id': native, 'version': version, 'host': host, 'build': build,
                    'kind': 'function', 'uri': uri, 'owner_issue': OWNERS[uri],
                    'native_schema_sha256': digest(catalog['schemas'][uri]),
                    'public_route': f'{version}|function|{uri}'})
                for section in ('argsSchema', 'optionsSchema', 'resultSchema'):
                    schema = catalog['schemas'][uri][section]
                    def visit(value, pointer, context, document, active, location):
                        for item in schema_branches(value, pointer):
                            identity = native + '|' + item['pointer']
                            address = location + _path(item['pointer'][len(pointer):], schema=value,
                                schema_pointer=pointer, legacy_paths=frozenset())
                            if address not in locations[identity]:
                                locations[identity].append(address)
                            row = {'id': identity, 'route': native, 'pointer': item['pointer'],
                                'kind': item['kind'], 'shape_sha256': digest(item['value']),
                                'owner_issue': OWNERS[uri], 'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'}
                            if item['kind'] != 'schema':
                                row['value'] = item['value']
                            if item['kind'] == 'reference':
                                target = resolve_schema_reference(item['value'], root_schema=context, graph=graph)
                                doc = document if target.document_name == '<schema>' else target.document_name
                                key = (doc, target.pointer)
                                ptr = '/' + section + '/@definition/' + doc + target.pointer
                                row['reference'] = {'target': native + '|' + ptr, 'recursive': key in active,
                                    'document': doc, 'target_sha256': digest(target.target)}
                                if key not in active:
                                    visit(target.target, ptr, context if target.document_name == '<schema>' else graph.documents[doc],
                                        doc, active | {key}, address)
                            if identity in rows and rows[identity] != row:
                                raise ValueError('Files reachable definition identity collision')
                            rows[identity] = row
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    return {'routes': routes, 'catalogs': catalogs, 'obligations': sorted(rows.values(), key=lambda r: r['id'])}, dict(locations)


def files_component(root):
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    root = Path(root)
    native, locations = discover_files(root)
    observed = {row['id']: {'kind': row['kind'], 'shape_sha256': row['shape_sha256']} for row in native['obligations']}
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    if roster != {'catalogs': native['catalogs'], 'entries': observed}:
        raise ValueError('Files native field/choice/version/definition differs from reviewed roster')
    wanted = {route['public_route'] for route in native['routes']}
    public = [deepcopy(row) for row in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes']
        if row['id'] in wanted]
    if {row['id'] for row in public} != wanted:
        raise ValueError('Files current public route/version missing')
    sources = debug_control_component(root)['sources']
    for name in [*TICKETS, POLICY, 'docs/research/soundbank183-lightweight-closeout.md',
            'tests/support/files_completion_mapping.py', 'tests/support/topic_completion_mapping.py',
            'tests/semantic/support/codex_archive_paths.py', BASE + 'source-roster.json', BASE + 'accepted-history.json',
            *[str(path.relative_to(root)) for path in sorted((root / BASE / 'historical').glob('*.json'))]]:
        sources[name] = digest((root / name).read_text(encoding='utf-8'))
    component = {'component': 'files-195-r1', 'routes': public, 'sources': sources,
        'native_locations': locations, 'native_coverage': native}
    native['candidate_sha256'] = candidate_identity(root, component, native['catalogs'], digest=digest)
    return component


# These joins are reviewed against the compiler, not generated by string-case
# conversion. The contract is checked independently before a join can be used.
CLI_FIELDS = {
    'project': ['project_file'], 'path': ['project_file'],
    'new-platform-base': ['base_platform'], 'new-platform-name': ['platform_name'],
    'copy-from-platform': ['copy_settings_from_platform'], 'platform': ['platforms'],
    'quiet': ['verbosity'], 'verbose': ['verbosity'], 'no-wwise-dat': ['wwise_dat'],
    'source-file': ['source_files'], 'source-by-platform': ['source_files_by_platform'],
    'output': ['output_directory', 'output_directories_by_platform'],
    'content': ['content'], 'no-session': ['include_session_objects'],
    'abort-on-load-issues': ['stop_on_load_issues'], 'no-source-control': ['source_control'],
    'bank': ['soundbanks', 'soundbank_scope'], 'language': ['languages'], 'skip-languages': ['skip_languages'],
    'cache': ['cache_directory'], 'clear-audio-file-cache': ['clear_converted_media_cache'],
    'continue-on-error': ['continue_on_error'], 'audio-source-from-original': ['audio_sources_from_project_originals'],
    'header-file': ['generate_header'], 'header-file-path': ['header_directory'],
    'import-definition-file': ['definition_files'], 'import-language': ['import_language'],
    'tab-delimited-import-file': ['tabular_import_files'], 'tab-delimited-operation': ['tabular_import_mode'],
    'license': ['license_text'], 'license-file': ['license_file'], 'no-decode': ['decoded_media'],
    'root-output-path': ['root_output_directory'], 'soundbank-path': ['soundbank_directories_by_platform'],
    'save': ['save_project'], 'readable-soundbanks': ['readable_soundbanks'], 'use-stable-guid': ['stable_guids'],
    'use-user-overrides': ['use_user_overrides'], 'languages': ['languages'], 'platforms': ['platforms'],
    'autoCheckOutToSourceControl': ['auto_checkout'], 'onMigrationRequired': ['migration_policy'],
}
HOOKS = {'custom-global-opening-cmd', 'custom-global-closing-cmd', 'custom-pre-gen-cmd', 'custom-post-gen-cmd'}
CORE_FIELDS = {
    'generate': {'soundbanks': ['soundbanks', 'all_user_soundbanks'], 'platforms': ['platforms'], 'languages': ['languages'],
        'writeToDisk': ['write_to_disk'], 'skipLanguages': ['skip_languages'], 'rebuildSoundBanks': ['rebuild_soundbanks'],
        'clearAudioFileCache': ['clear_audio_file_cache'], 'rebuildInitBank': ['rebuild_init_bank']},
    'setInclusions': {'soundbank': ['soundbank_handle'], 'operation': ['mode'], 'inclusions': ['inclusions']},
    'getInclusions': {'soundbank': ['soundbank_id']},
    'convertExternalSources': {'sources': ['sources']}, 'processDefinitionFiles': {'files': ['files']},
    'convert': {'objects': ['audio_object_handles'], 'platforms': ['platform_names'], 'languages': ['languages']},
    'setConversionPlugin': {'conversion': ['conversion_handle'], 'platform': ['platform_name'], 'plugin': ['plugin_type_handle']},
}


def _contract(route):
    from wwise_waapi.cli_console_business_contracts import cli_console_business_contract_data
    from wwise_waapi.core_business_contracts import core_business_contract_data
    from wwise_waapi.soundbank_business_contracts import soundbank_business_contract_data
    from wwise_waapi.media_build_business_contracts import media_build_business_contract_data
    uri, version = route['uri'], route['version']
    if uri.endswith('project.close'):
        return {'declaration': {'required_fields': [], 'optional_fields': [], 'subcommand': 'draft-check'}, 'zero_value': True}
    if '.cli.' in uri or '.console.' in uri:
        return cli_console_business_contract_data(uri, version)
    if uri.endswith('getInclusions'):
        return media_build_business_contract_data(uri, version)
    if '.core.audio.' in uri:
        return core_business_contract_data(uri, version)
    return soundbank_business_contract_data('soundbank.' + uri.rsplit('.', 1)[1], version)


def _input_fields(uri, path):
    """One exact native address to closed business fields, including nesting."""
    name, top = uri.rsplit('.', 1)[1], path[0] if path else None
    if top is None:
        return [], 'closed_argument_envelope'
    if '*' in path:
        return [], 'closed_schema_additional_member_guard'
    if top in HOOKS:
        return [], 'prohibited_external_command_hook'
    if '.cli.' in uri or '.console.' in uri:
        if top not in CLI_FIELDS:
            raise ValueError('Files native argument lacks reviewed public mapping: ' + uri + '/' + str(path))
        fields = CLI_FIELDS[top]
        if name == 'dumpObjects' and top == 'output':
            fields = ['output_file']
        if name == 'generateSoundbank':
            fields = {'source-file': ['external_source_files'], 'source-by-platform': ['external_source_files_by_platform'],
                'output': ['external_source_output_directory', 'output_directories_by_platform']}.get(top, fields)
        if name == 'create' and top == 'platforms' and path[-1] in ('basePlatform', 'name'):
            return ['platforms[][0]' if path[-1] == 'basePlatform' else 'platforms[][1]'], 'closed_platform_creation_tuple'
        return fields, 'closed_cli_business_field'
    if top not in CORE_FIELDS[name]:
        raise ValueError('Files native argument lacks reviewed public mapping: ' + uri + '/' + str(path))
    fields = CORE_FIELDS[name][top]
    if name == 'generate' and top == 'soundbanks':
        nested = next((token for token in path[1:] if token is not None), None)
        if nested:
            fields = {'name': ['soundbanks[].soundbank_handle', 'soundbanks[].name'],
                'events': ['soundbanks[].event_handles'], 'auxBusses': ['soundbanks[].aux_bus_handles'],
                'inclusions': ['soundbanks[].inclusions'], 'rebuild': ['soundbanks[].rebuild']}.get(nested)
            if fields is None:
                raise ValueError('Files nested SoundBank field lacks public mapping')
    if name == 'setInclusions' and top == 'inclusions':
        nested = next((token for token in path[1:] if token is not None), None)
        if nested:
            fields = {'object': ['inclusions[].object_handle'], 'filter': ['inclusions[].filters']}.get(nested)
            if fields is None:
                raise ValueError('Files nested inclusion field lacks public mapping')
    if name == 'convertExternalSources' and top == 'sources':
        nested = next((token for token in path[1:] if token is not None), None)
        if nested:
            if nested not in ('input', 'output', 'platform'):
                raise ValueError('Files nested external source field lacks public mapping')
            fields = ['sources[].' + nested]
    return fields, 'closed_core_business_field'


def _validate_disclosure(declaration, field, row, uri, address):
    """Check nested choices against their actual public schema/form."""
    schema = declaration.get('schema')
    if schema is not None:
        node = schema
        for token in field.split('.'):
            array = '[]' in token
            key = token.split('[')[0]
            if key not in node.get('properties', {}):
                raise ValueError('Files nested public field/choice is not disclosed: ' + field)
            node = node['properties'][key]
            if array:
                node = node['items']
        if row['kind'] == 'enum_value' and node.get('type') == 'array':
            node = node.get('items', {})
        if row['kind'] == 'enum_value' and 'enum' in node:
            choice = row['value']
            if uri.endswith('soundbank.generate'):
                choice = {'event': 'events', 'structure': 'structures'}.get(choice, choice)
            if choice not in node['enum']:
                raise ValueError('Files public enum choice is not disclosed: ' + str(choice))
    if '.cli.' in uri or '.console.project.' in uri:
        form = declaration.get('input_forms', {}).get(field.split('[')[0], {})
        if row['kind'] == 'enum_value':
            choice = {'createNew': 'create', 'replaceExisting': 'replace', 'useExisting': 'reuse',
                'name': 'names', 'propertyset': 'property_sets'}.get(row['value'], row['value'])
            disclosed = form.get('base_platform_choices') if address[-1:] == ['basePlatform'] else form.get('choices')
            if disclosed is not None and choice not in disclosed:
                raise ValueError('Files public enum choice is not disclosed: ' + str(choice))


def _encoding(uri, fields, path, version):
    name, top = uri.rsplit('.', 1)[1], path[0] if path else None
    if not fields:
        return 'Gateway-owned closed envelope; no caller args/options or external-command escape'
    if top in ('quiet', 'verbose'):
        return 'verbosity=' + top + ' emits true; normal/omitted emits neither flag; mutually exclusive'
    if top in ('no-wwise-dat', 'no-decode', 'no-source-control'):
        return 'omit/disabled emits true; write/enabled/absent omits native negative flag; native defaults retained'
    if top == 'no-session':
        return 'include_session_objects=false emits true; true/absent omits no-session'
    if top == 'tab-delimited-operation':
        return 'create=createNew; replace=replaceExisting; reuse=useExisting; absent retains native default'
    if top == 'content':
        return 'names=name; property_sets=propertyset; absent retains native default'
    if top == 'bank':
        return 'selected names or exact hashed .txt list; soundbank_scope=all omits native bank'
    if top in ('output', 'source-by-platform', 'soundbank-path'):
        return ('global exact directory or repeated [platform,value] tuples; one tuple emits native pair, many emit pair array; '
            'paths confined to derived owned I/O root; omitted project defaults remain omitted; 2022.1 one source per platform limitation retained')
    if top in ('project', 'path'):
        return 'exact .wproj path, owned I/O proof and process binding; host path conversion is Gateway-owned'
    if top in ('new-platform-base', 'new-platform-name', 'copy-from-platform'):
        return ('installed base/name or existing copy-source platform; settings and unrelated model compared; '
            'only 2025.1 omitted new name defaults to base name; earlier versions require explicit name')
    if uri.endswith('project.create') and top == 'platforms':
        return 'platforms base-name string or [base,name] tuple; one row emits object, many emit array; exact pinned base enum; explicit empty retained'
    if uri.endswith('project.create') and top == 'languages':
        return 'ordered exact names; first is default; omission retains native English(US); explicit empty is disclosed unresolved'
    if name == 'generate' and top == 'soundbanks':
        return ('bound bank name or noncolliding temporary name; events/AuxBusses resolve exact GUIDs; '
            'events=event, structures=structure, media=media; explicit empty nested choices retained; '
            'all_user_soundbanks uses empty list in 2023+ and exact live enumeration in 2021/2022')
    if top == 'writeToDisk':
        return 'public default true; explicit false selects result-only memory generation; native-default omits field (native false); Topic data requires subscription before generation'
    if top == 'skipLanguages':
        return 'explicit boolean forwarded; native-default omits; public omission derives from artifact expectation; language omission retains all project languages'
    if name == 'setConversionPlugin':
        return {'conversion': 'exact Conversion handle resolves canonical GUID',
            'platform': 'exact unique live project platform name resolves GUID; association is not verified',
            'plugin': 'discovered installed Conversion Type Handle resolves native codec name; no codec GUID or automatic scalar continuation'}[top]
    if name == 'convert':
        return 'bound exact audio object GUIDs; exact live platform/language names; declared I/O root and source/identity guards; result schema only'
    if name == 'convertExternalSources':
        return 'ordered hashed .wsources input/platform rows; explicit output confined; omission binds live platform-specific Project.ExternalSourcesOutputPath, not stale schema prose default'
    if name == 'processDefinitionFiles':
        return 'ordered hashed UTF-8 TSV files without rewriting; version-aware GUID/Short-ID/type binding and retained GUID table guards; lightweight code-only table acceptance'
    if name in ('getInclusions', 'setInclusions'):
        return 'exact bound SoundBank/object GUIDs; add/remove/replace and events/structures/media identity; explicit replace-empty clears; readback expands exact object identity and normalized includes'
    return 'closed typed business value/list; order and explicit false retained; optional omission retains native default; live selectors and exact file/I/O proofs are Gateway-owned'


def _verification(uri):
    if uri.endswith('setConversionPlugin'):
        return {'status': 'result_schema_checked', 'business_state_verified': False, 'codec_guid_returned': False,
            'unverified': ['actual replacement', 'platform-to-codec GUID association', 'other-platform preservation']}
    if uri.endswith('audio.convert'):
        return {'status': 'result_schema_checked', 'business_state_verified': False,
            'retained_independent_native_artifact': 'soundbank183-core-files-2025-r1 scoped WEM PASS; combined original node remains FAIL'}
    if uri.endswith('cli.migrate'):
        return {'status': 'conservative_partial_or_unverified', 'lossless_migration': False,
            'accepted_limit': 'observed Soundcaster audition-state references lost; original native FAIL retained; no narrower verifier implemented'}
    if uri.endswith('processDefinitionFiles'):
        return {'acceptance': 'lightweight_table_code_only', 'exact_inclusions': 'unique single-file bank with empty prestate only',
            'otherwise': 'result_schema_only_business_state_verified_false', 'exclusion_effects_verified': False}
    if uri.endswith('soundbank.generate'):
        return {'files': 'independent requested nonempty changed bank/platform/language artifacts and bounded tree/input guards',
            'memory': 'result_schema_diagnostics_only_business_state_verified_false_no_bank_data_captured'}
    if '.cli.' in uri:
        return {'process_result': '0 success; 1 error/possible partial effects; 2 warnings; unknown remains unverified without retry',
            'terminal': 'no post-terminal WAAPI calls', 'effects': 'independent exact owned file/project observation; process success alone is insufficient',
            'create_acceptance': 'closed wrapper/code-only accepted; unobserved effect is not native absence',
            'table_acceptance': 'Definition/audio TSV code-only; ordinary generation/conversion artifacts remain separate'}
    if uri.endswith('project.close'):
        return {'result': 'hadProjectOpen boolean retained', 'effect': 'attested transition_to_none'}
    if uri.endswith('project.create'):
        return {'acceptance': 'lightweight_wrapper_code_only', 'production_verifier': 'saved project and exact live transition; explicit-empty effect remains unresolved'}
    if uri.endswith('project.open'):
        return {'effect': 'exact requested saved GUID/name/path live transition; migration policy never implies migration success'}
    if uri.endswith('setInclusions'):
        return {'effect': 'independent exact inclusion pre/post-state plus object identity; unrelated objects preserved'}
    return {'result': 'bounded native schema and exact identity-normalized inclusion output; no mutation'}


def _result_projection(uri, path, version):
    if uri.endswith('getInclusions'):
        if path[-1:] == ['object']:
            return {'public': ['inclusions[].object_id'],
                'derived_live_fields': ['name', 'type', 'path'], 'rule': 'exact_GUID_identity_readback_join'}
        if 'filter' in path:
            return {'public': ['inclusions[].includes'], 'rule': 'same_filter_values_sorted_no_aliasing'}
        return {'public': ['inclusions', 'count'], 'rule': 'bounded_identity_expansion_sorted_by_path_and_GUID'}
    if '.cli.' in uri:
        return {'public': ['execution_evidence.native_result'],
            'rule': 'integer_process_result_0_success_1_partial_error_2_warning; missing_or_unknown_is_unverified',
            'early_media_id_void': version in ('2021.1', '2022.1', '2023.1') and 'MediaIds' in uri,
            'scoped_compatibility': 'moveMediaIdsToSingleFile_2021_to_2023_observed_result_only; pinned_schema_preserved'}
    if uri.endswith('project.close'):
        return {'public': ['execution_evidence.native_result.hadProjectOpen'],
            'rule': 'boolean_not_a_substitute_for_independent_transition_to_none'}
    if uri.endswith('soundbank.generate'):
        return {'public': ['execution_evidence.native_result'],
            'rule': '2025_error_must_be_empty; logs_are_bounded_diagnostics; artifact_or_memory_verification_stays_separate'}
    if uri.endswith('audio.convert'):
        return {'public': ['execution_evidence.native_result.errors'],
            'rule': 'bounded_returned_conversion_failures; no_codec_GUID_or_artifact_success_inferred'}
    return {'public': ['execution_evidence.native_result'],
        'rule': 'bounded_schema_checked_acknowledgement; no_unobserved_effect_inferred'}


def _mechanism(uri):
    if '.cli.' in uri:
        return 'cli-build' if uri in ('ak.wwise.cli.generateSoundbank', 'ak.wwise.cli.convertExternalSource') else 'cli-project-files'
    if '.console.project.' in uri:
        return 'console-project-transitions'
    if uri.endswith('setConversionPlugin'):
        return 'conversion-result-only'
    if uri.endswith('audio.convert'):
        return 'audio-convert'
    if uri.endswith('getInclusions') or uri.endswith('setInclusions'):
        return 'inclusions'
    if uri.endswith('processDefinitionFiles'):
        return 'definition-table'
    return 'core-generation-conversion'


def files_bindings(root, inventory):
    """Fail closed on native roster drift and removed closed public fields."""
    root = Path(root)
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    rows = inventory['native_coverage']['obligations']
    if roster['entries'] != {row['id']: {'kind': row['kind'], 'shape_sha256': row['shape_sha256']} for row in rows}:
        raise ValueError('Files native field/choice/version/definition differs from reviewed roster')
    public = {row['id']: row for row in inventory['routes']}
    routes = {row['id']: row for row in inventory['native_coverage']['routes']}
    if {row['route'] for row in rows} != set(routes) or {r['public_route'] for r in routes.values()} != set(public):
        raise ValueError('Files native/public route roster differs')
    contracts = {key: _contract(route) for route in routes.values() for key in [route['public_route']]}
    bindings = {}
    for row in rows:
        route, pointer = routes[row['route']], row['pointer']
        uri, key = route['uri'], route['public_route']
        section = pointer.split('/')[1]
        contract = contracts[key]
        declaration = contract.get('declaration', contract)
        exposed = set(declaration.get('required_fields', [])) | set(declaration.get('optional_fields', []))
        addresses = inventory['native_locations'][row['id']]
        choices = []
        for address in addresses:
            fields, rule = _input_fields(uri, address) if section == 'argsSchema' else ([],
                'fixed_empty_options' if section == 'optionsSchema' else 'bounded_native_result')
            if {field.split('[')[0] for field in fields} - exposed:
                raise ValueError('Files mapped public field/choice is not disclosed: ' + uri + ' ' + repr(fields))
            for field in fields:
                _validate_disclosure(declaration, field, row, uri, address)
            choices.append({'native_path': address, 'public_fields': fields, 'rule': rule,
                'encoding': _encoding(uri, fields, address, route['version']) if section == 'argsSchema' else
                    'Gateway emits {}' if section == 'optionsSchema' else 'bounded native keys/values retained in execution evidence; diagnostic/error/process result is not independent business verification'})
        fields = sorted({field for choice in choices for field in choice['public_fields']})
        correspondence = {'rule': choices[0]['rule'] if len({c['rule'] for c in choices}) == 1 else 'all_exact_reference_sites',
            'native_addresses': choices, 'public_fields': fields, 'contract_sha256': digest(contract),
            'verification': _verification(uri),
            **({'output_projection': [_result_projection(uri, address, route['version']) for address in addresses]}
                if section == 'resultSchema' else {}),
            'choice': {'kind': row['kind'], **({'value': row['value']} if 'value' in row else {})}}
        if row['kind'] == 'enum_value' and section == 'argsSchema':
            native_choice = row['value']
            correspondence['public_choice'] = ({'event': 'events', 'structure': 'structures'}.get(native_choice, native_choice)
                if uri.endswith('soundbank.generate') else {'createNew': 'create', 'replaceExisting': 'replace',
                    'useExisting': 'reuse', 'name': 'names', 'propertyset': 'property_sets'}.get(native_choice, native_choice)
                if '.cli.' in uri else native_choice)
        if 'reference' in row:
            correspondence['reference'] = row['reference']
        cli = '.cli.' in uri or ('.console.project.' in uri and not uri.endswith('close'))
        read = uri.endswith('getInclusions')
        soundbank = '.core.soundbank.' in uri and not read
        construction = (LIB + 'cli_console_business.py#materialize_cli_console_business_request' if cli else
            LIB + 'media_build_business.py#materialize_media_build_business_request' if read else
            LIB + 'soundbank_business.py#materialize_soundbank_business_request' if soundbank else
            LIB + 'operation_registry.py#prepare_operation' if uri.endswith('project.close') else
            LIB + 'core_business.py#materialize_core_business_request')
        operation = 'soundbank.' + uri.rsplit('.', 1)[1] if soundbank else uri
        bindings[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
            'public_route': key, 'public_route_sha256': digest(public[key]),
            'input': {'gateway_argv': ['core-call' if read else 'draft-start', operation],
                'declaration': 'core-call' if read else declaration.get('subcommand', 'draft-declare-core-plan'),
                'selector': pointer, 'correspondence': correspondence},
            'construction': {'source': construction, 'selector': pointer},
            'validation': {'source': LIB + 'builders/schema.py#' + ('validate_semantic_result' if section == 'resultSchema' else 'validate_semantic_payload'), 'selector': pointer},
            'verifier': {'source': LIB + 'media_build_business.py#normalize_media_build_result' if read else
                LIB + 'operation_registry.py#verify_prepared_operation', 'selector': pointer},
            'representative_mechanism': 'files195-' + _mechanism(uri) + '-v1', 'evidence': {}}
    return bindings


SELECTED_TESTS = {
    'cli-build': ['tests/unit/test_cli_console_business_adapter.py::test_generate_soundbank_plan_derives_flags_mappings_and_modes'],
    'cli-project-files': [
        'tests/unit/test_console_project_alternatives_gateway.py::test_cli_media_ids_observe_owned_file_and_work_units_without_inventing_mapping_format',
        'tests/unit/test_console_project_alternatives_gateway.py::test_cli_migration_distinguishes_failed_preservation_and_unresolved_transformation'],
    'console-project-transitions': [
        'tests/unit/test_console_project_alternatives_gateway.py::test_console_create_saves_requested_language_order_and_default',
        'tests/unit/test_console_project_native_witness.py::test_console_create_close_collector_uses_two_authorized_transitions_and_final_writer'],
    'conversion-result-only': ['tests/unit/test_conversion_plugin_gateway.py::test_conversion_type_handle_invokes_setter_without_claiming_codec_or_platform_effect'],
    'audio-convert': ['tests/unit/test_core_business_gateway.py::test_audio_convert_core_plan_accepts_bound_objects_names_and_exact_io_root'],
    'inclusions': ['tests/unit/test_soundbank_business_gateway.py::test_business_inclusion_plan_checks_and_seals_one_immutable_preview',
        'tests/unit/test_media_build_business_gateway.py::test_soundbank_inclusion_core_call_resolves_business_identities'],
    'definition-table': ['tests/unit/test_soundbank_business_gateway.py::test_definition_ordered_repeated_bank_files_disclose_result_only_before_authorization'],
    'core-generation-conversion': [
        'tests/unit/test_soundbank_business_gateway.py::test_generation_business_choice_reaches_immutable_preview_and_truthful_verifier',
        'tests/unit/test_soundbank_business_gateway.py::test_external_source_omitted_output_binds_live_project_platform_setting'],
}
RUNTIME_SOURCES = {GATEWAY, 'tests/support/gateway_config.py',
    'tests/destructive/test_gateway_workflow_transaction_matrix.py',
    'tests/unit/test_field_interface_closure_gateway.py', 'tests/unit/test_object_graph_business_gateway.py',
    'tests/semantic/support/codex_project_prelaunch_v3.py', 'tests/semantic/support/codex_archive_paths.py',
    *(node.split('::')[0] for nodes in SELECTED_TESTS.values() for node in nodes),
    *(LIB + name + '.py' for name in ('soundbank_business', 'soundbank_business_contracts', 'operation_soundbank',
        'cli_console_business', 'cli_console_business_contracts', 'console_project_operations', 'console_platform_copy',
        'console_media_ids', 'core_business', 'core_business_contracts', 'media_build_business',
        'media_build_business_contracts', 'business_adapters', 'business_declaration_state', 'business_declarations',
        'operation_registry', 'operation_drafts', 'operation_composer', 'transactions', 'transaction_runtime',
        'transaction_cleanup', 'dispatcher', 'config', 'capabilities', 'execution_contracts', 'builders/schema', 'io_policy'))}


def files_program_anchors(root, inventory, destination, run):
    """Copy finalized ordinary aggregate CODE proof; never invent node outcomes."""
    import subprocess
    from tests.maintenance.branch_audit_completion import binding_semantics
    from tests.support.ordinary_test_run_evidence import RUNNER_SOURCES
    from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
    root, destination, run = Path(root).resolve(), Path(destination).resolve(), Path(run).resolve()
    plan = json.loads((run / 'run.plan.json').read_bytes())
    result = json.loads((run / 'run.result.json').read_bytes())
    summary = json.loads((run / 'run.summary.json').read_bytes())
    if (result.get('candidate_unchanged') is not True or result.get('exit_code') != 0
            or result.get('git_status') != '' or result.get('remaining_owned_processes') != []
            or summary.get('status') != 'PASS' or summary.get('source_unchanged') is not True
            or summary.get('skipped') != 0 or result.get('head_after') != plan.get('candidate')):
        raise ValueError('Files selected code anchor is missing or unfinalized')
    if not {node for nodes in SELECTED_TESTS.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('Files code anchor omits a selected representative mechanism')
    originals = {}
    for name in RUNTIME_SOURCES | RUNNER_SOURCES:
        raw = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        originals[name] = hashlib.sha256(raw).hexdigest()
        if name in RUNTIME_SOURCES and hashlib.sha256((root / name).read_bytes()).hexdigest() != originals[name]:
            raise ValueError('Files relevant selected source changed: ' + name)
    destination.mkdir(parents=True, exist_ok=True)
    files = {}
    for key, name in {'plan': 'run.plan.json', 'result': 'run.result.json', 'summary': 'run.summary.json',
            'log': 'run.log', 'exit': 'run.exit'}.items():
        raw = (run / name).read_bytes()
        target = destination / 'original' / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(raw)
        files[key] = {'artifact': archive_relative_from_absolute(target, destination).canonical,
            'sha256': hashlib.sha256(raw).hexdigest()}
    selected = {}
    for identity, binding in files_bindings(root, inventory).items():
        selected.setdefault(binding['representative_mechanism'], (identity, binding))
    anchors = {}
    for number, (mechanism, (identity, binding)) in enumerate(sorted(selected.items()), 1):
        anchor = {'ordinary_test_run_attachment': True, 'relevant_sources': sorted(RUNTIME_SOURCES), 'evidence': {}}
        binding.update(anchor)
        group = mechanism.removeprefix('files195-').removesuffix('-v1')
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': originals, 'skip_lines': [],
            'review': {'reason': 'Byte-identical relevant sources in an actual focused aggregate CODE run; no native/per-node observation inferred',
                'selection_reason': 'Accepted #183/#184 representative closed construction and safety/weak-result controls; original native histories remain separate, not rerun per mapping leaf',
                'sources': {name: {'original_sha256': originals[name], 'current_sha256': originals[name],
                    'reviewed_reason': 'Byte-identical relevant source'} for name in sorted(RUNTIME_SOURCES)}, 'skip_attribution': {}},
            'mechanism': {'branch_id': identity, 'native_route': identity.rsplit('|', 1)[0],
                'native_shape_sha256': binding['native_shape_sha256'],
                'binding_semantics_sha256': digest(binding_semantics(binding)), 'selected_tests': SELECTED_TESTS[group]}}
        target = destination / f'program-anchor-{number:02}.json'
        target.write_text(json.dumps(proof, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        anchor['evidence']['program'] = {'artifact': archive_relative_from_absolute(target, destination).canonical,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
        anchors[identity] = anchor
    return anchors


def export_files_mapping(root, destination, *, inventory=None, anchors=None):
    """Use standard mapping attachments and bounded requirements parts only."""
    from tests.maintenance.branch_coverage_audit import write_requirements
    from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
    root, destination = Path(root).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    inventory = files_component(root) if inventory is None else inventory
    bindings = files_bindings(root, inventory)
    anchors = anchors or {}
    if set(anchors) - set(bindings):
        raise ValueError('Files selected anchor is outside exact family')
    for identity, anchor in anchors.items():
        if (set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True or set(anchor['evidence']) != {'program'}):
            raise ValueError('Files anchor requires original ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    groups = defaultdict(dict)
    for identity, binding in bindings.items():
        mechanism = binding['representative_mechanism']
        groups[mechanism][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'],
            'categories': ['program'], 'representative_mechanism': mechanism,
            'reason': 'Accepted #183/#184 representative mapping/code policy; retained native proof and limits separately attributed; no new per-leaf/native credit'}
    for mechanism, members in groups.items():
        selected = sorted(set(members) & set(anchors))
        if len(selected) > 1:
            raise ValueError('Files mechanism requires one selected ordinary anchor')
        sources = {binding[key]['source'].split('#')[0] for binding in members.values()
            for key in ('construction', 'validation', 'verifier')}
        sources.update({POLICY, *TICKETS, 'docs/research/soundbank183-lightweight-closeout.md',
            LIB + 'cli_console_business_contracts.py', LIB + 'soundbank_business_contracts.py',
            LIB + 'core_business_contracts.py', LIB + 'media_build_business_contracts.py',
            LIB + 'operation_soundbank.py', LIB + 'console_project_operations.py'})
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact versioned #183/#184 closed mapping and accepted verification limits; aggregate CODE mechanism only, no member native effect claim',
            'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(sources)},
            'members': {identity: {'native_route': rows[identity]['route'], 'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': digest({key: value for key, value in binding.items() if key != 'evidence'})} for identity, binding in members.items()},
            'selected_proofs': {'program': selected or [min(members)]}}
    def write(name, body):
        path = destination / name
        path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        return {'artifact': archive_relative_from_absolute(path, destination).canonical,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    entries, descriptors = [], []
    for number, (mechanism, members) in enumerate(sorted(groups.items()), 1):
        for identity in sorted(set(members) & set(anchors)):
            original = deepcopy(members[identity])
            record = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: original}}
            binding_descriptor = write(f'selected-{number:02}.json', record)
            policy_descriptor = write(f'selected-policy-{number:02}.json', {'contract': requirements['contract'],
                'branches': {identity: requirements['branches'][identity]}})
            entries.append({'id': identity, 'bindings': binding_descriptor, 'origin': {
                'bindings': binding_descriptor, 'program': original['evidence']['program'], 'requirements': policy_descriptor,
                'capture': write(f'selected-review-{number:02}.json', {'mechanism': mechanism,
                    'scope': 'actual aggregate CODE proof; no per-node/native observation'})}})
        proposed = deepcopy(members)
        predecessors = {identity: {'binding_sha256': digest(binding), 'policy_sha256': digest(requirements['branches'][identity])}
            if identity in anchors else None for identity, binding in members.items()}
        for binding in proposed.values():
            binding['evidence'] = {}
        descriptors.append(write(f'mapping-{number:02}.json', {'contract': 'waapi-skill.branch-mapping-attachment/v1',
            'scope_kind': 'product', 'requirements_sha256': digest(requirements), 'mechanisms': [mechanism],
            'bindings': proposed, 'predecessors': predecessors}))
    write_requirements(destination / 'requirements.json', requirements)
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': entries, 'mapping_attachments': descriptors}
    write('evidence-index.json', index)
    summary = {'component': inventory['component'], 'public_routes': len(inventory['routes']),
        'native_routes': len(inventory['native_coverage']['routes']), 'native_members': len(rows),
        'catalogs': inventory['native_coverage']['catalogs'], 'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
        'mechanisms': {key: len(members) for key, members in sorted(groups.items())},
        'mapping_is_not_execution_credit': True, 'native_or_fresh_started': False,
        'canonical_import_pending': True, 'largest_mapping_bytes': max((destination / d['artifact']).stat().st_size for d in descriptors)}
    write('summary.json', summary)
    return {'index_path': destination / 'evidence-index.json', 'requirements': requirements, 'summary': summary}

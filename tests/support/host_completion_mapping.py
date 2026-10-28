"""Exact #190 and remaining #193 host mappings; no native observation credit."""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tests.maintenance.branch_coverage_audit import digest, schema_branches
from tests.support.topic_completion_mapping import _path
from tests.support.ui_completion_mapping import _public_nodes
LIB = 'skills/waapi-skill/wwise_waapi/'
GATEWAY = 'skills/waapi-skill/scripts/gateway.py'
BASE = 'tests/fixtures/branch-evidence/product/host-195-r1/'
POLICY = 'docs/plans/full-waapi-coverage/SPEC.md'
OWNERS = {
 **{'ak.wwise.'+name:190 for name in ('core.project.save','core.remote.connect','core.remote.disconnect',
 'core.remote.getAvailableConsoles','core.remote.getConnectionStatus','ui.bringToForeground','ui.captureScreen',
 'ui.getSelectedFiles','ui.getSelectedObjects','ui.cli.executeLuaScript','ui.cli.launch','ui.commands.execute',
 'ui.commands.getCommands','ui.commands.register','ui.commands.unregister','ui.project.close','ui.project.create','ui.project.open')},
 **{'ak.wwise.'+name:193 for name in ('cli.executeLuaScript','cli.waapiServer','core.executeLuaScript',
 'core.getInfo','core.getProjectInfo','core.ping','debug.generateToneWAV','debug.getWalTree','debug.validateCall',
 'waapi.getFunctions','waapi.getSchema','waapi.getTopics')},
}
EXCLUDED = frozenset({'ak.wwise.ui.cli.executeLuaScript','ak.wwise.ui.cli.launch'})
SOURCES = [GATEWAY, *[LIB+n+'.py' for n in ('authoring_ui_business','authoring_ui_business_contracts',
 'host_ui_debug_business','host_ui_debug_business_contracts','exact_artifact_business','exact_artifact_business_contracts',
 'runtime_inspection_business','runtime_inspection_business_contracts','cli_console_business','cli_console_business_contracts',
 'core_business','core_business_contracts','operation_ui_commands','operation_registry','builders/debug_lua','builders/schema','debug_business','wal_read_continuation','remote_transition',
 # Exact Tone/project artifact preparation and verification, including their
 # shared regular-file, path and digest helpers; importing registry is not closure.
 'operation_tone','console_project_operations','operation_soundbank','filesystem_security','host_paths','canonical')],
 'tests/support/host_completion_mapping.py','tests/support/ui_completion_mapping.py','tests/support/topic_completion_mapping.py',
 'tests/maintenance/map_host_completion.py', POLICY, BASE+'source-roster.json',BASE+'accepted-history.json']


def discover_host(root):
    """Enumerate all ten source catalogs, keeping reference and recursive identities."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root)
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    expected = {key.split('|',1)[1]: row['owner_issue'] for key,row in owners.items()
        if row['owner_issue'] == 190 or row['owner_issue'] == 193 and key.split('|',1)[1] in OWNERS}
    if expected != OWNERS: raise ValueError('Host exact #190/#193 ownership roster changed')
    routes, rows, catalogs, locations = [], {}, {}, defaultdict(list)
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        for host in NATIVE_HOSTS:
            catalog = load_native_catalog(version, host, root=root / 'skills/waapi-skill/resources/native-catalog')
            build = catalog['provenance']['build']
            catalogs[f'{version}|{host}|{build}'] = catalog['content_sha256']
            wanted = set(OWNERS) & set(catalog['functions'])
            graph = DefinitionGraph(**{k: catalog['definitions'][k] for k in
                ('contract', 'version', 'wwise_build', 'source_file_names', 'documents', 'inventory_sha256')})
            for uri in sorted(wanted):
                native = f'{version}|{host}|{build}|function|{uri}'
                routes.append({'id': native, 'version': version, 'host': host, 'build': build, 'kind': 'function',
                    'uri': uri, 'native_schema_sha256': digest(catalog['schemas'][uri]), 'public_route': None if uri in EXCLUDED else f'{version}|function|{uri}'})
                for section in ('argsSchema', 'optionsSchema', 'resultSchema'):
                    schema, visited = catalog['schemas'][uri][section], set()
                    def visit(value, pointer, context, document, active, location):
                        for item in schema_branches(value, pointer):
                            identity = native + '|' + item['pointer']
                            address = location + _path(item['pointer'][len(pointer):], schema=value,
                                schema_pointer=pointer, legacy_paths=frozenset())
                            if address not in locations[identity]: locations[identity].append(address)
                            row = {'id': identity, 'route': native, 'pointer': item['pointer'], 'kind': item['kind'],
                                'shape_sha256': digest(item['value']), 'owner_issue': OWNERS[uri],
                                'parent_issue': 174, 'blocks_issue': 195, 'state': 'unresolved'}
                            if item['kind'] != 'schema': row['value'] = item['value']
                            if item['kind'] == 'reference':
                                target = resolve_schema_reference(item['value'], root_schema=context, graph=graph)
                                doc = document if target.document_name == '<schema>' else target.document_name
                                key = (doc, target.pointer)
                                ptr = '/' + section + '/@definition/' + doc + target.pointer
                                row['reference'] = {'target': native + '|' + ptr, 'recursive': key in active,
                                    'document': doc, 'target_sha256': digest(target.target)}
                                if key not in active:
                                    visited.add(key)
                                    visit(target.target, ptr, context if target.document_name == '<schema>' else graph.documents[doc],
                                        doc, active | {key}, address)
                            if identity in rows and rows[identity] != row: raise ValueError('Host native identity collision')
                            rows[identity] = row
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    return {'routes': routes, 'catalogs': catalogs, 'obligations': sorted(rows.values(), key=lambda r: r['id'])}, dict(locations)


def host_component(root):
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    root = Path(root)
    history=json.loads((root / BASE / 'accepted-history.json').read_bytes())
    import subprocess
    for name,record in history['sources'].items():
        original=subprocess.run(['git','show',record['original_candidate']+':'+name],cwd=root,
            check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
        if hashlib.sha256(original).hexdigest()!=record['sha256']:
            raise ValueError('Host retained historical source changed: '+name)
    native, locations = discover_host(root)
    observed = {'catalogs': native['catalogs'], 'entries': {r['id']: {'kind': r['kind'], 'shape_sha256': r['shape_sha256']} for r in native['obligations']}}
    if json.loads((root / BASE / 'source-roster.json').read_bytes()) != observed:
        raise ValueError('Host native field/choice/version/definition differs from reviewed roster')
    wanted = {r['public_route'] for r in native['routes'] if r['public_route'] is not None}
    public = [deepcopy(r) for r in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes'] if r['id'] in wanted]
    if {r['id'] for r in public} != wanted: raise ValueError('Host current public route/version missing')
    sources = debug_control_component(root)['sources']
    sources.update({name: digest((root / name).read_text(encoding='utf-8')) for name in SOURCES})
    inventory = {'component': 'host-195-r1', 'routes': public, 'sources': sources, 'native_locations': locations, 'native_coverage': native}
    native['candidate_sha256'] = candidate_identity(root, inventory, native['catalogs'], digest=digest)
    inventory['host_roster_sha256'] = digest([(r['id'], r['shape_sha256']) for r in native['obligations']])
    inventory['host_routes_sha256'] = digest(native['routes'])
    return inventory


HOST_FIELDS = {
 'waapi.getSchema': {'uri':['target_uri'],'includeExamples':['include_examples']},
 'debug.generateToneWAV': {n:[p] for n,p in {'path':'output_file','waveform':'waveform','frequency':'frequency_hz',
 'channelConfig':'channel_layout','bitDepth':'bit_depth','sampleRate':'sample_rate_hz','attackTime':'attack_seconds',
 'sustainTime':'sustain_seconds','releaseTime':'release_seconds','sustainLevel':'sustain_db','setAnonymous':'anonymous_channels',
 'waveformChannelMask':'waveform_channels','markers':'markers'}.items()},
 'ui.project.open': {'path':['project_file'],'bypassSave':['discard_unsaved_current_project'],
 'onUpgrade':['upgrade_policy'],'onMigrationRequired':['migration_policy'],'autoCheckOutToSourceControl':['auto_checkout']},
 'ui.project.close': {'bypassSave':['discard_unsaved_changes']},
 'ui.project.create': {'path':['project_file'],'platforms':['platforms'],'languages':['languages']},
 'ui.captureScreen': {'viewName':['view_name'],'viewSelectionChannel':['view_channel'],'viewSyncGroup':['view_channel'],'rect':['rectangle']},
 'ui.commands.execute': {'command':['command_id'],'objects':['objects'],'platforms':['platforms'],'files':['files'],'value':['value']},
 'ui.commands.unregister': {'commands':['registered_command_keys','existing_command_ids','confirm_unknown_ownership']},
 'core.remote.connect': {'host':['remote_host'],'appName':['application_name'],'commandPort':['command_port'],'notificationPort':['notification_port']},
 'core.project.save': {'autoCheckOutToSourceControl':['auto_check_out']},
}
REGISTER_FIELDS = {
 'id':['commands[].key'], 'displayName':['commands[].display_name'], 'args':['commands[].handler.argument_tokens'],
 'cwd':['commands[].handler.working_directory'], 'defaultShortcut':['commands[].default_shortcut'],
 'program':['commands[].handler.program_path'], 'luaScript':['commands[].handler.lua_script_path'],
 'luaPaths':['commands[].handler.lua_module_directories'], 'luaSelectedReturn':['commands[].handler.lua_selected_return'],
 'redirectOutputs':['commands[].handler.redirect_outputs'], 'startMode':['commands[].handler.start_mode'],
 'contextMenu':['commands[].context_menu'], 'mainMenu':['commands[].main_menu'],
}
SERVER_FIELDS = {n:[p] for n,p in {'project':'project_file','allow-migration':'allow_project_migration',
 'allowed-addr':'allowed_addresses','allowed-origin':'allowed_origins','wamp-port':'wamp_port','http-port':'http_port',
 'wamp-max-clients':'wamp_max_clients','http-max-clients':'http_max_clients','watchdog-timeout':'watchdog_seconds',
 'no-source-control':'source_control','quiet':'verbosity','verbose':'verbosity'}.items()}


def _contract(uri, version):
    from wwise_waapi.host_ui_debug_business_contracts import HOST_UI_DEBUG_BUSINESS_OPERATIONS, host_ui_debug_business_contract_data
    from wwise_waapi.authoring_ui_business_contracts import AUTHORING_UI_BUSINESS_OPERATIONS, authoring_ui_business_contract_data
    from wwise_waapi.runtime_inspection_business_contracts import runtime_inspection_business_contract_data
    from wwise_waapi.core_business_contracts import core_business_contract_data
    from wwise_waapi.exact_artifact_business_contracts import exact_artifact_business_contract_data
    from wwise_waapi.cli_console_business_contracts import cli_console_business_contract_data
    name=uri.removeprefix('ak.wwise.')
    if uri in HOST_UI_DEBUG_BUSINESS_OPERATIONS: return host_ui_debug_business_contract_data(uri,version)
    if name in AUTHORING_UI_BUSINESS_OPERATIONS: return authoring_ui_business_contract_data(name,version)
    if name=='core.remote.connect': return runtime_inspection_business_contract_data(uri,version)
    if name=='core.project.save': return core_business_contract_data(uri,version)
    if name in ('core.getInfo','core.getProjectInfo'):
        return {'start':{'gateway_argv':['status','--detail']},'declaration':{'public_fields':['detail']},
            'result_projection':'complete native getInfo and getProjectInfo in agent_result.wwise/project; compact status is summary only'}
    if name=='ui.getSelectedObjects': return {'start':{'gateway_argv':['selected']},'declaration':{'public_fields':[]},
        'projection':'Gateway fixes id/name/type/path for mutation identity handoff; no caller native return grammar'}
    if name=='debug.getWalTree': return {'start':{'gateway_argv':['debug-wal-tree']},'declaration':{'public_fields':[]}}
    if name=='debug.validateCall': return {'start':{'gateway_argv':['debug-validate-call']},'declaration':{'public_fields':['target_uri','exact_user_artifact']}}
    if name=='cli.waapiServer': return cli_console_business_contract_data(uri,version)
    if name in ('cli.executeLuaScript','core.executeLuaScript'):
        return exact_artifact_business_contract_data('lua.executeCliFile' if name.startswith('cli.') else 'lua.executeCoreFile',version)
    return {'declaration':{'public_fields':[]},'input_mode':'approved_exclusion' if uri in EXCLUDED else 'closed_fixed_read_or_zero_plan'}


def _fields(name, address, version):
    path=[p for p in address if p is not None and p!='*']
    if not path: return [],'closed_envelope'
    top=path[0]
    if name=='ui.commands.register':
        if top!='commands': raise ValueError('Host unhandled registration root '+repr(path))
        if len(path)==1: return ['command_count','commands'],'owned_command_collection'
        field=path[1]
        if field not in REGISTER_FIELDS: raise ValueError('Host unhandled command native field '+repr(path))
        if field=='args' and version in ('2021.1','2022.1'): return [],'prohibited_generic_program_arguments'
        fields=REGISTER_FIELDS[field]
        if len(path)>2 and field in ('contextMenu','mainMenu'):
            nested={'basePath':'base_path','visibleFor':'visible_for','enabledFor':'enabled_for'}[path[2]]
            fields=[fields[0]+'.'+nested]
        return fields,'closed_command_descriptor'
    if name in ('cli.executeLuaScript','core.executeLuaScript'):
        if top in ('lua-script','luaScript'): return ['script_file'],'exact_user_source_file'
        if top=='luaString': return ['lua_source','io_root'],'exact_user_source_inline_alternative'
        if top=='watchdog-timeout': return ['watchdog_seconds'],'closed_watchdog'
        return [],'existing_lua_reserved_loader_boundary'
    if name=='debug.validateCall': return ['target_uri'] if top=='id' else ['exact_user_artifact'], 'validation_only_no_target_execution'
    mapping=SERVER_FIELDS if name=='cli.waapiServer' else HOST_FIELDS.get(name,{})
    if top not in mapping: raise ValueError('Host unmapped native input '+name+' '+repr(path))
    fields=mapping[top]
    if name=='debug.generateToneWAV' and top=='markers' and len(path)>1:
        fields=['markers[].'+{'position':'position_seconds','label':'label'}[path[1]]]
    if name=='ui.captureScreen' and top=='rect' and len(path)>1: fields=['rectangle.'+path[1]]
    return fields,'closed_business_field'


def _registration_schema(declaration):
    header=declaration['header_schema']
    return {'type':'object','properties':{**header['properties'],'commands':{'type':'array','items':declaration['item_schema']}}}


def _validate_public(contract, fields, name, version):
    if name=='debug.validateCall': return
    declaration=contract['declaration']
    schema=declaration.get('schema')
    if name=='ui.commands.register': schema=_registration_schema(declaration)
    exposed=set(declaration.get('public_fields', schema.get('properties',{}) if schema else [*declaration.get('required_fields',[]),*declaration.get('optional_fields',[])]))
    # Core inline Lua is a separate already-supported exact-source declaration.
    if name=='core.executeLuaScript' and 'lua_source' in fields:
        from wwise_waapi.exact_artifact_business_contracts import exact_artifact_business_contract_data
        declaration=exact_artifact_business_contract_data('lua.executeCoreInline',version)['declaration']
        schema=declaration['schema']; exposed=set(declaration['public_fields'])
    for field in fields:
        if field.split('.')[0].split('[')[0] not in exposed:
            raise ValueError('Host mapped public field is not disclosed: '+name+' '+field)
        if schema and not _public_nodes(schema,field): raise ValueError('Host nested public field is not disclosed: '+field)


def _correspondence(row, route, addresses, contract):
    uri,pointer=route['uri'],row['pointer']; name=uri.removeprefix('ak.wwise.'); section=pointer.split('/')[1]
    choices=[]
    for address in addresses:
        if uri in EXCLUDED: fields,rule=[],'approved_ui_lua_launch_exclusion'
        elif section=='resultSchema': fields,rule=[],'bounded_versioned_result'
        elif section=='optionsSchema':
            fields,rule=([], 'gateway_owned_exact_identity_projection' if name=='ui.getSelectedObjects' else 'fixed_empty_options')
        else: fields,rule=_fields(name,address,route['version'])
        _validate_public(contract,fields,name,route['version'])
        choices.append({'native_path':address,'public_fields':fields,'rule':rule})
    fields=sorted({f for c in choices for f in c['public_fields']})
    result={'rule':choices[0]['rule'] if len({c['rule'] for c in choices})==1 else 'all_exact_reference_sites',
        'native_addresses':choices,'public_fields':fields,'contract_sha256':digest(contract),'native_effect':'not_claimed',
        'host_version':{'host':route['host'],'version':route['version'],'build':route['build']},
        'encoding':'closed typed values; absent optional fields retain native defaults; explicit false and empty collections remain distinct; exact authority and native serialization Gateway-owned',
        'safety':'configuration-bound; mutations require policy authorization, immutable preview, drift checks, single execution, bounded verification and cleanup'}
    if row['kind']=='enum_value':
        value=row['value']; result['native_choice']=value; result['public_choice']={'whiteNoise':'white_noise'}.get(value,value)
        declaration=contract['declaration']; forms=declaration.get('input_forms',{})
        if section=='argsSchema':
            for field in fields:
                form=forms.get(field,{})
                disclosed=form.get('choices',form.get('key_choices'))
                if disclosed is not None and result['public_choice'] not in disclosed:
                    raise ValueError('Host mapped native choice is not disclosed: '+name+' '+repr(value))
            if name=='ui.commands.register' and 'commands[].handler.start_mode' in fields:
                nodes=_public_nodes(_registration_schema(declaration),'commands[].handler.start_mode')
                if not any(value in node.get('enum',[]) for node in nodes): raise ValueError('Host command start mode is not disclosed')
    if 'reference' in row: result['reference']=row['reference']
    if name.startswith('ui.commands.'):
        result['fresh_command_inventory']='gateway_owned_getCommands_before_dispatch'
        result['command_ids']='live host/project/plugin snapshot, never packaged allowlist; registration derives project-scoped ID and owns paired unregister'
    if name.startswith('ui.project.'):
        result['verification']='create: exact live project and owned saved file; explicit-empty effects unresolved; open: live saved identity/path transition; close: observed no-project transition; no new GUI QA'
        if name.endswith(('open','close')): result['save_prompt']='discard defaults false; bypassSave true requires explicit user intent; pending prompt/transition stays incomplete without retry'
    if name=='debug.generateToneWAV':
        result['encoding']='waveform white_noise→whiteNoise; channel index set→sum(1<<index), including empty zero mask; marker position_seconds→position; optional omission forwarded; exact owned output path'
        result['verification']='tone_file_creation / file_creation_only; stable changed owned regular file; no format, waveform, header, channel, marker or audibility certification'
    if name in ('debug.getWalTree','debug.validateCall'): result['accepted_boundary']='existing closed internal Debug wrapper; no extra Debug/native availability claim or environment validation'
    if '.executeLuaScript' in name:
        result['accepted_boundary']='existing Core/CLI exact-source scope unchanged; reserved side-load/project/migration keys cannot be injected via arguments; code must be supplied verbatim by user'
        result['verification']='result-schema-only; terminal/nonretry process boundary; no semantic Lua effect claim'
    if name=='ui.commands.register': result['code_boundary']='generic Program argument tokens remain prohibited; supported Lua handler tokens use host serializer; no arbitrary raw args string or generated handler source'
    if name=='core.remote.connect': result['remote_binding']='fresh exact discovery binding; 2021 command+notification ports pair; later notificationPort retained as unused, no effect promise; capture host uses exact owned file proof'
    if section=='resultSchema':
        result['result']='bounded versioned native result with exact final agent_result; absent/null retained; no acknowledgement upgraded to business effect'
        if name in ('core.getInfo','core.getProjectInfo'): result['result']='status --detail preserves complete native info/project in agent_result.wwise/project; ordinary status is compact summary only'
        elif name=='ui.getSelectedObjects': result['result']='selected fixes identity fields id/name/type/path; full object projection belongs to query-object; canonical native result fields outside identity are not caller-authored return grammar'
        elif name=='debug.getWalTree': result['result']='complete nodes map, exact native number IDs and absent/empty distinction; bounded pages share whole-result proof and host/config binding; no Debug availability claim'
    if name=='ui.project.create': result['encoding']='ordered languages (first is default), native omission English(US); platforms [base] or [base,name] -> object fields basePlatform/name, native omission Windows; explicit empty collections retained without invented effects'
    if name=='cli.waapiServer': result['encoding']='allowed address/origin lists -> comma-separated exact strings; verbosity quiet/verbose -> mutually exclusive true flags, normal omits both; disabled source_control -> no-source-control=true; omitted/default ports and watchdog retained; versioned migration/source-control fields only'
    if name=='ui.captureScreen': result['encoding']='view_channel -> viewSyncGroup in 2021.1, viewSelectionChannel later; rectangle x/y/width/height -> rect; all-UI/default current channel and whole-view capture retain native omission'
    if name=='ui.commands.register': result['encoding']='key -> Gateway project-scoped id; display_name/default_shortcut -> displayName/defaultShortcut; menu paths join / and object types join commas; exact handler source/path ownership, host-specific token serializer, typed startMode and booleans; Lua module directories -> host ?.lua patterns'
    return result


def host_bindings(root, inventory):
    native=inventory['native_coverage']
    if (digest([(r['id'],r['shape_sha256']) for r in native['obligations']])!=inventory['host_roster_sha256']
            or digest(native['routes'])!=inventory['host_routes_sha256']): raise ValueError('Host mapping native field/host/version roster differs')
    routes={r['id']:r for r in native['routes']}; public={r['id']:r for r in inventory['routes']}
    if {r['public_route'] for r in routes.values() if r['public_route'] is not None}!=set(public): raise ValueError('Host mapping public route roster differs')
    contracts={r['public_route']:_contract(r['uri'],r['version']) for r in routes.values() if r['public_route'] is not None}
    bindings={}
    for row in native['obligations']:
        route=routes[row['route']]; uri=route['uri']; name=uri.removeprefix('ak.wwise.'); section=row['pointer'].split('/')[1]
        if uri in EXCLUDED: continue
        contract=contracts[route['public_route']]
        module=('authoring_ui_business' if name in ('ui.captureScreen','ui.commands.execute','ui.commands.register','ui.commands.unregister') else
            'host_ui_debug_business' if name in HOST_FIELDS and name not in ('core.remote.connect','core.project.save') else
            'runtime_inspection_business' if name=='core.remote.connect' else 'cli_console_business' if name=='cli.waapiServer' else
            'exact_artifact_business' if name.endswith('executeLuaScript') and uri not in EXCLUDED else 'core_business' if name=='core.project.save' else None)
        construct=LIB+module+'.py#materialize_'+module+'_request' if module else GATEWAY+'#execute_gateway'
        if name=='waapi.getSchema': construct=LIB+'host_ui_debug_business.py#materialize_waapi_schema_read_args'
        if name=='core.remote.connect': construct=LIB+'runtime_inspection_business.py#materialize_runtime_control_business_request'
        argv=contract.get('start',{}).get('gateway_argv',contract.get('start',{}).get('gateway_argv_prefix',['request-schema',uri]))
        group=('excluded' if uri in EXCLUDED else 'commands' if name.startswith('ui.commands.') or name=='ui.captureScreen' else
            'project' if name.startswith('ui.project.') or name=='core.project.save' else 'tone' if name=='debug.generateToneWAV' else
            'lua-server' if name in ('cli.waapiServer','cli.executeLuaScript','core.executeLuaScript') else
            'debug-read' if name.startswith('debug.') else 'remote' if name.startswith('core.remote.') else 'fixed-read')
        bindings[row['id']]={'branch_id':row['id'],'native_shape_sha256':row['shape_sha256'],'public_route':route['public_route'],
            'public_route_sha256':digest(public[route['public_route']]),'input':{'gateway_argv':argv,'selector':row['pointer'],
                'correspondence':_correspondence(row,route,inventory['native_locations'][row['id']],contract)},
            'construction':{'source':construct,'selector':row['pointer']},
            'validation':{'source':LIB+'builders/schema.py#validate_semantic_'+('result' if section=='resultSchema' else 'payload'),'selector':row['pointer']},
            'verifier':{'source':LIB+'operation_registry.py#verify_prepared_operation' if module else GATEWAY+'#execute_gateway','selector':row['pointer']},
            'representative_mechanism':'host195-'+group+'-v1','evidence':{}}
    return bindings


def export_mapping(root, destination, *, inventory=None, anchors=None):
    """One cohort, standard mapping attachments and ordinary requirements parts."""
    from tests.maintenance.branch_coverage_audit import write_requirements
    root, destination = Path(root).resolve(), Path(destination).resolve()
    inventory = host_component(root) if inventory is None else inventory
    bindings = host_bindings(root, inventory)
    destination.mkdir(parents=True, exist_ok=True)
    anchors = anchors or {}
    if set(anchors) - set(bindings): raise ValueError('Host selected anchor is outside exact family')
    for identity, anchor in anchors.items():
        if (set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True or set(anchor['evidence']) != {'program'}):
            raise ValueError('Host anchor requires original ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    rows = {r['id']: r for r in inventory['native_coverage']['obligations']}
    groups = defaultdict(dict)
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    for identity, binding in bindings.items():
        mechanism = binding['representative_mechanism']
        groups[mechanism][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'], 'categories': ['program'],
            'representative_mechanism': mechanism, 'reason': POLICY + ': accepted lightweight #190/#193 wrappers; internal Debug no-additional-verification and Tone file-creation outcome preserved; no native effect inferred'}
    for mechanism, members in groups.items():
        selected = sorted(set(members) & set(anchors))
        if len(selected) > 1: raise ValueError('Host mechanism uses one selected ordinary anchor')
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact lightweight Host wrapper mapping with truthful schema/host/version/effect limits; aggregate CODE only',
            'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES},
            'members': {identity: {'native_route': rows[identity]['route'], 'native_shape_sha256': rows[identity]['shape_sha256'],
                'mapping_sha256': digest({k: v for k, v in binding.items() if k != 'evidence'})} for identity, binding in members.items()},
            'selected_proofs': {'program': selected or [min(members)]}}
    def write(name, body):
        path = destination / name
        path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        return {'artifact': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    entries, attachments = [], []
    for number, (mechanism, members) in enumerate(sorted(groups.items()), 1):
        for identity in sorted(set(members) & set(anchors)):
            original = deepcopy(members[identity])
            descriptor = write(f'selected-{number:02}.json', {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: original}})
            policy = write(f'selected-policy-{number:02}.json', {'contract': requirements['contract'], 'branches': {identity: requirements['branches'][identity]}})
            entries.append({'id': identity, 'bindings': descriptor, 'origin': {'bindings': descriptor, 'program': original['evidence']['program'],
                'requirements': policy, 'capture': write(f'selected-review-{number:02}.json', {'mechanism': mechanism, 'scope': 'actual ordinary aggregate proof; no native/per-node observations'})}})
        proposed = deepcopy(members)
        for binding in proposed.values(): binding['evidence'] = {}
        predecessors = {identity: {'binding_sha256': digest(binding), 'policy_sha256': digest(requirements['branches'][identity])}
            if identity in anchors else None for identity, binding in members.items()}
        attachments.append(write(f'mapping-{number:02}.json', {'contract': 'waapi-skill.branch-mapping-attachment/v1', 'scope_kind': 'product',
            'requirements_sha256': digest(requirements), 'mechanisms': [mechanism], 'bindings': proposed, 'predecessors': predecessors}))
    write_requirements(destination / 'requirements.json', requirements)
    write('evidence-index.json', {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': '.', 'entries': entries, 'mapping_attachments': attachments})
    summary = {'component': inventory['component'], 'public_routes': len(inventory['routes']), 'native_routes': len(inventory['native_coverage']['routes']), 'approved_exclusion_routes': sum(r['public_route'] is None for r in inventory['native_coverage']['routes']),
        'native_members': len(rows), 'mapped_members': len(bindings), 'approved_exclusion_members': len(rows)-len(bindings), 'catalogs': inventory['native_coverage']['catalogs'], 'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
        'mechanisms': {k: len(v) for k, v in sorted(groups.items())}, 'mapping_is_not_execution_credit': True, 'native_effect_credit': False,
        'canonical_import_pending': True, 'requirements_parts': json.loads((destination / 'requirements.json').read_bytes()).get('parts', [])}
    write('summary.json', summary)
    return {'index_path': destination / 'evidence-index.json', 'requirements_path': destination / 'requirements.json', 'requirements': requirements, 'summary': summary}


SELECTED_TESTS = {
 'commands':['tests/unit/test_authoring_ui_gateway.py::test_public_business_register_succeeds_then_public_cleanup_unregisters',
 'tests/unit/test_authoring_ui_gateway.py::test_public_business_execute_and_unregister_run_one_full_gateway_chain',
 'tests/unit/test_authoring_ui_gateway.py::test_business_capture_screen_finishes_as_result_schema_only'],
 'project':['tests/unit/test_authoring_project_workflows.py::test_authoring_project_create_verifies_saved_requested_effect',
 'tests/unit/test_authoring_project_workflows.py::test_authoring_project_close_accepts_observed_no_project'],
 'tone':['tests/unit/test_host_ui_debug_business_adapter.py::test_tone_business_completion_proves_file_creation_without_audio_quality_checks',
 'tests/unit/test_host_ui_debug_business_adapter.py::test_tone_empty_choices_keep_all_three_modification_policies',
 'tests/unit/test_host_ui_debug_business_adapter.py::test_tone_verifier_rejects_missing_artifact_after_one_native_dispatch'],
 'lua-server':['tests/unit/test_debug_lua_gateway_full_chain.py::test_cli_lua_file_runs_once_then_finishes_at_result_schema_only',
 'tests/unit/test_cli_console_business_adapter.py::test_waapi_server_plan_joins_closed_allow_lists_and_derives_controls'],
 'debug-read':['tests/unit/test_debug_read_gateway.py::test_debug_wal_tree_dispatches_one_closed_bounded_request',
 'tests/unit/test_debug_read_gateway.py::test_debug_validate_call_validates_target_without_executing_it'],
 'remote':['tests/unit/test_authoring_core_gateway.py::test_remote_connect_reuses_closed_preview_and_verification'],
 'fixed-read':['tests/unit/test_authoring_core_gateway.py::test_selected_files_uses_disclosed_zero_input_and_validates_result'],
}

RUNTIME_SOURCES = {name for name in SOURCES if name.startswith('skills/waapi-skill/')}
RUNTIME_SOURCES.update({*(node.split('::')[0] for nodes in SELECTED_TESTS.values() for node in nodes),
    # Collection configuration and the phase/finalization hook ran for every
    # selected node even though this ordinary capture has no per-node receipts.
    'pyproject.toml', 'tests/conftest.py', 'tests/support/exact_evidence_finalization.py',
    'tests/support/gateway_config.py', 'tests/support/riff_wave.py', 'tests/support/canonical_preview.py',
    'tests/support/operation_directory.py', 'tests/unit/test_transaction_gateway.py', 'tests/unit/test_runtime_business_gateway.py',
    'tests/unit/test_waapi_gateway.py', 'tests/unit/test_debug_read_gateway.py',
    *(LIB + name + '.py' for name in ('operation_drafts', 'operation_composer', 'transactions', 'transaction_runtime',
        'transaction_cleanup', 'business_adapters', 'business_declaration_state', 'business_declarations',
        'dispatcher', 'capabilities', 'execution_contracts', 'config', 'io_policy'))})


def program_anchors(root, inventory, destination, run):
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
        raise ValueError('Host selected code anchor is missing or unfinalized')
    if not {node for nodes in SELECTED_TESTS.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('Host code anchor omits a selected representative mechanism')
    originals = {}
    for name in RUNTIME_SOURCES | RUNNER_SOURCES:
        raw = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        originals[name] = hashlib.sha256(raw).hexdigest()
        if name in RUNTIME_SOURCES and hashlib.sha256((root / name).read_bytes()).hexdigest() != originals[name]:
            raise ValueError('Host relevant selected source changed: ' + name)
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
    for identity, binding in host_bindings(root, inventory).items():
        selected.setdefault(binding['representative_mechanism'], (identity, binding))
    anchors = {}
    for number, (mechanism, (identity, binding)) in enumerate(sorted(selected.items()), 1):
        anchor = {'ordinary_test_run_attachment': True, 'relevant_sources': sorted(RUNTIME_SOURCES), 'evidence': {}}
        binding.update(anchor)
        group = mechanism.removeprefix('host195-').removesuffix('-v1')
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': originals, 'skip_lines': [],
            'review': {'reason': 'Byte-identical relevant sources in an actual focused aggregate CODE run; no native/per-node observation inferred',
                'selection_reason': 'Accepted #190/#193 representative closed construction and safety/weak-result controls; original native histories remain separate, not rerun per mapping leaf',
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

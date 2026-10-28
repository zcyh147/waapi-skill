"""Exact #182 input/result mapping, with representative CODE proof kept separate.

Discovery reads all ten pinned catalogs before consulting the public contracts.
Table acceptance never manufactures native evidence or erases original failures.
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
BASE = 'tests/fixtures/branch-evidence/product/imports-195-r1/'
POLICY = 'docs/plans/full-waapi-coverage/SPEC.md'
TICKETS = ['docs/plans/full-waapi-coverage/tickets/08-complete-audio-import-reimport-and-replacement-workflows.md']
OWNERS = {uri: 182 for uri in ('ak.wwise.cli.tabDelimitedImport',
    'ak.wwise.core.audio.import', 'ak.wwise.core.audio.importTabDelimited')}
ACCEPTED_LIMITS = {
    'duplicate_source_guard': 'wwise-console|2025.1.7.9143',
    'group_descriptors': 'Switch/State groups under Default Work Unit only; ordinary Object Path destinations and DialogueEvent destinations unchanged',
    'older_dialogue_spelling': '2021.1/2022.1 MultiSwitchEntry.AudioNode Container spelling for RandomSequenceContainer remains guarded; canonical spelling and 2023.1+ mapping retained',
    'table_acceptance': 'closed wrapper and code tests only, including multilingual; no new native QA',
    'dialogue_sequence': 'requested association/numeric values checked; decision-path ordering not read back',
    'ordinary_import': 'retained selected representative native observations only; mapping is not native execution credit',
}

def discover_imports(root):
    """Expand reachable definitions; retain every host/version and reference site."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root)
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    if {key.split('|', 1)[1]: value['owner_issue'] for key, value in owners.items()
            if value['owner_issue'] == 182} != OWNERS:
        raise ValueError('Imports exact #183/#184 ownership roster changed')
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
                                raise ValueError('Imports reachable definition identity collision')
                            rows[identity] = row
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    return {'routes': routes, 'catalogs': catalogs, 'obligations': sorted(rows.values(), key=lambda r: r['id'])}, dict(locations)


def imports_component(root):
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    root = Path(root)
    native, locations = discover_imports(root)
    observed = {row['id']: {'kind': row['kind'], 'shape_sha256': row['shape_sha256']} for row in native['obligations']}
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    if roster != {'catalogs': native['catalogs'], 'entries': observed}:
        raise ValueError('Imports native field/choice/version/definition differs from reviewed roster')
    wanted = {route['public_route'] for route in native['routes']}
    public = [deepcopy(row) for row in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes']
        if row['id'] in wanted]
    if {row['id'] for row in public} != wanted:
        raise ValueError('Imports current public route/version missing')
    sources = debug_control_component(root)['sources']
    for name in [*TICKETS, POLICY,
            'tests/support/imports_completion_mapping.py', 'tests/support/topic_completion_mapping.py',
            'tests/semantic/support/codex_archive_paths.py', BASE + 'source-roster.json', BASE + 'accepted-history.json',
            *[str(path.relative_to(root)) for path in sorted((root / BASE / 'historical').glob('*.json'))]]:
        sources[name] = digest((root / name).read_text(encoding='utf-8'))
    component = {'component': 'imports-195-r1', 'routes': public, 'sources': sources,
        'native_locations': locations, 'native_coverage': native, 'accepted_limits': ACCEPTED_LIMITS}
    native['candidate_sha256'] = candidate_identity(root, component, native['catalogs'], digest=digest)
    return component


# Reviewed spellings: no case conversion or native caller envelope is admitted.
ROW_FIELDS = {
    'audioFile': 'media_file', 'audioFileBase64': 'inline_wav',
    'audioSourceNotes': 'audio_source_notes', 'dialogueEvent': 'dialogue_event',
    'event': 'event', 'importLanguage': 'language', 'notes': 'notes',
    'originalsSubFolder': 'originals_subfolder', 'switchAssignation': 'switch_group',
}
CLI_FIELDS = {
    'project': 'project_file', 'tab-delimited-import-file': 'table_file',
    'audio-source-from-original': 'audio_sources_from_project_originals',
    'continue-on-error': 'continue_on_error', 'import-language': 'import_language',
    'tab-delimited-operation': 'tabular_import_mode', 'no-source-control': 'source_control',
    'quiet': 'verbosity', 'verbose': 'verbosity',
}
TABLE_FIELDS = {
    'importFile': 'table_file', 'importLanguage': 'language',
    'importLocation': 'location_handle', 'importOperation': 'mode',
    'autoAddToSourceControl': 'add_to_source_control',
    'autoCheckOutToSourceControl': 'check_out_from_source_control',
}
MODE_MAPPING = {'createNew': 'derived_create', 'useExisting': 'derived_reimport', 'replaceExisting': 'explicit_replace'}


def _contract(route):
    from wwise_waapi.audio_import_business_contracts import audio_import_business_contract_data
    from wwise_waapi.exact_artifact_business_contracts import exact_artifact_business_contract_data
    from wwise_waapi.cli_console_business_contracts import cli_console_business_contract_data
    if '.cli.' in route['uri']:
        return cli_console_business_contract_data(route['uri'], route['version'])
    if route['uri'].endswith('importTabDelimited'):
        return exact_artifact_business_contract_data('audio.importTabDelimited', route['version'])
    return audio_import_business_contract_data(route['version'])


def _input_fields(uri, path):
    if not path or path == ['*']:
        return [], 'closed_argument_envelope'
    top = path[0]
    if '.cli.' in uri:
        if top in ('custom-global-opening-cmd', 'custom-global-closing-cmd'):
            return [], 'prohibited_external_command_hook'
        if top not in CLI_FIELDS:
            raise ValueError('Imports native field lacks reviewed public mapping: ' + str(path))
        return [CLI_FIELDS[top]], 'closed_cli_business_field'
    if uri.endswith('importTabDelimited'):
        if top not in TABLE_FIELDS:
            raise ValueError('Imports native table field lacks reviewed public mapping: ' + str(path))
        return [TABLE_FIELDS[top]], 'exact_table_business_field'
    if top in ('autoAddToSourceControl', 'autoCheckOutToSourceControl'):
        return [TABLE_FIELDS[top]], 'explicit_source_control_policy'
    if top == 'importOperation':
        return ['mode'], 'derived_create_reimport_or_explicit_replace'
    if top not in ('default', 'imports'):
        raise ValueError('Imports native row field lacks reviewed public mapping: ' + str(path))
    prefix = 'defaults.' if top == 'default' else ''
    field = next((token for token in path[1:] if token is not None), None)
    if field is None:
        return ['defaults'] if top == 'default' else [], 'row_defaults_precedence' if top == 'default' else 'ordered_business_declarations'
    if field == '*':
        return [prefix + 'field_values'], 'live_metadata_bound_property_reference'
    if field in ('objectPath', 'objectType', 'importLocation'):
        return [], 'bound_existing_or_new_parent_kind_name_target'
    if field not in ROW_FIELDS:
        raise ValueError('Imports nested row field lacks reviewed public mapping: ' + str(path))
    fields = [prefix + ROW_FIELDS[field]]
    if field == 'switchAssignation':
        fields.append(prefix + 'switch_value')
    return fields, 'row_defaults_precedence' if prefix else 'closed_import_row_field'


def _validate_public(contract, fields, row, uri, path):
    declaration = contract.get('declaration')
    if declaration:
        exposed = set(declaration['required_fields']) | set(declaration['optional_fields'])
        for field in fields:
            if field not in exposed:
                raise ValueError('Imports public field/choice is not disclosed: ' + field)
        if row['kind'] == 'enum_value' and fields:
            choice = {'createNew': 'create', 'useExisting': 'reuse' if '.cli.' in uri else 'reimport',
                'replaceExisting': 'replace'}.get(row['value'], row['value'])
            schema = declaration.get('schema', {}).get('properties', {}).get(fields[0], {})
            form = declaration.get('input_forms', {}).get(fields[0], {})
            choices = schema.get('enum', form.get('choices'))
            if choices is not None and choice not in choices:
                raise ValueError('Imports public enum choice is not disclosed: ' + str(choice))
        return
    for field in fields:
        name = field.removeprefix('defaults.')
        if name == 'mode':
            if 'replace' not in contract['modes'] or 'all_new_rows' not in contract['mode_selection']:
                raise ValueError('Imports public mode choice is not disclosed')
        elif name in ('defaults', 'add_to_source_control', 'check_out_from_source_control'):
            if name not in contract['settings'] or (name == 'check_out_from_source_control'
                    and contract['version_features'].get(name) is not True):
                raise ValueError('Imports public setting is not disclosed: ' + name)
        elif name not in contract['declaration_fields']:
            raise ValueError('Imports public row field is not disclosed: ' + name)
        if field.startswith('defaults.') and 'defaults' not in contract['settings']:
            raise ValueError('Imports public defaults not disclosed')
    if not fields and path and path[-1] in ('objectPath', 'objectType', 'importLocation'):
        if not {'canonical_object_path', 'native_object_type', 'target_parent_handle'} <= set(contract['gateway_derivations']):
            raise ValueError('Imports public target derivation not disclosed')


def _encoding(uri, path, version):
    top, field = (path[0] if path else None), next((x for x in reversed(path) if x is not None), None)
    if field == 'audioFile':
        return 'exact available regular media_file path; hashed source proof and host-path binding; no fabricated file'
    if field == 'audioFileBase64':
        return 'inline_wav exact bounded canonical WAV artifact; Gateway owns filename/base64 validation and source evidence'
    if field in ('importLanguage', 'import-language'):
        return 'exact configured language; ordinary sound-sfx/music-track derive SFX; Source rows require explicit language; preserve other languages'
    if field in ('importLocation', 'objectPath', 'objectType'):
        return 'bound exact existing object or bound parent plus business kind and literal name; Gateway constructs hierarchy/type/importLocation; defaults target syntax replaced by each explicit declaration, no caller native path'
    if field == '*':
        return 'fresh scoped Field Handles select property/reference tokens and typed literal or bound target; row override deduplicates identical binding digests; no caller @Property grammar'
    if field == 'switchAssignation':
        return 'bound Switch/State group with optional exact child value; inherited current group supported; Gateway owns directives; Default Work Unit group descriptor boundary retained'
    if field == 'dialogueEvent':
        return 'new bound parent/name or exact existing Event handle; optional ordered group/value/wildcard conditions plus probability/weight; directives owned; old Container spelling guard retained'
    if field == 'event':
        return 'bound parent and exact event name plus disclosed Break/Pause/Play/Resume/Seek/Stop action; Gateway owns @action grammar'
    if field == 'originalsSubFolder':
        return 'safe relative originals_subfolder; ordinary native support retained; exact TSV OriginalsSubFolder column is 2023.1+ only'
    if field in ('notes', 'audioSourceNotes'):
        return 'exact string including empty; owner and Source fields remain distinct; omission leaves unspecified'
    if field == 'autoAddToSourceControl':
        return 'explicit add_to_source_control defaults false in all public lanes; native 2021/2022 false versus 2023+ true defaults deliberately overridden'
    if field == 'autoCheckOutToSourceControl':
        return 'explicit check_out_from_source_control boolean; public default false, native 2023+ true deliberately overridden; earlier lanes reject this choice'
    if field in ('importOperation', 'tab-delimited-operation'):
        return ('ordinary new/existing declaration derives createNew/useExisting; explicit replace requires exact replacement scope; table create/reimport/replace and CLI create/reuse/replace map exactly; omitted CLI mode retains native default')
    if top == 'default':
        return 'defaults fields merge before each row; row values override; equivalent scoped Field Handles deduplicated; target ownership remains per row'
    if top in ('quiet', 'verbose'):
        return 'verbosity quiet/verbose emits only selected true flag; normal/omitted emits neither'
    if top == 'no-source-control':
        return 'source_control disabled emits true; enabled/omitted omits flag; available 2023.1+ only'
    if top in ('custom-global-opening-cmd', 'custom-global-closing-cmd'):
        return 'prohibited external command hooks, no public escape'
    if top in ('importFile', 'tab-delimited-import-file'):
        return 'exact hashed UTF-8 TSV unchanged; header/cells mapped by version-aware parser, owned sources/GUIDs and declared location; exact unsafe Console build remains blocked'
    return 'closed typed declaration; ordering, explicit false/empty and omission retained; configuration, immutable Preview, one execution, drift and bounded result enforced'


def _return_projection(row, version, section, addresses):
    from wwise_waapi.object_query_outputs import available_query_outputs
    native = row.get('value') if section == 'optionsSchema' and row['kind'] == 'enum_value' else None
    outputs = available_query_outputs(version)
    names = sorted(name for name, (accessor, _) in outputs.items() if accessor == native) if native else []
    identity = native in ('id', 'name', 'type', 'path')
    if native is not None and not names and not identity:
        raise ValueError('Imports native return choice lacks exact closed public read mapping: ' + str(native))
    return {'native_choice': native, 'query_outputs': names,
        'automatic_identity': identity, 'mutation_option_input': False,
        'owned_import_projection': 'fixed identity/property/source fields selected by Gateway preparation and verifier',
        'other_reads': 'query-object exact returned GUID with --include closed output or live metadata-bound --include-field; versioned query contract, no import args/options',
        'native_accessors': 'metadata-bound property/reference accessors use exact fresh Field Handles; no caller return-expression grammar',
        'result_addresses': addresses if section == 'resultSchema' else [],
        'preservation': 'native objects/files/log retained when returned; unavailable fields are not synthesized and a valid result is not independent effect proof'}


def _mechanism(uri, section, paths):
    if '.cli.' in uri: return 'cli-table'
    if section == 'optionsSchema': return 'owned-return-options'
    if section == 'resultSchema':
        tops = {path[2] for path in paths if len(path) > 2 and path[0] == 'objects'}
        return 'object-result-' + ('identity' if tops & {'id', 'name', 'type', 'path', 'parent', 'owner', 'workunit'} else 'metadata') if tops else 'import-diagnostics'
    return 'exact-table' if uri.endswith('importTabDelimited') else 'ordinary-import'


def imports_bindings(root, inventory):
    root = Path(root)
    rows, routes = inventory['native_coverage']['obligations'], inventory['native_coverage']['routes']
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    if roster['entries'] != {r['id']: {'kind': r['kind'], 'shape_sha256': r['shape_sha256']} for r in rows}:
        raise ValueError('Imports native field/choice/version/definition differs from reviewed roster')
    public, native = {r['id']: r for r in inventory['routes']}, {r['id']: r for r in routes}
    if {r['route'] for r in rows} != set(native) or {r['public_route'] for r in routes} != set(public):
        raise ValueError('Imports native/public route roster differs')
    contracts = {r['public_route']: _contract(r) for r in routes}
    bindings = {}
    for row in rows:
        route = native[row['route']]; uri = route['uri']; section = row['pointer'].split('/')[1]
        contract = contracts[route['public_route']]; addresses = inventory['native_locations'][row['id']]
        choices = []
        for address in addresses:
            fields, rule = _input_fields(uri, address) if section == 'argsSchema' else ([],
                'gateway_owned_return_projection' if section == 'optionsSchema' else 'bounded_native_result')
            _validate_public(contract, fields, row, uri, address) if section == 'argsSchema' else None
            choices.append({'native_path': address, 'public_fields': fields, 'rule': rule,
                'encoding': _encoding(uri, address, route['version']) if section == 'argsSchema' else
                    'Gateway fixes exact identity/verification return projection; language/platform context belongs to bound objects and media; other result reads use closed query outputs, never caller native options' if section == 'optionsSchema' else
                    'bounded native objects/files/log or process result retained; schema acknowledgement alone never proves requested business effects'})
        correspondence = {'rule': choices[0]['rule'] if len({c['rule'] for c in choices}) == 1 else 'all_exact_reference_sites',
            'native_addresses': choices, 'public_fields': sorted({f for c in choices for f in c['public_fields']}),
            'contract_sha256': digest(contract), 'accepted_limits': ACCEPTED_LIMITS,
            'choice': {'kind': row['kind'], **({'value': row['value']} if 'value' in row else {})}}
        if any(p and p[0] == 'importOperation' for p in addresses): correspondence['mode_mapping'] = MODE_MAPPING
        if 'reference' in row: correspondence['reference'] = row['reference']
        if section != 'argsSchema':
            correspondence['return_projection'] = _return_projection(row, route['version'], section, addresses)
        cli = '.cli.' in uri; ordinary = uri.endswith('.import')
        construction = LIB + ('cli_console_business.py#materialize_cli_console_business_request' if cli else
            'audio_import_business.py#materialize_audio_import_business_request' if ordinary else
            'exact_artifact_business.py#materialize_exact_artifact_business_request')
        operation = uri if cli else 'audio.import' if ordinary else 'audio.importTabDelimited'
        bindings[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
            'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
            'input': {'gateway_argv': ['draft-start', operation],
                'declaration': 'draft-declare-import-batch' if ordinary else contract['declaration']['subcommand'],
                'selector': row['pointer'], 'correspondence': correspondence},
            'construction': {'source': construction, 'selector': row['pointer']},
            'validation': {'source': LIB + 'builders/schema.py#' + ('validate_semantic_result' if section == 'resultSchema' else 'validate_semantic_payload'), 'selector': row['pointer']},
            'verifier': {'source': LIB + 'operation_registry.py#verify_prepared_operation', 'selector': row['pointer']},
            'representative_mechanism': 'imports195-' + _mechanism(uri, section, addresses) + '-v1', 'evidence': {}}
    return bindings

SELECTED_TESTS = {
    'ordinary-import': [
        'tests/unit/test_audio_import_business_gateway.py::test_import_preview_preserves_independent_default_fields_and_row_overrides',
        'tests/unit/test_audio_import_business_gateway.py::test_mixed_replace_import_public_transaction_replaces_and_creates_exact_targets',
        'tests/unit/test_audio_import_named_sources.py::test_sdk_two_named_sources_share_one_sound_and_preserve_existing_owner'],
    'exact-table': [
        'tests/unit/test_tsv_source_lifecycle_gateway.py::test_exact_table_source_reuse_and_replacement_preserve_owner_and_unrelated_media',
        'tests/unit/test_localized_table_lifecycle_gateway.py::test_localized_owner_only_table_creates_voice_with_requested_fields'],
    'cli-table': [*['tests/unit/test_cli_console_business_adapter.py::test_every_cli_console_lane_materializes_one_schema_valid_request[ak.wwise.cli.tabDelimitedImport-' + v + ']' for v in ('2021.1','2022.1','2023.1','2024.1','2025.1')]],
    'owned-return-options': ['tests/unit/test_audio_import_business_gateway.py::test_exact_table_guid_cells_are_blocked_on_observed_2025_console_before_preview'],
    'object-result-identity': ['tests/unit/test_import_switch_assignment_gateway.py::test_import_assigns_new_owner_to_bound_switch_and_preserves_unrelated_pairs'],
    'object-result-metadata': ['tests/unit/test_import_dialogue_association_gateway.py::test_explicit_dialogue_conditions_bind_values_and_verify_requested_numeric_effects'],
    'import-diagnostics': ['tests/unit/test_audio_import_business_gateway.py::test_localized_existing_fields_do_not_verify_missing_requested_effects'],
}
RUNTIME_SOURCES = {GATEWAY, 'tests/support/gateway_config.py',
    *(node.split('::')[0] for nodes in SELECTED_TESTS.values() for node in nodes),
    *(LIB + name + '.py' for name in ('audio_import_business', 'audio_import_business_contracts',
        'exact_artifact_business', 'exact_artifact_business_contracts', 'operation_import',
        'cli_console_business', 'cli_console_business_contracts', 'business_adapters',
        'business_declaration_state', 'business_declarations', 'business_fields',
        'operation_registry', 'operation_drafts', 'operation_composer', 'transactions',
        'transaction_runtime', 'transaction_cleanup', 'dispatcher', 'config', 'capabilities',
        'execution_contracts', 'object_query_outputs', 'builders/schema', 'io_policy'))}


def imports_program_anchors(root, inventory, destination, run):
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
        raise ValueError('Imports selected code anchor is missing or unfinalized')
    if not {node for nodes in SELECTED_TESTS.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('Imports code anchor omits a selected representative mechanism')
    originals = {}
    for name in RUNTIME_SOURCES | RUNNER_SOURCES:
        raw = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        originals[name] = hashlib.sha256(raw).hexdigest()
        if name in RUNTIME_SOURCES and hashlib.sha256((root / name).read_bytes()).hexdigest() != originals[name]:
            raise ValueError('Imports relevant selected source changed: ' + name)
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
    for identity, binding in imports_bindings(root, inventory).items():
        selected.setdefault(binding['representative_mechanism'], (identity, binding))
    anchors = {}
    for number, (mechanism, (identity, binding)) in enumerate(sorted(selected.items()), 1):
        anchor = {'ordinary_test_run_attachment': True, 'relevant_sources': sorted(RUNTIME_SOURCES), 'evidence': {}}
        binding.update(anchor)
        group = mechanism.removeprefix('imports195-').removesuffix('-v1')
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': originals, 'skip_lines': [],
            'review': {'reason': 'Byte-identical relevant sources in an actual focused aggregate CODE run; no native/per-node observation inferred',
                'selection_reason': 'Accepted #182 representative closed construction and safety/weak-result controls; original native histories remain separate, not rerun per mapping leaf',
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


def export_imports_mapping(root, destination, *, inventory=None, anchors=None):
    """Use standard mapping attachments and bounded requirements parts only."""
    from tests.maintenance.branch_coverage_audit import write_requirements
    from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
    root, destination = Path(root).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    inventory = imports_component(root) if inventory is None else inventory
    bindings = imports_bindings(root, inventory)
    anchors = anchors or {}
    if set(anchors) - set(bindings):
        raise ValueError('Imports selected anchor is outside exact family')
    for identity, anchor in anchors.items():
        if (set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True or set(anchor['evidence']) != {'program'}):
            raise ValueError('Imports anchor requires original ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    groups = defaultdict(dict)
    for identity, binding in bindings.items():
        mechanism = binding['representative_mechanism']
        groups[mechanism][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'],
            'categories': ['program'], 'representative_mechanism': mechanism,
            'reason': 'Accepted #182 representative mapping/code policy; retained native proof and limits separately attributed; no new per-leaf/native credit'}
    for mechanism, members in groups.items():
        selected = sorted(set(members) & set(anchors))
        if len(selected) > 1:
            raise ValueError('Imports mechanism requires one selected ordinary anchor')
        sources = {binding[key]['source'].split('#')[0] for binding in members.values()
            for key in ('construction', 'validation', 'verifier')}
        sources.update({POLICY, *TICKETS, LIB + 'cli_console_business_contracts.py', LIB + 'audio_import_business_contracts.py',
            LIB + 'exact_artifact_business_contracts.py', LIB + 'operation_import.py'})
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact versioned #182 closed mapping and accepted verification limits; aggregate CODE mechanism only, no member native effect claim',
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

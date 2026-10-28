"""Exact #192 provider/history mapping with accepted compound scope.

Native field/choice discovery reads every pinned host/version and reachable
reference. Representative CODE stays separate from native effects and history.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import subprocess
from pathlib import Path
from tests.maintenance.branch_coverage_audit import digest, schema_branches
from tests.support.topic_completion_mapping import _path
LIB = 'skills/waapi-skill/wwise_waapi/'
GATEWAY = 'skills/waapi-skill/scripts/gateway.py'
BASE = 'tests/fixtures/branch-evidence/product/history-195-r1/'
POLICY = 'docs/plans/full-waapi-coverage/SPEC.md'
TICKETS = ['docs/plans/full-waapi-coverage/tickets/18-complete-source-control-and-compound-edit-history-workflows.md']
OWNERS = {'ak.wwise.core.' + name: 192 for name in (
    'sourceControl.add', 'sourceControl.checkOut', 'sourceControl.commit', 'sourceControl.delete',
    'sourceControl.getSourceFiles', 'sourceControl.getStatus', 'sourceControl.move',
    'sourceControl.revert', 'sourceControl.setProvider',
    'undo.beginGroup', 'undo.cancelGroup', 'undo.endGroup', 'undo.redo', 'undo.undo')}
ACCEPTED_LIMITS = {
    'authority': 'SPEC user-approved lightweight wrapper and compound scope stop, 2026-10-27',
    'provider': 'accepted private-profile component; provider identity, availability and effects remain native-unverified',
    'group': 'same-connection owned lifecycle only; advanced compound unions outside accepted scope; source-owned admitted families retained',
    'cancellation': 'acknowledgement is not rollback proof; exact partial execution, scoped observation and cleanup uncertainty retained; no retry',
    'history': 'latest native project entry; optional receipt is a scoped state expectation, never stack-entry selection; no stack-head or outside-scope preservation proof',
    'history_without_receipt': 'result-schema-only; no graph restoration claim or further optional observer requirement',
    'files': 'exact bounded path/object-file scopes, live roots, immutable preview, policy authorization, execution-time drift checks; no provider-effect proof',
}

def discover_history(root):
    """Expand reachable definitions; retain every host/version and reference site."""
    from wwise_waapi.native_catalog import load_native_catalog, NATIVE_HOSTS
    from wwise_waapi.schema_inventory import DefinitionGraph, resolve_schema_reference
    from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS
    root = Path(root)
    owners = json.loads((root / 'docs/branch-coverage-ownership.json').read_bytes())['routes']
    if {key.split('|', 1)[1]: value['owner_issue'] for key, value in owners.items()
            if value['owner_issue'] == 192} != OWNERS:
        raise ValueError('History exact #192 ownership roster changed')
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
                                raise ValueError('History reachable definition identity collision')
                            rows[identity] = row
                    visit(schema, '/' + section, schema, '<schema>', set(), [])
    return {'routes': routes, 'catalogs': catalogs, 'obligations': sorted(rows.values(), key=lambda r: r['id'])}, dict(locations)


def history_component(root):
    from tests.maintenance.branch_audit_completion import candidate_identity
    from tests.maintenance.branch_audit_mapping import debug_control_component
    root = Path(root)
    native, locations = discover_history(root)
    observed = {row['id']: {'kind': row['kind'], 'shape_sha256': row['shape_sha256']} for row in native['obligations']}
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    if roster != {'catalogs': native['catalogs'], 'entries': observed}:
        raise ValueError('History native field/choice/version/definition differs from reviewed roster')
    wanted = {route['public_route'] for route in native['routes']}
    public = [deepcopy(row) for row in json.loads((root / 'docs/branch-coverage-inventory.json').read_bytes())['routes']
        if row['id'] in wanted]
    if {row['id'] for row in public} != wanted:
        raise ValueError('History current public route/version missing')
    sources = debug_control_component(root)['sources']
    for name in [*TICKETS, POLICY, *SELECTED_TEST_DEPENDENCIES, 'tests/support/history_completion_mapping.py',
            'tests/support/topic_completion_mapping.py', 'tests/maintenance/map_history_completion.py',
            'tests/semantic/support/codex_archive_paths.py', BASE + 'source-roster.json', BASE + 'accepted-history.json']:
        sources[name] = digest((root / name).read_text(encoding='utf-8'))
    component = {'component': 'history-195-r1', 'routes': public, 'sources': sources,
        'native_locations': locations, 'native_coverage': native, 'accepted_limits': ACCEPTED_LIMITS}
    native['candidate_sha256'] = candidate_identity(root, component, native['catalogs'], digest=digest)
    return component


FIELDS = {
    'sourceControl.add': {'files': ['files', 'object_files']},
    'sourceControl.checkOut': {'files': ['files', 'object_files']},
    'sourceControl.commit': {'files': ['files', 'object_files'], 'message': ['commit_message']},
    'sourceControl.delete': {'files': ['files', 'object_files']},
    'sourceControl.getStatus': {'files': ['files', 'object_files']},
    'sourceControl.revert': {'files': ['files', 'object_files']},
    'sourceControl.move': {'files': ['moves', 'object_moves'], 'newFiles': ['moves', 'object_moves']},
    'sourceControl.setProvider': {name: ['provider_profile'] for name in
        ('provider', 'host', 'port', 'server', 'username', 'workspace', 'password')},
    'sourceControl.getSourceFiles': {'filter': ['usage_scope'], 'folder': ['originals_folder'], 'recursive': ['recursive'],
        'return': ['include_usage_objects'], 'objectReturn': ['usage_outputs', 'include_usage_objects']},
    'undo.beginGroup': {}, 'undo.cancelGroup': {'undo': ['failure_cancellation']},
    'undo.endGroup': {'displayName': ['display_name']}, 'undo.undo': {}, 'undo.redo': {},
}


def _contract(route):
    from wwise_waapi.source_control_business_contracts import source_control_business_contract_data
    from wwise_waapi.compound_undo_business_contracts import compound_undo_business_contract_data
    from wwise_waapi.core_business_contracts import core_business_contract_data
    uri, version = route['uri'], route['version']
    if '.sourceControl.' in uri:
        return source_control_business_contract_data(uri, version)
    if uri.endswith(('beginGroup', 'cancelGroup', 'endGroup')):
        return compound_undo_business_contract_data(version)
    return core_business_contract_data(uri, version)


def _mechanism(uri):
    if uri.endswith('setProvider'): return 'provider'
    if '.sourceControl.' in uri: return 'files'
    return 'group' if uri.endswith(('beginGroup', 'cancelGroup', 'endGroup')) else 'history'


def _correspondence(row, route, addresses, contract):
    from wwise_waapi.object_query_outputs import available_query_outputs
    uri, version, pointer = route['uri'], route['version'], row['pointer']
    name, section = uri.removeprefix('ak.wwise.core.'), pointer.split('/')[1]
    declaration = contract['declaration']
    fields, rule = [], 'closed_argument_envelope'
    if section == 'resultSchema':
        rule = 'protected_provider_acknowledgement' if name.endswith('setProvider') else 'bounded_native_result_preserved'
    elif section == 'optionsSchema' and name != 'sourceControl.getSourceFiles':
        rule = 'fixed_empty_options'
    else:
        for path in addresses:
            if not path or path == ['*']: continue
            top = path[0]
            if top not in FIELDS[name]: raise ValueError('History unreviewed native argument: ' + name + '/' + repr(path))
            fields.extend(FIELDS[name][top])
        fields = sorted(set(fields))
        exposed = set(declaration['required_fields']) | set(declaration.get('optional_fields', []))
        if set(fields) - exposed:
            raise ValueError('History mapped public field is not disclosed: ' + uri + ' ' + repr(fields))
        rule = 'closed_business_fields'
    if name in ('undo.beginGroup', 'undo.cancelGroup', 'undo.endGroup'):
        rule = 'owned_undo_group_lifecycle'
    if name in ('undo.undo', 'undo.redo'):
        rule = 'empty_native_history_envelope'
        fields = ['expectation_receipt', 'history_scope']
        if set(fields) - (set(declaration['required_fields']) | set(declaration.get('optional_fields', []))):
            raise ValueError('History basic and optional receipt fields must remain public')
    mapped = {'rule': rule, 'native_addresses': addresses, 'public_fields': fields,
        'public_contract_sha256': digest(contract), 'native_effect': 'not_claimed',
        'choice': {'kind': row['kind'], **({'value': row['value']} if 'value' in row else {})},
        'encoding': 'Gateway owns native envelopes, absolute path localization, aligned move arrays, private credentials and same-client group lifecycle',
        'result_boundary': 'bounded schema acknowledgement is not independent provider effect, rollback, graph restoration or outside-scope preservation proof',
        'accepted_limits_sha256': digest(ACCEPTED_LIMITS)}
    if 'reference' in row: mapped['reference'] = row['reference']
    if row['kind'] == 'enum_value': mapped['native_choice'] = row['value']
    if name == 'sourceControl.getSourceFiles' and section != 'resultSchema':
        mapped['source_file_defaults'] = {'usage_scope': 'all', 'recursive': True, 'originals_folder': 'omitted_native_Originals_root'}
        mapped['projection'] = 'file/folder/isUsed/isMissing always selected; usage is optional; canonical identity plus versioned business usage_outputs; 1..1000 max_results(default 100), truncated disclosed'
        expected = {key: {'result_field': value[0]} for key, value in available_query_outputs(version).items()}
        choices = declaration['usage_output_choices']
        if choices != expected:
            changed = sorted(key for key in expected if choices.get(key) != expected[key])
            raise ValueError('History missing public usage output: ' + repr(changed))
        if row['kind'] == 'enum_value' and section == 'argsSchema':
            if row['value'] not in {'all', 'used', 'unused'}: raise ValueError('History unreviewed usage scope')
            mapped['public_choices'] = [row['value']]
        if row['kind'] == 'enum_value' and section == 'optionsSchema' and any(path and path[0] == 'return' for path in addresses):
            if row['value'] not in {'file', 'folder', 'isUsed', 'isMissing', 'usage'}: raise ValueError('History unreviewed file output')
            mapped['public_choices'] = ['include_usage_objects'] if row['value'] == 'usage' else []
            mapped['normalization'] = 'fixed useful file fields retained; no business difference requires native return omission/empty/duplicates or scalar-vs-array syntax'
        if any(path and path[0] == 'objectReturn' for path in addresses):
            mapped['rule'] = ('prohibited_caller_native_accessor_expression'
                if '/definitions/returnExpression/items/anyOf/1' in pointer else 'closed_usage_output_projection')
            mapped['usage_output_mapping_sha256'] = digest(choices)
            if row['kind'] == 'enum_value':
                mapped['public_choices'] = sorted(key for key, value in choices.items() if value['result_field'] == row['value'])
                mapped['identity_always_included'] = row['value'] in {'id', 'name', 'type', 'path'}
                if not mapped['public_choices'] and not mapped['identity_always_included']:
                    raise ValueError('History native output has no public correspondence: ' + row['value'])
            mapped['projection_boundary'] = 'closed versioned business outputs, not caller-authored native return expressions, aliases or field tokens; unselected raw expression syntax remains prohibited'
    if name == 'sourceControl.setProvider' and section != 'resultSchema':
        profile = declaration['provider_profile']
        expected_fields = ['host', 'port', 'server', 'username', 'workspace']
        if profile['connection_fields'] != expected_fields:
            raise ValueError('History missing public private-profile connection field: ' + repr(expected_fields))
        if profile['selection_choices'] != ['disabled', 'provider'] or 'password_file' not in profile['profile_document']:
            raise ValueError('History missing public private-profile selection or password_file')
        mapped['provider_selection'] = {'disabled': '', 'provider': 'exact configured provider name'}
        mapped['profile_fields'] = {field: 'connection.' + field for field in expected_fields} | {'password': 'private password_file UTF-8 bytes', 'provider': 'selection/provider'}
        mapped['omission'] = 'optional connection fields and password stay omitted; server native default localhost not inferred as availability; disabled forbids connection and password'
        mapped['secret_boundary'] = 'human-owned private profile only; profile/credential content and native echoed text never persisted/disclosed; exact bounded schema/log-count category only'
    if name in ('undo.beginGroup', 'undo.cancelGroup', 'undo.endGroup'):
        choices = {'native-default': {}} if version in {'2021.1', '2022.1'} else {
            'native-default': {}, 'preserve-changes': {'undo': False}, 'undo-changes': {'undo': True}}
        if set(declaration['failure_cancellation']['choices']) != set(choices):
            raise ValueError('History missing public cancellation choice')
        mapped['cancellation_choices'] = choices
        mapped['cancellation_default'] = declaration['failure_cancellation']['default']
        mapped['lifecycle'] = 'one parent-owned immutable child snapshot; beginGroup {}; child calls; endGroup displayName=display_name; on inner failure same-client cancelGroup with selected args; no independent session-scoped route or nested compound child'
        mapped['accepted_composition_scope'] = 'source-owned supported families retained; existing-only List/field unions and other advanced unions excluded by accepted compound scope stop, not native absence'
    if name in ('undo.undo', 'undo.redo'):
        mapped['native_envelopes'] = {'args': {}, 'options': {}, 'result': {}}
        mapped['receipt_scope'] = 'optional scoped expectation from owned verified receipt; latest project history always selected; without receipt result_schema_only before authorization; existing observers retained'
    if section == 'argsSchema' and name.startswith('sourceControl.') and name not in ('sourceControl.getSourceFiles', 'sourceControl.setProvider'):
        mapped['file_scope'] = 'project/originals relative or exact-under-io_root locators; exact object filePath/originalFilePath and explicit Sound source/language binding; symlink/reparse/escape denied; 1..256 files and 64 object scopes'
        mapped['normalization'] = 'one file supplied as one-item native array; duplicates canonicalized; empty mutation file set has no business outcome'
        if name == 'sourceControl.move':
            mapped['move_alignment'] = 'moves source/destination pairs or object_moves closed rows; literal pairs then sorted labels; same ordered files/newFiles length; duplicates/intersections rejected; source exists and destination absent, rechecked'
        if name == 'sourceControl.commit': mapped['message'] = 'bounded exact nonempty commit_message to message, no trimming/rewrite; empty commit intent rejected'
        if name == 'sourceControl.getStatus': mapped['status_scope'] = 'read_only core-call alternative: one exact file per native read; native response retained with no inferred row/file association; shared deadline and total byte/row limits; incomplete never complete'
    return mapped


def history_bindings(root, inventory):
    root = Path(root)
    native = inventory['native_coverage']
    roster = json.loads((root / BASE / 'source-roster.json').read_bytes())
    if roster != {'catalogs': native['catalogs'], 'entries': {r['id']: {'kind': r['kind'], 'shape_sha256': r['shape_sha256']} for r in native['obligations']}}:
        raise ValueError('History native field/choice/version roster differs')
    public, routes = {r['id']: r for r in inventory['routes']}, {r['id']: r for r in native['routes']}
    if {r['route'] for r in native['obligations']} != set(routes) or {r['public_route'] for r in routes.values()} != set(public):
        raise ValueError('History native/public route roster differs')
    contracts = {r['public_route']: _contract(r) for r in routes.values()}
    bindings = {}
    for row in native['obligations']:
        route = routes[row['route']]; uri, section = route['uri'], row['pointer'].split('/')[1]
        group = _mechanism(uri); contract = contracts[route['public_route']]
        module, symbol = ('source_control_business', 'materialize_source_control_business_request') if group in {'files', 'provider'} else (
            ('compound_undo_business', 'materialize_compound_undo_business_request') if group == 'group' else ('core_business', 'materialize_core_business_request'))
        bindings[row['id']] = {'branch_id': row['id'], 'native_shape_sha256': row['shape_sha256'],
            'public_route': route['public_route'], 'public_route_sha256': digest(public[route['public_route']]),
            'input': {'gateway_argv': contract['start']['gateway_argv'], 'declaration': contract['declaration'].get('subcommand'),
                'selector': row['pointer'], 'correspondence': _correspondence(row, route, inventory['native_locations'][row['id']], contract)},
            'construction': {'source': LIB + module + '.py#' + symbol, 'selector': row['pointer']},
            'validation': {'source': LIB + 'builders/schema.py#' + ('validate_semantic_result' if section == 'resultSchema' else 'validate_semantic_payload'), 'selector': row['pointer']},
            'verifier': {'source': LIB + 'operation_registry.py#verify_prepared_operation', 'selector': row['pointer']},
            'representative_mechanism': 'history195-' + group + '-v1', 'evidence': {}}
    return bindings


SELECTED_TESTS = {
    'files': [
        'tests/unit/test_remaining_core_business_gateway.py::test_source_file_usage_outputs_do_not_advertise_unpinned_source_control_route',
        'tests/unit/test_remaining_core_business_gateway.py::test_source_file_usage_outputs_are_disclosed_and_sealed_through_public_draft',
        'tests/unit/test_remaining_core_business_gateway.py::test_source_control_move_preserves_multiple_bound_rows_and_literal_pairs',
        'tests/unit/test_remaining_core_business_gateway.py::test_source_control_object_file_accessor_drift_stops_before_provider_write',
        'tests/unit/test_remaining_core_business_gateway.py::test_source_control_per_file_status_read_preserves_native_responses_under_read_only_policy'],
    'provider': [
        'tests/unit/test_remaining_core_business_gateway.py::test_source_control_provider_profile_preview_and_execution_never_persist_credentials_or_native_echo',
        'tests/unit/test_remaining_core_business_gateway.py::test_source_control_provider_disabled_intent_is_reviewable_and_has_no_connection_arguments',
        'tests/unit/test_remaining_core_business_gateway.py::test_source_control_provider_file_or_configuration_drift_cannot_reach_native_provider'],
    'group': [
        'tests/unit/test_compound_undo_business_gateway.py::test_public_compound_undo_snapshots_checked_business_children_into_one_preview',
        'tests/unit/test_compound_undo_business_gateway.py::test_compound_failure_cancellation_keeps_native_choices_and_observes_partial_state',
        'tests/unit/test_compound_undo_business_gateway.py::test_older_compound_native_default_is_observed_without_inventing_undo_option',
        'tests/unit/test_compound_undo_business_gateway.py::test_compound_cancellation_does_not_turn_acknowledgement_or_missing_reads_into_rollback'],
    'history': [
        'tests/unit/test_compound_undo_business_gateway.py::test_standalone_history_latest_gui_action_without_receipt_reports_only_result_schema',
        'tests/unit/test_compound_undo_business_gateway.py::test_standalone_history_without_expectation_still_requires_confirmation_and_valid_native_result',
        'tests/unit/test_compound_undo_business_gateway.py::test_standalone_history_ambiguous_native_failure_is_not_replayed_or_compensated'],
}
# These helpers execute the selected fake-client flows.  Keep the pytest
# configuration/report finalizer and the nonlive launcher's readiness check in
# the same reviewed closure; optional batch/live helpers are not invoked here.
SELECTED_TEST_DEPENDENCIES = {
    'tests/unit/test_operation_input_gateway.py',
    'tests/unit/test_object_graph_business_gateway.py',
    'tests/conftest.py', 'tests/support/exact_evidence_finalization.py',
    'pyproject.toml', 'ci/test_readiness.py',
}
# The ordinary aggregate has no call graph. Seal its finite tracked Python
# runtime through existing Git enumeration and original/current byte checks.
# Unrelated packaged code changes deliberately invalidate conservative reuse;
# generated files, caches and local environments never enter this roster.
PACKAGED_RUNTIME_SOURCES = {name for name in subprocess.check_output(
    ['git', 'ls-files', '--', 'skills/waapi-skill/scripts', 'skills/waapi-skill/wwise_waapi'],
    cwd=Path(__file__).resolve().parents[2], text=True).splitlines() if name.endswith('.py')}
RUNTIME_SOURCES = {GATEWAY, 'tests/support/gateway_config.py', *SELECTED_TEST_DEPENDENCIES,
    *(node.split('::')[0] for nodes in SELECTED_TESTS.values() for node in nodes),
    *(LIB + name + '.py' for name in ('source_control_business', 'source_control_business_contracts',
        'source_control_business_cli', 'source_control_profiles', 'source_control_windows_permissions',
        'source_control_protected_dispatch', 'source_control_status_read', 'source_control_object_files', 'source_control_object_moves',
        'compound_undo_business', 'compound_undo_business_contracts', 'compound_undo_observation',
        'edit_history_business', 'edit_history_contracts', 'core_business', 'core_business_contracts',
        'object_query_outputs', 'host_paths', 'filesystem_security', 'business_adapters', 'business_declaration_state',
        'business_declarations', 'business_fields', 'operation_registry', 'operation_drafts', 'operation_composer',
        'transactions', 'transaction_runtime', 'transaction_cleanup', 'dispatcher', 'config', 'capabilities',
        'execution_contracts', 'builders/schema', 'typed_requests', 'typed_operations', 'io_policy'))}

from tests.support.ordinary_test_run_evidence import RUNNER_SOURCES
RUNTIME_SOURCES.update(PACKAGED_RUNTIME_SOURCES | RUNNER_SOURCES)


def history_program_anchors(root, inventory, destination, run):
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
        raise ValueError('History selected code anchor is missing or unfinalized')
    if not {node for nodes in SELECTED_TESTS.values() for node in nodes} <= set(plan['argv'][6:]):
        raise ValueError('History code anchor omits a selected representative mechanism')
    original_runtime = {name for name in subprocess.check_output(
        ['git', 'ls-tree', '-r', '--name-only', plan['candidate'], '--',
            'skills/waapi-skill/scripts', 'skills/waapi-skill/wwise_waapi'],
        cwd=root, text=True).splitlines() if name.endswith('.py')}
    if original_runtime != PACKAGED_RUNTIME_SOURCES:
        raise ValueError('History packaged runtime source roster changed')
    originals = {}
    for name in RUNTIME_SOURCES | RUNNER_SOURCES:
        raw = subprocess.run(['git', 'show', plan['candidate'] + ':' + name], cwd=root,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        originals[name] = hashlib.sha256(raw).hexdigest()
        if name in RUNTIME_SOURCES and hashlib.sha256((root / name).read_bytes()).hexdigest() != originals[name]:
            raise ValueError('History relevant selected source changed: ' + name)
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
    for identity, binding in history_bindings(root, inventory).items():
        selected.setdefault(binding['representative_mechanism'], (identity, binding))
    anchors = {}
    for number, (mechanism, (identity, binding)) in enumerate(sorted(selected.items()), 1):
        anchor = {'ordinary_test_run_attachment': True, 'relevant_sources': sorted(RUNTIME_SOURCES), 'evidence': {}}
        binding.update(anchor)
        group = mechanism.removeprefix('history195-').removesuffix('-v1')
        proof = {'contract': 'waapi-skill.ordinary-test-run-attachment/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'original_candidate': plan['candidate'],
            'files': files, 'original_sources': originals, 'skip_lines': [],
            'review': {'reason': 'Byte-identical relevant sources in an actual focused aggregate CODE run; no native/per-node observation inferred',
                'selection_reason': 'Accepted #192 representative closed construction and safety/weak-result controls; original native histories remain separate, not rerun per mapping leaf',
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


def export_history_mapping(root, destination, *, inventory=None, anchors=None):
    """Use standard mapping attachments and bounded requirements parts only."""
    from tests.maintenance.branch_coverage_audit import write_requirements
    from tests.semantic.support.codex_archive_paths import archive_relative_from_absolute
    root, destination = Path(root).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    inventory = history_component(root) if inventory is None else inventory
    bindings = history_bindings(root, inventory)
    anchors = anchors or {}
    if set(anchors) - set(bindings):
        raise ValueError('History selected anchor is outside exact family')
    for identity, anchor in anchors.items():
        if (set(anchor) != {'ordinary_test_run_attachment', 'relevant_sources', 'evidence'}
                or anchor['ordinary_test_run_attachment'] is not True or set(anchor['evidence']) != {'program'}):
            raise ValueError('History anchor requires original ordinary program evidence')
        bindings[identity].update(deepcopy(anchor))
    rows = {row['id']: row for row in inventory['native_coverage']['obligations']}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    groups = defaultdict(dict)
    for identity, binding in bindings.items():
        mechanism = binding['representative_mechanism']
        groups[mechanism][identity] = binding
        requirements['branches'][identity] = {'native_shape_sha256': rows[identity]['shape_sha256'],
            'categories': ['program'], 'representative_mechanism': mechanism,
            'reason': 'Accepted #192 representative mapping/code policy; retained native proof and limits separately attributed; no new per-leaf/native credit'}
    for mechanism, members in groups.items():
        selected = sorted(set(members) & set(anchors))
        if len(selected) > 1:
            raise ValueError('History mechanism requires one selected ordinary anchor')
        sources = {binding[key]['source'].split('#')[0] for binding in members.values()
            for key in ('construction', 'validation', 'verifier')}
        sources.update({POLICY, *TICKETS, LIB + 'core_business_contracts.py', LIB + 'source_control_business_contracts.py',
            LIB + 'compound_undo_business_contracts.py', LIB + 'edit_history_contracts.py'})
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'product',
            'candidate_sha256': inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Exact versioned #192 closed mapping and accepted verification limits; aggregate CODE mechanism only, no member native effect claim',
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

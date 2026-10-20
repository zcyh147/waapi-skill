"""Exact created-Topic scalar witnesses using the existing pytest finalizer.

Callbacks and sink records are observed independently. No agent_result is added;
no injected callback is native execution, or proof of native co-occurrence.
"""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support.created_topic_cases import URI, BUILDS, created_fields
from tests.support.metadata_read_branch_evidence import source_seals as metadata_source_seals
from tests.support.media_pool_branch_evidence import _git_candidate, _write

NODE = 'tests/unit/test_topic_monitoring_contracts.py::test_created_fixed_scalar_packets_preserve_ordered_public_stream'
DEFINITION = '/publishSchema/@definition/waapi_definitions.json/definitions/objectReturn/properties/'
COUNTS = {'2021.1': 79, '2022.1': 112, '2023.1': 116, '2024.1': 116, '2025.1': 136}


def source_seals():
    seals = metadata_source_seals()  # Preserve the existing broad runtime closure.
    for name in ('tests/support/created_topic_cases.py', 'tests/support/created_topic_branch_evidence.py',
                 'tests/unit/test_topic_monitoring_contracts.py', 'tests/unit/test_created_topic_branch_evidence.py',
                 'docs/branch-coverage-requirements.json'):
        seals[name] = hashlib.sha256((audit.ROOT / name).read_bytes()).hexdigest()
    return dict(sorted(seals.items()))


def selected_branches(inventory):
    rows = []
    for branch in inventory['native_coverage']['obligations']:
        route = branch['route'] or ''
        if '|wwise-console|' not in route or not route.endswith('|topic|' + URI):
            continue
        version = route.split('|')[0]
        field = branch['pointer'].removeprefix(DEFINITION).split('/')[0]
        if (branch['pointer'].startswith(DEFINITION) and field in created_fields(version)
                and branch['kind'] in ('schema', 'optional_presence', 'empty_string', 'boolean_value', 'enum_value')):
            rows.append(branch)
    if {version: sum(row['route'].startswith(version + '|') for row in rows) for version in BUILDS} != COUNTS:
        raise ValueError('Reviewed exact created Topic selection changed')
    return rows


def validate_packets(version, packets):
    from wwise_waapi.native_catalog import load_native_catalog
    catalog = load_native_catalog(version, 'wwise-console')
    branch = {'route': '|'.join((version, 'wwise-console', BUILDS[version], 'topic', URI)),
              'pointer': '/publishSchema', 'shape_sha256': audit.digest(catalog['schemas'][URI]['publishSchema'])}
    for packet in packets:
        completion.validate_native_alternative(audit.ROOT, branch, packet)


def stream_observation(code, terminal, client, records):
    return {'gateway': {'argv': list(client.argv), 'exit_code': code, 'payload': deepcopy(terminal)},
            'subscriptions': deepcopy(client.subscriptions), 'observations': {'callbacks': deepcopy(client.callbacks)},
            'info_calls': deepcopy(client.calls), 'stream_records': deepcopy(records),
            'lifecycle': {'unsubscribe_count': client.unsubscribed, 'disconnected': client.disconnected}}


def make_receipt(capture, reports, observed):
    """Shared materializer; controlled reader tests never publish product proof."""
    version = capture['version']
    group = capture['groups'][version]
    outcome = 'PASS' if all(reports.get(phase) == 'passed' for phase in ('setup', 'call', 'teardown')) else 'FAIL'
    record = {'candidate_sha256': capture['candidate_sha256'], 'scope_kind': capture.get('scope_kind', 'product'),
              'evidence_kind': 'injected_client_program', 'git_candidate': capture['git_candidate'],
              'relevant_sources': capture['relevant_sources'],
              'invocation': {'phase': 'final', 'outcome': outcome,
                             'node_outcomes': [{'nodeid': capture['nodeid'], 'outcome': outcome}]},
              **deepcopy(observed), 'branch_assertions': {}}
    bindings = {}
    for branch in group['branches']:
        field = branch['pointer'][len(DEFINITION):].split('/')[0]
        witness = None
        for index, callback in enumerate(record.get('observations', {}).get('callbacks', [])):
            parent = callback.get('event', {}).get('object')
            if not isinstance(parent, dict):
                continue
            absent = branch['kind'] == 'optional_presence' and branch.get('value') == 'absent'
            if absent != (field not in parent):
                continue
            pointer = f'/observations/callbacks/{index}/event/object/{field}'
            check = {'pointer': pointer, 'absent': True} if absent else {'pointer': pointer, 'equals': deepcopy(parent[field])}
            if completion.proves_alternative(check, branch):
                witness = index, check
                break
        if witness is None:
            continue  # Unobserved alternatives remain in the frozen residual list.
        index, check = witness
        public_pointer = f'/stream_records/{index + 1}/event/object/{field}'
        checks = [check, {**deepcopy(check), 'pointer': public_pointer}]
        checks.extend({'pointer': path, 'equals': deepcopy(completion.pointer_value(record, path))} for path in (
            f'/stream_records/{index + 1}/event', '/gateway/payload', '/subscriptions', '/lifecycle'))
        record['branch_assertions'][branch['id']] = {'native_shape_sha256': branch['shape_sha256'],
            'native_route': branch['route'], 'checks': checks}
        bindings[branch['id']] = {'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
            'public_route': group['public']['id'], 'public_route_sha256': audit.digest(group['public']),
            'input': {'gateway_argv': deepcopy(record['gateway']['argv']), 'selector': 'fixed_builtin_include_to_ordered_created_stream'},
            'construction': {'source': 'skills/waapi-skill/wwise_waapi/topic_business.py#materialize_topic_business_inputs', 'selector': branch['pointer']},
            'validation': {'source': 'skills/waapi-skill/scripts/gateway.py#validate_monitored_topic_event', 'selector': branch['pointer']},
            'verifier': {'source': 'skills/waapi-skill/scripts/gateway.py#dispatch_topic_stream', 'selector': branch['pointer']},
            'dispatch_pointer': f'/observations/callbacks/{index}', 'observation_pointer': check['pointer'],
            'reference_chain': [branch['route'] + '|/publishSchema/properties/object/$ref'],
            'gateway_observation_pointer': public_pointer, 'native_hosts': ['wwise-console'],
            'relevant_sources': list(capture['relevant_sources']), 'evidence': {}}
    return record, bindings


def prepare_capture(root):
    """Freeze only after source review; actual publication happens at teardown."""
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=audit.ROOT, text=True).strip():
        raise ValueError('Created Topic capture requires a clean committed source')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    inventory = audit.build_inventory()
    selected = selected_branches(inventory)
    policy = audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')
    for branch in selected:
        requirement = policy['branches'][branch['id']]
        if (requirement['native_shape_sha256'] != branch['shape_sha256']
                or requirement['categories'] != ['program', 'native'] or not requirement['reason']):
            raise ValueError('Reviewed created Topic requirement changed')
    with gzip.open(root / 'frozen-inventory.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump(inventory, stream, ensure_ascii=False, separators=(',', ':'))
    context = {'contract': 'waapi-skill.created-topic-program-context/v1', 'root': str(root.resolve()),
        'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'git_candidate': _git_candidate(),
        'relevant_sources': source_seals(), 'requirements': {row['id']: policy['branches'][row['id']] for row in selected},
        'groups': {version: {'branches': [row for row in selected if row['route'].startswith(version + '|')],
            'public': next(row for row in inventory['routes'] if row['id'] == version + '|topic|' + URI)} for version in BUILDS}}
    selected_ids = {row['id'] for row in selected}
    _write(root / 'planning-index.json', {'selected_branch_ids': sorted(selected_ids),
        'residual_branch_ids': sorted(row['id'] for row in inventory['native_coverage']['obligations'] if row['id'] not in selected_ids),
        'mapping_is_not_execution_credit': True})
    _write(root / 'context.json', context)
    return root / 'context.json'


def load_capture(path, nodeid, version):
    context = json.loads(Path(path).read_text())
    if (context.get('contract') != 'waapi-skill.created-topic-program-context/v1'
            or nodeid != NODE + '[' + version + ']' or context['git_candidate'] != _git_candidate()
            or context['relevant_sources'] != source_seals()):
        raise ValueError('Prepared created Topic node/source changed')
    return {**context, 'version': version, 'nodeid': nodeid}


def finish_capture(capture, reports, observed):
    unchanged = capture['git_candidate'] == _git_candidate() and capture['relevant_sources'] == source_seals()
    record, bindings = make_receipt(capture, reports if unchanged else {}, observed)
    root = Path(capture['root']) / capture['version']
    root.mkdir(parents=True, exist_ok=False)
    descriptor = _write(root / 'program.json', record)
    for binding in bindings.values():
        binding['evidence']['program'] = {**descriptor, 'nodeid': capture['nodeid']}
    _write(root / 'bindings.json', {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings})
    _write(root / 'requirements.json', {'contract': 'waapi-skill.branch-evidence-requirements/v1',
        'branches': {identity: capture['requirements'][identity] for identity in bindings}})
    _write(root / 'capture.json', {'outcome': record['invocation']['outcome'], 'phase_reports': reports,
        'source_unchanged': unchanged, 'observed_branch_ids': sorted(bindings),
        'selected_unobserved_branch_ids': sorted({row['id'] for row in capture['groups'][capture['version']]['branches']} - set(bindings)),
        'functional_coverage': 'program_only_native_missing', 'native_cooccurrence_proven': False})

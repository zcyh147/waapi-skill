"""Baseline-first strict reader controls; controlled receipts grant no product credit."""
from copy import deepcopy
import hashlib
import json

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.support import created_topic_branch_evidence as producer
from tests.support.created_topic_cases import URI, BUILDS, created_packets, created_fields
from tests.unit.test_topic_monitoring_contracts import run


@pytest.fixture(scope='module')
def inventory():
    return audit.load(audit.ROOT / 'docs/branch-coverage-inventory.json')


def observed_stream(tmp_path, version):
    packets = created_packets(version)
    producer.validate_packets(version, packets)
    facts = [token for field in created_fields(version) for token in ('--topic-option', 'include', field)]
    code, terminal, client, records = run(tmp_path, version, 'stream-topic', URI, packets, *facts,
        timeout_seconds=1.0, event_count=4, pinned_build=BUILDS[version])
    assert code == 0, terminal
    return producer.stream_observation(code, terminal, client, records)


def receipt(inventory, version, observed):
    selected = producer.selected_branches(inventory)
    capture = {'version': version, 'scope_kind': 'controlled', 'candidate_sha256': 'c' * 64,
        'git_candidate': 'controlled-reader-only', 'relevant_sources': {}, 'nodeid': producer.NODE + '[' + version + ']',
        'groups': {version: {'branches': [row for row in selected if row['route'].startswith(version + '|')],
            'public': next(row for row in inventory['routes'] if row['id'] == version + '|topic|' + URI)}}}
    record, bindings = producer.make_receipt(capture, dict.fromkeys(('setup', 'call', 'teardown'), 'passed'), observed)
    return capture, record, bindings


def read(tmp_path, record, binding, branch, edges):
    path = tmp_path / 'control.json'
    path.write_text(json.dumps(record), encoding='utf-8')
    descriptor = {'artifact': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  'nodeid': record['invocation']['node_outcomes'][0]['nodeid']}
    return completion.evidence_result(descriptor, branch, 'c' * 64, 'program', 'controlled',
        tmp_path, binding, source_root=audit.ROOT, reference_edges=edges)


@pytest.mark.parametrize('version', BUILDS)
def test_exact_created_scalar_receipts_start_from_actual_public_stream(inventory, tmp_path, version):
    capture, record, bindings = receipt(inventory, version, observed_stream(tmp_path, version))
    edges = {row['id']: row for row in inventory['native_coverage']['obligations'] if row['kind'] == 'reference'}
    assert len(bindings) == producer.COUNTS[version]
    for branch in capture['groups'][version]['branches']:
        assert read(tmp_path, record, bindings[branch['id']], branch, edges) == ('passed', None), branch['id']


@pytest.mark.parametrize('damage', ('callback-index', 'sibling', 'reference-chain', 'absent-missing-parent',
    'absent-null-parent', 'absent-null-leaf', 'false-is-zero', 'options-borrowing', 'args-borrowing',
    'missing-final-cleanup', 'missing-lifecycle-cleanup', 'missing-whole-event', 'wrong-subscribe-options',
    'wrong-argv', 'out-of-order', 'unresolved-validation', 'failed-teardown', 'product-credit'))
def test_created_topic_reader_rejects_corruption_from_valid_baseline(inventory, tmp_path, damage):
    capture, record, bindings = receipt(inventory, '2025.1', observed_stream(tmp_path, '2025.1'))
    branches = capture['groups']['2025.1']['branches']
    suffix = '/name/@presence/absent' if damage.startswith('absent-') or damage == 'missing-whole-event' else '/isPlayable/@boolean/false'
    branch = deepcopy(next(row for row in branches if row['pointer'].endswith(suffix)))
    binding = deepcopy(bindings[branch['id']])
    edges = {row['id']: row for row in inventory['native_coverage']['obligations'] if row['kind'] == 'reference'}
    assert read(tmp_path, record, binding, branch, edges) == ('passed', None)
    checks = record['branch_assertions'][branch['id']]['checks']
    index = int(binding['dispatch_pointer'].rsplit('/', 1)[1])
    if damage == 'callback-index':
        binding['gateway_observation_pointer'] = binding['gateway_observation_pointer'].replace(f'/{index + 1}/', f'/{index + 2}/')
    elif damage == 'sibling':
        binding['gateway_observation_pointer'] = binding['gateway_observation_pointer'].replace('/isPlayable', '/workunitIsDefault')
    elif damage == 'reference-chain':
        binding['reference_chain'] = [branch['route'] + '|/optionsSchema/properties/return/$ref']
    elif damage in ('absent-missing-parent', 'absent-null-parent'):
        for event in (record['observations']['callbacks'][index]['event'], record['stream_records'][index + 1]['event']):
            if damage == 'absent-missing-parent':
                del event['object']
            else:
                event['object'] = None
    elif damage == 'absent-null-leaf':
        record['observations']['callbacks'][index]['event']['object']['name'] = None
        record['stream_records'][index + 1]['event']['object']['name'] = None
    elif damage == 'false-is-zero':
        # Re-sign matching assertions as well: a numeric zero still cannot prove false.
        record['observations']['callbacks'][index]['event']['object']['isPlayable'] = 0
        record['stream_records'][index + 1]['event']['object']['isPlayable'] = 0
    elif damage in ('options-borrowing', 'args-borrowing'):
        branch['pointer'] = branch['pointer'].replace('/publishSchema/', '/optionsSchema/' if damage == 'options-borrowing' else '/argsSchema/')
    elif damage == 'missing-final-cleanup':
        del record['gateway']['payload']['cleanup']
    elif damage == 'missing-lifecycle-cleanup':
        record['lifecycle']['unsubscribe_count'] = 0
    elif damage == 'missing-whole-event':
        checks[:] = [check for check in checks if check['pointer'] != f'/stream_records/{index + 1}/event']
    elif damage == 'wrong-subscribe-options':
        record['subscriptions'][0]['options']['return'] = ['name']
    elif damage == 'wrong-argv':
        record['gateway']['argv'] = binding['input']['gateway_argv'] = ['stream-topic', URI]
    elif damage == 'out-of-order':
        record['stream_records'][1], record['stream_records'][2] = record['stream_records'][2], record['stream_records'][1]
    elif damage == 'unresolved-validation':
        record['stream_records'][index + 1]['event_validation']['unresolved_refs'] = ['unresolved']
    elif damage == 'failed-teardown':
        record['invocation']['outcome'] = 'FAIL'
    else:
        record['scope_kind'] = 'product'
    # Update equals checks to the damaged original values. These controls test
    # semantic/structural validation, not an unrelated old checksum assertion.
    if damage not in ('missing-whole-event',):
        for check in checks:
            if 'equals' in check:
                try:
                    check['equals'] = deepcopy(completion.pointer_value(record, check['pointer']))
                except (KeyError, IndexError):
                    pass
    result = read(tmp_path, record, binding, branch, edges)
    assert result[0] == 'missing', (damage, result)


def test_created_policy_selects_exact_559_console_leaves_and_retains_other_ids(inventory):
    selected = producer.selected_branches(inventory)
    assert len(selected) == 559
    policy = audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')
    selected_ids = {row['id'] for row in selected}
    for branch in selected:
        assert branch['owner_issue'] == 187
        requirement = policy['branches'][branch['id']]
        assert requirement['native_shape_sha256'] == branch['shape_sha256']
        assert requirement['categories'] == ['program', 'native']
        assert 'native' in requirement['reason'].lower()
    family = [row for row in inventory['native_coverage']['obligations'] if row['route']
              and row['route'].endswith('|topic|' + URI)]
    assert len(family) == 4902 and len(family) - len(selected) == 4343
    assert len(inventory['native_coverage']['obligations']) == 272313
    assert not any(row['id'] in selected_ids for row in family if '|wwise-authoring|' in row['route'])

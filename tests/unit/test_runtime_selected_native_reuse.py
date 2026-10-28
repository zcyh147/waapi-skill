"""Selected historical native facts stay separate from current CODE proof."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance import branch_audit_completion as completion
from tests.unit.test_runtime_log_branch_evidence import log_inventory

PREFIX = 'tests/fixtures/branch-evidence/product/runtime-remaining-195-r1/'
REVIEW = PREFIX + 'selected-native-source-successor.json'
METER = '2025.1|wwise-authoring|2025.1.7.9143|function|ak.wwise.core.profiler.getMeters'


def retained_input():
    packet = audit.ROOT / PREFIX / 'retained-meter-r137'
    requirements = json.loads((packet / 'requirements.json').read_bytes())
    imported, base, _ = audit.portable_binding_inputs(packet / 'index.json', requirements)
    binding = deepcopy(imported['bindings'][METER + '|/resultSchema'])
    prefix = packet.relative_to(audit.ROOT).as_posix()
    binding['evidence'] = {'native': {**binding['evidence']['native'],
        'artifact': prefix + '/' + binding['evidence']['native']['artifact']}}
    binding['qualified_runtime_read_attachment'] = {**binding['qualified_runtime_read_attachment'],
        'artifact': prefix + '/' + binding['qualified_runtime_read_attachment']['artifact']}
    binding['native_only_base'] = prefix
    binding['native_only_review'] = {'artifact': REVIEW,
        'sha256': hashlib.sha256((audit.ROOT / REVIEW).read_bytes()).hexdigest()}
    inventory = log_inventory(METER, pointers={'/resultSchema'})
    branch, = inventory['native_coverage']['obligations']
    return binding, branch


def test_selected_meter_native_remains_valid_without_fake_current_code():
    binding, branch = retained_input()
    result = completion.evidence_result(binding['evidence']['native'], branch, 'e' * 64,
        'native', 'product', audit.ROOT, binding=binding, source_root=audit.ROOT)
    assert result == ('passed', None), result
    assert 'program' not in binding['evidence']


@pytest.fixture
def native_output():
    parent = audit.ROOT / ".waapi-skill-state"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="selected-native-test-", dir=parent) as name:
        yield Path(name)


def test_partial_cpu_native_conversion_does_not_create_current_program(native_output):
    from tests.support import extra_runtime_read_evidence as extra
    route = '2024.1|wwise-authoring|2024.1.13.9056|function|ak.wwise.core.profiler.getCpuUsage'
    identity = route + '|/resultSchema'
    index = extra.write_bundle(native_output / 'native-only', [],
        inventory=log_inventory(route, pointers={'/resultSchema'}), retained_native=[identity])
    document = json.loads(index.read_bytes())
    assert document['qualified_runtime_read_attachments']
    assert document['entries']
    assert not any('program' in binding['evidence']
        for entry in document['entries']
        for binding in completion.read_sealed_artifact(entry['bindings'], audit.ROOT)['bindings'].values())


@pytest.fixture(scope='module')
def selected_native_inputs():
    from tests.support import runtime_observation_evidence as runtime
    review = runtime.selected_runtime_source_successor()
    routes = [identity.removesuffix('|/resultSchema') for identity in review['scope_ids']]
    inventory = log_inventory(routes, pointers={'/resultSchema'})
    branches = {branch['id']: branch for branch in inventory['native_coverage']['obligations']}
    bindings = {}
    prefixes = sorted({member['base'] for member in review['members'].values()})
    for prefix in prefixes:
        packet = audit.ROOT / prefix
        policies = json.loads((packet / 'requirements.json').read_bytes())
        imported, base, _ = audit.portable_binding_inputs(packet / 'index.json', policies)
        for identity, original in imported['bindings'].items():
            if identity not in review['members']:
                continue
            binding = deepcopy(original)
            if 'native_only_base' not in binding:
                binding['evidence'] = {'native': {**binding['evidence']['native'],
                    'artifact': prefix + '/' + binding['evidence']['native']['artifact']}}
                binding['qualified_runtime_read_attachment'] = {**binding['qualified_runtime_read_attachment'],
                    'artifact': prefix + '/' + binding['qualified_runtime_read_attachment']['artifact']}
                binding['native_only_base'] = prefix
                binding['native_only_review'] = {'artifact': REVIEW,
                    'sha256': hashlib.sha256((audit.ROOT / REVIEW).read_bytes()).hexdigest()}
            bindings[identity] = binding
    assert set(bindings) == set(review['scope_ids'])
    return inventory, branches, bindings, review


def native_result(binding, branch):
    return completion.evidence_result(binding['evidence']['native'], branch, 'e' * 64,
        'native', 'product', audit.ROOT, binding=binding, source_root=audit.ROOT)


def test_adopted_shared_native_converters_preserve_all_original_fact_boundaries(selected_native_inputs):
    inventory, branches, bindings, review = selected_native_inputs
    from tests.support.runtime_remaining_completion_mapping import runtime_gateway_argv
    for identity, binding in bindings.items():
        if binding['input'].get('native_observation_only'):
            assert binding['input']['gateway_argv'] == runtime_gateway_argv(branches[identity]['route'].split('|')[-1])
    failures = {identity: native_result(binding, branches[identity])
        for identity, binding in bindings.items()}
    assert set(failures.values()) == {('passed', None)}, {key: value for key, value in failures.items() if value != ('passed', None)}
    cpu = next(member for identity, member in review['members'].items()
        if '|wwise-authoring|' in identity and identity.endswith('getCpuUsage|/resultSchema'))
    assert cpu['facts']['original_finalization'] == 'BLOCKED'
    assert cpu['facts']['original_public_complete'] is False
    assert cpu['facts']['native_nonempty_rows'] == 34
    assert all('program' not in binding['evidence'] for binding in bindings.values())


@pytest.mark.parametrize('damage', ['identity', 'mapping', 'source-review', 'qualification-candidate',
    'partial-as-complete', 'capture', 'assessment', 'native-source'])
def test_selected_native_tampering_cannot_inherit_validity(selected_native_inputs, native_output, damage):
    _, branches, bindings, _ = selected_native_inputs
    identity = next(i for i in bindings if '|wwise-authoring|' in i and i.endswith('getCpuUsage|/resultSchema'))
    binding = deepcopy(bindings[identity]); branch = deepcopy(branches[identity])
    if damage == 'identity': branch['id'] = branch['id'].replace('wwise-authoring', 'wwise-console')
    elif damage == 'mapping': binding['input']['selector'] = '/native_call/args'
    elif damage == 'source-review': binding['native_only_review']['sha256'] = '0' * 64
    elif damage in {'qualification-candidate', 'partial-as-complete', 'native-source'}:
        record = completion.read_sealed_artifact(binding['evidence']['native'], audit.ROOT)
        if damage == 'qualification-candidate': record['candidate_sha256'] = '0' * 40
        elif damage == 'partial-as-complete': record['retained_facts']['original_public_complete'] = True
        else: record['relevant_sources']['skills/waapi-skill/scripts/run.py'] = '0' * 64
        path = native_output / 'tampered-qualified.json'
        path.write_text(json.dumps(record))
        binding['evidence']['native'] = {'artifact': path.relative_to(audit.ROOT).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    elif damage == 'assessment': binding['qualified_runtime_read_attachment']['sha256'] = '0' * 64
    else:
        # A capture tamper changes an exact protected member descriptor.
        member = json.loads((audit.ROOT / REVIEW).read_bytes())['members'][identity]
        capture_path = audit.ROOT / member['capture']['artifact']
        original = capture_path.read_bytes()
        try:
            capture_path.write_bytes(original + b' ')
            assert native_result(binding, branch)[0] == 'missing'
        finally:
            capture_path.write_bytes(original)
        return
    assert native_result(binding, branch)[0] == 'missing'


def test_missing_current_code_leaves_requirement_incomplete_and_native_fact_intact(selected_native_inputs):
    inventory, branches, bindings, _ = selected_native_inputs
    identity = next(i for i in bindings if '|wwise-authoring|' in i and i.endswith('getCpuUsage|/resultSchema'))
    binding = bindings[identity]
    one = deepcopy(inventory)
    one['native_coverage']['obligations'] = [branches[identity]]
    from tests.support import runtime_remaining_evidence as remaining
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1',
        'branches': {identity: remaining.policy(remaining.exact_entry(branches[identity]))}}
    result = completion.evaluate_coverage(audit.ROOT, one,
        {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {identity: binding}},
        digest=audit.digest, evidence_base=audit.ROOT, requirements_document=requirements)
    row, = result['obligations']
    assert row['evidence_results']['native']['outcome'] == 'passed'
    assert row['evidence_results']['program']['outcome'] == 'missing'
    assert row['state'] != 'verified'


def test_scoped_native_reuse_does_not_relax_legacy_source_or_cache_guards(selected_native_inputs):
    from tests.support import runtime_observation_evidence as runtime
    from tests.support import runtime_cursor_evidence as cursor
    old = audit.ROOT / runtime.RUNTIME_SOURCE_SUCCESSOR
    assert hashlib.sha256(old.read_bytes()).hexdigest() == 'da83fa524df905daf8b3ced0b83269777f085d7bb4d23f54b05f34a055cc7381'
    # Existing legacy300 review is independently stale at this combined package.
    with pytest.raises(ValueError, match='exact current source'):
        runtime.runtime_source_successor()
    route = '2024.1|wwise-authoring|2024.1.13.9056|function|ak.wwise.core.profiler.getCursorTime'
    with pytest.raises(ValueError, match='source delta'):
        cursor.original_cursor(route)

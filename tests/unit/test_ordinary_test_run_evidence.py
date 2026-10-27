"""Ordinary report-format admission controls; never execute the fixture tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.maintenance import branch_audit_completion as completion
from tests.maintenance.branch_coverage_audit import digest
from tests.support.ordinary_test_run_evidence import CONTRACT, OUTCOME, RUNNER_SOURCES


def sealed(path):
    return {'artifact': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return sealed(path)


@pytest.fixture
def ordinary_run(tmp_path):
    """A local Git/source context and controlled original report-format fixture."""
    root = tmp_path / 'source';root.mkdir()
    code = 'skills/waapi-skill/wwise_waapi/example.py'
    test = 'tests/unit/test_code.py'
    selected = test + '::test_selected_mechanism'
    sources = {name: '# Controlled historical runner source, never executed\n' for name in RUNNER_SOURCES}
    sources.update({code: 'def build(): pass\ndef validate(): pass\ndef verify(): pass\n',
        test: 'def test_selected_mechanism(): pass\ndef test_unselected(): pass\n',
        'ci/program-test-nodes.txt': selected + '\ntests/unit/test_windows.py\ntests/unit/test_junction.py\n',
        'tests/unit/test_windows.py': '@pytest.mark.skipif(True, reason="native Windows shell proof")\ndef test_shell(): pass\n@pytest.mark.skipif(True, reason="native Python runner locator")\ndef test_locator(): pass\n',
        'tests/unit/test_junction.py': '@pytest.mark.skipif(True, reason="NTFS junction behavior requires Windows")\ndef test_junction(): pass\n'})
    for name, text in sources.items():
        path = root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_text(text)
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE, text=True).strip()
    git('init', '-q');git('add', '.')
    git('-c', 'user.name=Reader Fixture', '-c', 'user.email=reader@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Controlled source fixture only')
    original = git('rev-parse', 'HEAD')
    fixture = Path(__file__).parents[1] / 'fixtures/branch-evidence/ordinary-test-run-format.json'
    run = json.loads(fixture.read_text().replace('CONTROLLED_GIT_CANDIDATE', original))
    run['result'] = {**run['plan'], **run['result']}
    original_hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sources.items()}
    route = '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.ping'
    public = '2025.1|function|ak.wwise.core.ping'
    branches = [{'id': route + '|/resultSchema/' + name, 'route': route, 'pointer': '/resultSchema/' + name,
        'shape_sha256': digest(name), 'kind': 'schema', 'owner_issue': 193} for name in ('selected', 'sibling')]
    inventory = {'routes': [{'id': public}], 'native_coverage': {'candidate_sha256': 'a' * 64,
        'catalogs': {}, 'routes': [{'id': route, 'host': 'wwise-console', 'uri': 'ak.wwise.core.ping', 'public_route': public}],
        'obligations': branches}}
    bindings = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {}}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}, 'representative_mechanisms': {}}
    for branch in branches:
        binding = {'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
            'public_route': public, 'public_route_sha256': digest(inventory['routes'][0]),
            'input': {'gateway_argv': ['controlled-not-executed'], 'selector': branch['pointer']},
            **{key: {'source': code + '#' + symbol, 'selector': branch['pointer']}
               for key, symbol in (('construction', 'build'), ('validation', 'validate'), ('verifier', 'verify'))},
            'representative_mechanism': 'controlled', 'evidence': {}}
        bindings['bindings'][branch['id']] = binding
        requirements['branches'][branch['id']] = {'native_shape_sha256': branch['shape_sha256'],
            'categories': ['program'], 'reason': 'Controlled reader/mechanism format test', 'representative_mechanism': 'controlled'}
    binding = bindings['bindings'][branches[0]['id']]
    binding.update(ordinary_test_run_attachment=True, relevant_sources=[code, test])
    attachment = {'contract': CONTRACT, 'scope_kind': 'controlled', 'candidate_sha256': 'a' * 64,
        'original_candidate': original, 'files': {}, 'original_sources': original_hashes,
        'review': {'reason': 'Controlled aggregate evidence admission, no original node outcomes.',
            'selection_reason': 'Pinned original runner/manifest supplies the selected test without filters.',
            'skip_attribution': {line: {'collected_test': node,
                'reviewed_reason': 'Original direct test marker and collection are unrelated to the selected mechanism.'}
                for line, node in zip((line for line in run['log'].splitlines() if line.startswith('SKIPPED ')),
                    ('tests/unit/test_windows.py::test_shell', 'tests/unit/test_windows.py::test_locator',
                     'tests/unit/test_junction.py::test_junction'))},
            'sources': {name: {'original_sha256': original_hashes[name], 'current_sha256': original_hashes[name],
                              'reviewed_reason': 'Identical relevant source bytes.'} for name in (code, test)}},
        'mechanism': {'branch_id': branches[0]['id'], 'native_route': route,
            'native_shape_sha256': branches[0]['shape_sha256'],
            'binding_semantics_sha256': digest(completion.binding_semantics(binding)), 'selected_tests': [selected]},
        'skip_lines': [line for line in run['log'].splitlines() if line.startswith('SKIPPED ')]}
    scope = {'contract': 'waapi-skill.controlled-branch-scope/v1', 'credit': 'controlled_program_only',
        'id': 'ordinary-report-reader-control', 'requirements': ['program'], 'native_catalogs': {},
        'route_ids': [route], 'obligation_ids': [branch['id'] for branch in branches]}
    context = {'root': root, 'base': tmp_path, 'run': run, 'attachment': attachment, 'binding': binding,
        'branch': branches[0], 'inventory': inventory, 'bindings': bindings, 'requirements': requirements, 'scope': scope}
    reseal(context)
    return context


def reseal(context):
    run, attachment, base = context['run'], context['attachment'], context['base']
    log_hash = hashlib.sha256(run['log'].encode()).hexdigest()
    run['result']['log_sha256'] = run['summary']['log_sha256'] = log_hash
    for name in ('plan', 'result', 'summary', 'log', 'exit'):
        path = base / ('run.' + name + ('.json' if name in ('plan', 'result', 'summary') else ''))
        if name in ('log', 'exit'):
            path.write_text(run[name]);attachment['files'][name] = sealed(path)
        else:
            attachment['files'][name] = write_json(path, run[name])
    context['descriptor'] = write_json(base / 'attachment.json', attachment)
    context['binding']['evidence']['program'] = context['descriptor']


def read(context, category='program'):
    return completion.evidence_result(context['descriptor'], context['branch'], 'a' * 64, category,
        'controlled', context['base'], context['binding'], source_root=context['root'])


def representative_review(context):
    bindings, requirements, inventory = (context[name] for name in ('bindings', 'requirements', 'inventory'))
    source = context['binding']['construction']['source'].split('#')[0]
    requirements['representative_mechanisms']['controlled'] = {
        'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'controlled',
        'candidate_sha256': 'a' * 64, 'reviewed_reason': 'Controlled source-backed identity rule; no sibling execution claim.',
        'sources': {source: hashlib.sha256((context['root'] / source).read_bytes()).hexdigest()},
        'members': {branch['id']: {'native_route': branch['route'], 'native_shape_sha256': branch['shape_sha256'],
            'mapping_sha256': digest({key: value for key, value in bindings['bindings'][branch['id']].items() if key != 'evidence'})}
            for branch in inventory['native_coverage']['obligations']},
        'selected_proofs': {'program': [context['branch']['id']]}}


def test_ordinary_run_reader_to_existing_completion_and_selected_mechanism(ordinary_run):
    context = ordinary_run
    assert read(context) == (OUTCOME, None)
    representative_review(context)
    ledger = completion.evaluate_coverage(context['root'], context['inventory'], context['bindings'], digest=digest,
        scope=context['scope'], evidence_base=context['base'], requirements_document=context['requirements'])
    direct, sibling = ledger['obligations']
    assert ledger['completion']['complete'] is True and ledger['scope_kind'] == 'controlled'
    proof = direct['evidence_results']['program']
    assert proof['outcome'] == OUTCOME and proof['proof_strength'] == OUTCOME
    assert proof['per_node_outcomes'] == proof['gateway_observations'] == proof['direct_member_execution'] == 'not_recorded'
    assert proof['native_effect'] == 'not_observed'
    assert sibling['state'] == 'mapped_with_representative_proof'
    assert sibling['evidence_results']['program']['outcome'] == 'reviewed_representative_mechanism'
    assert sibling['representative_proof']['direct_member_execution'] == 'not_observed'
    assert all('native' not in row['evidence_results'] for row in ledger['obligations'])
    assert 'node_outcomes' not in context['attachment'] and 'gateway' not in context['attachment']


def test_debug_control_mapping_producer_covers_exact_finite_shapes_without_execution():
    from tests.maintenance.branch_audit_mapping import debug_control_component, debug_control_bindings
    from tests.maintenance.branch_coverage_audit import ROOT
    inventory = debug_control_component(ROOT)
    bindings = debug_control_bindings(inventory)
    assert len(inventory['routes']) == 23
    assert len(inventory['native_coverage']['routes']) == 46
    assert len(bindings) == len(inventory['native_coverage']['obligations']) == 454
    booleans = [binding for key, binding in bindings.items() if '/@boolean/' in key]
    assert len(booleans) == 40
    assert {binding['input']['correspondence']['value'] for binding in booleans} == {False, True}
    assert all(binding['input']['correspondence']['rule'] == 'boolean_identity' for binding in booleans)
    assert all(binding['input']['correspondence']['fields'] == {'enable': 'debug_intent.enabled'} for binding in booleans)
    assert all(binding['evidence'] == {} for binding in bindings.values())


def test_debug_result_mapping_distinguishes_terminal_boundary_from_mode_validation():
    from tests.maintenance.branch_audit_mapping import debug_control_component, debug_control_bindings
    from tests.maintenance.branch_coverage_audit import ROOT
    bindings = debug_control_bindings(debug_control_component(ROOT))
    terminal = [binding for key, binding in bindings.items() if '|/resultSchema' in key
                and any(uri in key for uri in ('.restartWaapiServers|', '.testAssert|', '.testCrash|'))]
    mode = [binding for key, binding in bindings.items() if '|/resultSchema' in key
            and any(uri in key for uri in ('.enableAsserts|', '.enableAutomationMode|'))]
    assert len(terminal) == 78 and len(mode) == 60
    assert all(binding['validation']['source'] ==
               'skills/waapi-skill/scripts/gateway.py#dispatch_host_control_transaction' for binding in terminal)
    assert all(binding['input']['correspondence']['rule'] ==
               'terminal_acknowledgement_or_indeterminate_without_result_validation' for binding in terminal)
    assert all(binding['validation']['source'] ==
               'skills/waapi-skill/wwise_waapi/builders/schema.py#validate_semantic_result' for binding in mode)


@pytest.mark.parametrize('missing', ['boolean', 'version', 'route'])
def test_debug_mapping_producer_rejects_missing_legal_choice_version_or_route(missing):
    from tests.maintenance.branch_audit_mapping import debug_control_component, debug_control_bindings
    from tests.maintenance.branch_coverage_audit import ROOT
    inventory = debug_control_component(ROOT)
    native = inventory['native_coverage']
    if missing == 'boolean':
        removed = next(row for row in native['obligations'] if row['pointer'].endswith('/@boolean/false'))
        native['obligations'].remove(removed)
    else:
        ids = {row['id'] for row in native['routes'] if row['version'] == '2021.1'} if missing == 'version' else {native['routes'][0]['id']}
        native['routes'] = [row for row in native['routes'] if row['id'] not in ids]
        native['obligations'] = [row for row in native['obligations'] if row['route'] not in ids]
    with pytest.raises(ValueError, match='Debug.*(roster|field|choice)'):
        debug_control_bindings(inventory)


def test_aggregate_selected_mechanism_cannot_complete_without_original_proof(ordinary_run):
    context = ordinary_run
    representative_review(context)
    context['binding']['evidence'] = {}
    ledger = completion.evaluate_coverage(context['root'], context['inventory'], context['bindings'], digest=digest,
        scope=context['scope'], evidence_base=context['base'], requirements_document=context['requirements'])
    assert ledger['completion']['complete'] is False
    assert all(row['state'] == 'implemented_unverified' for row in ledger['obligations'])


@pytest.mark.parametrize('damage', ['tampered-log', 'log-count', 'wrong-original-candidate', 'wrong-current-candidate',
    'original-source', 'current-source', 'unselected-test', 'affected-skip', 'skip-report', 'skip-source',
    'failed', 'partial', 'candidate-drift', 'unsealed', 'relabel-node-pass', 'relabel-gateway', 'scope', 'filtered'])
def test_ordinary_run_corruption_fails_closed(ordinary_run, damage):
    context = ordinary_run;run = context['run'];record = context['attachment']
    if damage == 'tampered-log':
        Path(record['files']['log']['artifact']).write_text(run['log'] + 'tampered\n')
    elif damage == 'log-count': run['log'] = run['log'].replace('2 passed', '9 passed')
    elif damage == 'wrong-original-candidate': record['original_candidate'] = 'b' * 40
    elif damage == 'wrong-current-candidate': record['candidate_sha256'] = 'b' * 64
    elif damage == 'original-source': record['original_sources']['ci/run_program_tests.py'] = 'b' * 64
    elif damage == 'current-source':
        path = context['root'] / 'skills/waapi-skill/wwise_waapi/example.py';path.write_text(path.read_text() + '# changed\n')
    elif damage == 'unselected-test': record['mechanism']['selected_tests'] = ['tests/unit/test_code.py::test_unselected']
    elif damage == 'affected-skip': record['mechanism']['selected_tests'] = ['tests/unit/test_windows.py::test_shell']
    elif damage == 'skip-report': record['skip_lines'] = []
    elif damage == 'skip-source':
        run['log'] = run['log'].replace('test_windows.py:1:', 'test_windows.py:99:')
        record['skip_lines'] = [line for line in run['log'].splitlines() if line.startswith('SKIPPED ')]
    elif damage == 'failed': run['result']['exit_code'] = 1
    elif damage == 'partial': run['log'] = run['log'].rsplit('2 passed', 1)[0]
    elif damage == 'candidate-drift': run['result']['head_after'] = 'b' * 40
    elif damage == 'unsealed': record['files']['result'].pop('sha256')
    elif damage == 'relabel-node-pass': record['node_outcomes'] = [{'nodeid': 'invented', 'outcome': 'PASS'}]
    elif damage == 'relabel-gateway': record['gateway'] = {'ok': True}
    elif damage == 'scope': record['scope_kind'] = 'product'
    elif damage == 'filtered': run['plan']['argv'].extend(['-k', 'different']);run['result']['argv'] = run['plan']['argv'][:]
    if damage not in ('tampered-log', 'unsealed'):
        reseal(context)
    else:
        context['descriptor'] = write_json(context['base'] / 'attachment.json', record)
    outcome, reason = read(context)
    assert outcome == 'missing' and reason


@pytest.mark.parametrize('category', ['native', 'live_metadata', 'fresh', 'native_absence'])
def test_ordinary_run_never_grants_other_evidence_categories(ordinary_run, category):
    assert read(ordinary_run, category)[0] == 'missing'


def test_ordinary_run_does_not_enable_recursive_selected_representative_proof(ordinary_run):
    context = ordinary_run;representative_review(context)
    ledger = deepcopy(context['inventory']['native_coverage'])
    for branch in ledger['obligations']:
        branch.update(state='implemented_unverified', requirements=['program'],
            evidence_results={'program': {'outcome': 'reviewed_representative_mechanism', 'reason': 'another relation'}})
    completion.apply_representative_mechanisms(ledger, context['bindings']['bindings'], context['requirements'],
        context['root'], digest=digest, scope_kind='controlled')
    assert all('representative_proof' not in row for row in ledger['obligations'])


def test_ordinary_run_cannot_complete_a_missing_required_native_category(ordinary_run):
    context = ordinary_run
    context['requirements']['representative_mechanisms'] = {}
    for binding in context['bindings']['bindings'].values():
        binding.pop('representative_mechanism')
    for policy in context['requirements']['branches'].values():
        policy.pop('representative_mechanism');policy['categories'] = ['program', 'native']
    context['attachment']['mechanism']['binding_semantics_sha256'] = digest(completion.binding_semantics(context['binding']))
    reseal(context)
    ledger = completion.evaluate_coverage(context['root'], context['inventory'], context['bindings'], digest=digest,
        scope=context['scope'], evidence_base=context['base'], requirements_document=context['requirements'])
    assert ledger['completion']['complete'] is False
    direct = ledger['obligations'][0]
    assert direct['state'] == 'implemented_unverified'
    assert direct['evidence_results']['program']['outcome'] == OUTCOME
    assert direct['evidence_results']['native']['outcome'] == 'missing'


def test_ordinary_reader_bytes_participate_in_existing_candidate_identity(tmp_path):
    source_root = Path(__file__).parents[2]
    names = ('skills/waapi-skill/SKILL.md', 'tests/maintenance/branch_coverage_audit.py',
        'tests/maintenance/branch_audit_completion.py', 'docs/branch-coverage-ownership.json',
        'docs/branch-coverage-condition-sources.json', 'docs/branch-coverage-requirements.json',
        'tests/support/ordinary_test_run_evidence.py')
    for name in names:
        path = tmp_path / name;path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((source_root / name).read_bytes())
    before = completion.candidate_identity(tmp_path, {'sources': {}}, {}, digest=digest)
    helper = tmp_path / names[-1]
    helper.write_bytes(helper.read_bytes() + b'\n# Changed aggregate proof acceptance\n')
    assert completion.candidate_identity(tmp_path, {'sources': {}}, {}, digest=digest) != before


def test_cross_file_fixture_skip_cannot_certify_selected_mechanism(ordinary_run):
    context = ordinary_run;record = context['attachment'];root = context['root']
    selected_source = root / 'tests/unit/test_code.py'
    selected_source.write_text('from tests.unit.test_support import unavailable\n\ndef test_selected_mechanism(unavailable): pass\n')
    helper = root / 'tests/unit/test_support.py'
    helper.write_text('import pytest\n\n@pytest.fixture\ndef unavailable():\n    pytest.skip("dependency missing")\n')
    subprocess.check_call(['git', 'add', '.'], cwd=root)
    subprocess.check_call(['git', '-c', 'user.name=Reader Fixture', '-c', 'user.email=reader@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Cross-file fixture skip source control'], cwd=root)
    original = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    record['original_candidate'] = original
    for name in ('plan', 'result', 'summary'):
        context['run'][name]['candidate'] = original
    context['run']['result']['head_after'] = original
    record['original_sources']['tests/unit/test_support.py'] = hashlib.sha256(helper.read_bytes()).hexdigest()
    record['original_sources']['tests/unit/test_code.py'] = hashlib.sha256(selected_source.read_bytes()).hexdigest()
    source_review = record['review']['sources']['tests/unit/test_code.py']
    source_review['original_sha256'] = source_review['current_sha256'] = record['original_sources']['tests/unit/test_code.py']
    context['run']['log'] = context['run']['log'].replace(
        'tests/unit/test_windows.py:1: native Windows shell proof', 'tests/unit/test_support.py:5: dependency missing')
    record['skip_lines'] = [line for line in context['run']['log'].splitlines() if line.startswith('SKIPPED ')]
    attributions = record['review']['skip_attribution']
    original_line = next(line for line in attributions if ':1: native Windows shell proof' in line)
    attributions.pop(original_line)
    attributions['SKIPPED [1] tests/unit/test_support.py:5: dependency missing'] = {
        'collected_test': 'tests/unit/test_code.py::test_selected_mechanism',
        'reviewed_reason': 'The reported fixture is consumed by the selected mechanism.'}
    reseal(context)
    outcome, reason = read(context)
    assert outcome == 'missing' and 'skip' in reason


@pytest.mark.parametrize('damage', ['missing-review', 'empty-review', 'wrong-consumer', 'multiple-consumers', 'malformed-marker'])
def test_direct_skip_requires_reviewed_original_consumer_linkage(ordinary_run, damage):
    context = ordinary_run;record = context['attachment']
    row = record['skip_lines'][0]
    attributions = record['review']['skip_attribution']
    if damage == 'missing-review': attributions.pop(row)
    elif damage == 'empty-review': attributions[row]['reviewed_reason'] = ''
    elif damage == 'wrong-consumer': attributions[row]['collected_test'] = 'tests/unit/test_windows.py::test_locator'
    elif damage == 'multiple-consumers':
        context['run']['log'] = context['run']['log'].replace('SKIPPED [1] tests/unit/test_windows.py:1:',
            'SKIPPED [2] tests/unit/test_windows.py:1:').replace('3 skipped', '4 skipped')
        context['run']['summary']['skipped'] = 4
        changed_row = row.replace('SKIPPED [1]', 'SKIPPED [2]')
        attributions[changed_row] = attributions.pop(row)
        record['skip_lines'][0] = changed_row
    elif damage == 'malformed-marker': attributions[row]['collected_test'] = 'tests/unit/test_windows.py::test_shell[unknown]'
    reseal(context)
    outcome, reason = read(context)
    assert outcome == 'missing' and 'skip' in reason


def test_runtime_native_successor_requires_exact_scope_mapping_capture_and_current_sources(tmp_path, monkeypatch):
    """A retained native origin is separate from current program execution."""
    from tests.support import runtime_observation_evidence as runtime
    code = 'skills/waapi-skill/example.py'
    (tmp_path / code).parent.mkdir(parents=True)
    (tmp_path / code).write_text('retained behavior\n')
    sources = {code: runtime.sha((tmp_path / code).read_bytes())}
    branch = {'id': '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.log.get|/resultSchema',
        'route': '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.log.get',
        'shape_sha256': 'a' * 64}
    binding = {'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
        'input': {'gateway_argv': ['core-call', 'ak.wwise.core.log.get'], 'selector': '/native_call/result'}}
    capture = {'historical_capture': True}
    program = {'candidate_sha256': 'f' * 64, 'runtime_read_program': capture}
    review = {'contract': 'waapi-skill.runtime-read-source-successor/v1',
        'packaged_sources': sources, 'historical_packaged_sources': [sources],
        'members': {branch['id']: {'mapping_sha256': digest(binding),
            'program_sha256': digest(program), 'capture_sha256': digest(capture),
            'source_reviews': [], 'sources': sources}},
        'scope_ids': [branch['id']], 'selected_program_ids': ['selected-code-mechanism']}
    descriptor = write_json(tmp_path / 'successor.json', review)
    monkeypatch.setattr(runtime, 'RUNTIME_SOURCE_SUCCESSOR', 'successor.json', raising=False)
    monkeypatch.setattr(runtime, 'RUNTIME_SOURCE_SUCCESSOR_SHA', descriptor['sha256'], raising=False)
    monkeypatch.setattr(runtime, 'program_source_context', lambda root, **kwargs: {'packaged': sources})
    assert runtime.retained_runtime_origin(binding, branch['id'], program, capture, tmp_path)
    for damage in ('scope', 'mapping', 'capture', 'source', 'selected'):
        changed = deepcopy(review)
        if damage == 'scope': changed['scope_ids'] = []
        if damage == 'mapping': changed['members'][branch['id']]['mapping_sha256'] = '0' * 64
        if damage == 'capture': changed['members'][branch['id']]['capture_sha256'] = '0' * 64
        if damage == 'source': changed['packaged_sources'] = {code: '0' * 64}
        if damage == 'selected': changed['selected_program_ids'] = []
        updated = write_json(tmp_path / 'successor.json', changed)
        monkeypatch.setattr(runtime, 'RUNTIME_SOURCE_SUCCESSOR_SHA', updated['sha256'])
        with pytest.raises(ValueError):
            runtime.retained_runtime_origin(binding, branch['id'], program, capture, tmp_path)


def test_ordinary_focused_nonlive_run_keeps_aggregate_strength_and_exact_selection(ordinary_run):
    context = ordinary_run
    selected = context['attachment']['mechanism']['selected_tests'][0] + '[owned-case]'
    context['attachment']['mechanism']['selected_tests'] = [selected]
    argv = ['ci/test.sh', '--mode', 'nonlive', '--', '-q', '-ra', selected]
    context['run']['plan']['argv'] = context['run']['result']['argv'] = argv
    context['run']['log'] = context['run']['log'].replace('mode:         program', 'mode:         nonlive').replace(
        'pytest args:  -q -ra', 'pytest args:  -q -ra ' + selected)
    reseal(context)
    assert read(context) == (OUTCOME, None)
    for altered in (argv + ['-k', 'selected'], argv[:-1] + ['tests/unit/test_code.py'],
                    argv[:-1] + [selected.replace('[owned-case]', '[wrong-case]')],
                    argv[:-1] + ['tests/unit/../test_code.py::test_selected_mechanism[owned-case]'],
                    argv[:-1] + ['tests/unit/test_code.py::test_unselected']):
        context['run']['plan']['argv'] = context['run']['result']['argv'] = altered
        reseal(context)
        assert read(context)[0] == 'missing'


def test_immutable_git_source_cache_never_hides_current_source_or_wrong_expected_seal(ordinary_run, monkeypatch):
    context = ordinary_run
    name = next(key for key in context['attachment']['original_sources'] if key.endswith('example.py'))
    original = context['attachment']['original_candidate']
    expected = {name: context['attachment']['original_sources'][name]}
    calls = []
    run = subprocess.run
    def observed(argv, **kwargs):
        if argv[0] == 'git' and 'show' in argv:
            calls.append(tuple(argv))
        return run(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'run', observed)
    assert completion.historical_source_seals(context['root'], original, expected) == expected
    assert completion.historical_source_seals(context['root'], original, expected) == expected
    assert len(calls) == 1
    assert '--no-replace-objects' in calls[0]
    assert completion.historical_source_seals(context['root'], original, {name: '0' * 64}) != {name: '0' * 64}
    (context['root'] / name).write_text('changed mutable current source\n')
    assert completion.historical_source_seals(context['root'], original, expected) == expected
    assert read(context)[0] == 'missing'


def focused_failed_subset(context):
    root, base = context['root'], context['base']
    for name in ('tests/conftest.py', 'pyproject.toml'):
        (root / name).write_text('# Controlled collection configuration\n')
    subprocess.run(['git', 'add', '.'], cwd=root, check=True, capture_output=True)
    subprocess.run(['git', '-c', 'user.name=Reader Fixture', '-c', 'user.email=reader@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Controlled collection configuration'], cwd=root, check=True, capture_output=True)
    original = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    attachment, run = context['attachment'], context['run']
    attachment['original_candidate'] = original
    for name in ('plan', 'result', 'summary'): run[name]['candidate'] = original
    run['result']['head_after'] = original
    selected = 'tests/unit/test_code.py::test_selected_mechanism[kept]'
    nodes = [selected, 'tests/unit/test_code.py::test_unselected[failed]',
        'tests/unit/test_code.py::test_unselected[teardown]', 'tests/unit/test_code.py::test_unselected[kept]']
    argv = ['ci/test.sh', '--mode', 'nonlive', '--', '-q', '-ra', *nodes]
    run['plan']['argv'] = run['result']['argv'] = argv
    run['result'].update(status='FAIL', exit_code=1)
    run['summary'].update(status='FAIL', exit_code=1, passed=0, skipped=0, pytest_seconds=0.31)
    run['exit'] = '1\n'
    original_summary = write_json(base / 'original-failed-summary.json', deepcopy(run['summary']))
    run['summary'].update(passed=3, failed=1, errors=1, pytest_seconds=0.3)
    run['log'] = '\n'.join(['mode:         nonlive', 'pytest args:  ' + ' '.join(argv[4:]),
        '_ ERROR at teardown of test_unselected[teardown] _',
        'FAILED ' + nodes[1], 'ERROR ' + nodes[2], '1 failed, 3 passed, 1 error in 0.3s'])
    attachment['skip_lines'] = []
    attachment['review']['skip_attribution'] = {}
    attachment['mechanism']['selected_tests'] = [selected]
    attachment['original_sources'] = {name: seal for name, seal in attachment['original_sources'].items()
        if name not in ('tests/unit/test_windows.py', 'tests/unit/test_junction.py')}
    collection = base / 'collection.log'
    collection.write_text('\n'.join([*nodes, '4 tests collected in 0.01s']))
    required = {'tests/unit/test_code.py', 'tests/conftest.py', 'pyproject.toml', 'ci/test.sh', 'ci/test_driver.py'}
    review = {'contract': 'waapi-skill.focused-successful-subset-review/v1', 'collection': sealed(collection),
        'collection_source_review': {'collection_basis': original, 'run_candidate': original,
            'sources': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in required},
            'reviewed_reason': 'Controlled identical test definitions and collection configuration.'},
        'collected_nodes': nodes, 'failed_nodes': [nodes[1]],
        'error_nodes': [{'nodeid': nodes[2], 'phase': 'teardown'}], 'successful_nodes': [nodes[0], nodes[3]],
        'file_sha256': {}, 'reviewed_reason': 'Controlled aggregate subset; original whole run stays FAIL.',
        'original_summary': original_summary}
    original_summary_data = json.loads((base / 'original-failed-summary.json').read_bytes())
    original_summary_data['log_sha256'] = hashlib.sha256(run['log'].encode()).hexdigest()
    review['original_summary'] = write_json(base / 'original-failed-summary.json', original_summary_data)
    context['subset_review'] = review
    reseal_subset(context)
    return context


def reseal_subset(context):
    reseal(context)
    review = context['subset_review']
    review['file_sha256'] = {name: descriptor['sha256'] for name, descriptor in context['attachment']['files'].items()}
    context['attachment']['successful_subset_review'] = write_json(context['base'] / 'subset-review.json', review)
    context['descriptor'] = write_json(context['base'] / 'attachment.json', context['attachment'])
    context['binding']['evidence']['program'] = context['descriptor']


def test_focused_successful_subset_preserves_original_failure_and_summary_correction(ordinary_run):
    context = focused_failed_subset(ordinary_run)
    assert read(context) == (OUTCOME, None)
    assert context['run']['result']['status'] == 'FAIL'
    assert context['run']['exit'] == '1\n'
    assert json.loads((context['base'] / 'original-failed-summary.json').read_bytes())['passed'] == 0


@pytest.mark.parametrize('damage', ('missing-error', 'unknown-error', 'selected-teardown', 'counts',
    'cleanup', 'interrupted', 'collection', 'param', 'summary-metadata'))
def test_focused_successful_subset_rejects_incomplete_or_failed_scope(ordinary_run, damage):
    context = focused_failed_subset(ordinary_run)
    review = context['subset_review']; nodes = review['collected_nodes']
    if damage == 'missing-error': review['error_nodes'] = []
    elif damage == 'unknown-error': context['run']['log'] = context['run']['log'].replace('ERROR ' + nodes[2], 'ERROR tests/unit/test_code.py::test_unselected[unknown]')
    elif damage == 'selected-teardown': context['attachment']['mechanism']['selected_tests'] = [nodes[2]]
    elif damage == 'counts': context['run']['summary']['passed'] = 4
    elif damage == 'cleanup': context['run']['result']['remaining_owned_processes'] = ['unclosed-owned-worker']
    elif damage == 'interrupted': context['run']['log'] = context['run']['log'].replace('FAILED ', 'KeyboardInterrupt\nFAILED ')
    elif damage == 'collection':
        path = context['base'] / 'collection.log'; path.write_text('\n'.join(nodes[:-1] + ['3 tests collected in 0.01s'])); review['collection'] = sealed(path)
    elif damage == 'param': context['attachment']['mechanism']['selected_tests'] = [nodes[0].replace('[kept]', '[unknown]')]
    else: context['run']['summary']['source_unchanged'] = False
    reseal_subset(context)
    assert read(context)[0] == 'missing'

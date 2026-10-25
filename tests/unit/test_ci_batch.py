"""Batch behavior through the ordinary developer launcher and real pytest."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / 'checkout'
    shutil.copytree(ROOT / 'ci', root / 'ci', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy(ROOT / 'pyproject.toml', root / 'pyproject.toml')
    shutil.copy(ROOT / '.gitignore', root / '.gitignore')
    (root / 'tests/unit').mkdir(parents=True)
    (root / 'tests/support').mkdir()
    for name in ('tests/__init__.py', 'tests/support/__init__.py', 'tests/conftest.py',
                 'tests/support/exact_evidence_finalization.py', 'tests/support/test_run_result.py'):
        if (ROOT / name).exists():
            shutil.copy(ROOT / name, root / name)
    case = root / 'tests/unit/test_cases.py'
    case.write_text('def test_good():\n    assert True\n\ndef test_bad():\n    assert False, "ordinary case failure"\n')
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Batch Test', '-c',
                    'user.email=batch@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    return root


def group(name, nodes, **values):
    return {'id': name, 'mode': 'nonlive', 'version': 'none', 'host': 'none',
            'nodes': nodes, 'sources': ['tests/unit/test_cases.py'], 'depends_on': [], **values}


def run_batch(checkout, root, groups, **values):
    plan = root.with_suffix('.plan.json')
    plan.write_text(json.dumps({'contract': 'waapi-skill.test-batch/v1',
        'root': str(root), 'groups': groups, **values}))
    env = {**os.environ, 'WAAPI_TEST_PYTHON': sys.executable,
           'PYTHONPATH': str(ROOT / 'skills/waapi-skill'), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
    env.pop('PYTEST_ADDOPTS', None)
    launcher = (['cmd.exe', '/d', '/c', str(checkout / 'ci/test.bat')] if os.name == 'nt'
                else ['bash', str(checkout / 'ci/test.sh')])
    result = subprocess.run([*launcher, '--batch-plan', str(plan)],
        cwd=checkout, env=env, text=True, capture_output=True, timeout=90)
    (root.parent / (root.name + '.stdout')).write_text(result.stdout)
    (root.parent / (root.name + '.stderr')).write_text(result.stderr)
    return result


def test_public_batch_keeps_independent_outcomes_and_deduplicates(checkout, tmp_path):
    node = 'tests/unit/test_cases.py::'
    root = tmp_path / 'durable-first'
    result = run_batch(checkout, root, [group('cases', [node + 'test_good', node + 'test_bad', node + 'test_good'])])
    assert result.returncode == 1, result.stdout + result.stderr
    summary = json.loads((root / 'summary.json').read_bytes())
    assert summary['outcome'] == 'FAIL'
    assert summary['groups'][0]['node_outcomes'] == [
        {'nodeid': node + 'test_good', 'outcome': 'PASS'},
        {'nodeid': node + 'test_bad', 'outcome': 'FAIL'}]
    assert summary['groups'][0]['failure_layer'] == 'case'
    assert summary['rerun'] == [{'group': 'cases', 'nodes': [node + 'test_bad'], 'reason': 'failed'}]
    receipt = json.loads((root / 'groups/cases/result.json').read_bytes())
    assert receipt['terminal'] is True and receipt['duplicates_removed'] == 1
    assert 'ordinary case failure' in result.stdout


def test_ordinary_failure_blocks_dependents_but_collects_independent_groups(checkout, tmp_path):
    node = 'tests/unit/test_cases.py::'
    root = tmp_path / 'dependency-batch'
    result = run_batch(checkout, root, [group('failed', [node + 'test_bad']),
        group('dependent', [node + 'test_good'], depends_on=['failed']),
        group('independent', [node + 'test_good'])])
    assert result.returncode == 1, result.stdout + result.stderr
    summary = json.loads((root / 'summary.json').read_bytes())
    assert [row['outcome'] for row in summary['groups']] == ['FAIL', 'BLOCKED', 'PASS']
    assert summary['groups'][1]['failure_layer'] == 'prerequisite'
    assert summary['groups'][2]['node_outcomes'][0]['outcome'] == 'PASS'
    assert not (root / 'groups/dependent/result.json').exists()


def test_existing_root_is_preserved_and_unknown_dependencies_never_dispatch(checkout, tmp_path):
    node = 'tests/unit/test_cases.py::test_good'
    root = tmp_path / 'retained'
    assert run_batch(checkout, root, [group('one', [node])]).returncode == 0
    before = (root / 'summary.json').read_bytes()
    assert run_batch(checkout, root, [group('one', [node])]).returncode == 2
    assert (root / 'summary.json').read_bytes() == before
    invalid = tmp_path / 'unknown-dependency'
    result = run_batch(checkout, invalid, [group('one', [node], depends_on=['missing'])])
    assert result.returncode == 2
    assert not (invalid / 'groups/one/result.json').exists()
    assert 'missing' in result.stdout + result.stderr


@pytest.mark.parametrize('fault', ['source', 'finalizer'])
def test_systemic_fault_stops_later_independent_groups(checkout, tmp_path, fault):
    case = checkout / 'tests/unit/test_cases.py'
    case.write_text(case.read_text() + '\n\ndef test_fault(request):\n' + (
        '    from pathlib import Path\n    Path("mechanism.py").write_text("changed")\n' if fault == 'source' else
        '    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer\n'
        '    def fail(phases):\n        raise RuntimeError("controlled evidence writer fault")\n'
        '    register_exact_evidence_finalizer(request.node, fail)\n'))
    (checkout / 'mechanism.py').write_text('original')
    root = tmp_path / ('systemic-' + fault)
    prefix = 'tests/unit/test_cases.py::'
    result = run_batch(checkout, root, [group('fault', [prefix + 'test_fault'], sources=['mechanism.py']),
        group('later', [prefix + 'test_good'])])
    assert result.returncode == 2, result.stdout + result.stderr
    summary = json.loads((root / 'summary.json').read_bytes())
    assert summary['groups'][0]['failure_layer'] == ('source' if fault == 'source' else 'framework')
    assert summary['groups'][1]['outcome'] == 'BLOCKED'
    assert not (root / 'groups/later/result.json').exists()


def test_rerun_keeps_original_pass_and_runs_failed_plus_affected_callers(checkout, tmp_path):
    case = checkout / 'tests/unit/test_cases.py'
    case.write_text('from pathlib import Path\ndef test_good():\n    assert True\n'
                    'def test_bad():\n    assert Path("bad.txt").read_text() == "fixed"\n')
    (checkout / 'bad.txt').write_text('broken')
    (checkout / 'good.txt').write_text('stable')
    prefix = 'tests/unit/test_cases.py::'
    groups = [group('repair', [prefix + 'test_bad'], sources=['bad.txt']),
        group('caller', [prefix + 'test_good'], depends_on=['repair'], sources=['good.txt']),
        group('unchanged', [prefix + 'test_good'], sources=['good.txt'])]
    first = tmp_path / 'first'
    assert run_batch(checkout, first, groups).returncode == 1
    original = (first / 'groups/unchanged/result.json').read_bytes()
    (checkout / 'bad.txt').write_text('fixed')
    second = tmp_path / 'repaired'
    result = run_batch(checkout, second, groups, previous=str(first / 'summary.json'))
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((second / 'summary.json').read_bytes())
    assert [r['outcome'] for r in summary['groups']] == ['PASS', 'PASS', 'REUSED']
    assert [r['id'] for r in summary['groups'] if r['executed']] == ['repair', 'caller']
    assert not (second / 'groups/unchanged/result.json').exists()
    assert (first / 'groups/unchanged/result.json').read_bytes() == original
    assert summary['groups'][2]['original_result']['artifact'] == str(first / 'groups/unchanged/result.json')
    assert summary['rerun'] == []


def test_unknown_change_blocks_reuse_and_explicit_irrelevance_keeps_original(checkout, tmp_path):
    groups = [group('one', ['tests/unit/test_cases.py::test_good'])]
    first = tmp_path / 'first'
    assert run_batch(checkout, first, groups).returncode == 0
    (checkout / 'review-notes.md').write_text('unrelated notes')
    unknown = tmp_path / 'unknown'
    result = run_batch(checkout, unknown, groups, previous=str(first / 'summary.json'))
    assert result.returncode == 2, result.stdout + result.stderr
    summary = json.loads((unknown / 'summary.json').read_bytes())
    assert summary['unknown_impact'] == ['review-notes.md']
    assert not (unknown / 'groups/one/result.json').exists()
    relevant = tmp_path / 'reviewed'
    result = run_batch(checkout, relevant, groups, previous=str(first / 'summary.json'),
        irrelevant_changes={'review-notes.md': 'Only maintainer notes; no runtime or fixture dependency.'})
    assert result.returncode == 0, result.stdout + result.stderr
    row, = json.loads((relevant / 'summary.json').read_bytes())['groups']
    assert row['outcome'] == 'REUSED' and row['executed'] is False


def test_partial_rerun_retains_passes_in_same_group_and_missing_evidence_blocks(checkout, tmp_path):
    case = checkout / 'tests/unit/test_cases.py'
    case.write_text('import os\ndef test_good():\n    assert True\ndef test_bad():\n    assert os.getenv("BATCH_REPAIRED") == "yes"\n')
    prefix = 'tests/unit/test_cases.py::'
    groups = [group('one', [prefix + 'test_good', prefix + 'test_bad'])]
    first = tmp_path / 'first'
    assert run_batch(checkout, first, groups).returncode == 1
    # Repair here substitutes an external prerequisite, leaving test sources
    # fixed so only the failed node should run in the next frozen batch.
    previous = os.environ.get('BATCH_REPAIRED')
    os.environ['BATCH_REPAIRED'] = 'yes'
    try:
        second = tmp_path / 'second'
        result = run_batch(checkout, second, groups, previous=str(first / 'summary.json'))
    finally:
        if previous is None:
            os.environ.pop('BATCH_REPAIRED', None)
        else:
            os.environ['BATCH_REPAIRED'] = previous
    assert result.returncode == 0, result.stdout + result.stderr
    row, = json.loads((second / 'summary.json').read_bytes())['groups']
    assert row['selection'] == [prefix + 'test_bad']
    assert row['node_outcomes'] == [{'nodeid': prefix + 'test_good', 'outcome': 'PASS'},
                                    {'nodeid': prefix + 'test_bad', 'outcome': 'PASS'}]
    assert row['node_results'][prefix + 'test_good']['artifact'] == str(first / 'groups/one/result.json')
    (first / 'groups/one/result.json').unlink()
    third = tmp_path / 'third'
    assert run_batch(checkout, third, groups, previous=str(second / 'summary.json')).returncode == 2
    assert not (third / 'groups/one/result.json').exists()


@pytest.mark.parametrize('unsafe', [False, True])
def test_five_native_lanes_use_existing_preflight_and_authoritative_cleanup(checkout, tmp_path, unsafe):
    from ci.test_driver import main, SUPPORTED_VERSIONS, WWISE_BUILDS
    from tests.destructive.support.category_evidence import build_category_evidence_record
    native = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::test_console_owned_runtime_read_batch'
    (checkout / 'tests/destructive').mkdir()
    shutil.copy(ROOT / native.split('::')[0], checkout / native.split('::')[0])
    # Only the child-process boundary is substituted. The developer driver,
    # readiness checks, finite selection, category writer and result reader run.
    from ci.test_batch import COLLECTOR_PREFLIGHT
    for node in COLLECTOR_PREFLIGHT:
        shutil.copy(ROOT / node.split('::')[0], checkout / node.split('::')[0])
    collector = 'tests/destructive/support/console_profiler_probe.py'
    (checkout / 'tests/destructive/support').mkdir()
    shutil.copy(ROOT / collector, checkout / collector)
    configs = {}
    index = checkout / 'skills/waapi-skill/resources/native-catalog/index.json'
    index.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / 'skills/waapi-skill/resources/native-catalog/index.json', index)
    for version in SUPPORTED_VERSIONS:
        source = tmp_path / ('source-' + version); source.mkdir()
        project = source / 'SampleProject.wproj'; project.write_text('<Project WwiseVersion="' + version + '"/>')
        console = source / 'WwiseConsole'; console.write_text('fake external process boundary')
        console.chmod(0o755)
        configs[version] = {'wwise_console': str(console), 'sample_project': str(project)}
        catalog = 'skills/waapi-skill/resources/native-catalog/' + version + '/wwise-console.json'
        (checkout / catalog).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / catalog, checkout / catalog)
    config = tmp_path / 'live-environment.json'; config.write_text(json.dumps({'versions': configs}))
    root = tmp_path / 'five-native-lanes'
    groups = [group('native-' + v[:4], [native], mode='destructive', version=v,
                    host='wwise-console', sources=[collector]) for v in SUPPORTED_VERSIONS]
    plan = tmp_path / 'native.plan.json'; plan.write_text(json.dumps({
        'contract': 'waapi-skill.test-batch/v1', 'root': str(root), 'groups': groups}))
    order = []
    def external(command, **options):
        env = options['env']; version = env.get('WWISE_VERSION', 'none')
        order.append(version)
        args = list(command); nodes = [n for n in args if n.startswith('tests/')]
        nodes = [expanded for n in nodes for expanded in (
            [n + '[' + v + ']' for v in SUPPORTED_VERSIONS] if n == COLLECTOR_PREFLIGHT[0] else [n])]
        failed = version == '2022.1'; code = int(failed)
        path = Path(env['WAAPI_TEST_BATCH_RESULT']); path.parent.mkdir(parents=True, exist_ok=True)
        phases = {n: {'setup': 'passed', 'call': 'failed' if failed else 'passed', 'teardown': 'passed'} for n in nodes}
        path.write_text(json.dumps({'terminal': True, 'exit_code': code, 'duplicates_removed': 0,
            'node_outcomes': [{'nodeid': n, 'outcome': 'FAIL' if failed else 'PASS'} for n in nodes], 'phase_reports': phases}))
        if version != 'none':
            outcome = 'FAIL' if failed else 'PASS'
            quarantine = path.parent / 'quarantine'; quarantine.mkdir()
            report = path.parent / 'observation.json'; report.write_text(json.dumps({'cleanup': {'complete': True}}))
            year, major, minor, build = map(int, WWISE_BUILDS[version].split('.'))
            candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip()
            record = build_category_evidence_record(repo_root=checkout, candidate=candidate, version=version,
                host={'is_command_line': True, 'version': {'year': year, 'major': major, 'minor': minor, 'build': build}},
                categories=[{'category': 'console-runtime-read-batch', 'status': 'blocked' if failed else 'PASS',
                    'verifier_strength': 'fake scheduling boundary', 'observation_path': str(report),
                    'observation_sha256': __import__('hashlib').sha256(report.read_bytes()).hexdigest()}],
                source={'hash_before': 'a' * 64, 'hash_after': 'b' * 64 if unsafe and failed else 'a' * 64,
                    'mtime_before_ns': 1, 'mtime_after_ns': 1, 'project': env['WWISE_SAMPLE_PROJECT_PATH']},
                residual_state={'sandbox': 'quarantined' if failed else 'deleted', 'quarantine_path': str(quarantine),
                    'process_cleanup': 'cleaned', 'residual_processes': []},
                invocation={'selected_test_nodeids': nodes, 'node_outcomes': [{'nodeid': n, 'outcome': outcome} for n in nodes],
                    'started_at_unix_ns': 1, 'finished_at_unix_ns': 2, 'phase': 'final', 'outcome': outcome}, transactions=[])
            Path(env['WWISE_CATEGORY_EVIDENCE_PATH']).write_text(json.dumps(record) + '\n')
        return subprocess.CompletedProcess(command, code)
    code = main(['--batch-plan', str(plan)], repo_root=checkout, python_executable=sys.executable,
        command_runner=external, environment={**os.environ, 'WWISE_TEST_CONFIG': str(config),
        'PYTEST_ADDOPTS': '-x', 'PYTEST_PLUGINS': 'unrelated-plugin'})
    assert code == (2 if unsafe else 1)
    assert order == ['none', *SUPPORTED_VERSIONS[:2 if unsafe else 5]]
    summary = json.loads((root / 'summary.json').read_bytes())
    assert summary['groups'][0]['id'] == 'collector-preflight'
    assert summary['groups'][2]['failure_layer'] == ('evidence' if unsafe else 'case')
    assert summary['groups'][-1]['outcome'] == ('BLOCKED' if unsafe else 'PASS')
    if not unsafe:
        import hashlib
        # The existing consumer proofs remain valid after a separately tested
        # batch-wrapper edit. Reuse references them, without repackaging them.
        helper = checkout / 'ci/test_batch.py'
        helper.write_text(helper.read_text() + '\n# Wrapper-only successor\n')
        original = root / 'summary.json'
        successor = tmp_path / 'native-with-retained-preflight'
        plan.write_text(json.dumps({'contract': 'waapi-skill.test-batch/v1', 'root': str(successor),
            'groups': [groups[-1]], 'preflight_evidence': {'artifact': str(original),
                'sha256': hashlib.sha256(original.read_bytes()).hexdigest()}}))
        order.clear()
        assert main(['--batch-plan', str(plan)], repo_root=checkout, python_executable=sys.executable,
            command_runner=external, environment={**os.environ, 'WWISE_TEST_CONFIG': str(config)}) == 0
        assert order == ['2025.1']
        reused = json.loads((successor / 'summary.json').read_bytes())['groups'][0]
        assert reused['outcome'] == 'REUSED' and reused['executed'] is False
        assert reused['original_result']['artifact'] == str(root / 'groups/collector-preflight/result.json')
        native_plan = json.loads(plan.read_bytes())
        native_plan['previous'] = str(successor / 'summary.json')
        native_plan['root'] = str(tmp_path / 'unchanged-native')
        plan.write_text(json.dumps(native_plan)); order.clear()
        assert main(['--batch-plan', str(plan)], repo_root=checkout, python_executable=sys.executable,
            command_runner=external, environment={**os.environ, 'WWISE_TEST_CONFIG': str(config)}) == 0
        assert order == []
        # A different source fixture is a meaningful native dependency even
        # when the selected test node and Git candidate are unchanged.
        project = Path(configs['2025.1']['sample_project'])
        project.write_text(project.read_text() + '\n<!-- fixture changed -->')
        native_plan['root'] = str(tmp_path / 'changed-native-fixture')
        plan.write_text(json.dumps(native_plan)); order.clear()
        assert main(['--batch-plan', str(plan)], repo_root=checkout, python_executable=sys.executable,
            command_runner=external, environment={**os.environ, 'WWISE_TEST_CONFIG': str(config)}) == 0
        assert order == ['2025.1']
        collector_path = checkout / collector
        collector_path.write_text(collector_path.read_text() + '\n# Collector changed\n')
        native_plan['root'] = str(tmp_path / 'changed-consumer')
        plan.write_text(json.dumps(native_plan)); order.clear()
        assert main(['--batch-plan', str(plan)], repo_root=checkout, python_executable=sys.executable,
            command_runner=external, environment={**os.environ, 'WWISE_TEST_CONFIG': str(config)}) == 2
        assert order == []


def test_evidence_survives_later_default_pytest_retention_cycles(checkout, tmp_path):
    (checkout / 'tests/unit/test_cases.py').write_text(
        'import json\ndef test_good(tmp_path):\n'
        '    (tmp_path / "evidence.json").write_text(json.dumps({"business_value": 42}))\n')
    root = tmp_path / 'durable-evidence'
    result = run_batch(checkout, root, [group('one', ['tests/unit/test_cases.py::test_good'])])
    assert result.returncode == 0, result.stdout + result.stderr
    original, = (root / 'groups/one/pytest').rglob('evidence.json')
    before = original.read_bytes()
    default_root = tmp_path / 'default-temps'; default_root.mkdir()
    environment = {**os.environ, 'TMPDIR': str(default_root), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
        'PYTHONPATH': str(ROOT / 'skills/waapi-skill')}
    environment.pop('WAAPI_TEST_BATCH_RESULT', None)
    for _ in range(4):
        completed = subprocess.run([sys.executable, '-m', 'pytest', 'tests/unit/test_cases.py::test_good',
            '-o', 'addopts=', '-q'], cwd=checkout, env=environment, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stdout + completed.stderr
    assert original.read_bytes() == before
    assert json.loads(original.read_bytes()) == {'business_value': 42}


def test_same_frozen_selection_is_not_executed_again_for_another_group(checkout, tmp_path):
    node = 'tests/unit/test_cases.py::test_good'
    root = tmp_path / 'duplicate-groups'
    result = run_batch(checkout, root, [group('ticket-a', [node]), group('ticket-b', [node])])
    assert result.returncode == 0, result.stdout + result.stderr
    rows = json.loads((root / 'summary.json').read_bytes())['groups']
    assert [r['outcome'] for r in rows] == ['PASS', 'REUSED']
    assert rows[1]['executed'] is False
    assert not (root / 'groups/ticket-b/result.json').exists()
    assert rows[1]['original_result'] == rows[0]['result']


def test_abrupt_child_exit_retains_completed_phase_records_and_stops(checkout, tmp_path):
    case = checkout / 'tests/unit/test_cases.py'
    case.write_text(case.read_text() + '\ndef test_exit():\n    import os\n    os._exit(2)\n')
    prefix = 'tests/unit/test_cases.py::'
    root = tmp_path / 'abrupt'
    result = run_batch(checkout, root, [group('abrupt', [prefix + 'test_good', prefix + 'test_exit']),
        group('later', [prefix + 'test_good'])])
    assert result.returncode == 2, result.stdout + result.stderr
    partial = json.loads((root / 'groups/abrupt/result.json').read_bytes())
    assert partial['terminal'] is False
    assert partial['phase_reports'][prefix + 'test_good'] == dict.fromkeys(('setup', 'call', 'teardown'), 'passed')
    assert not (root / 'groups/later/result.json').exists()
    assert json.loads((root / 'summary.json').read_bytes())['outcome'] == 'BLOCKED'

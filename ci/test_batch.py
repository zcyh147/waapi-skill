"""Finite, opt-in batches dispatched by the ordinary developer test driver."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import subprocess


CONTRACT = 'waapi-skill.test-batch/v1'
VERSIONS = ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')
CONSOLE_NODE = 'tests/destructive/test_gateway_workflow_transaction_matrix.py::test_console_owned_runtime_read_batch'
COLLECTOR_PREFLIGHT = (
    'tests/unit/test_console_runtime_read_batch.py::test_grouped_console_reads_reach_final_writer_at_one_numeric_position',
    'tests/unit/test_console_runtime_read_batch.py::test_grouped_reader_failure_preserves_sibling_facts_after_final_cleanup[invalid-busses-busses]',
    'tests/unit/test_console_runtime_read_batch.py::test_grouped_shared_failure_stops_dependents_and_cleanup_cannot_create_pass[cleanup]',
    'tests/unit/test_meter_runtime_read_evidence.py::test_meter_first_vertical_cardinality_absence_teardown_and_native_gate',
    'tests/unit/test_runtime_owned_control_evidence.py::test_owned_mutations_belong_to_their_matching_execute_phase',
    'tests/unit/test_runtime_owned_control_evidence.py::test_file_boundary_is_exact_and_does_not_load_unrelated_scope',
    'tests/unit/test_runtime_transport_branch_evidence.py::test_transport_list_cardinality_uses_ordinary_assertion_contract',
    'tests/unit/test_runtime_transport_branch_evidence.py::test_transport_namespace_composes_with_cursor_without_rewriting',
    'tests/unit/test_branch_coverage_completion_cli.py::test_exact_reviewed_equivalence_reuses_unchanged_sources_and_rejects_stale_claims',
    'tests/unit/test_branch_coverage_audit.py::test_runtime_prefixed_families_share_one_base_without_overwrite_or_duplicate_credit',
)
# These files deliver the separate batch wrapper, not a collector, public
# Gateway assertion, native fake, evidence writer or ordinary consumer.
PREFLIGHT_WRAPPER_PATHS = {'ci/test_driver.py', 'ci/test_batch.py', 'tests/unit/test_ci_batch.py',
                           'tests/support/test_run_result.py'}
BATCH_SOURCE_FILES = {'ci/test_driver.py', 'ci/test_batch.py', 'ci/test_readiness.py',
    'ci/run_live_test_command.py', 'ci/resolve_live_test_config.py', 'tests/conftest.py',
    'tests/support/test_run_result.py', 'tests/support/exact_evidence_finalization.py'}


class BatchError(ValueError):
    """A batch cannot safely run its declared selection."""


def read_json(path):
    if Path(path).stat().st_size > 4 * 1024 * 1024:
        raise BatchError('Batch input exceeds 4 MiB')
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise BatchError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs)


def relative_file(root, name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise BatchError('Expected a repository-relative file')
    path = Path(name)
    if path.is_absolute() or path.as_posix() != name or any(p in ('.', '..') for p in path.parts):
        raise BatchError('Unsafe repository path: ' + name)
    target = root / path
    if any(part.is_symlink() for part in (target, *target.parents)) or not target.is_file():
        raise BatchError('Missing or aliased source: ' + name)
    return target


def validate_plan(plan, repo):
    if (not isinstance(plan, dict) or not {'contract', 'root', 'groups'} <= set(plan)
            or set(plan) - {'contract', 'root', 'groups', 'previous', 'irrelevant_changes', 'preflight_evidence', 'recover_from'}
            or plan['contract'] != CONTRACT or not isinstance(plan['groups'], list)
            or not 1 <= len(plan['groups']) <= 64):
        raise BatchError('Invalid bounded batch plan')
    if plan.get('recover_from') and (plan.get('previous') or plan.get('preflight_evidence')):
        raise BatchError('Report recovery cannot select execution or preflight reuse')
    root = Path(plan['root'])
    if (not root.is_absolute() or root != root.resolve() or os.path.lexists(root)
            or any(p.is_symlink() for p in root.parents)
            or (root.is_relative_to(repo) and not root.is_relative_to(repo / '.waapi-skill-state'))):
        raise BatchError('Batch root must be fresh, absolute and without aliases')
    seen = set()
    if any(not isinstance(g, dict) for g in plan['groups']):
        raise BatchError('Each batch group must be an object')
    ignored = plan.get('irrelevant_changes', {})
    if (not isinstance(ignored, dict) or any(not isinstance(p, str) or not isinstance(reason, str)
            or not reason.strip() for p, reason in ignored.items())):
        raise BatchError('Irrelevant changes require explicit path/reason pairs')
    native = any(g.get('mode') != 'nonlive' for g in plan['groups'] if isinstance(g, dict))
    if plan.get('preflight_evidence') and not native:
        raise BatchError('Retained collector preflight belongs to a native selection')
    if native:
        if any(g.get('id') == 'collector-preflight' for g in plan['groups']):
            raise BatchError('collector-preflight is reserved for the existing consumer checks')
        plan['groups'].insert(0, {'id': 'collector-preflight', 'mode': 'nonlive', 'version': 'none',
            'host': 'none', 'nodes': list(COLLECTOR_PREFLIGHT),
            'sources': sorted({n.split('::')[0] for n in COLLECTOR_PREFLIGHT}), 'depends_on': []})
    for group in plan['groups']:
        if (not isinstance(group, dict) or set(group) != {
                'id', 'mode', 'version', 'host', 'nodes', 'sources', 'depends_on'}
                or not isinstance(group['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', group['id'])
                or group['id'] in seen):
            raise BatchError('Invalid or duplicate batch group')
        if group['mode'] == 'nonlive':
            if (group['version'], group['host']) != ('none', 'none'):
                raise BatchError('Non-live group needs version/host none')
        elif (group['mode'] != 'destructive' or group['version'] not in VERSIONS
              or group['host'] != 'wwise-console' or group['nodes'] != [CONSOLE_NODE]):
            raise BatchError('Native batch admission is the existing exact Console grouped-reader node only')
        else:
            from wwise_waapi.native_catalog import load_native_catalog
            try:
                load_native_catalog(group['version'], group['host'],
                    root=repo / 'skills/waapi-skill/resources/native-catalog')
            except Exception as exc:
                raise BatchError('Matching native schema/provenance is not ready: ' + str(exc)) from exc
            group['sources'] = list(dict.fromkeys([*group['sources'],
                'skills/waapi-skill/resources/native-catalog/index.json',
                'skills/waapi-skill/resources/native-catalog/' + group['version'] + '/wwise-console.json']))
            group['depends_on'] = list(dict.fromkeys(['collector-preflight', *group['depends_on']]))
        nodes = group['nodes']
        if (not isinstance(nodes, list) or not 1 <= len(nodes) <= 256
                or not all(isinstance(n, str) and n.startswith('tests/') for n in nodes)):
            raise BatchError('Batch nodes must be explicit repository tests')
        for node in nodes:
            relative_file(repo, node.split('::')[0])
        if not isinstance(group['sources'], list) or not group['sources']:
            raise BatchError('Each group needs its finite relevant source map')
        for name in group['sources']:
            path = relative_file(repo, name)
            if root == path or root in path.parents or path in root.parents:
                raise BatchError('Batch output overlaps a source')
        if (not isinstance(group['depends_on'], list) or not set(group['depends_on']) <= seen):
            raise BatchError('Unknown, cyclic or out-of-order dependency: ' + str(group['depends_on']))
        seen.add(group['id'])
    return root


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def source_identity(driver, plan, *, include_native_scopes=True):
    files = set(BATCH_SOURCE_FILES)
    for group in plan['groups']:
        files.update(group['sources'])
        files.update(n.split('::')[0] for n in group['nodes'])
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=driver.repo_root,
                                     text=True).strip()
    dirty = subprocess.check_output(['git', 'ls-files', '-m', '-d', '-o', '--exclude-standard'],
                                    cwd=driver.repo_root, text=True).splitlines()
    return {'commit': commit, 'sources': {name: hashlib.sha256(
        relative_file(driver.repo_root, name).read_bytes()).hexdigest() for name in sorted(files)},
        'native_scopes': {g['id']: native_scope(driver, g) for g in plan['groups']
                          if include_native_scopes and g['mode'] != 'nonlive'},
        'worktree_changes': {name: hashlib.sha256((driver.repo_root / name).read_bytes()).hexdigest()
            if (driver.repo_root / name).is_file() else None for name in sorted(set(dirty))}}


def native_scope(driver, group):
    if __package__:
        from .test_driver import default_live_paths
        from .run_live_test_command import build_live_test_environment
    else:
        from test_driver import default_live_paths
        from run_live_test_command import build_live_test_environment
    from tests.destructive.support.sandbox_fixture import hash_project
    defaults = default_live_paths(group['version'], group['mode'], repo_root=driver.repo_root,
                                  windows=driver.windows)
    env = build_live_test_environment(driver.environment, version=group['version'], mode=group['mode'],
        repo_root=driver.repo_root, default_config=defaults.config, default_console=defaults.console,
        default_project=defaults.project, default_sandbox=defaults.sandbox)
    project, config = Path(env['WWISE_SAMPLE_PROJECT_PATH']), Path(env['WWISE_TEST_CONFIG'])
    return {'project': str(project), 'source_hash': hash_project(project.parent, preferred_strategy='full').digest,
            'console': env['WWISE_CONSOLE'], 'config': str(config),
            'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else None}


def descriptor(path):
    return {'artifact': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def read_descriptor(value):
    path = Path(value['artifact'])
    if descriptor(path) != value:
        raise BatchError('Original result is missing or changed: ' + str(path))
    return path


def changed_paths(driver, before, after):
    committed = subprocess.check_output(['git', 'diff', '--name-only', before['commit'], 'HEAD'],
                                       cwd=driver.repo_root, text=True).splitlines()
    dirty = before['worktree_changes'].keys() | after['worktree_changes'].keys()
    changed = set(committed) | {p for p in dirty if before['worktree_changes'].get(p) != after['worktree_changes'].get(p)}
    for name, seal in before['sources'].items():
        path = driver.repo_root / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == seal:
            changed.discard(name)
        else:
            changed.add(name)
    return changed


def retained_preflight(driver, plan, frozen):
    if not plan.get('preflight_evidence'):
        return None
    previous = read_json(read_descriptor(plan['preflight_evidence']))
    required = {COLLECTOR_PREFLIGHT[0] + '[' + v + ']' for v in VERSIONS} | set(COLLECTOR_PREFLIGHT[1:])
    prior, = [g for g in previous['groups'] if required <= {
        r['nodeid'] for r in g['node_outcomes'] if r['outcome'] == 'PASS'}]
    if prior['outcome'] not in {'PASS', 'REUSED'}:
        raise BatchError('Original collector preflight did not pass')
    validate_retained_passes(prior, required, previous['source_identity'])
    ignored = plan.get('irrelevant_changes', {})
    if set(ignored) & set(previous['source_identity']['sources']):
        raise BatchError('Irrelevance cannot override original preflight sources')
    changed = changed_paths(driver, previous['source_identity'], frozen)
    if changed - PREFLIGHT_WRAPPER_PATHS - ignored.keys():
        raise BatchError('Collector preflight relevance changed or is unknown: ' +
                         ', '.join(sorted(changed - PREFLIGHT_WRAPPER_PATHS - ignored.keys())))
    return {**prior, 'id': 'collector-preflight', 'spec': plan['groups'][0],
        'outcome': 'REUSED', 'executed': False, 'original_result': prior.get('original_result', prior['result']),
        'reuse_reason': 'Original consumer proofs unchanged; separate batch wrapper changes only',
        'changed_wrapper_paths': sorted(changed & PREFLIGHT_WRAPPER_PATHS),
        'preflight_evidence': plan['preflight_evidence']}


def validate_context(reference, spec, before, *, node=None):
    context = read_json(read_descriptor(reference))
    if (context.get('contract') != 'waapi-skill.test-batch-context/v1'
            or {k: v for k, v in context['spec'].items() if k != 'id'}
            != {k: v for k, v in spec.items() if k != 'id'}):
        raise BatchError('Original result belongs to a different planned group')
    names = BATCH_SOURCE_FILES | set(spec['sources']) | {n.split('::')[0] for n in spec['nodes']}
    original = context['source_identity']
    if (not names <= original['sources'].keys() or not names <= before['sources'].keys()
            or any(original['sources'][name] != before['sources'][name] for name in names)
            or original.get('native_scopes', {}).get(context['spec']['id'])
            != before.get('native_scopes', {}).get(spec['id'])):
        raise BatchError('Original result source or native scope differs')
    if node is not None and not any(matches_node(node, n) for n in context['selection']):
        raise BatchError('Original node was not in its saved execution selection')
    return context


def matches_node(node, selector):
    return node == selector or node.startswith(selector + '[') or node.startswith(selector + '::')


def validate_retained_passes(prior, nodes, before):
    """A PASS pointer is reusable only with its original complete receipt."""
    if prior.get('preflight_evidence'):
        before = read_json(read_descriptor(prior['preflight_evidence']))['source_identity']
    for node in nodes:
        path = read_descriptor(prior['node_results'][node])
        observed = read_json(path)
        checked_result(path, observed['exit_code'])
        if ({'nodeid': node, 'outcome': 'PASS'} not in observed['node_outcomes']
                or observed['phase_reports'].get(node)
                != dict.fromkeys(('setup', 'call', 'teardown'), 'passed')):
            raise BatchError('Original successful node lacks complete final evidence: ' + node)
        if observed.get('batch_context') is not None:
            validate_context(observed['batch_context'], prior['spec'], before, node=node)
        elif prior.get('context') is not None:
            raise BatchError('Original result lacks its planned source context')


def affected_selection(driver, plan, frozen):
    previous = read_json(plan['previous']) if plan.get('previous') else None
    selections, retained, unknown = {}, {}, []
    if previous is None:
        return {g['id']: g['nodes'] for g in plan['groups']}, retained, unknown
    previous_root = Path(plan['previous']).parent
    recorded = {g['id'] for g in previous['groups']}
    old_plan = read_json(previous_root / 'plan.json')
    if (previous.get('outcome') == 'RUNNING' or any(
            g['id'] not in recorded and (previous_root / 'groups' / g['id']).exists()
            for g in old_plan['groups'])):
        raise BatchError('Incomplete previous report; use recover_from without replaying producers')
    before = previous['source_identity']
    changed = changed_paths(driver, before, frozen)
    sources = before['sources'].keys() | frozen['sources'].keys()
    ignored = plan.get('irrelevant_changes', {})
    if (not isinstance(ignored, dict) or any(not isinstance(reason, str) or not reason.strip()
                                          for reason in ignored.values()) or set(ignored) & sources):
        raise BatchError('Irrelevance needs explicit reasons and cannot override relevant sources')
    unknown = sorted(changed - sources - ignored.keys())
    old = {r['id']: r for r in previous['groups']}
    shared = set(frozen['sources']) - set().union(*(set(g['sources']) for g in plan['groups']))
    for group in plan['groups']:
        prior = old.get(group['id'])
        changed_group = (prior is None or prior.get('spec') != group
            or bool(changed & (set(group['sources']) | shared))
            or before.get('native_scopes', {}).get(group['id']) != frozen['native_scopes'].get(group['id'])
            or any(selections.get(dep) for dep in group['depends_on']))
        if changed_group or prior['outcome'] == 'BLOCKED':
            selections[group['id']] = group['nodes']
        elif prior['outcome'] in {'PASS', 'REUSED'}:
            original = prior.get('original_result', prior.get('result'))
            validate_retained_passes(prior, prior['node_results'], before)
            if group['mode'] != 'nonlive':
                reference = prior['native_result']
                if descriptor(reference['artifact'])['sha256'] != reference['sha256']:
                    raise BatchError('Original native category evidence changed')
                original_result = read_json(read_descriptor(prior['result']))
                if native_result(reference['artifact'], group, original_result,
                                 prior['source_commit'], before['native_scopes'][group['id']]) != reference:
                    raise BatchError('Original native finalizer facts changed')
            retained[group['id']] = {**prior, 'outcome': 'REUSED', 'executed': False,
                                     'original_result': original, 'reuse_reason': 'Relevant inputs unchanged; original verdict retained'}
            selections[group['id']] = []
        else:
            validate_retained_passes(prior, [r['nodeid'] for r in prior['node_outcomes']
                                             if r['outcome'] == 'PASS'], before)
            selections[group['id']] = [r['nodeid'] for r in prior['node_outcomes'] if r['outcome'] != 'PASS']
    return selections, retained, unknown


def checked_result(path, code):
    result = read_json(path)
    if (result.get('terminal') is not True or result.get('exit_code') != code
            or not isinstance(result.get('node_outcomes'), list) or not result['node_outcomes']):
        raise BatchError('Missing or inconsistent terminal pytest result')
    nodes = [r['nodeid'] for r in result['node_outcomes']]
    if len(set(nodes)) != len(nodes):
        raise BatchError('Duplicate terminal pytest node')
    for row in result['node_outcomes']:
        phases = result['phase_reports'].get(row['nodeid'], {})
        expected = ('FAIL' if 'failed' in phases.values() else 'SKIP' if 'skipped' in phases.values()
                    else 'PASS' if phases == dict.fromkeys(('setup', 'call', 'teardown'), 'passed') else 'BLOCKED')
        if row != {'nodeid': row['nodeid'], 'outcome': expected}:
            raise BatchError('Node outcome differs from final phase reports')
    failed = any(r['outcome'] == 'FAIL' for r in result['node_outcomes'])
    if (code == 0 and failed) or (code == 1 and not failed):
        raise BatchError('Pytest exit code does not match recorded failures')
    return result


def native_result(path, group, result, candidate, scope):
    """Scheduling safety from existing finalizer facts; no coverage promotion."""
    from tests.maintenance.branch_audit_completion import native_host_context, read_category_run
    from wwise_waapi.versions import WWISE_VERSION_CONTRACTS
    raw = Path(path).read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise BatchError('Native final evidence exceeds the batch bound')
    records = [json.loads(line) for line in raw.splitlines()]
    finals = [(i, r) for i, r in enumerate(records) if r.get('invocation', {}).get('phase') == 'final']
    if len(finals) != 1:
        raise BatchError('Exactly one original native final record is required')
    index, record = finals[0]
    invocation, residual, source = (record[k] for k in ('invocation', 'residual_state', 'source'))
    context = native_host_context(record['host'], 'is_command_line')
    if (record.get('contract') != 'waapi-skill.host-category-evidence/v3'
            or record['candidate'] != candidate or record['version'] != group['version']
            or context != {'host': group['host'], 'version': group['version'],
                           'build': WWISE_VERSION_CONTRACTS[group['version']].build}
            or invocation['selected_test_nodeids'] != group['nodes']
            or invocation['node_outcomes'] != result['node_outcomes']
            or invocation['outcome'] != ('PASS' if result['exit_code'] == 0 else 'FAIL')
            or source.get('project') != scope['project']
            or not source.get('hash_before') or source['hash_before'] != source.get('hash_after')
            or source.get('mtime_before_ns') is None or source['mtime_before_ns'] != source.get('mtime_after_ns')
            or residual.get('process_cleanup') != 'cleaned' or residual.get('residual_processes') != []):
        raise BatchError('Native final source, node, host or cleanup facts differ')
    reference = {**descriptor(path), 'record_index': index, 'nodeid': group['nodes'][0]}
    if result['exit_code'] == 0:
        read_category_run(reference, Path(path).parent)
    elif (residual.get('sandbox') != 'quarantined'
          or not Path(residual.get('quarantine_path', '')).is_dir()):
        raise BatchError('Failed native evidence lacks its retained quarantine')
    category, = [r for r in record['categories'] if r['category'] == 'console-runtime-read-batch']
    observation = Path(category['observation_path'])
    if (not observation.is_relative_to(Path(path).parent)
            or descriptor(observation)['sha256'] != category['observation_sha256']
            or read_json(observation).get('cleanup', {}).get('complete') is not True):
        raise BatchError('Native observation/cleanup is missing or changed')
    return reference


def recover_report(plan, root, report_source):
    """Rebuild a report from saved validated group facts, without dispatch."""
    original_path = Path(plan['recover_from'])
    original = read_json(original_path)
    original_root = original_path.parent
    saved_plan = read_json(original_root / 'plan.json')
    if (original.get('contract') != CONTRACT or original.get('root') != str(original_root)
            or saved_plan['groups'] != plan['groups']):
        raise BatchError('Recovery scope differs from the original owned batch')
    before = original['source_identity']
    indexed = {r['id']: r for r in original['groups']}
    recovered = []
    for group in saved_plan['groups']:
        checkpoint = original_root / 'groups' / group['id'] / 'completion.json'
        if checkpoint.is_file():
            completion = read_json(checkpoint)
            row = completion['row']
            context = validate_context(completion['context'], group, before)
            if (completion.get('contract') != 'waapi-skill.test-batch-completion/v1'
                    or completion.get('source_unchanged') is not True
                    or context['source_identity'] != before or row['spec'] != group
                    or row['context'] != completion['context'] or row['source_commit'] != before['commit']):
                raise BatchError('Saved completion lacks original source/context proof')
            result = checked_result(read_descriptor(row['result']), row['exit_code'])
            if (result.get('batch_context') != completion['context']
                    or row['selection'] != context['selection']
                    or any(not any(matches_node(r['nodeid'], n) for n in context['selection'])
                           or row['node_results'].get(r['nodeid']) != row['result']
                           for r in result['node_outcomes'])):
                raise BatchError('Saved completion differs from actual selected pytest result')
        else:
            # A preflight reused before this interrupted run has no new producer
            # checkpoint. Its already-persisted original references remain the
            # only proof; an attempted but unfinished producer never enters here.
            row = indexed.get(group['id'])
            if row is None or row.get('outcome') != 'REUSED' or row.get('executed') is not False:
                raise BatchError('Missing trusted group completion; producer replay is blocked: ' + group['id'])
        validate_retained_passes(row, [r['nodeid'] for r in row['node_outcomes']
                                      if r['outcome'] == 'PASS'], before)
        for outcome in row['node_outcomes']:
            observed = read_json(read_descriptor(row['node_results'][outcome['nodeid']]))
            checked_result(Path(row['node_results'][outcome['nodeid']]['artifact']), observed['exit_code'])
            if (outcome not in observed['node_outcomes']
                    or not any(matches_node(outcome['nodeid'], n) for n in group['nodes'])):
                raise BatchError('Saved node outcome differs from its original receipt or planned scope')
        expected = 'PASS' if all(r['outcome'] == 'PASS' for r in row['node_outcomes']) else 'FAIL'
        if (not row['node_outcomes'] or (row['outcome'] != expected
                and not (row['outcome'] == 'REUSED' and expected == 'PASS'))):
            raise BatchError('Saved group verdict is not a complete original outcome')
        if group['mode'] != 'nonlive':
            reference = row['native_result']
            if (descriptor(reference['artifact'])['sha256'] != reference['sha256']
                    or native_result(reference['artifact'], group,
                        read_json(read_descriptor(row['result'])), row['source_commit'],
                        before['native_scopes'][group['id']]) != reference):
                raise BatchError('Saved native cleanup/finalizer facts differ')
        recovered.append({**row, 'executed': False, 'original_outcome': expected,
            'outcome': 'REUSED' if expected == 'PASS' else 'FAIL',
            'original_result': row.get('original_result', row['result']),
            'recovered_completion': descriptor(checkpoint) if checkpoint.is_file() else None,
            'reuse_reason': 'Report-only recovery of original validated results; no producer executed'})
    outcome = 'PASS' if all(r['outcome'] == 'REUSED' for r in recovered) else 'FAIL'
    summary = {'contract': CONTRACT, 'outcome': outcome, 'groups': recovered, 'root': str(root),
        'source_identity': before, 'report_source_identity': report_source,
        'recovered_from': descriptor(original_path), 'unknown_impact': [],
        'rerun': [{'group': r['id'], 'nodes': [n['nodeid'] for n in r['node_outcomes'] if n['outcome'] != 'PASS'],
                   'reason': 'original failure retained; not replayed during recovery'}
                  for r in recovered if r['outcome'] == 'FAIL']}
    write_json(root / 'summary.json', summary)
    print(json.dumps({'outcome': outcome, 'recovered_groups': len(recovered),
                      'executed': 0, 'summary': str(root / 'summary.json')}))
    return 0 if outcome == 'PASS' else 1


def run_batch(driver, plan_path):
    root = None
    try:
        plan = read_json(plan_path)
        root = validate_plan(plan, driver.repo_root)
        return execute_batch(driver, plan, root)
    except (BatchError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        error = {'outcome': 'BLOCKED', 'failure_layer': 'batch', 'error': str(exc)}
        if root is not None and root.is_dir():
            target = root / 'summary.json'
            previous = read_json(target) if target.exists() else {'groups': []}
            write_json(target, {**previous, **error})
        print(json.dumps(error))
        return 2


def execute_batch(driver, plan, root):
    if __package__:
        from .test_driver import TestRequest
    else:
        from test_driver import TestRequest
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / 'plan.json', plan)
    if plan.get('recover_from'):
        return recover_report(plan, root, source_identity(driver, plan, include_native_scopes=False))
    frozen = source_identity(driver, plan)
    selections, retained, unknown = affected_selection(driver, plan, frozen)
    preflight = retained_preflight(driver, plan, frozen)
    if preflight is not None:
        retained['collector-preflight'] = preflight
    summary = {'contract': CONTRACT, 'outcome': 'PASS', 'groups': [], 'rerun': [],
               'source_identity': frozen, 'root': str(root), 'unknown_impact': unknown,
               'previous': descriptor(plan['previous']) if plan.get('previous') else None}
    old = {r['id']: r for r in read_json(plan['previous'])['groups']} if plan.get('previous') else {}
    write_json(root / 'summary.json', {**summary, 'outcome': 'RUNNING'})
    if unknown:
        summary.update(outcome='BLOCKED', failure_layer='impact_unknown')
        write_json(root / 'summary.json', summary)
        print(json.dumps({'outcome': 'BLOCKED', 'unknown_impact': unknown, 'summary': str(root / 'summary.json')}))
        return 2
    stopped = False
    for group in plan['groups']:
        blocked = [name for name in group['depends_on'] if not any(
            row['id'] == name and row['outcome'] in {'PASS', 'REUSED'} for row in summary['groups'])]
        if blocked or stopped:
            summary['groups'].append({'id': group['id'], 'outcome': 'BLOCKED',
                'spec': group, 'executed': False, 'node_outcomes': [],
                'failure_layer': 'framework' if stopped else 'prerequisite', 'blocked_by': blocked})
            if summary['outcome'] == 'PASS':
                summary['outcome'] = 'FAIL'
            if blocked and not stopped:
                summary['rerun'].append({'group': group['id'], 'nodes': group['nodes'],
                                         'reason': 'prerequisite'})
            write_json(root / 'summary.json', summary)
            continue
        if group['id'] in retained:
            summary['groups'].append(retained[group['id']])
            write_json(root / 'summary.json', summary)
            continue
        duplicate = next((row for row in summary['groups']
            if row['outcome'] in {'PASS', 'REUSED', 'FAIL'}
            and all(row['spec'][k] == group[k] for k in ('mode', 'version', 'host', 'nodes'))
            and all(sorted(row['spec'][k]) == sorted(group[k]) for k in ('sources', 'depends_on'))), None)
        if duplicate is not None:
            for reference in duplicate['node_results'].values():
                read_descriptor(reference)
            summary['groups'].append({**duplicate, 'id': group['id'], 'spec': group,
                'outcome': 'REUSED' if duplicate['outcome'] != 'FAIL' else 'FAIL', 'executed': False,
                'original_result': duplicate.get('original_result', duplicate['result']),
                'reuse_reason': 'Duplicate compatible selection in this frozen batch'})
            write_json(root / 'summary.json', summary)
            continue
        destination = root / 'groups' / group['id']
        destination.mkdir(parents=True, exist_ok=False)
        result_path = destination / 'result.json'
        previous = driver.environment
        nodes = selections[group['id']]
        context_path = destination / 'context.json'
        write_json(context_path, {'contract': 'waapi-skill.test-batch-context/v1',
            'spec': group, 'selection': nodes, 'source_identity': frozen})
        context_reference = descriptor(context_path)
        driver.environment = {**previous, 'WAAPI_TEST_BATCH_RESULT': str(result_path),
                              'WAAPI_TEST_BATCH_CONTEXT': json.dumps(context_reference),
                              'WAAPI_TEST_BATCH_DUPLICATES': str(len(nodes) - len(set(nodes))),
                              'PYTEST_ADDOPTS': ''}
        driver.environment.pop('PYTEST_PLUGINS', None)
        category_path = destination / 'category.jsonl'
        if group['mode'] != 'nonlive':
            driver.environment.update(WWISE_CATEGORY_EVIDENCE_PATH=str(category_path),
                                      WWISE_SANDBOX_ROOT=str(destination / 'sandboxes'))
        try:
            try:
                code = driver.run(TestRequest(group['version'], group['mode'],
                    (*dict.fromkeys(nodes), '--basetemp', str(destination / 'pytest'),
                     '-o', 'addopts=', '-q', '-ra')))
            except KeyboardInterrupt:
                code = 130
        finally:
            driver.environment = previous
        error = None
        result = {}
        try:
            result = checked_result(result_path, code)
            outcomes = result['node_outcomes']
            phase_fault = any(any(phases.get(p) == 'failed' for p in ('setup', 'teardown'))
                              for phases in result['phase_reports'].values())
            stopped = code not in (0, 1) or phase_fault
            layer = 'framework' if stopped else 'case' if code else None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            outcomes, stopped, layer, error = [], True, 'framework', str(exc)
        native_reference = None
        if group['mode'] != 'nonlive' and not stopped:
            try:
                native_reference = native_result(category_path, group, result, frozen['commit'],
                                                 frozen['native_scopes'][group['id']])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                stopped, layer, error = True, 'evidence', str(exc)
        if source_identity(driver, plan) != frozen:
            stopped, layer, error = True, 'source', 'Frozen batch sources changed'
        state = 'BLOCKED' if stopped else 'FAIL' if code else 'PASS'
        if state == 'PASS' and any(r['outcome'] != 'PASS' for r in outcomes):
            state, layer = 'BLOCKED', 'prerequisite'
        result_reference = descriptor(result_path) if result_path.exists() else None
        node_results = {r['nodeid']: result_reference for r in outcomes}
        prior = old.get(group['id'])
        if prior is not None and nodes != group['nodes']:
            merged = {r['nodeid']: r for r in prior['node_outcomes']}
            node_results = {**prior['node_results'], **node_results}
            merged.update({r['nodeid']: r for r in outcomes})
            outcomes = list(merged.values())
        row = {'id': group['id'], 'node_outcomes': outcomes,
            'spec': group, 'executed': True, 'selection': nodes,
            'outcome': state, 'failure_layer': layer, 'error': error,
            'failures': result.get('failures', []) if result_path.is_file() else [],
            'exit_code': code, 'result': result_reference, 'node_results': node_results,
            'native_result': native_reference, 'source_commit': frozen['commit'],
            'context': context_reference}
        if not stopped and state in {'PASS', 'FAIL'}:
            write_json(destination / 'completion.json', {
                'contract': 'waapi-skill.test-batch-completion/v1', 'context': context_reference,
                'source_unchanged': True, 'row': row})
        summary['groups'].append(row)
        if stopped:
            summary['outcome'] = 'BLOCKED'
        elif state != 'PASS':
            summary['outcome'] = 'FAIL'
            summary['rerun'].append({'group': group['id'],
                'nodes': [r['nodeid'] for r in outcomes if r['outcome'] == 'FAIL'], 'reason': 'failed'})
        write_json(root / 'summary.json', summary)
    write_json(root / 'summary.json', summary)
    print(json.dumps({'outcome': summary['outcome'], 'groups': len(summary['groups']),
        'executed': sum(r['executed'] for r in summary['groups']),
        'rerun': summary['rerun'], 'summary': str(root / 'summary.json')}))
    return 0 if summary['outcome'] == 'PASS' else 2 if stopped else 1

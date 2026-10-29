"""Read an existing ordinary Program run as reviewed aggregate code proof.

Quiet pytest output has no per-node outcomes or Gateway observations. This
adapter preserves that limit; it does not manufacture either kind of receipt.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess


CONTRACT = 'waapi-skill.ordinary-test-run-attachment/v1'
OUTCOME = 'reviewed_aggregate_code_mechanism'
PROOF_SCOPE = {
    'proof_strength': OUTCOME,
    'execution_scope': 'completed_ordinary_test_run_with_reviewed_source_selection',
    'direct_member_execution': 'not_recorded',
    'per_node_outcomes': 'not_recorded',
    'gateway_observations': 'not_recorded',
    'native_effect': 'not_observed',
}
RUNNER_SOURCES = {'ci/test.sh', 'ci/test_driver.py', 'ci/run_program_tests.py',
                  'ci/program-test-nodes.txt'}
PROGRAM_ARGV = ['ci/test.sh', '--mode', 'program', '--', '-q', '-ra']
SUMMARY = re.compile(r'(\d+) passed(?:, (\d+) skipped)? in (\d+(?:\.\d+)?)s(?: \([^\n]+\))?')
SKIP = re.compile(r'SKIPPED \[([1-9]\d*)\] (tests/unit/[^\s:]+\.py):(\d+): (.+)')


def _bytes(descriptor, base):
    if not isinstance(descriptor, dict) or set(descriptor) != {'artifact', 'sha256'}:
        raise ValueError('ordinary run requires exact sealed file descriptors')
    path = Path(descriptor['artifact'])
    raw = (path if path.is_absolute() else base / path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
        raise ValueError('ordinary run artifact digest mismatch')
    return raw


def _source_name(name):
    path = Path(name)
    if (path.is_absolute() or path.as_posix() != name or '..' in path.parts
            or not name or name.startswith('-')):
        raise ValueError('ordinary run source path invalid')
    return path


def _original_source(root, candidate, name, seal):
    _source_name(name)
    result = subprocess.run(['git', 'show', candidate + ':' + name], cwd=root,
                            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode or hashlib.sha256(result.stdout).hexdigest() != seal:
        raise ValueError('ordinary run original candidate/source mismatch')
    return result.stdout.decode('utf-8')


def _validate_direct_skip(row, attribution, original_text, manifest):
    """Only a reviewed, collected test's own static marker owns its skip.

    A body/helper/fixture skip can affect arbitrary consumers in another file.
    Quiet output cannot resolve those consumers, so such origins stay blocked.
    """
    if (int(row[1]) != 1 or not isinstance(attribution, dict)
            or set(attribution) != {'collected_test', 'reviewed_reason'}
            or not isinstance(attribution['reviewed_reason'], str) or not attribution['reviewed_reason'].strip()):
        raise ValueError('ordinary run exact reviewed direct skip consumer required')
    node = attribution['collected_test']
    if (not isinstance(node, str) or not re.fullmatch(r'tests/unit/test_[^\s:\[\]]+\.py::test_\w+', node)):
        raise ValueError('ordinary run exact reviewed direct skip consumer required')
    name, function = node.split('::')
    if name != row[2] or (node not in manifest and name not in manifest):
        raise ValueError('ordinary run skip consumer absent from original collection')
    definitions = [item for item in ast.parse(original_text[name]).body
                   if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == function]
    if len(definitions) != 1 or len(definitions[0].decorator_list) != 1:
        raise ValueError('ordinary run skip origin is not a reviewed direct collected test marker')
    marker = definitions[0].decorator_list[0]
    reason = (next((keyword.value for keyword in marker.keywords if keyword.arg == 'reason'), None)
              if isinstance(marker, ast.Call) else None)
    if (not isinstance(marker, ast.Call) or marker.lineno != int(row[3])
            or ast.unparse(marker.func) not in {'pytest.mark.skip', 'pytest.mark.skipif'}
            or not isinstance(reason, ast.Constant) or reason.value != row[4]):
        raise ValueError('ordinary run skip origin is not a reviewed direct collected test marker')


def read_ordinary_test_run(descriptor, branch, candidate, category, scope_kind, base, binding, root):
    """Return reviewed aggregate support, never an inferred individual PASS."""
    from tests.maintenance.branch_audit_completion import binding_semantics
    from wwise_waapi.native_catalog import canonical_digest

    if category != 'program' or binding.get('ordinary_test_run_attachment') is not True:
        raise ValueError('ordinary run is program code proof only')
    record = json.loads(_bytes(descriptor, base))
    fields = {'contract', 'scope_kind', 'candidate_sha256', 'original_candidate', 'files',
              'original_sources', 'review', 'mechanism', 'skip_lines'}
    if (set(record) not in (fields, fields | {'successful_subset_review'}) or record['contract'] != CONTRACT
            or record['scope_kind'] != scope_kind or record['candidate_sha256'] != candidate
            or not re.fullmatch(r'[0-9a-f]{40}', record['original_candidate'])):
        raise ValueError('ordinary run exact candidate/scope contract required')
    mechanism = record['mechanism']
    if (set(mechanism) != {'branch_id', 'native_route', 'native_shape_sha256',
                           'binding_semantics_sha256', 'selected_tests'}
            or mechanism['branch_id'] != branch['id'] or mechanism['native_route'] != branch['route']
            or mechanism['native_shape_sha256'] != branch['shape_sha256']
            or mechanism['binding_semantics_sha256'] != canonical_digest(binding_semantics(binding))):
        raise ValueError('ordinary run exact reviewed mechanism binding differs')
    files = record['files']
    if set(files) != {'plan', 'result', 'summary', 'log', 'exit'}:
        raise ValueError('ordinary run finalized file set required')
    raw = {name: _bytes(item, base) for name, item in files.items()}
    plan, result, summary = (json.loads(raw[name]) for name in ('plan', 'result', 'summary'))
    original = record['original_candidate']
    argv = plan.get('argv', [])
    focused = (isinstance(argv, list) and 7 <= len(argv) <= 22
        and argv[:6] == ['ci/test.sh', '--mode', 'nonlive', '--', '-q', '-ra']
        and len(set(argv[6:])) == len(argv[6:])
        and all(isinstance(node, str) and re.fullmatch(r'tests/unit/test_[A-Za-z0-9_]+\.py::test_\w+(?:\[[^\s\]]+\])?', node) for node in argv[6:]))
    subset = _review_focused_successful_subset(record, raw, argv, summary, base, root) if record.get('successful_subset_review') else None
    expected_exit, expected_status = (1, 'FAIL') if subset is not None else (0, 'PASS')
    if (plan.get('candidate') != original or (argv != PROGRAM_ARGV and not focused)
            or any(result.get(key) != value for key, value in plan.items())
            or result.get('head_after') != original or result.get('candidate_unchanged') is not True
            or result.get('exit_code') != expected_exit or type(result.get('exit_code')) is not int
            or result.get('git_status') != '' or result.get('remaining_owned_processes') != []
            or result.get('status', 'PASS') != expected_status
            or summary.get('candidate') != original or summary.get('status') != expected_status
            or summary.get('exit_code') != expected_exit or type(summary.get('exit_code')) is not int
            or summary.get('source_unchanged') is not True or summary.get('owned_processes_remaining') != []
            or summary.get('original_receipt') != Path(files['result']['artifact']).name
            or raw['exit'].strip() != str(expected_exit).encode()):
        raise ValueError('ordinary run must be finalized successful unchanged candidate')
    log_hash = hashlib.sha256(raw['log']).hexdigest()
    if result.get('log_sha256') != log_hash or summary.get('log_sha256') != log_hash:
        raise ValueError('ordinary run original log seal differs')
    lines = raw['log'].decode('utf-8').splitlines()
    terminal = FOCUSED_TERMINAL.fullmatch(lines[-1]) if subset is not None and lines else SUMMARY.fullmatch(lines[-1]) if lines else None
    if (terminal is None or sum(bool((FOCUSED_TERMINAL if subset is not None else SUMMARY).fullmatch(line)) for line in lines) != 1
            or ('mode:         nonlive' if focused else 'mode:         program') not in lines
            or ('pytest args:  ' + ' '.join(argv[4:]) if focused else 'pytest args:  -q -ra') not in lines
            or any(token in line for line in lines for token in (('Interrupted', 'KeyboardInterrupt') if subset is not None else ('FAILURES', 'ERRORS', 'Interrupted', 'KeyboardInterrupt')))):
        raise ValueError('ordinary run complete successful pytest summary required')
    passed, skipped, seconds = (subset['passed'], subset['skipped'], subset['seconds']) if subset is not None else (int(terminal[1]), int(terminal[2] or 0), float(terminal[3]))
    if subset is not None and (summary.get('failed') != subset['failed'] or type(summary.get('failed')) is not int
            or summary.get('errors') != subset['errors'] or type(summary.get('errors')) is not int):
        raise ValueError('focused subset effective summary failure/error counts differ')
    if (passed <= 0 or not math.isfinite(seconds) or seconds <= 0
            or summary.get('passed') != passed or type(summary.get('passed')) is not int
            or summary.get('skipped') != skipped or type(summary.get('skipped')) is not int
            or summary.get('pytest_seconds') != seconds
            or not isinstance(result.get('duration_seconds'), (int, float))
            or not math.isfinite(result['duration_seconds']) or result['duration_seconds'] < seconds
            or any(name in result and (type(result[name]) is not int or result[name] != count)
                   for name, count in (('passed', passed), ('skipped', skipped), ('failed', subset['failed'] if subset is not None else 0), ('errors', subset['errors'] if subset is not None else 0)))):
        raise ValueError('ordinary run original counts/duration disagree')
    skip_lines = [line for line in lines if line.startswith('SKIPPED ')]
    skips = [SKIP.fullmatch(line) for line in skip_lines]
    if (record['skip_lines'] != skip_lines or any(row is None for row in skips)
            or sum(int(row[1]) for row in skips) != skipped):
        raise ValueError('ordinary run exact original skip attribution required')

    review = record['review']
    if (set(review) != {'reason', 'selection_reason', 'sources', 'skip_attribution'}
            or not isinstance(review['reason'], str) or not review['reason'].strip()
            or not isinstance(review['selection_reason'], str) or not review['selection_reason'].strip()
            or not isinstance(review['sources'], dict) or not review['sources']
            or set(review['sources']) != set(binding.get('relevant_sources', []))):
        raise ValueError('ordinary run explicit relevant-source/selection review required')
    if (not isinstance(review['skip_attribution'], dict) or set(review['skip_attribution']) != set(skip_lines)
            or len(skip_lines) != len(set(skip_lines))):
        raise ValueError('ordinary run exact reviewed direct skip attribution required')
    selected = mechanism['selected_tests']
    if (not isinstance(selected, list) or not selected or len(set(selected)) != len(selected)
            or any(not isinstance(node, str) or not re.fullmatch(r'tests/unit/[^\s:\[\]]+\.py::test_\w+(?:\[[^\s\]]+\])?', node)
                   for node in selected)):
        raise ValueError('ordinary run exact selected test functions required')
    selected_paths = {node.split('::')[0] for node in selected}
    skip_paths = {row[2] for row in skips}
    if selected_paths & skip_paths:
        raise ValueError('ordinary run selected mechanism has an affected skip')
    required = {binding[key]['source'].partition('#')[0] for key in ('construction', 'validation', 'verifier')}
    if not required | selected_paths <= review['sources'].keys():
        raise ValueError('ordinary run relevant source closure omits mechanism/tests')
    originals = record['original_sources']
    if set(originals) != set(review['sources']) | RUNNER_SOURCES | skip_paths:
        raise ValueError('ordinary run original runner/test/skip source closure differs')
    original_text = {name: _original_source(root, original, name, seal) for name, seal in originals.items()}
    for name, item in review['sources'].items():
        path = root / _source_name(name)
        if (not isinstance(item, dict) or set(item) != {'original_sha256', 'current_sha256', 'reviewed_reason'}
                or item['original_sha256'] != originals[name]
                or not isinstance(item['reviewed_reason'], str) or not item['reviewed_reason'].strip()
                or path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
                or hashlib.sha256(path.read_bytes()).hexdigest() != item['current_sha256']):
            raise ValueError('ordinary run reviewed current relevant source changed')
    manifest = {line for line in original_text['ci/program-test-nodes.txt'].splitlines()
                if line and not line.startswith('#')}
    if focused and not set(selected) <= set(argv[6:]):
        raise ValueError('ordinary focused run does not select the reviewed mechanism')
    for node in selected:
        name, function = node.split('::')
        function = function.split('[', 1)[0]
        if not focused and node not in manifest and name not in manifest:
            raise ValueError('ordinary run selected test absent from original manifest')
        tree = ast.parse(original_text[name])
        if not any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == function
                   for item in tree.body):
            raise ValueError('ordinary run selected test absent from original source')
    consumers = []
    for row in skips:
        attribution = review['skip_attribution'][row[0]]
        _validate_direct_skip(row, attribution, original_text, manifest)
        consumers.append(attribution['collected_test'])
    if len(consumers) != len(set(consumers)):
        raise ValueError('ordinary run skip has unknown or duplicate affected consumers')
    return OUTCOME, None


FOCUSED_TERMINAL = re.compile(r'(?:(\d+) failed, )?(\d+) passed(?:, (\d+) skipped)?(?:, (\d+) errors?)? in (\d+(?:\.\d+)?)s(?: \([^\n]+\))?')


def _review_focused_successful_subset(record, raw, argv, summary, base, root):
    """Qualify a finite successful subset while retaining the original FAIL."""
    review = json.loads(_bytes(record['successful_subset_review'], base))
    fields = {'contract', 'collection', 'collection_source_review', 'collected_nodes',
        'failed_nodes', 'error_nodes', 'successful_nodes', 'file_sha256', 'reviewed_reason'}
    if (set(review) not in (fields, fields | {'original_summary'})
            or review['contract'] != 'waapi-skill.focused-successful-subset-review/v1'
            or not isinstance(review['reviewed_reason'], str) or not review['reviewed_reason'].strip()
            or review['file_sha256'] != {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
            or argv[:6] != ['ci/test.sh', '--mode', 'nonlive', '--', '-q', '-ra']
            or review['collected_nodes'] != argv[6:] or len(set(argv[6:])) != len(argv[6:])):
        raise ValueError('closed exact focused successful-subset review required')
    collection = _bytes(review['collection'], base).decode('utf-8').splitlines()
    collected = [line for line in collection if re.fullmatch(r'tests/unit/test_[A-Za-z0-9_]+\.py::test_\w+(?:\[[^\s\]]+\])?', line)]
    count = re.fullmatch(r'(\d+) tests? collected in \d+(?:\.\d+)?s', collection[-1] if collection else '')
    if collected != argv[6:] or count is None or int(count[1]) != len(collected):
        raise ValueError('original exact complete focused collection required')
    source_review = review['collection_source_review']
    required = {node.split('::')[0] for node in collected} | {'tests/conftest.py', 'pyproject.toml', 'ci/test.sh', 'ci/test_driver.py'}
    if (set(source_review) != {'collection_basis', 'run_candidate', 'sources', 'reviewed_reason'}
            or source_review['run_candidate'] != record['original_candidate']
            or not re.fullmatch(r'[0-9a-f]{40}', source_review['collection_basis'])
            or not source_review['reviewed_reason'] or set(source_review['sources']) != required):
        raise ValueError('focused collection definition/config source review required')
    for name, seal in source_review['sources'].items():
        _original_source(root, source_review['collection_basis'], name, seal)
        _original_source(root, record['original_candidate'], name, seal)
    lines = raw['log'].decode('utf-8').splitlines()
    terminal = FOCUSED_TERMINAL.fullmatch(lines[-1] if lines else '')
    if (terminal is None or sum(bool(FOCUSED_TERMINAL.fullmatch(line)) for line in lines) != 1
            or any(token in line for line in lines for token in ('Interrupted', 'KeyboardInterrupt', 'INTERNALERROR', 'INTERNAL ERROR', 'ERROR collecting', 'Fatal Python error'))):
        raise ValueError('focused subset requires complete ordinary-failure terminal output')
    failed, passed, skipped, errors = int(terminal[1] or 0), int(terminal[2]), int(terminal[3] or 0), int(terminal[4] or 0)
    seconds = float(terminal[5])
    failed_nodes = [line.split()[1] for line in lines if line.startswith('FAILED ')]
    error_nodes = [line.split()[1] for line in lines if line.startswith('ERROR ')]
    phases = []
    for line in lines:
        phase = re.fullmatch(r'_+ ERROR at (setup|teardown) of (.+?) _+', line)
        if phase:
            matches = [node for node in collected if node.split('::')[1] == phase[2]]
            if len(matches) != 1:
                raise ValueError('ambiguous focused error phase attribution')
            phases.append({'nodeid': matches[0], 'phase': phase[1]})
    if (not failed + errors or skipped or len(failed_nodes) != failed or len(error_nodes) != errors
            or len(set(failed_nodes)) != failed or len(set(error_nodes)) != errors
            or set(failed_nodes + error_nodes) - set(collected)
            or review['failed_nodes'] != failed_nodes or review['error_nodes'] != phases
            or {row['nodeid'] for row in phases} != set(error_nodes) or len(phases) != errors
            or len(collected) != passed + failed + sum(row['phase'] == 'setup' for row in phases)):
        raise ValueError('focused failure/error/count/phase scope differs')
    successful = [node for node in collected if node not in set(failed_nodes + error_nodes)]
    if (not successful or review['successful_nodes'] != successful
            or not set(record['mechanism']['selected_tests']) <= set(successful)):
        raise ValueError('selected focused mechanism has failed or incomplete phases')
    if 'original_summary' in review:
        original = json.loads(_bytes(review['original_summary'], base))
        corrected = {**original, 'passed': passed, 'failed': failed, 'errors': errors,
                     'skipped': skipped, 'pytest_seconds': seconds}
        if summary != corrected:
            raise ValueError('focused summary successor changed original metadata or terminal counts')
    return {'passed': passed, 'failed': failed, 'errors': errors, 'skipped': skipped, 'seconds': seconds}

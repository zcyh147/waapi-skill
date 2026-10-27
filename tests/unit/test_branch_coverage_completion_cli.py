"""Completion is observed at the existing audit CLI, using real Gateway receipts.

The sealed ping scope proves the ledger mechanics and injected-client program
behavior only. It deliberately grants no product/native execution credit.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage


def evaluate_snapshot(ping_scope, bindings, *, scope=None, requirements=None):
    path, _, inventory, _ = ping_scope
    scope = json.loads((path / "scope.json").read_text()) if scope is None else scope
    kwargs = {} if requirements is None else {"requirements_document": requirements}
    return evaluate_coverage(audit.ROOT, inventory, bindings, digest=audit.digest, scope=scope, evidence_base=path, **kwargs)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Reviewed expectation, independent of the capture validator and current policy.
CLI_PROGRAM_ONLY_METADATA_IDS = {
    version + '|wwise-console|' + build + '|function|ak.wwise.core.object.getPropertyInfo|/resultSchema/properties/default/@presence/absent'
    for version, build in (
        ('2021.1', '2021.1.14.8108'), ('2022.1', '2022.1.19.8584'),
        ('2023.1', '2023.1.19.8928'), ('2024.1', '2024.1.13.9056'),
        ('2025.1', '2025.1.7.9143'))
}


def expected_cli_categories(identity):
    if identity in CLI_PROGRAM_ONLY_METADATA_IDS:
        return ['program']
    return ['live_metadata', 'program'] if '|function|ak.wwise.core.object.getPropertyInfo|' in identity else ['native', 'program']


def test_cli_metadata_category_expectations_cover_exact_reviewed_five_and_other_sixty():
    policy = audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json')['branches']
    metadata = {identity: requirement for identity, requirement in policy.items()
                if '|function|ak.wwise.core.object.getPropertyInfo|' in identity}
    assert len(metadata) == 65
    assert {identity for identity, requirement in metadata.items() if requirement['categories'] == ['program']} == CLI_PROGRAM_ONLY_METADATA_IDS
    assert len(set(metadata) - CLI_PROGRAM_ONLY_METADATA_IDS) == 60
    for identity, requirement in metadata.items():
        assert expected_cli_categories(identity) == sorted(requirement['categories'])


def test_default_product_inputs_select_portable_stale_receipt_without_business_credit(tmp_path, capsys, monkeypatch):
    import shutil
    original_open = Path.open
    def portable_open(path, *args, **kwargs):
        assert '/waapi-query-coverage/' not in str(path), 'Historical workstation path was opened'
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', portable_open)
    output = tmp_path / 'default.json'
    argv = ['--output', str(output), '--require-complete']
    assert audit.main(argv) == 2
    capsys.readouterr()
    default = audit.load(output)['native_coverage']
    branch_id = ('2025.1|wwise-console|2025.1.7.9143|function|'
                 'ak.wwise.cli.moveMediaIdsToSingleFile|/resultSchema')
    branch = next(row for row in default['obligations'] if row['id'] == branch_id)
    assert branch['state'] == 'implemented_unverified'
    assert branch['requirements'] == ['native', 'program']
    assert branch['evidence_results']['program']['outcome'] == 'missing'
    assert branch['evidence_results']['native']['outcome'] == 'missing'
    assert default['completion']['complete'] is False
    assert default['completion']['obligations'] == 272313
    # Existing625 selected leaves plus exact26 Source leaves. Metadata65 and
    # Source26 have their own complete categories; Topic559 still lacks native.
    assert default['completion']['states'] == {'approved_exclusion': 116,
        'verified': 91, 'implemented_unverified': 560, 'unresolved': 271546}
    assert audit.main([*argv, '--check']) == 2
    capsys.readouterr()
    copied = tmp_path / 'relocated-product'
    shutil.copytree(audit.ROOT / 'tests/fixtures/branch-evidence/product', copied)
    index = audit.load(audit.ROOT / 'docs/branch-coverage-evidence-index.json')
    index['base'] = 'relocated-product'
    index_path = tmp_path / 'relocated-index.json'
    write_json(index_path, index)
    selected, _, _ = audit.portable_binding_inputs(index_path,
        audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json'))
    expected_families = {('media', '2025.1'): 1,
        **{('source', version): count for version, count in
            (('2021.1', 4), ('2022.1', 4), ('2023.1', 6), ('2024.1', 6), ('2025.1', 6))},
        **{('metadata', version): 13 for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')},
        **{('topic', version): count for version, count in
            (('2021.1', 79), ('2022.1', 112), ('2023.1', 116), ('2024.1', 116), ('2025.1', 136))}}
    def family(identity):
        return ('source' if '|function|ak.wwise.core.object.copy|' in identity else 'topic' if '|topic|' in identity else 'metadata' if
            '|function|ak.wwise.core.object.getPropertyInfo|' in identity else 'media', identity.split('|')[0])
    assert Counter(family(identity) for identity in selected['bindings']) == expected_families
    assert sum('|function|ak.wwise.core.object.copy|' in identity for identity in selected['bindings']) == 26
    selected_rows = {row['id']: row for row in default['obligations'] if row['state'] in {'verified', 'implemented_unverified'}}
    assert set(selected_rows) == set(selected['bindings'])
    for identity, row in selected_rows.items():
        expected_categories = expected_cli_categories(identity)
        assert row['requirements'] == expected_categories
        assert row['evidence_results']['program']['outcome'] == ('missing' if family(identity)[0] == 'media' else 'passed')
    program_index = deepcopy(index)
    program_index.pop('metadata_attachments')
    program_index_path = tmp_path / 'program-only-index.json'
    write_json(program_index_path, program_index)
    program_only, _, _ = audit.portable_binding_inputs(program_index_path,
        audit.load(audit.ROOT / 'docs/branch-coverage-requirements.json'))
    assert set(program_only['bindings']) == set(selected['bindings'])
    strengthened = Counter()
    for identity, binding in selected['bindings'].items():
        baseline = deepcopy(binding)
        if 'live_metadata' in baseline['evidence']:
            strengthened[identity.split('|')[0]] += 1
            baseline['evidence'].pop('live_metadata')
            baseline.pop('category_inputs')
        assert set(program_only['bindings'][identity]['evidence']) == ({'program', 'native'} if family(identity)[0] == 'source' else {'program'})
        assert baseline == program_only['bindings'][identity]
    assert strengthened == {version: 12 for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1')}
    explicit_bindings = copied / 'all.bindings.json'
    write_json(explicit_bindings, selected)
    explicit = tmp_path / 'explicit.json'
    assert audit.main(['--bindings', str(explicit_bindings),
        '--output', str(explicit), '--require-complete']) == 2
    capsys.readouterr()
    actual = audit.load(explicit)['native_coverage']
    assert actual['obligations'] == default['obligations']
    assert actual['bindings_sha256'] == default['bindings_sha256']
    assert actual['requirements_sha256'] == default['requirements_sha256']


@pytest.mark.parametrize('damage,reason', [
    ('duplicate', 'duplicate exact branch'), ('program-byte', 'artifact digest mismatch'),
    ('missing-descriptor', 'original descriptors missing'), ('projection', 'changed more than')])
def test_cli_rejects_damaged_portable_inputs_without_omitting_them(tmp_path, capsys, damage, reason):
    import shutil
    base = tmp_path / 'product'
    shutil.copytree(audit.ROOT / 'tests/fixtures/branch-evidence/product', base)
    index = json.loads((audit.ROOT / 'docs/branch-coverage-evidence-index.json').read_bytes())
    index['base'] = 'product'
    entry = index['entries'][0]
    if damage == 'duplicate':
        index['entries'].append({**deepcopy(entry), 'id': 'second-authority-for-same-branch'})
    elif damage == 'program-byte':
        program = base / entry['origin']['program']['artifact']
        program.write_bytes(program.read_bytes() + b' ')
    elif damage == 'missing-descriptor':
        del entry['origin']['program']
    else:
        projection = base / entry['bindings']['artifact']
        altered = json.loads(projection.read_bytes())
        next(iter(altered['bindings'].values()))['input']['gateway_argv'][-1] = 'forged-transaction'
        entry['bindings']['sha256'] = write_json(projection, altered)
    source = tmp_path / 'index.json'
    write_json(source, index)
    output = tmp_path / 'ledger.json'
    assert audit.main(['--binding-index', str(source), '--output', str(output), '--require-complete']) == 1
    message = json.loads(capsys.readouterr().out)
    assert message['structural_check'] == 'invalid' and reason in message['errors'][0]
    assert not output.exists()


def test_default_portable_input_keeps_absent_explicit_requirement_unresolved(tmp_path, capsys):
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    requirements = tmp_path / 'requirements.json'
    write_json(requirements, policy)
    output = tmp_path / 'incomplete.json'
    assert audit.main(['--requirements', str(requirements), '--output', str(output), '--require-complete']) == 2
    message = json.loads(capsys.readouterr().out)
    assert message['structural_check'] == 'consistent' and message['business_coverage'] == 'incomplete'
    coverage = audit.load(output)['native_coverage']
    branch = next(row for row in coverage['obligations'] if row['id'] ==
        '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.cli.moveMediaIdsToSingleFile|/resultSchema')
    assert branch['state'] == 'unresolved'
    assert branch['reasons'] == ['reviewed exact branch evidence requirements missing or stale']
    assert branch['requirements'] == [] and branch['evidence_results'] == {}
    assert coverage['requirements_sha256'] == audit.digest(policy)
    assert coverage['completion']['complete'] is False
    assert coverage['completion']['states'] == {'approved_exclusion': 116, 'unresolved': 272197}


@pytest.fixture(scope='module')
def ping_scope(tmp_path_factory):
    path = tmp_path_factory.mktemp('complete-controlled-scope')
    spec = importlib.util.spec_from_file_location('branch_completion_gateway', audit.ROOT / 'skills/waapi-skill/scripts/gateway.py')
    gateway = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gateway
    spec.loader.exec_module(gateway)
    inventory = audit.build_inventory()
    native = inventory['native_coverage']
    pointers = {'/argsSchema', '/argsSchema/additionalProperties', '/optionsSchema', '/optionsSchema/additionalProperties',
                '/resultSchema', '/resultSchema/additionalProperties', '/resultSchema/properties/isAvailable',
                '/argsSchema/@empty/object', '/optionsSchema/@empty/object',
                '/resultSchema/properties/isAvailable/@boolean/true', '/resultSchema/properties/isAvailable/@boolean/false'}
    routes = [r for r in native['routes'] if r['uri'] == 'ak.wwise.core.ping']
    assert {(r['version'], r['host']) for r in routes} == {
        ('2024.1', 'wwise-console'), ('2024.1', 'wwise-authoring'),
        ('2025.1', 'wwise-console'), ('2025.1', 'wwise-authoring')}
    obligations = [b for b in native['obligations'] if b['route'] in {r['id'] for r in routes}]
    assert all({b['pointer'] for b in obligations if b['route'] == r['id']} == pointers for r in routes)
    scope = {'contract': 'waapi-skill.controlled-branch-scope/v1', 'id': 'ping-program-mechanics',
             'route_ids': sorted(r['id'] for r in routes), 'obligation_ids': sorted(b['id'] for b in obligations),
             'native_catalogs': native['catalogs'], 'requirements': ['program'],
             'credit': 'controlled_program_only'}
    scope_sha = write_json(path / 'scope.json', scope)
    bindings = {}
    for route in routes:
        selected = [b for b in obligations if b['route'] == route['id']]
        env = {'WAAPI_SKILL_CONFIG_PATH': str(path / (route['version'] + route['host'] + '-config.json')),
               'WWISE_EVIDENCE_DIR': str(path / 'evidence')}
        assert gateway.execute_gateway(['config-set', '--wwise-version', route['version'], '--waapi-port', '31337', '--project-modification-policy', 'read_only'], env=env)[0] == 0
        code, disclosed = gateway.execute_gateway(['request-schema', route['uri']], env=env)
        assert code == 0 and disclosed['input_shape'] == 'zero'
        argv = disclosed['continuation']['gateway_argv']
        for available in (True, False):
            case_branches = [b for b in selected if b['pointer'].endswith('/@boolean/false') == (not available)]
            native_calls = []
            class Client:
                def call(self, uri, args=None, options=None):
                    if uri == 'ak.wwise.core.getInfo':
                        year, major, minor, build = map(int, route['build'].split('.'))
                        return {'displayName': 'Wwise', 'isCommandLine': route['host'] == 'wwise-console',
                                'version': {'year': year, 'major': major, 'minor': minor, 'build': build, 'displayName': route['build']}}
                    if uri == 'ak.wwise.core.getProjectInfo':
                        return {'id': '{11111111-1111-1111-1111-111111111111}', 'name': 'Fixture', 'path': '\\Fixture'}
                    assert uri == route['uri']
                    assert args in ({}, None) and options in ({}, None)
                    native_calls.append({'uri': uri, 'args': args or {}, 'options': options or {}, 'result': {'isAvailable': available}})
                    return {'isAvailable': available}
                def disconnect(self):
                    pass
            code, payload = gateway.execute_gateway(argv, env=env, client_factory=lambda _: Client())
            assert code == 0 and payload['ok'] is True, payload
            record = {'candidate_sha256': native.get('candidate_sha256', 'not-implemented'), 'scope_kind': 'controlled',
                      'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': 'test_ping_public_gateway', 'outcome': 'PASS'}]},
                      'gateway': {'argv': argv, 'exit_code': code, 'payload': payload},
                      'native_call': native_calls[-1],
                      'artifacts': [{'artifact': payload['call']['evidence_path'], 'sha256': hashlib.sha256(Path(payload['call']['evidence_path']).read_bytes()).hexdigest()}],
                      'branch_assertions': {b['id']: {'native_shape_sha256': b['shape_sha256'], 'native_route': route['id'],
                          'checks': [{'pointer': '/native_call/' + ('args' if b['pointer'].startswith('/argsSchema') else 'options' if b['pointer'].startswith('/optionsSchema') else 'result/isAvailable' if '/properties/isAvailable' in b['pointer'] else 'result'),
                                      'equals': {} if b['pointer'].startswith(('/argsSchema', '/optionsSchema')) else available if '/properties/isAvailable' in b['pointer'] else {'isAvailable': available}},
                                     {'pointer': '/gateway/payload/agent_result', 'equals': payload['agent_result']}]}
                          for b in case_branches}}
            receipt = path / (route['version'] + route['host'] + '-' + str(available) + '-receipt.json')
            receipt_sha = write_json(receipt, record)
            public = next(r for r in inventory['routes'] if r['id'] == route['public_route'])
            for branch in case_branches:
                bindings[branch['id']] = {'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
                    'public_route': route['public_route'], 'public_route_sha256': audit.digest(public),
                    'input': {'gateway_argv': argv, 'selector': 'zero-input'},
                    'construction': {'source': 'skills/waapi-skill/scripts/gateway.py#preflight_typed_zero_input', 'selector': branch['pointer']},
                    'validation': {'source': public['verifier_source'][0], 'selector': branch['pointer']},
                    'verifier': {'source': public['verifier_source'][0], 'selector': branch['pointer']},
                    'evidence': {'program': {'artifact': str(receipt), 'sha256': receipt_sha, 'nodeid': 'test_ping_public_gateway'}}}
    evidence = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': bindings}
    write_json(path / 'bindings.json', evidence)
    return path, scope_sha, inventory, evidence


def test_cli_completes_sealed_controlled_scope_from_public_gateway_receipts(ping_scope, capsys):
    path, seal, _, _ = ping_scope
    result = audit.main(['--output', str(path / 'ledger.json'), '--controlled-scope', str(path / 'scope.json'),
                         '--scope-sha256', seal, '--bindings', str(path / 'bindings.json'), '--require-complete'])
    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report['business_coverage'] == 'complete'
    assert report['scope_kind'] == 'controlled'
    assert report['product_coverage'] == 'not_evaluated'


def representative_ping_inputs(ping_scope):
    """One selected public receipt per host/build; every legal mapping stays exact."""
    path, _, inventory, original = ping_scope
    bindings = deepcopy(original)
    native = inventory['native_coverage']
    scope = json.loads((path / 'scope.json').read_bytes())
    branches = {row['id']: row for row in native['obligations']
                if row['route'] in scope['route_ids']}
    requirements = {'contract': 'waapi-skill.branch-evidence-requirements/v1',
                    'branches': {}, 'representative_mechanisms': {}}
    for route in scope['route_ids']:
        members = {key: binding for key, binding in bindings['bindings'].items()
                   if branches[key]['route'] == route}
        selected = next(key for key in members if key.endswith('/@boolean/true'))
        mechanism = 'ping:' + route
        for key, binding in members.items():
            binding['representative_mechanism'] = mechanism
            if key != selected:
                binding['evidence'] = {}
            requirements['branches'][key] = {
                'native_shape_sha256': branches[key]['shape_sha256'],
                'categories': ['program'], 'reason': 'Controlled shared zero-input mechanism',
                'representative_mechanism': mechanism}
        sources = {binding[key]['source'].split('#')[0]
                   for binding in members.values() for key in ('construction', 'validation', 'verifier')}
        requirements['representative_mechanisms'][mechanism] = {
            'contract': 'waapi-skill.representative-branch-mechanism/v1',
            'scope_kind': 'controlled', 'candidate_sha256': native['candidate_sha256'],
            'reviewed_reason': 'Same zero-input construction and bounded Boolean transport; sibling values are mapped, not observed.',
            'sources': {source: hashlib.sha256((audit.ROOT / source).read_bytes()).hexdigest()
                        for source in sources},
            'members': {key: {'native_route': route,
                'native_shape_sha256': branches[key]['shape_sha256'],
                'mapping_sha256': audit.digest({k: v for k, v in binding.items() if k != 'evidence'})}
                for key, binding in members.items()},
            'selected_proofs': {'program': [selected]}}
    return bindings, requirements


def test_cli_accepts_exact_mapped_unexecuted_siblings_with_selected_mechanism_proof(ping_scope, tmp_path, capsys):
    path, seal, _, _ = ping_scope
    bindings, requirements = representative_ping_inputs(ping_scope)
    write_json(tmp_path / 'bindings.json', bindings)
    write_json(tmp_path / 'requirements.json', requirements)
    output = tmp_path / 'ledger.json'
    assert audit.main(['--output', str(output), '--controlled-scope', str(path / 'scope.json'),
        '--scope-sha256', seal, '--bindings', str(tmp_path / 'bindings.json'),
        '--requirements', str(tmp_path / 'requirements.json'), '--require-complete']) == 0
    assert json.loads(capsys.readouterr().out)['product_coverage'] == 'not_evaluated'
    ledger = audit.load(output)['native_coverage']
    assert ledger['completion']['complete'] is True
    direct = [row for row in ledger['obligations'] if row['id'].endswith('/@boolean/true')]
    reused = [row for row in ledger['obligations'] if row not in direct]
    assert len(direct) == 4 and len(reused) == 40
    assert all(row['evidence_results']['program']['outcome'] == 'passed' for row in direct)
    assert all(row['evidence_results']['program']['outcome'] == 'reviewed_representative_mechanism' for row in reused)
    assert all(row['representative_proof']['direct_member_execution'] == 'not_observed'
               and row['representative_proof']['verification_strength'] == 'reviewed_shared_mechanism'
               and row['state'] == 'mapped_with_representative_proof'
               for row in reused)
    assert all(not bindings['bindings'][row['id']]['evidence'] for row in reused)


@pytest.mark.parametrize('damage', [
    'missing-legal-choice', 'missing-route', 'missing-version', 'missing-mapping',
    'unsupported-ordinary-function', 'false-native-absence', 'missing-selected-proof',
    'stale-source', 'stale-candidate', 'wrong-shape', 'wrong-member-version',
    'unreviewed-member', 'conflicting-link', 'open-review'])
def test_representative_proof_keeps_mapping_and_selected_evidence_fail_closed(ping_scope, monkeypatch, damage):
    path, _, inventory, _ = ping_scope
    bindings, requirements = representative_ping_inputs(ping_scope)
    mechanism = next(iter(requirements['representative_mechanisms']))
    review = requirements['representative_mechanisms'][mechanism]
    selected = review['selected_proofs']['program'][0]
    sibling = next(key for key in review['members'] if key.endswith('/@boolean/false'))
    scope = json.loads((path / 'scope.json').read_bytes())
    if damage == 'missing-legal-choice':
        del bindings['bindings'][sibling]
    elif damage == 'missing-route':
        del bindings['bindings'][sibling]['public_route']
    elif damage == 'missing-version':
        scope['route_ids'] = [route for route in scope['route_ids'] if not route.startswith('2025.1|')]
    elif damage == 'missing-mapping':
        del bindings['bindings'][sibling]['validation']
        # Re-sign the proposed review so the ordinary mapping validator, not
        # merely a stale outer digest, must still refuse implementation credit.
        review['members'][sibling]['mapping_sha256'] = audit.digest(
            {k: v for k, v in bindings['bindings'][sibling].items() if k != 'evidence'})
    elif damage == 'unsupported-ordinary-function':
        route = next(route for route in inventory['native_coverage']['routes']
                     if route['id'] == review['members'][sibling]['native_route'])
        monkeypatch.setitem(route, 'public_route', None)
    elif damage == 'false-native-absence':
        bindings['bindings'][sibling]['disposition'] = 'native_absence'
        bindings['bindings'][sibling]['alternatives_considered'] = ['claimed absence']
    elif damage == 'missing-selected-proof':
        bindings['bindings'][selected]['evidence'] = {}
    elif damage == 'stale-source':
        review['sources'][next(iter(review['sources']))] = '0' * 64
    elif damage == 'stale-candidate':
        review['candidate_sha256'] = '0' * 64
    elif damage == 'wrong-shape':
        review['members'][sibling]['native_shape_sha256'] = '0' * 64
    elif damage == 'wrong-member-version':
        review['members'][sibling]['native_route'] = '2021.1|wwise-console|2021.1.14.8108|function|ak.wwise.core.ping'
    elif damage == 'unreviewed-member':
        del review['members'][sibling]
    elif damage == 'conflicting-link':
        requirements['branches'][sibling]['representative_mechanism'] = 'unreviewed'
    else:
        review['ignore_missing_evidence'] = True
    try:
        result = evaluate_snapshot(ping_scope, bindings, scope=scope, requirements=requirements)
    except ValueError:
        return  # Structural corruption is an invalid ledger, never completion.
    assert result['completion']['complete'] is False


def test_representative_proof_preserves_failed_direct_sibling_receipt(ping_scope):
    bindings, requirements = representative_ping_inputs(ping_scope)
    review = next(iter(requirements['representative_mechanisms'].values()))
    selected = review['selected_proofs']['program'][0]
    sibling = next(key for key in review['members'] if key.endswith('/@boolean/false'))
    # The selected true receipt cannot prove false. Its failed direct assertion
    # must remain a failure rather than falling back to representative credit.
    bindings['bindings'][sibling]['evidence'] = deepcopy(bindings['bindings'][selected]['evidence'])
    result = evaluate_snapshot(ping_scope, bindings, requirements=requirements)
    row = next(row for row in result['obligations'] if row['id'] == sibling)
    assert result['completion']['complete'] is False
    assert row['state'] == 'implemented_unverified'
    assert row['evidence_results']['program']['outcome'] == 'missing'
    assert 'representative_proof' not in row


def test_parent_pass_cannot_complete_descendant_branches(ping_scope, tmp_path, capsys):
    path, seal, _, evidence = ping_scope
    damaged = deepcopy(evidence)
    for index, binding in enumerate(damaged['bindings'].values()):
        receipt = json.loads(Path(binding['evidence']['program']['artifact']).read_text())
        for assertion in receipt['branch_assertions'].values():
            assertion['checks'] = [{'pointer': '/gateway/payload/ok', 'equals': True}]
        target = tmp_path / f'receipt-{index}.json'
        binding['evidence']['program'].update(artifact=str(target), sha256=write_json(target, receipt))
    write_json(tmp_path / 'bindings.json', damaged)
    result = evaluate_snapshot(ping_scope, damaged)
    assert result['completion']['complete'] is False


@pytest.mark.parametrize('damage', ['missing-mapping', 'public-route', 'public-input', 'public-argv', 'construction',
                                    'verifier', 'parent-selector', 'required-evidence', 'test-filename',
                                    'native-absence', 'broaden-exclusion', 'stale-candidate', 'native-shape',
                                    'equivalence', 'missing-artifact', 'artifact-hash', 'asserted-branch', 'forged-native'])
def test_completion_loses_credit_when_exact_binding_or_required_evidence_is_damaged(ping_scope, tmp_path, capsys, damage):
    path, seal, _, original = ping_scope
    damaged = deepcopy(original)
    branch_id = next(k for k in damaged['bindings'] if k.endswith('/properties/isAvailable'))
    binding = damaged['bindings'][branch_id]
    if damage == 'missing-mapping':
        del damaged['bindings'][branch_id]
    elif damage in ('public-route', 'public-input', 'construction', 'verifier'):
        binding.pop({'public-route': 'public_route', 'public-input': 'input'}.get(damage, damage))
    elif damage == 'public-argv':
        binding['input']['gateway_argv'] = ['not-a-public-command']
    elif damage == 'parent-selector':
        binding['construction']['selector'] = '/resultSchema'
    elif damage == 'required-evidence':
        binding['evidence'] = {}
    elif damage == 'test-filename':
        binding['evidence'] = {'program': {'artifact': 'tests/unit/test_branch_coverage_completion_cli.py'}}
    elif damage == 'native-absence':
        binding.update(disposition='native_absence', alternatives_considered=['missing Skill is not absence'])
    elif damage == 'broaden-exclusion':
        binding['disposition'] = 'approved_exclusion'
    elif damage == 'forged-native':
        receipt = json.loads(Path(binding['evidence']['program']['artifact']).read_text())
        receipt['evidence_kind'] = 'native_execution'
        receipt['lifecycle'] = {'phase': 'final', 'source_unchanged': True, 'residual_processes': [], 'cleanup': 'complete'}
        target = tmp_path / 'fake-native.json'
        binding['additional_requirements'] = ['native']
        binding['evidence']['native'] = {'artifact': str(target), 'sha256': write_json(target, receipt), 'nodeid': 'test_ping_public_gateway'}
    elif damage == 'native-shape':
        binding['native_shape_sha256'] = '0' * 64
    elif damage == 'missing-artifact':
        binding['evidence']['program']['artifact'] = str(tmp_path / 'not-present.json')
    elif damage == 'artifact-hash':
        binding['evidence']['program']['sha256'] = '0' * 64
    else:
        receipt = json.loads(Path(binding['evidence']['program']['artifact']).read_text())
        if damage == 'asserted-branch':
            receipt['branch_assertions'].pop(branch_id)
        else:
            receipt['candidate_sha256'] = '0' * 64
            if damage == 'equivalence':
                binding['equivalence'] = {'same_family': True, 'status': 'PASS'}
        target = tmp_path / 'receipt.json'
        binding['evidence']['program'].update(artifact=str(target), sha256=write_json(target, receipt))
    write_json(tmp_path / 'bindings.json', damaged)
    if damage != 'public-argv':
        assert evaluate_snapshot(ping_scope, damaged)['completion']['complete'] is False
        return
    assert audit.main(['--output', str(tmp_path / 'ledger.json'), '--controlled-scope', str(path / 'scope.json'),
        '--scope-sha256', seal, '--bindings', str(tmp_path / 'bindings.json'), '--require-complete']) == 2
    assert json.loads(capsys.readouterr().out)['business_coverage'] == 'incomplete'


@pytest.mark.parametrize('damage', ['empty', 'branch', 'version', 'same-count-uri', 'catalog-seal'])
def test_controlled_scope_cannot_launder_removed_native_obligations(ping_scope, tmp_path, capsys, damage):
    path, seal, _, _ = ping_scope
    scope = json.loads((path / 'scope.json').read_text())
    if damage == 'empty':
        scope['route_ids'] = []
        scope['obligation_ids'] = []
    elif damage == 'branch':
        scope['obligation_ids'].pop()
    elif damage == 'version':
        scope['native_catalogs'] = {k: v for k, v in scope['native_catalogs'].items() if not k.startswith('2024.1')}
    elif damage == 'same-count-uri':
        scope['route_ids'][0] = scope['route_ids'][0].replace('core.ping', 'core.inventedSameCount')
    else:
        key = next(iter(scope['native_catalogs']))
        scope['native_catalogs'][key] = '0' * 64
    scope_path = tmp_path / 'scope.json'
    # Even a newly sealed malformed scope cannot conceal missing members.
    changed_seal = write_json(scope_path, scope)
    with pytest.raises(ValueError):
        evaluate_snapshot(ping_scope, ping_scope[3], scope=scope)


def test_environment_blocker_does_not_turn_missing_implementation_into_verified(ping_scope, tmp_path, capsys):
    path, seal, _, original = ping_scope
    damaged = deepcopy(original)
    branch_id = next(k for k in damaged['bindings'] if k.endswith('/properties/isAvailable'))
    binding = damaged['bindings'][branch_id]
    receipt = json.loads(Path(binding['evidence']['program']['artifact']).read_text())
    receipt['invocation']['outcome'] = 'BLOCKED'
    receipt['invocation']['node_outcomes'][0]['outcome'] = 'BLOCKED'
    receipt['environment_blocker'] = 'owned fixture unavailable'
    target = tmp_path / 'blocked.json'
    binding['evidence']['program'].update(artifact=str(target), sha256=write_json(target, receipt))
    write_json(tmp_path / 'bindings.json', damaged)
    argv = ['--output', str(tmp_path / 'ledger.json'), '--controlled-scope', str(path / 'scope.json'),
            '--scope-sha256', seal, '--bindings', str(tmp_path / 'bindings.json'), '--require-complete']
    assert evaluate_snapshot(ping_scope, damaged)['completion']['states']['environment_blocked'] == 1
    binding.pop('construction')
    write_json(tmp_path / 'bindings.json', damaged)
    assert evaluate_snapshot(ping_scope, damaged)['completion']['states']['missing_implementation'] == 1


def test_reviewed_requirements_can_be_program_only_and_absence_is_unresolved(ping_scope):
    _, _, inventory, bindings = ping_scope
    selected = {r['id']: r for r in inventory['native_coverage']['obligations'] if r['id'] in bindings['bindings']}
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {
        identity: {'native_shape_sha256': row['shape_sha256'], 'categories': ['program'],
                   'reason': 'Controlled fixed read: exact input and result projection are deterministic program obligations.'}
        for identity, row in selected.items()}}
    result = evaluate_snapshot(ping_scope, bindings, requirements=policy)
    assert result['completion']['complete'] is True
    identity = next(iter(policy['branches']))
    policy['branches'].pop(identity)
    result = evaluate_snapshot(ping_scope, bindings, requirements=policy)
    assert next(r for r in result['obligations'] if r['id'] == identity)['state'] == 'unresolved'


def test_projected_nonzero_public_query_receipt_supports_multiple_native_calls(ping_scope, tmp_path):
    from tests.maintenance.branch_audit_completion import evidence_result
    path, _, inventory, _ = ping_scope
    gateway = sys.modules['branch_completion_gateway']
    route = next(r for r in inventory['native_coverage']['routes'] if r['uri'] == 'ak.wwise.core.object.get' and r['version'] == '2025.1' and r['host'] == 'wwise-console')
    branch = next(b for b in inventory['native_coverage']['obligations'] if b['route'] == route['id'] and b['pointer'] == '/argsSchema')
    calls = []
    class Client:
        def call(self, uri, args=None, options=None):
            if uri == 'ak.wwise.core.getInfo':
                year, major, minor, build = map(int, route['build'].split('.'))
                result = {'displayName': 'WwiseConsole', 'isCommandLine': True, 'version': {'year': year, 'major': major, 'minor': minor, 'build': build}}
            elif uri == 'ak.wwise.core.object.get':
                result = {'return': [{'id':'{11111111-1111-1111-1111-111111111111}','name':'Sound','type':'Sound','path':'\\Sound'}]}
            else:
                result = {'id': '{11111111-1111-1111-1111-111111111111}', 'name': 'Fixture', 'path': '\\Fixture'}
            calls.append({'uri': uri, 'args': args or {}, 'options': options or {}, 'result': result})
            return result
        def disconnect(self):
            pass
    argv = ['query-object', '--kind', 'all-sounds', '--max-results', '1', '--detail']
    code, payload = gateway.execute_gateway(argv, env={'WAAPI_SKILL_CONFIG_PATH': str(path / '2025.1wwise-console-config.json'), 'WWISE_EVIDENCE_DIR': str(tmp_path / 'dispatch')}, client_factory=lambda _: Client())
    assert code == 0, payload
    index = next(i for i, c in enumerate(calls) if c['uri'] == route['uri'])
    assert len(calls) > 1 and calls[index]['args'] and payload['agent_result'] != calls[index]['result']
    dispatch = f'/native_calls/{index}'
    record = {'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'scope_kind': 'controlled',
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': 'query', 'outcome': 'PASS'}]},
        'gateway': {'argv': argv, 'exit_code': code, 'payload': payload}, 'native_calls': calls,
        'branch_assertions': {branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
          'checks': [{'pointer': dispatch + '/args', 'equals': calls[index]['args']},
                     {'pointer': '/gateway/payload/agent_result', 'equals': payload['agent_result']}]}}}
    descriptor = {'artifact': str(tmp_path / 'query.json'), 'sha256': write_json(tmp_path / 'query.json', record), 'nodeid': 'query'}
    binding = {'input': {'gateway_argv': argv}, 'dispatch_pointer': dispatch, 'observation_pointer': dispatch + '/args',
               'gateway_observation_pointer': '/gateway/payload/agent_result'}
    assert evidence_result(descriptor, branch, record['candidate_sha256'], 'program', 'controlled', tmp_path, binding) == ('passed', None)
    binding['dispatch_pointer'] = '/native_calls/0'
    assert evidence_result(descriptor, branch, record['candidate_sha256'], 'program', 'controlled', tmp_path, binding)[0] == 'missing'


    # A reachable definition keeps the exact array/caller reference context.
    binding['dispatch_pointer'] = dispatch
    edges = {b['id']: b for b in inventory['native_coverage']['obligations'] if b['route'] == route['id'] and b['kind'] == 'reference'}
    edge = next(e for e in edges.values() if e['pointer'] == '/resultSchema/properties/return/items/$ref')
    target_id = edge['reference']['target']
    defined = next(b for b in inventory['native_coverage']['obligations'] if b['id'].startswith(target_id + '/patternProperties/') and b['pointer'].endswith('/anyOf/0') and b['kind'] == 'schema')
    binding['reference_chain'] = [edge['id']]
    binding['observation_pointer'] = dispatch + '/result/return/0/name'
    record['branch_assertions'] = {defined['id']: {'native_shape_sha256':defined['shape_sha256'],'native_route':defined['route'],
        'checks':[{'pointer':binding['observation_pointer'],'equals':'Sound'}, {'pointer':'/gateway/payload/agent_result','equals':payload['agent_result']}]}}
    descriptor['sha256'] = write_json(tmp_path / 'query.json', record)
    assert evidence_result(descriptor,defined,record['candidate_sha256'],'program','controlled',tmp_path,binding,reference_edges=edges) == ('passed',None)
    binding['observation_pointer'] = dispatch + '/result/other/0/name'
    assert evidence_result(descriptor,defined,record['candidate_sha256'],'program','controlled',tmp_path,binding,reference_edges=edges)[0] == 'missing'


@pytest.mark.parametrize('kind,value,observed,check', [
    ('enum_value', 'A', 'B', {'equals': 'B'}),
    ('boolean_value', True, False, {'equals': False}),
    ('nullable', None, 'not-null', {'equals': 'not-null'}),
    ('empty_string', '', 'filled', {'equals': 'filled'}),
    ('empty_object', {}, {'x': 1}, {'equals': {'x': 1}}),
    ('default', 7, 8, {'equals': 8}),
    ('collection_cardinality', 'single', [1, 2], {'cardinality': 'multiple'}),
    ('collection_cardinality', 'empty', [1], {'cardinality': 'single'}),
    ('collection_cardinality', 'multiple', [], {'cardinality': 'empty'}),
    ('optional_presence', 'absent', 'present', {'equals': 'present'}),
    ('optional_presence', 'present', None, {'absent': True}),
    ('type_variant', 'integer', 'text', {'equals': 'text'}),
])
def test_branch_semantics_cannot_borrow_an_unrelated_matching_value(ping_scope, tmp_path, kind, value, observed, check):
    from tests.maintenance.branch_audit_completion import evidence_result
    _, _, inventory, original = ping_scope
    binding = deepcopy(next(iter(original['bindings'].values())))
    record = json.loads(Path(binding['evidence']['program']['artifact']).read_text())
    branch = {'id': 'controlled-semantics', 'route': record['native_call']['uri'], 'pointer': '/argsSchema/properties/field',
              'shape_sha256': audit.digest(value), 'kind': kind, 'value': value}
    branch['route'] = next(iter(record['branch_assertions'].values()))['native_route']
    record['native_call']['args'] = {} if check.get('absent') else {'field': observed}
    record['unrelated'] = value
    record['branch_assertions'] = {branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
        'checks': [dict(pointer='/native_call/args/field', **check), {'pointer': '/unrelated', 'equals': value},
                   {'pointer': '/gateway/payload/agent_result', 'equals': record['gateway']['payload']['agent_result']}]}}
    target = tmp_path / 'semantic.json'
    descriptor = {'artifact': str(target), 'sha256': write_json(target, record), 'nodeid': 'test_ping_public_gateway'}
    assert evidence_result(descriptor, branch, record['candidate_sha256'], 'program', 'controlled', tmp_path, binding)[0] == 'missing'

    # The corresponding exact alternative remains provable; rejection is not blanket.
    correct = value
    if kind == 'collection_cardinality':
        correct = {'empty': [], 'single': [1], 'multiple': [1, 2]}[value]
    elif kind == 'optional_presence':
        correct = 'present'
    elif kind == 'type_variant':
        correct = 1
    record['native_call']['args'] = {} if kind == 'optional_presence' and value == 'absent' else {'field': correct}
    assertion = record['branch_assertions'][branch['id']]['checks'][0]
    assertion.clear()
    assertion['pointer'] = '/native_call/args/field'
    assertion.update({'absent': True} if kind == 'optional_presence' and value == 'absent' else
                     {'cardinality': value} if kind == 'collection_cardinality' else {'equals': correct})
    if kind == 'default':
        binding['default_omission_pointer'] = '/gateway/request/field'
        record['gateway']['request'] = {}
        record['branch_assertions'][branch['id']]['checks'].append({'pointer': '/gateway/request/field', 'absent': True})
    descriptor['sha256'] = write_json(target, record)
    assert evidence_result(descriptor, branch, record['candidate_sha256'], 'program', 'controlled', tmp_path, binding) == ('passed', None)


def test_exact_reviewed_equivalence_reuses_unchanged_sources_and_rejects_stale_claims(ping_scope, tmp_path):
    from tests.maintenance.branch_audit_completion import evidence_result
    _, _, inventory, original = ping_scope
    identity = next(iter(original['bindings']))
    binding = deepcopy(original['bindings'][identity])
    branch = next(b for b in inventory['native_coverage']['obligations'] if b['id'] == identity)
    record = json.loads(Path(binding['evidence']['program']['artifact']).read_text())
    required_sources = sorted({binding[k]['source'].split('#')[0] for k in ('construction', 'validation', 'verifier')} | {'skills/waapi-skill/scripts/run.py', 'skills/waapi-skill/scripts/gateway.py'})
    binding['relevant_sources'] = required_sources
    record['relevant_sources'] = {p: hashlib.sha256((audit.ROOT / p).read_bytes()).hexdigest() for p in required_sources}
    target = tmp_path / 'original.json'
    descriptor = {'artifact': str(target), 'sha256': write_json(target, record), 'nodeid': 'test_ping_public_gateway'}
    successor = 'f' * 64
    attestation = {'contract': 'waapi-skill.branch-evidence-equivalence/v1', 'reviewed_reason': 'Only unrelated ownership documentation changed; exact behavior dependencies are unchanged.',
        'from_candidate': record['candidate_sha256'], 'to_candidate': successor, 'branch_id': identity,
        'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'], 'evidence_sha256': descriptor['sha256'],
        'binding_semantics_sha256': audit.digest({k:v for k,v in binding.items() if k not in ('evidence', 'equivalence')}),
        'sources': record['relevant_sources']}
    proof = tmp_path / 'equivalence.json'
    binding['equivalence'] = {'artifact': str(proof), 'sha256': write_json(proof, attestation)}
    assert evidence_result(descriptor, branch, successor, 'program', 'controlled', tmp_path, binding) == ('passed', None)
    for key in ('from_candidate', 'to_candidate', 'branch_id', 'native_shape_sha256', 'native_route', 'evidence_sha256', 'binding_semantics_sha256', 'sources'):
        damaged = deepcopy(attestation)
        damaged[key] = {} if key == 'sources' else 'stale'
        binding['equivalence']['sha256'] = write_json(proof, damaged)
        assert evidence_result(descriptor, branch, successor, 'program', 'controlled', tmp_path, binding)[0] == 'missing', key
    binding['equivalence']['sha256'] = write_json(proof, attestation)
    binding['input']['selector'] = 'changed behavior'
    assert evidence_result(descriptor, branch, successor, 'program', 'controlled', tmp_path, binding)[0] == 'missing'
    binding['input']['selector'] = original['bindings'][identity]['input']['selector']
    changed_root = tmp_path / 'changed-source'
    for name in required_sources:
        target_source = changed_root / name
        target_source.parent.mkdir(parents=True, exist_ok=True)
        target_source.write_bytes((audit.ROOT / name).read_bytes())
    (changed_root / required_sources[0]).write_text('changed relevant implementation')
    assert evidence_result(descriptor, branch, successor, 'program', 'controlled', tmp_path, binding, changed_root)[0] == 'missing'



def test_fresh_adapter_bytes_change_completion_candidate_identity(tmp_path):
    from tests.maintenance.branch_audit_completion import candidate_identity
    # Reuse the minimal source-root pattern: no inventory generation or archive run.
    names = ('skills/waapi-skill/SKILL.md', 'tests/maintenance/branch_coverage_audit.py',
        'tests/maintenance/branch_audit_completion.py', 'docs/branch-coverage-ownership.json',
        'docs/branch-coverage-condition-sources.json', 'docs/branch-coverage-requirements.json',
        'tests/support/fresh_branch_evidence.py')
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((audit.ROOT / name).read_bytes())
    before = candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest)
    adapter = tmp_path / names[-1]
    adapter.write_bytes(adapter.read_bytes() + b'\n# changed Fresh acceptance semantics\n')
    assert candidate_identity(tmp_path, {'sources': {}}, {}, digest=audit.digest) != before


def test_fresh_label_without_formal_archive_bridge_has_no_credit(ping_scope, tmp_path):
    from tests.maintenance.branch_audit_completion import evidence_result
    _, _, inventory, original = ping_scope
    identity, binding = next(iter(original['bindings'].items()))
    branch = next(b for b in inventory['native_coverage']['obligations'] if b['id'] == identity)
    record = json.loads(Path(binding['evidence']['program']['artifact']).read_text())
    record['harness'] = 'formal_fresh_codex'
    target = tmp_path / 'label.json'
    descriptor = {'artifact': str(target), 'sha256': write_json(target, record), 'nodeid': 'test_ping_public_gateway'}
    mapped = dict(binding, observation_pointer='/native_call/args')
    outcome, reason = evidence_result(descriptor, branch, record['candidate_sha256'], 'fresh', 'controlled', tmp_path, mapped)
    assert outcome == 'missing' and 'closed original formal Fresh archive reference' in reason


def test_exact_console_ui_boundary_completes_without_native_dispatch(ping_scope, tmp_path):
    path, _, inventory, _ = ping_scope
    native = inventory['native_coverage']
    route = next(r for r in native['routes'] if r['uri'] == 'ak.wwise.ui.commands.getCommands' and r['host'] == 'wwise-console')
    selected = [b for b in native['obligations'] if b['route'] == route['id']]
    branch = next(b for b in selected if b['pointer'] == '/argsSchema')
    public = next(r for r in inventory['routes'] if r['id'] == route['public_route'])
    gateway = sys.modules['branch_completion_gateway']
    env = {'WAAPI_SKILL_CONFIG_PATH': str(tmp_path / 'config.json')}
    assert gateway.execute_gateway(['config-set', '--wwise-version', route['version'], '--waapi-port', '31337'], env=env)[0] == 0
    code, disclosed = gateway.execute_gateway(['request-schema', route['uri']], env=env)
    assert code == 0
    argv = disclosed['continuation']['gateway_argv']
    calls = []
    class Client:
        def call(self, uri, args=None, options=None):
            assert uri == 'ak.wwise.core.getInfo', 'Forbidden UI call reached native client'
            year, major, minor, build = map(int, route['build'].split('.'))
            result = {'displayName': 'WwiseConsole', 'isCommandLine': True, 'version': {'year': year, 'major': major, 'minor': minor, 'build': build}}
            calls.append({'uri': uri, 'args': args or {}, 'options': options or {}, 'result': result})
            return result
        def disconnect(self):
            pass
    code, payload = gateway.execute_gateway(argv, env=env, client_factory=lambda _: Client())
    assert code == 2 and payload['error_code'] == 'AUTHORING_HOST_REQUIRED' and payload['executed'] is False
    record = {'candidate_sha256': native['candidate_sha256'], 'scope_kind': 'controlled',
        'invocation': {'phase': 'final', 'outcome': 'PASS', 'node_outcomes': [{'nodeid': 'public-host-boundary', 'outcome': 'PASS'}]},
        'gateway': {'argv': argv, 'exit_code': code, 'payload': payload}, 'native_calls': calls,
        'branch_assertions': {branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'native_route': branch['route'],
          'checks': [{'pointer': '/gateway/payload/error_code', 'equals': 'AUTHORING_HOST_REQUIRED'},
                     {'pointer': '/gateway/payload/executed', 'equals': False}]}}}
    receipt = tmp_path / 'boundary.json'
    binding = {'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'], 'public_route': public['id'], 'public_route_sha256': audit.digest(public),
        'disposition': 'approved_boundary', 'boundary': {'kind': 'wrong_host', 'required_host': 'wwise-authoring'},
        'input': {'gateway_argv': argv, 'selector': 'host guard'},
        **{k: {'source': 'skills/waapi-skill/scripts/gateway.py#authoring_host_required_payload', 'selector': branch['pointer']} for k in ('construction','validation','verifier')},
        'evidence': {'program': {'artifact': str(receipt), 'sha256': write_json(receipt, record), 'nodeid': 'public-host-boundary'}}}
    scope = {'contract': 'waapi-skill.controlled-branch-scope/v1', 'id': 'exact-host-boundary', 'credit': 'controlled_program_only',
        'route_ids': [route['id']], 'obligation_ids': [b['id'] for b in selected], 'native_catalogs': native['catalogs'], 'requirements': ['program']}
    document = {'contract': 'waapi-skill.branch-bindings/v1', 'bindings': {branch['id']: binding}}
    result = evaluate_coverage(audit.ROOT, inventory, document, digest=audit.digest, scope=scope, evidence_base=tmp_path)
    assert next(b for b in result['obligations'] if b['id'] == branch['id'])['state'] == 'verified'
    assert result['completion']['complete'] is False  # Other branches get no inherited host-boundary credit.
    binding['boundary'] = {'kind': 'unsupported_skill', 'reason': 'not implemented'}
    result = evaluate_coverage(audit.ROOT, inventory, document, digest=audit.digest, scope=scope, evidence_base=tmp_path)
    assert next(b for b in result['obligations'] if b['id'] == branch['id'])['state'] == 'missing_implementation'


def test_explicit_sibling_observation_cannot_prove_a_different_field(ping_scope, tmp_path):
    from tests.maintenance.branch_audit_completion import evidence_result
    _, _, inventory, original = ping_scope
    binding = deepcopy(next(iter(original['bindings'].values())))
    record = json.loads(Path(binding['evidence']['program']['artifact']).read_text())
    route = next(iter(record['branch_assertions'].values()))['native_route']
    branch = {'id': 'controlled-sibling', 'route': route, 'pointer': '/argsSchema/properties/field/enum/0', 'kind': 'enum_value', 'value': 'A', 'shape_sha256': audit.digest('A')}
    record['native_call']['args'] = {'field': 'B', 'unrelated': 'A'}
    binding['observation_pointer'] = '/native_call/args/unrelated'
    record['branch_assertions'] = {branch['id']: {'native_shape_sha256': branch['shape_sha256'], 'native_route': route,
        'checks': [{'pointer': '/native_call/args/unrelated', 'equals': 'A'}, {'pointer': '/gateway/payload/agent_result', 'equals': record['gateway']['payload']['agent_result']}]}}
    target = tmp_path / 'sibling.json'
    descriptor = {'artifact': str(target), 'sha256': write_json(target, record), 'nodeid': 'test_ping_public_gateway'}
    assert evidence_result(descriptor, branch, record['candidate_sha256'], 'program', 'controlled', tmp_path, binding)[0] == 'missing'


def test_native_union_alternatives_require_matching_real_public_receipt(ping_scope, tmp_path):
    from tests.maintenance.branch_audit_completion import evidence_result
    path, _, inventory, _ = ping_scope
    gateway = sys.modules['branch_completion_gateway']
    route = next(r for r in inventory['native_coverage']['routes'] if r['uri'] == 'ak.wwise.core.mediaPool.get' and r['host'] == 'wwise-console')
    prefix = '/argsSchema/properties/filters/items/properties/value/anyOf/'
    branches = [next(b for b in inventory['native_coverage']['obligations'] if b['route'] == route['id'] and b['pointer'] == prefix + str(i)) for i in (0, 1)]
    receipts = []
    for index, flags in enumerate((['--text-filter', 'filename', 'equals', 'hello'], ['--number-filter', 'duration-seconds', 'greaterThan', '3'])):
        calls = []
        class Client:
            def call(self, uri, args=None, options=None):
                if uri == 'ak.wwise.core.getInfo':
                    year, major, minor, build = map(int, route['build'].split('.'))
                    result = {'displayName': 'WwiseConsole', 'isCommandLine': True, 'version': {'year':year,'major':major,'minor':minor,'build':build}}
                elif uri == 'ak.wwise.core.getProjectInfo':
                    result = {'id': '{11111111-1111-1111-1111-111111111111}', 'name': 'Fixture', 'path': str(tmp_path / 'Fixture.wproj')}
                elif uri == 'ak.wwise.core.mediaPool.getFields':
                    result = {'return': ['Path','FileId','Db','Filename','WAV/Duration']}
                else:
                    assert uri == route['uri']
                    result = {'return': []}
                calls.append({'uri':uri,'args':args or {},'options':options or {},'result':result})
                return result
            def disconnect(self):
                pass
        argv = ['core-call', route['uri'], '--max-results','1'] + flags
        code, payload = gateway.execute_gateway(argv, env={'WAAPI_SKILL_CONFIG_PATH': str(path / '2025.1wwise-console-config.json')}, client_factory=lambda _: Client())
        assert code == 0, payload
        call_index = next(i for i,c in enumerate(calls) if c['uri'] == route['uri'])
        dispatch = f'/native_calls/{call_index}'
        observation = dispatch + '/args/filters/0/value'
        binding = {'input': {'gateway_argv': argv}, 'dispatch_pointer': dispatch, 'observation_pointer': observation}
        branch = branches[index]
        record = {'candidate_sha256': inventory['native_coverage']['candidate_sha256'], 'scope_kind':'controlled',
            'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':'union-public','outcome':'PASS'}]},
            'gateway':{'argv':argv,'exit_code':code,'payload':payload},'native_calls':calls,
            'branch_assertions':{b['id']:{'native_shape_sha256':b['shape_sha256'],'native_route':b['route'],
                'checks':[{'pointer':observation,'equals':calls[call_index]['args']['filters'][0]['value']}, {'pointer':'/gateway/payload/agent_result','equals':payload['agent_result']}]} for b in branches}}
        target = tmp_path / f'union-{index}.json'
        descriptor = {'artifact':str(target),'sha256':write_json(target,record),'nodeid':'union-public'}
        receipts.append((descriptor, record, binding))
        assert evidence_result(descriptor,branch,record['candidate_sha256'],'program','controlled',tmp_path,binding) == ('passed',None)
    descriptor,record,binding = receipts[0]
    assert evidence_result(descriptor,branches[1],record['candidate_sha256'],'program','controlled',tmp_path,binding)[0] == 'missing'


def test_legacy_blocked_labels_are_not_approved_full_coverage_boundaries(ping_scope):
    from tests.maintenance.branch_audit_completion import approved_boundary
    _, _, inventory, _ = ping_scope
    policy = json.loads((audit.ROOT / 'skills/waapi-skill/resources/native_surface_policy.json').read_text())
    native = inventory['native_coverage']
    def classify(uri, selector_fragment, branch_predicate):
        route = next(r for r in native['routes'] if r['uri'] == uri and r['version'] == '2025.1' and r['host'] == 'wwise-console')
        branch = next(b for b in native['obligations'] if b['route'] == route['id'] and branch_predicate(b))
        i,rule = next((i,r) for i,r in enumerate(policy['rules']) if r['uri'] == uri and '2025.1' in r['versions'])
        j = next(j for j,r in enumerate(rule['semantic_boundaries']) if selector_fragment in r['selector'])
        binding = {'boundary':{'kind':'prohibited_field','policy_sha256':audit.digest(policy),'policy_pointer':f'/rules/{i}/semantic_boundaries/{j}'}}
        public = next(r for r in inventory['routes'] if r['id'] == route['public_route'])
        return approved_boundary(audit.ROOT,branch,binding,route,public,audit.digest)
    assert classify('ak.wwise.core.object.move','::replace',lambda b:b['kind']=='enum_value' and b.get('value')=='replace') is None
    assert classify('ak.wwise.core.audio.import','childOfReference',lambda b:b['pointer']=='/argsSchema') is None
    route = next(r for r in native['routes'] if r['uri']=='ak.wwise.cli.generateSoundbank' and r['version']=='2025.1' and r['host']=='wwise-console')
    branch = next(b for b in native['obligations'] if b['route']==route['id'] and b['pointer']=='/argsSchema/properties/custom-pre-gen-cmd')
    i,rule = next((i,r) for i,r in enumerate(policy['rules']) if r['uri']==route['uri'] and '2025.1' in r['versions'])
    j = rule['scopes'][0]['classifications']['intentionally_blocked'].index('custom-pre-gen-cmd')
    binding = {'boundary':{'kind':'prohibited_field','policy_sha256':audit.digest(policy),'policy_pointer':f'/rules/{i}/scopes/0/classifications/intentionally_blocked/{j}'}}
    public = next(r for r in inventory['routes'] if r['id']==route['public_route'])
    assert approved_boundary(audit.ROOT,branch,binding,route,public,audit.digest)['kind'] == 'prohibited_field'
def test_prohibited_hook_requires_that_exact_public_input_rejection(ping_scope, tmp_path):
    _, _, inventory, _ = ping_scope
    gateway = sys.modules['branch_completion_gateway']
    native = inventory['native_coverage']
    route = next(r for r in native['routes'] if r['uri']=='ak.wwise.cli.generateSoundbank' and r['version']=='2025.1' and r['host']=='wwise-console')
    selected = [b for b in native['obligations'] if b['route']==route['id']]
    branch = next(b for b in selected if b['pointer']=='/argsSchema/properties/custom-pre-gen-cmd')
    public = next(r for r in inventory['routes'] if r['id']==route['public_route'])
    policy = json.loads((audit.ROOT / 'skills/waapi-skill/resources/native_surface_policy.json').read_text())
    i,rule = next((i,r) for i,r in enumerate(policy['rules']) if r['uri']==route['uri'] and '2025.1' in r['versions'])
    j = rule['scopes'][0]['classifications']['intentionally_blocked'].index('custom-pre-gen-cmd')
    env = {'WAAPI_SKILL_CONFIG_PATH':str(tmp_path / 'config.json')}
    assert gateway.execute_gateway(['config-set','--wwise-version','2025.1','--waapi-port','31337'],env=env)[0] == 0
    prefix = ['--state-dir',str(tmp_path / 'draft-state')]
    code,started = gateway.execute_gateway(prefix + ['draft-start',route['uri']],env=env,client_factory=lambda _:pytest.fail('Offline start must not connect'))
    assert code == 0, started
    scope = {'contract':'waapi-skill.controlled-branch-scope/v1','id':'approved-hook','credit':'controlled_program_only',
        'route_ids':[route['id']],'obligation_ids':[b['id'] for b in selected],'native_catalogs':native['catalogs'],'requirements':['program']}
    outcomes = []
    for field in ('custom-pre-gen-cmd', 'unrelated_invalid_field'):
        argv = prefix + ['draft-declare-cli-console-plan',started['draft']['draft_id'],'--task-authority',started['task_authority'],
            '--expected-revision','1','--value',field,'never-execute-this-command']
        calls = []
        class Client:
            def call(self, uri, args=None, options=None):
                if uri == 'ak.wwise.core.getInfo':
                    year,major,minor,build = map(int,route['build'].split('.'))
                    result = {'displayName':'WwiseConsole','isCommandLine':True,'apiVersion':1,'platform':'macosx','configuration':'release','version':{'year':year,'major':major,'minor':minor,'build':build,'displayName':route['build']}}
                else:
                    assert uri == 'ak.wwise.core.getProjectInfo', 'Prohibited native dispatch reached client'
                    result = {'id':'{11111111-1111-1111-1111-111111111111}','name':'Fixture','path':str(tmp_path / 'Fixture.wproj')}
                calls.append({'uri':uri,'args':args or {},'options':options or {},'result':result})
                return result
            def disconnect(self):
                pass
        code,payload = gateway.execute_gateway(argv,env=env,client_factory=lambda _:Client())
        assert code == 2 and payload['ok'] is False, payload
        assert field in payload['message'], payload
        checks = [{'pointer':f'/gateway/argv/{len(argv)-2}','equals':field},
                  {'pointer':f'/gateway/argv/{len(argv)-1}','equals':argv[-1]},
                  {'pointer':'/gateway/payload/error_code','equals':payload['error_code']},
                  {'pointer':'/gateway/payload/message','equals':payload['message']}]
        record = {'candidate_sha256':native['candidate_sha256'],'scope_kind':'controlled','native_calls':calls,
            'invocation':{'phase':'final','outcome':'PASS','node_outcomes':[{'nodeid':'hook-boundary','outcome':'PASS'}]},
            'gateway':{'argv':argv,'exit_code':code,'payload':payload},
            'branch_assertions':{branch['id']:{'native_shape_sha256':branch['shape_sha256'],'native_route':branch['route'],'checks':checks}}}
        target = tmp_path / (field + '.json')
        binding = {'branch_id':branch['id'],'native_shape_sha256':branch['shape_sha256'],'public_route':public['id'],'public_route_sha256':audit.digest(public),
            'disposition':'approved_boundary','boundary':{'kind':'prohibited_field','policy_sha256':audit.digest(policy),
                'policy_pointer':f'/rules/{i}/scopes/0/classifications/intentionally_blocked/{j}',
                'rejected_input_checks':checks[:2],'error_pointer':'/gateway/payload/message'},
            'input':{'gateway_argv':argv,'selector':'custom-pre-gen-cmd'},
            **{k:{'source':'skills/waapi-skill/scripts/gateway.py#execute_gateway','selector':branch['pointer']} for k in ('construction','validation','verifier')},
            'evidence':{'program':{'artifact':str(target),'sha256':write_json(target,record),'nodeid':'hook-boundary'}}}
        result = evaluate_coverage(audit.ROOT,inventory,{'contract':'waapi-skill.branch-bindings/v1','bindings':{branch['id']:binding}},digest=audit.digest,scope=scope,evidence_base=tmp_path)
        row = next(b for b in result['obligations'] if b['id']==branch['id'])
        outcomes.append(row['state'])
    assert outcomes == ['verified','implemented_unverified']

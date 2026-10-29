"""Synthetic archive-reader regressions; never real Fresh coverage receipts."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from tests.maintenance.branch_audit_completion import evidence_result as _evidence_result
from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import test_run_codex_skill_campaign_heavy_v3 as fixture


def _sealed_archive(tmp_path, *, status="PASS", identity_fault=None):
    options = replace(fixture._options(tmp_path), suite_path=campaign.matrix.DEFAULT_V3_SUITE,
                      case_ids=("OBJ22-F-GET-01",), versions=("2022.1",))
    units = campaign.load_heavy_v3_campaign_units(options)
    effective = campaign.build_heavy_v3_effective_config(options, units=units,
        required_units={unit.unit_id: (campaign.HEAVY_V3_PHASE,) for unit in units},
        sealed_codex_version="codex-cli 1.2.3")
    if identity_fault:
        section, field = identity_fault
        effective[section][field] = 'unsupported-original-identity'
    effective_hash = hashlib.sha256(campaign.canonical_json_bytes(effective)).hexdigest()
    config = campaign.create_immutable_campaign_config(options.campaign_root,
        {"effective": effective, "effective_sha256": effective_hash})
    campaign.write_campaign_marker(options.campaign_root, campaign_id=config["campaign_id"])
    _, attempt = campaign.create_attempt(options.campaign_root)
    group = attempt / "runs" / campaign.HEAVY_V3_GROUP_ID
    group.mkdir(parents=True)
    matrix_root = group / "matrix"
    fixture._write_matrix_evidence(matrix_root, options=options, units=units, statuses=(status,))
    argv = campaign.build_heavy_v3_child_argv(options, units=units, matrix_root=matrix_root)
    campaign.atomic_write_json_with_digest(group / "child-request.json",
        campaign.heavy_v3_child_request(options, units=units, argv=argv))
    campaign.atomic_write_json_with_digest(group / "child-result.json", {
        "contract": campaign.CHILD_EXECUTION_CONTRACT, "group_id": campaign.HEAVY_V3_GROUP_ID,
        "returncode": 0 if status == "PASS" else 1, "completed_at": campaign.utc_now()})
    validation = campaign.validate_heavy_v3_child_run(matrix_root, expected_units=units,
                                                    options=options, returncode=0 if status == "PASS" else 1)
    assert validation.observations[0]["status"] == status, validation
    campaign.seal_attempt(attempt, validation.observations)
    branch = {"id": "interaction-query", "shape_sha256": "b" * 64,
              "route": "2022.1|wwise-console|2022.1.19.8584|function|ak.wwise.core.object.get"}
    record = {"contract": "waapi-skill.formal-fresh-branch-reference/v1",
        "candidate_sha256": "c" * 64, "scope_kind": "controlled",
        "branch_id": branch["id"], "native_shape_sha256": branch["shape_sha256"],
        "native_route": branch["route"], "campaign_root": str(options.campaign_root),
        "campaign_config_sha256": campaign.sha256_file(options.campaign_root / "campaign-config.json"),
        "effective_sha256": effective_hash, "unit_id": units[0].unit_id, "version": units[0].version}
    path = tmp_path / "fresh-reference.json"
    path.write_text(json.dumps(record))
    descriptor = {"artifact": path.name, "sha256": campaign.sha256_file(path)}
    import shutil
    shutil.copytree(options.skill_source, tmp_path / 'current/skills/waapi-skill')
    requirement = {'contract': 'waapi-skill.formal-fresh-requirement/v1',
        'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
        'native_route': branch['route'], 'archive_reference_sha256': descriptor['sha256'],
        'profile': options.profile, 'effective_sha256': effective_hash,
        'unit_id': record['unit_id'], 'version': record['version'],
        'mechanism': 'bounded query discovery and exact continuation',
        'reviewed_reason': 'synthetic selected interaction requirement'}
    (tmp_path / 'reviewed-binding.json').write_text(json.dumps({'fresh_requirement': requirement}))
    return descriptor, branch, options, matrix_root


def test_current_formal_archive_reaches_completion_without_pytest_receipt(tmp_path, monkeypatch):
    descriptor, branch, _, _ = _sealed_archive(tmp_path)
    def no_process(*args, **kwargs):
        pytest.fail('archive completion reader must not launch processes')
    monkeypatch.setattr(campaign.subprocess, 'run', no_process)
    monkeypatch.setattr(campaign.subprocess, 'Popen', no_process)
    assert evidence_result(descriptor, branch, "c" * 64, "fresh", "controlled", tmp_path) == ("passed", None)


def evidence_result(descriptor, branch, candidate, category, scope, base, binding=None, source_root=None):
    reviewed = json.loads((base / 'reviewed-binding.json').read_text())
    reviewed.update(binding or {})
    return _evidence_result(descriptor, branch, candidate, category, scope, base, reviewed,
                            source_root or base / 'current')


def _rewrite_reference(tmp_path, descriptor, *, reviewed=False, **changes):
    path = tmp_path / descriptor['artifact']
    record = json.loads(path.read_text())
    record.update(changes)
    path.write_text(json.dumps(record))
    descriptor['sha256'] = campaign.sha256_file(path)
    if reviewed:
        binding_path = tmp_path / 'reviewed-binding.json'
        binding = json.loads(binding_path.read_text())
        binding['fresh_requirement']['archive_reference_sha256'] = descriptor['sha256']
        binding_path.write_text(json.dumps(binding))


@pytest.mark.parametrize('fault', ['missing', 'tamper', 'config', 'effective', 'unit', 'version', 'scope', 'branch', 'candidate', 'relabel'])
def test_fresh_completion_rejects_missing_tampered_or_misbound_archives(tmp_path, fault):
    descriptor, branch, options, matrix_root = _sealed_archive(tmp_path)
    if fault == 'missing':
        (matrix_root / 'summary.json').unlink()
    elif fault == 'tamper':
        events = next(matrix_root.rglob('events.jsonl'))
        events.write_text(events.read_text() + '{}\n')
    elif fault == 'relabel':
        _rewrite_reference(tmp_path, descriptor, contract='pytest', status='PASS')
    else:
        changes = {'config': {'campaign_config_sha256': '0' * 64},
                   'effective': {'effective_sha256': '0' * 64},
                   'unit': {'unit_id': 'other'}, 'version': {'version': '2025.1'},
                   'scope': {'scope_kind': 'product'}, 'branch': {'branch_id': 'other'},
                   'candidate': {'candidate_sha256': '0' * 64}}[fault]
        _rewrite_reference(tmp_path, descriptor, **changes)
    outcome, reason = evidence_result(descriptor, branch, 'c' * 64, 'fresh', 'controlled', tmp_path)
    assert outcome == 'missing'
    assert reason


def test_original_fail_is_preserved_as_nonpassing_fresh_evidence(tmp_path):
    descriptor, branch, _, _ = _sealed_archive(tmp_path, status='FAIL')
    assert evidence_result(descriptor, branch, 'c' * 64, 'fresh', 'controlled', tmp_path) == (
        'missing', 'original formal Fresh verdict: FAIL')


def test_sealed_pass_label_without_task_evidence_is_not_fresh(tmp_path):
    descriptor, branch, options, matrix_root = _sealed_archive(tmp_path)
    # Reseal after corrupting the task: integrity passes, full semantic replay must fail.
    from tests.semantic.support.codex_campaign import atomic_write_json_with_digest
    task = next(matrix_root.rglob('task-result.json'))
    payload = json.loads(task.read_text())
    payload['broker']['passed'] = False
    task.write_text(json.dumps(payload))
    attempt = matrix_root.parents[2]
    manifest = json.loads((attempt / 'attempt-manifest.json').read_text())
    from tests.semantic.support import codex_campaign
    manifest['artifacts'] = codex_campaign._strict_artifact_manifest(attempt)
    atomic_write_json_with_digest(attempt / 'attempt-manifest.json', manifest)
    outcome, reason = evidence_result(descriptor, branch, 'c' * 64, 'fresh', 'controlled', tmp_path)
    assert outcome == 'missing'
    assert reason


@pytest.mark.parametrize('identity_fault', [('harness', 'semantic_tree_sha256'),
    ('suite', 'sha256'), ('runner', 'campaign_sha256'), ('candidate', 'tree_sha256'),
    ('options', 'model'), ('options', 'profile')])
def test_current_reader_rejects_incompatible_original_identities(tmp_path, identity_fault):
    descriptor, branch, _, _ = _sealed_archive(tmp_path, identity_fault=identity_fault)
    outcome, reason = evidence_result(descriptor, branch, 'c' * 64, 'fresh', 'controlled', tmp_path)
    assert outcome == 'missing'
    assert reason


def test_proof_retains_raw_verdict_and_exact_original_identities(tmp_path):
    from tests.support.fresh_branch_evidence import read_fresh_proof
    descriptor, _, _, _ = _sealed_archive(tmp_path)
    record = json.loads((tmp_path / descriptor['artifact']).read_text())
    proof = read_fresh_proof(record)
    assert proof['original_verdict'] == 'PASS'
    assert proof['unit_id'] == 'OBJ22-F-GET-01'
    assert proof['version'] == '2022.1'
    assert proof['effective_sha256'] == record['effective_sha256']
    assert proof['original_observations'][0]['attempt_id'] == 'attempt-000001'
    assert {'candidate', 'suite', 'harness', 'runner', 'options'} <= proof.keys()


def test_separate_business_assessment_never_rewrites_original_fail(tmp_path):
    from tests.support.fresh_branch_evidence import read_fresh_proof
    descriptor, branch, _, _ = _sealed_archive(tmp_path, status='FAIL')
    path = tmp_path / 'assessment.json'
    record = json.loads((tmp_path / descriptor['artifact']).read_text())
    assessment_value = {'conclusion': 'business_pass', 'reason': 'presentation only',
        'effective_sha256': record['effective_sha256'], 'unit_id': record['unit_id'],
        'version': record['version'], 'original_verdict': 'FAIL'}
    path.write_text(json.dumps(assessment_value))
    assessment = {'artifact': str(path), 'sha256': campaign.sha256_file(path)}
    _rewrite_reference(tmp_path, descriptor, reviewed=True, business_assessment=assessment)
    record = json.loads((tmp_path / descriptor['artifact']).read_text())
    proof = read_fresh_proof(record)
    assert proof['original_verdict'] == 'FAIL'
    assert proof['business_assessment'] == assessment_value
    assert evidence_result(descriptor, branch, 'c' * 64, 'fresh', 'controlled', tmp_path) == (
        'missing', 'original formal Fresh verdict: FAIL')
    assessment_value['unit_id'] = 'other'
    path.write_text(json.dumps(assessment_value))
    _rewrite_reference(tmp_path, descriptor, reviewed=True, business_assessment={
        'artifact': str(path), 'sha256': campaign.sha256_file(path)})
    assert evidence_result(descriptor, branch, 'c' * 64, 'fresh', 'controlled', tmp_path)[0] == 'missing'


@pytest.mark.parametrize('changed_relevant', [False, True])
def test_historical_candidate_requires_exact_existing_reviewed_equivalence(tmp_path, changed_relevant):
    from tests.maintenance.branch_audit_completion import binding_semantics
    descriptor, branch, options, _ = _sealed_archive(tmp_path)
    source_root = tmp_path / 'current'
    (source_root / 'skills/waapi-skill/unrelated.md').write_text('unrelated source delta')
    if changed_relevant:
        (source_root / 'skills/waapi-skill/scripts/gateway.py').write_text('# changed relevant source')
    sources = {name: campaign.sha256_file(source_root / name) for name in (
        'skills/waapi-skill/scripts/run.py', 'skills/waapi-skill/scripts/gateway.py')}
    _rewrite_reference(tmp_path, descriptor, reviewed=True, relevant_sources=sources)
    binding = {**json.loads((tmp_path / 'reviewed-binding.json').read_text()),
        'relevant_sources': list(sources), **{key: {
        'source': 'skills/waapi-skill/scripts/gateway.py#main'} for key in
        ('construction', 'validation', 'verifier')}}
    proof = {'contract': 'waapi-skill.branch-evidence-equivalence/v1',
        'from_candidate': 'c' * 64, 'to_candidate': 'd' * 64,
        'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
        'native_route': branch['route'], 'evidence_sha256': descriptor['sha256'],
        'binding_semantics_sha256': hashlib.sha256(campaign.canonical_json_bytes(binding_semantics(binding))).hexdigest(),
        'reviewed_reason': 'synthetic unchanged scoped source review', 'sources': sources}
    path = tmp_path / 'equivalence.json'
    path.write_text(json.dumps(proof))
    binding['equivalence'] = {'artifact': str(path), 'sha256': campaign.sha256_file(path)}
    result = evidence_result(descriptor, branch, 'd' * 64, 'fresh', 'controlled', tmp_path,
                             binding, source_root)
    if changed_relevant:
        assert result[0] == 'missing' and 'original source hashes' in result[1]
        return
    assert result == ('passed', None)
    proof['branch_id'] = 'unrelated'
    path.write_text(json.dumps(proof))
    binding['equivalence']['sha256'] = campaign.sha256_file(path)
    outcome, reason = evidence_result(descriptor, branch, 'd' * 64, 'fresh', 'controlled',
                                    tmp_path, binding, source_root)
    assert outcome == 'missing' and 'equivalence' in reason


def test_valid_archive_cannot_be_relabelled_as_different_current_skill(tmp_path):
    import shutil
    descriptor, branch, options, _ = _sealed_archive(tmp_path)
    current = tmp_path / 'different-current'
    shutil.copytree(options.skill_source, current / 'skills/waapi-skill')
    (current / 'skills/waapi-skill/scripts/gateway.py').write_text('# different current implementation\n')
    # Same claimed label in both reference and caller used to skip equivalence.
    _rewrite_reference(tmp_path, descriptor, reviewed=True, candidate_sha256='d' * 64)
    outcome, reason = evidence_result(descriptor, branch, 'd' * 64, 'fresh', 'controlled',
                                    tmp_path, source_root=current)
    assert outcome == 'missing' and 'original source hashes' in reason



def test_query_archive_cannot_claim_an_unreviewed_mutation_scope(tmp_path):
    descriptor, branch, _, _ = _sealed_archive(tmp_path)
    mutation = {**branch, 'id': 'mutation-interaction',
                'route': branch['route'].replace('object.get', 'object.delete')}
    # Even a newly sealed reference must match the separately reviewed unit/mechanism scope.
    _rewrite_reference(tmp_path, descriptor, reviewed=True, branch_id=mutation['id'],
                       native_route=mutation['route'])
    outcome, reason = evidence_result(descriptor, mutation, 'c' * 64, 'fresh', 'controlled', tmp_path)
    assert outcome == 'missing' and 'reviewed Fresh interaction requirement' in reason

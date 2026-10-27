"""Closed completion adapter for current-compatible original formal archives.

This reader never launches a campaign, rewrites archived paths, or promotes a
program/native receipt into Fresh evidence. Unsupported historical formats stay
unverified. Synthetic reader tests are not product evidence.
"""
from dataclasses import replace
from pathlib import Path

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic.support.codex_campaign import (
    CampaignEvidenceError, canonical_json_bytes, consolidate_units,
    load_immutable_campaign_config, sha256_file, stable_tree_sha256,
)

SUPPORTED_PROFILES = campaign.EXECUTABLE_V3_PROFILE_IDS
CONTRACT = 'waapi-skill.formal-fresh-branch-reference/v1'


def read_fresh_proof(record):
    """Return original identities and raw verdict after full current replay."""
    import hashlib
    keys = {'contract', 'candidate_sha256', 'scope_kind', 'branch_id',
            'native_shape_sha256', 'native_route', 'campaign_root',
            'campaign_config_sha256', 'effective_sha256', 'unit_id', 'version'}
    if (not isinstance(record, dict) or set(record) - {'relevant_sources', 'business_assessment'} != keys
            or record['contract'] != CONTRACT):
        raise ValueError('closed original formal Fresh archive reference required')
    root = Path(record['campaign_root'])
    if not root.is_absolute():
        raise ValueError('original absolute Fresh campaign path required')
    config = load_immutable_campaign_config(root)
    if sha256_file(root / 'campaign-config.json') != record['campaign_config_sha256']:
        raise ValueError('Fresh campaign config identity mismatch')
    effective = config.get('effective')
    if not isinstance(effective, dict):
        raise ValueError('Fresh immutable effective object required')
    effective_hash = hashlib.sha256(canonical_json_bytes(effective)).hexdigest()
    if config.get('effective_sha256') != effective_hash or record['effective_sha256'] != effective_hash:
        raise ValueError('Fresh immutable effective identity mismatch')
    if effective.get('contract') != campaign.HEAVY_V3_EFFECTIVE_CONTRACT:
        raise ValueError('unsupported Fresh effective contract')
    values = dict(effective['options'])
    if values.get('profile') not in SUPPORTED_PROFILES:
        raise ValueError('unsupported Fresh profile; no completion credit')
    for name in ('campaign_root', 'suite_path', 'skill_source', 'codex_binary', 'auth_json', 'live_config'):
        values[name] = Path(values[name])
    for name in ('case_ids', 'versions', 'pair_ids'):
        values[name] = tuple(values[name])
    options = campaign.CampaignOptions(**values, resume=True, verify_only=True)
    if (options.campaign_root != root
            or campaign.heavy_v3_immutable_options(options) != effective['options']):
        raise ValueError('Fresh immutable options mismatch')
    codex = effective['codex']
    if (codex.get('memory') != 'disabled'
            or codex.get('fresh_process_thread_and_task_per_scenario') is not True
            or codex.get('allow_login_shell') is not False
            or any(codex.get(key) != getattr(options, key) for key in
                   ('model', 'reasoning_effort', 'service_tier', 'timeout_seconds'))):
        raise ValueError('Fresh Agent execution identity mismatch')
    # No current binary/version probe: these are original recorded identities.
    # Windows archives require their attested shell reader, outside this slice.
    if codex.get('windows_powershell_core_host') is not None:
        raise ValueError('unsupported Fresh Windows shell archive')
    skill = effective['candidate']
    skill_excludes = ['.venv', '__pycache__', '.pytest_cache', '.DS_Store', '.coverage']
    harness_excludes = ['__pycache__', '.pytest_cache', '.DS_Store', '.coverage']
    if (skill != {'path': str(options.skill_source), 'excluded_names': skill_excludes,
                  'tree_sha256': stable_tree_sha256(options.skill_source, exclude_names=skill_excludes)}):
        raise ValueError('unsupported Fresh Skill source identity')
    if effective['suite'] != campaign.build_heavy_v3_suite_fingerprint(options):
        raise ValueError('unsupported Fresh suite identity')
    expected_runner = {'campaign_path': str(Path(campaign.__file__).resolve()),
        'campaign_sha256': sha256_file(Path(campaign.__file__)),
        'matrix_path': str(Path(campaign.matrix.__file__).resolve()),
        'matrix_sha256': sha256_file(Path(campaign.matrix.__file__))}
    if effective['runner'] != expected_runner:
        raise ValueError('unsupported Fresh runner identity')
    expected_harness = {'excluded_names': harness_excludes,
        'semantic_tree_sha256': stable_tree_sha256(campaign.REPO_ROOT / 'tests/semantic', exclude_names=harness_excludes),
        'destructive_support_tree_sha256': stable_tree_sha256(campaign.REPO_ROOT / 'tests/destructive/support', exclude_names=harness_excludes)}
    if options.profile in {campaign.AUDIO_IMPORT_BUSINESS_PROFILE_ID, campaign.matrix.DEEP_BUSINESS_ACCEPTANCE_PROFILE_ID}:
        expected_harness['protocol_manifest_revision'] = campaign._CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
    if effective['harness'] != expected_harness:
        raise ValueError('unsupported Fresh harness identity')
    try:
        units = campaign.load_heavy_v3_campaign_units(options)
    except SystemExit as exc:
        raise ValueError('Fresh original suite selection is unsupported: ' + str(exc)) from exc
    required = {unit.unit_id: [campaign._heavy_unit_phase(unit)] for unit in units}
    rows = [{**campaign.heavy_v3_unit_row(unit, sequence=index),
             'prompt_sha256': unit.scenario.prompt_sha256,
             'user_turn_count': unit.user_turn_count, 'transaction_count': unit.transaction_count,
             **campaign._policy_unit_metadata(unit)} for index, unit in enumerate(units, 1)]
    if effective['selection'] != {'profile': options.profile, 'case_ids': list(options.case_ids),
            'versions': list(options.versions), 'pair_ids': [], 'offline_only': options.offline_only,
            'units': rows, 'required_units': required}:
        raise ValueError('Fresh suite unit selection identity mismatch')
    selected = [unit for unit in units if unit.unit_id == record['unit_id'] and unit.version == record['version']]
    if len(selected) != 1:
        raise ValueError('Fresh exact unit/version identity missing')
    if getattr(selected[0], 'evidence_kind', None) == 'capability_boundary':
        raise ValueError('capability boundary grants no Fresh Agent PASS credit')
    options = replace(options, campaign_inputs_sha256=effective_hash,
                      protocol_manifest_revision=campaign._sealed_protocol_manifest_revision(effective))
    campaign.verify_campaign_marker(root, campaign_id=config['campaign_id'])
    manifests = campaign.load_verified_attempts(root)
    campaign.replay_expansion_attempts(root, options=options, units=units, manifests=manifests)
    if options.profile == campaign.MODIFICATION_POLICY_V3_PROFILE_ID:
        campaign._validate_modification_policy_identity_history(root, manifests=manifests)
    consolidated = consolidate_units(required, manifests)
    original = consolidated['units'][record['unit_id']]
    assessment = None
    if 'business_assessment' in record:
        from tests.maintenance.branch_audit_completion import read_sealed_artifact
        descriptor = record['business_assessment']
        if (not isinstance(descriptor, dict) or set(descriptor) != {'artifact', 'sha256'}
                or not Path(descriptor['artifact']).is_absolute()):
            raise ValueError('separate sealed absolute business assessment reference required')
        assessment = read_sealed_artifact(descriptor, root)
        if (not isinstance(assessment, dict) or assessment.get('effective_sha256') != effective_hash
                or assessment.get('unit_id') != record['unit_id']
                or assessment.get('version') != record['version']
                or assessment.get('original_verdict') != original['status']
                or not isinstance(assessment.get('reason'), str) or not assessment['reason'].strip()):
            raise ValueError('separate business assessment original identity/justification mismatch')
    return {'campaign_id': config['campaign_id'],
        'completion_candidate_sha256': record['candidate_sha256'],
        'branch_id': record['branch_id'], 'scope_kind': record['scope_kind'],
        'native_shape_sha256': record['native_shape_sha256'], 'native_route': record['native_route'],
        'campaign_config_sha256': record['campaign_config_sha256'],
        'effective_sha256': effective_hash, 'candidate': skill, 'suite': effective['suite'],
        'harness': effective['harness'], 'runner': effective['runner'],
        'options': effective['options'], 'unit_id': record['unit_id'], 'version': record['version'],
        'original_verdict': original['status'], 'original_observations': original['observations'],
        'business_assessment': assessment}


def fresh_evidence_result(descriptor, branch, candidate, scope_kind, base, binding, root):
    """Adapt original Fresh evidence without pytest invocation/node wrappers."""
    from tests.maintenance.branch_audit_completion import read_sealed_artifact, validate_equivalence
    try:
        record = read_sealed_artifact(descriptor, base)
        proof = read_fresh_proof(record)
        if (record['scope_kind'] != scope_kind or record['branch_id'] != branch['id']
                or record['native_shape_sha256'] != branch['shape_sha256']
                or record['native_route'] != branch['route']):
            raise ValueError('Fresh completion scope/branch identity mismatch')
        requirement = binding.get('fresh_requirement', {})
        expected_requirement = {'contract': 'waapi-skill.formal-fresh-requirement/v1',
            'branch_id': branch['id'], 'native_shape_sha256': branch['shape_sha256'],
            'native_route': branch['route'], 'archive_reference_sha256': descriptor['sha256'],
            'profile': proof['options']['profile'], 'effective_sha256': proof['effective_sha256'],
            'unit_id': proof['unit_id'], 'version': proof['version']}
        if (not isinstance(requirement, dict)
                or set(requirement) != set(expected_requirement) | {'mechanism', 'reviewed_reason'}
                or any(requirement.get(key) != value for key, value in expected_requirement.items())
                or not all(isinstance(requirement.get(key), str) and requirement[key].strip()
                           for key in ('mechanism', 'reviewed_reason'))):
            raise ValueError('exact reviewed Fresh interaction requirement missing or mismatched')
        current_skill = Path(root) / 'skills/waapi-skill'
        same_source = stable_tree_sha256(current_skill,
            exclude_names=proof['candidate']['excluded_names']) == proof['candidate']['tree_sha256']
        if record['candidate_sha256'] != candidate or not same_source:
            # A claimed candidate label cannot substitute for original source bytes.
            # Only hashes derived from the already verified original Skill or
            # current-compatible original harness can enter reviewed equivalence.
            original_sources = {}
            skill_root = Path(proof['candidate']['path'])
            for name in binding.get('relevant_sources', []):
                relative = Path(name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Fresh equivalence source path escaped original source')
                if relative.is_relative_to('skills/waapi-skill'):
                    source_boundary = skill_root
                    original = skill_root / relative.relative_to('skills/waapi-skill')
                elif any(relative.is_relative_to(prefix) for prefix in ('tests/semantic', 'tests/destructive/support')):
                    prefix = next(prefix for prefix in ('tests/semantic', 'tests/destructive/support')
                                  if relative.is_relative_to(prefix))
                    source_boundary = campaign.REPO_ROOT / prefix
                    original = campaign.REPO_ROOT / relative
                else:
                    raise ValueError('Fresh equivalence source is not bound by original sealed trees')
                if not original.resolve().is_relative_to(source_boundary.resolve()):
                    raise ValueError('Fresh equivalence source escaped original sealed tree')
                original_sources[name] = sha256_file(original)
            if not original_sources or record.get('relevant_sources') != original_sources:
                raise ValueError('Fresh equivalence original source hashes missing or mismatched')
            validate_equivalence(binding.get('equivalence', {}), descriptor, record,
                                 branch, candidate, binding, base, root)
        verdict = proof['original_verdict']
        if verdict == 'PASS':
            return 'passed', None
        return ('blocked' if verdict == 'BLOCKED' else 'missing',
                'original formal Fresh verdict: ' + verdict)
    except (CampaignEvidenceError, campaign.CampaignConfigError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        return 'missing', str(exc)

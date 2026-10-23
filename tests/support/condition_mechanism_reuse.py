"""Narrow reviewed condition reuse over original program/native evidence.

This adapter never adds recipient assertions to a native witness or changes the
ordinary source-equivalence rules. The original native run is a stable shared
identity, not a new run for every attached source member.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tests.maintenance import branch_audit_completion as completion
from tests.maintenance.branch_coverage_audit import digest
from tests.support.condition_scalar_batch import scalar_manifest, scalar_plan

REVIEW_PATH = 'tests/fixtures/metadata-conditions/lfo-eq-mechanism-review.json'
REVIEW_SHA256 = '05e840728b7e9fbf8433bf3d4f97ba313ecaf4255c9082ca9b67b6088bb78e12'


def load_review(root):
    raw = (root / REVIEW_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEW_SHA256:
        raise ValueError('Exact accepted condition-mechanism review differs')
    return json.loads(raw)


def _read(descriptor, base, *, category=False):
    from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
    expected = {'artifact', 'sha256', 'record_index', 'nodeid'} if category else {'artifact', 'sha256'}
    if not isinstance(descriptor, dict) or set(descriptor) != expected:
        raise ValueError('Closed portable condition-mechanism descriptor required')
    relative = parse_archive_relative_path(descriptor['artifact']).canonical
    base = Path(base).resolve(strict=True)
    path = base / relative
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(base):
        raise ValueError('Condition mechanism descriptor escapes its bundle')
    return completion.read_sealed_artifact(descriptor, base)


def _validate(attachment, base, root):
    review = load_review(root)
    fields = {'contract', 'review', 'members', 'originals', 'direct_recipient_native_effect', 'new_native_runs'}
    if (set(attachment) not in (fields, fields | {'include_scoped_metadata_mechanism'})
            or ('include_scoped_metadata_mechanism' in attachment and attachment['include_scoped_metadata_mechanism'] is not True)
            or attachment['contract'] != 'waapi-skill.condition-mechanism-attachment/v1'
            or attachment['direct_recipient_native_effect'] != 'not_observed'
            or type(attachment['new_native_runs']) is not int or attachment['new_native_runs'] != 0
            or attachment['review']['sha256'] != REVIEW_SHA256
            or _read(attachment['review'], base) != review):
        raise ValueError('Closed exact reviewed condition-mechanism attachment required')
    expected = [{'branch_id': i, 'shape_sha256': shape, 'owner_issue': 177, 'parent_issue': 174}
                for i, shape in review['selected_members'].items()]
    members = attachment['members']
    if (not isinstance(members, list) or len(members) != len(expected)
            or any(not isinstance(row, dict) or set(row) != {'branch_id', 'shape_sha256', 'owner_issue', 'parent_issue'} for row in members)
            or {row['branch_id']: row for row in members} != {row['branch_id']: row for row in expected}):
        raise ValueError('Exact condition member/shape/owner roster differs')
    if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != seal
           for name, seal in review['current_sources'].items()):
        raise ValueError('Reviewed condition source dependencies changed')
    # Rebuild the source graph, not a caller-authored graph/class assertion.
    manifest = scalar_manifest(root)
    group = next(g for g in scalar_plan(manifest)['groups'] if g['id'] == review['group_id'])
    if ({m['id']: m['shape_sha256'] for m in group['members']} != review['selected_members']
            or digest(group['model']) != review['program_model_sha256']
            or group['version'] != review['version'] or group['build'] != review['build']):
        raise ValueError('Reviewed condition source grammar/type/topology differs')
    originals = attachment['originals']
    if (set(originals) != {'category', 'observation', 'class_metadata', 'accepted_review'}
            or any(originals[key]['sha256'] != value for key, value in review['originals'].items())):
        raise ValueError('Original condition witness or metadata digest differs')
    category = _read(originals['category'], base, category=True)
    witness = review['witness']
    if (originals['category']['nodeid'] != witness['nodeid']
            or originals['category']['record_index'] != witness['record_index']):
        raise ValueError('Original exact condition witness node differs')
    context = completion.read_category_run(originals['category'], base)
    if ({key: context[key] for key in ('version', 'build', 'host')} !=
            {key: review[key] for key in ('version', 'build', 'host')}
            or context['candidate'] != witness['candidate']):
        raise ValueError('Original condition witness host/build/candidate differs')
    observation = _read(originals['observation'], base)
    metadata = _read(originals['class_metadata'], base)
    accepted = _read(originals['accepted_review'], base)
    if (accepted['status'] != 'accepted_scoped_mechanism_reuse'
            or metadata['scope'] != {'kind': 'object_type', 'requested': 'ModulatorLfo',
                'resolved': {'classId': 4194320, 'name': 'ModulatorLfo', 'type': 'WObject'}}
            or metadata['mutation_authority'] is not False
            or metadata['metadata']['name'] != 'LfoSmoothing' or metadata['metadata']['type'] != 'Real64'
            or metadata['metadata']['dependencies'][0]['property'] != 'LfoWaveform'
            or metadata['metadata']['dependencies'][0]['action'] != 'Enable'
            or metadata['metadata']['dependencies'][0]['context'] != 'Self'
            or [r['value'] for r in metadata['metadata']['dependencies'][0]['conditions'][0]['restriction']['values']] != [1, 2, 3, 4]):
        raise ValueError('Exact class-scoped LFO metadata/accepted review differs')
    if (observation['candidate'] != witness['candidate'] or observation['version'] != review['version']
            or observation['status'] != 'PASS' or observation['business_effect_verified'] is not True
            or observation['before']['target']['class_id'] != 6881283
            or observation['after']['target']['properties']['GainBand1'] != 3.0
            or observation['before']['target']['properties']['GainBand1'] != 4.0
            or observation['metadata_before'] != observation['metadata_after']
            or not all(t['state'] == 'verified' for t in category['transactions'])
            or len(category['transactions']) != 1
            or not any(r.get('observation_sha256') == originals['observation']['sha256']
                       and r.get('business_effect_verified') is True and r.get('status') == 'PASS' for r in category['categories'])):
        raise ValueError('Original EQ condition effect/preservation linkage differs')
    target_id = observation['before']['target']['id']
    scoped = [r for r in observation['reads'] if r['argv'][:4] == ['metadata', 'detail', '--exact-id', target_id]]
    if (len(scoped) != 8 or any(r['exit_code'] != 0 or r['payload']['agent_result']['scope'] !=
            {'kind': 'object', 'object': target_id} for r in scoped)):
        raise ValueError('Original native object-scoped metadata/guard witness differs')
    return review, group


def attach_condition_mechanisms(descriptors, bindings, read, base, root):
    """Attach exact reviewed reuse to existing bindings; duplicate runs deduplicate."""
    if not isinstance(descriptors, list):
        raise ValueError('Closed condition attachment list required')
    attached, facts, pending = set(), {}, []
    for descriptor in descriptors:
        attachment = _read(descriptor, base)
        if read(descriptor) != attachment:
            raise ValueError('Condition attachment reader changed original content')
        review, _ = _validate(attachment, base, root)
        for identity in review['selected_members']:
            if identity in attached or identity not in bindings:
                raise ValueError('Missing or conflicting condition-mechanism attachment')
            binding = bindings[identity]
            if (binding.get('branch_id') != identity
                    or binding.get('native_shape_sha256') != review['selected_members'][identity]
                    or set(binding.get('evidence', {})) != {'program'}
                    or binding.get('condition_mechanism_attachment')):
                raise ValueError('Condition reuse requires its exact existing program binding')
            attached.add(identity)
        pending.append((descriptor, attachment, review))
        facts[review['review_id']] = {'review_id': review['review_id'],
            'original_witness_run_id': review['witness']['run_id'],
            'direct_recipient_native_effect': 'not_observed', 'new_native_runs': 0}
    for descriptor, attachment, review in pending:
        for identity in review['selected_members']:
            bindings[identity]['condition_mechanism_attachment'] = deepcopy(descriptor)
            bindings[identity]['evidence']['native'] = {**deepcopy(descriptor), 'nodeid': review['witness']['nodeid']}
            if attachment.get('include_scoped_metadata_mechanism'):
                bindings[identity]['condition_metadata_mechanism_attachment'] = deepcopy(descriptor)
                bindings[identity]['evidence']['live_metadata'] = {**deepcopy(descriptor), 'nodeid': review['witness']['nodeid']}
    return list(facts.values())


def condition_mechanism_result(descriptor, branch, candidate, scope_kind, base, binding, root, reference_edges, *, category="native"):
    """Keep program, class metadata and native-mechanism credit distinguishable."""
    proof = binding['condition_metadata_mechanism_attachment' if category == 'live_metadata' else 'condition_mechanism_attachment']
    if ({key: descriptor[key] for key in ('artifact', 'sha256')} != proof):
        raise ValueError('Condition native evidence must select its exact attachment')
    attachment = _read(proof, base)
    if category == 'live_metadata' and not attachment.get('include_scoped_metadata_mechanism'):
        raise ValueError('The explicit scoped metadata mechanism attachment is required')
    review, group = _validate(attachment, base, root)
    if (branch['id'] not in review['selected_members'] or branch['shape_sha256'] != review['selected_members'][branch['id']]
            or branch.get('source_file_sha256') != review['source_file_sha256']
            or branch.get('owner_issue') != 177 or branch.get('parent_issue') != 174
            or branch['version'] != review['version'] or branch['build'] != review['build']
            or branch.get('route') is not None or branch.get('kind') != 'metadata_condition'
            or descriptor['nodeid'] != review['witness']['nodeid']):
        raise ValueError('Condition reuse branch ownership/shape/host differs')
    program = completion.read_sealed_artifact(binding['evidence']['program'], base)
    if program.get('observations', {}).get('metadata') != group['model']['metadata'][group['field']]:
        raise ValueError('Current public program metadata graph differs from reviewed source model')
    result = completion.evidence_result(binding['evidence']['program'], branch, candidate, 'program',
        scope_kind, base, binding, root, reference_edges)
    if result != ('passed', None):
        raise ValueError('Current exact public condition program binding is not proven: ' + str(result))
    if category == 'live_metadata':
        _require_object_scope_mechanism(program, review)
        return 'reviewed_class_metadata_and_object_scope_mechanism', (review['review_id']
            + '; metadata_scope=object_type; direct_recipient_instance_metadata=not_observed')
    return 'reviewed_mechanism_reuse', (review['review_id'] + '; original_witness_run_id=' + review['witness']['run_id']
        + '; direct_recipient_native_effect=not_observed; new_native_runs=0')


def _require_object_scope_mechanism(program, review):
    if program.get('direct_recipient_instance_metadata', 'not_observed') != 'not_observed':
        raise ValueError('Reviewed class metadata cannot be promoted to an observed recipient instance')
    calls = program.get('object_scope_call_trace', [])
    mutation = program['native_call']
    if (not isinstance(calls, list) or any(not isinstance(call, dict)
            or not isinstance(call.get('uri'), str)
            or (call.get('args') is not None and not isinstance(call['args'], dict)) for call in calls)):
        raise ValueError('Current public object-scoped trace calls require a string URI and mapping or null arguments')
    if sum(c['uri'].endswith('setProperty') for c in calls) != 1:
        raise ValueError('Current public object-scoped read/refresh trace is missing')
    index = calls.index(mutation)
    identity = mutation['args']['object']
    for name in (review['selected_field'], review['controller']):
        def matches(call):
            return (call['uri'] == 'ak.wwise.core.object.getPropertyInfo'
                    and call['args'] == {'object': identity, 'property': name})
        if sum(matches(c) for c in calls[:index]) < 2 or not any(matches(c) for c in calls[index + 1:]):
            raise ValueError('Current public object-scoped read/refresh/verification trace differs')

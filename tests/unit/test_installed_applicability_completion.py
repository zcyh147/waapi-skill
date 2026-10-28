"""Source applicability is a join, never one native test per installed class."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

ROOT = Path(__file__).parents[2]


def test_exact_installed_roster_separates_birth_from_existing_field_access():
    from tests.support.applicability_completion_mapping import definition_mapping
    mapping = definition_mapping(ROOT)
    assert mapping['denominator'] == {'target_applicability': 1110, 'plugin_topology': 554}
    assert len({r['id'] for r in mapping['rows']}) == 1664
    rows = {(r['version'], r['class_name'], r['operation_mode'], r['kind']): r for r in mapping['rows']}
    assert rows['2025.1', 'MetadataSlot', 'new-object', 'target_applicability']['correspondence']['path'] == 'owned_list_constructor'
    assert rows['2021.1', 'MusicClip', 'new-object', 'target_applicability']['correspondence']['path'] == 'owned_list_constructor'
    assert rows['2021.1', 'MusicClip', 'new-object', 'target_applicability']['correspondence']['operations'] == ['object.create']
    assert rows['2025.1', 'MusicClip', 'existing-object', 'target_applicability']['correspondence']['path'] == 'exact_existing_object_fields'
    assert rows['2021.1', 'Wwise System Output Settings', 'new-object', 'plugin_topology']['state'] == 'approved_exclusion'
    assert rows['2021.1', 'Wwise System Output Settings', 'existing-object', 'plugin_topology']['state'] != 'approved_exclusion'
    assert rows['2025.1', 'Wwise System Output Settings', 'new-object', 'plugin_topology']['correspondence']['placements'] == ['shareset', 'owner-local-metadata']
    assert all(r['native_effect'] == 'not_claimed' for r in mapping['rows'])


def test_changed_or_unknown_source_cannot_become_constructible(tmp_path):
    from tests.support.applicability_completion_mapping import definition_mapping, validate_mapping
    mapping = definition_mapping(ROOT)
    for damage in ('mode', 'source', 'missing-source', 'route', 'missing', 'absence', 'version'):
        proposed = deepcopy(mapping)
        row = next(r for r in proposed['rows'] if r['class_name'] == 'MetadataSlot' and r['operation_mode'] == 'new-object')
        if damage == 'mode': row['operation_mode'] = 'existing-object'
        elif damage == 'source': row['source_file_sha256'] = '0' * 64
        elif damage == 'missing-source': row.pop('class_source')
        elif damage == 'route': row['correspondence']['operations'] = []
        elif damage == 'missing': proposed['rows'].pop()
        elif damage == 'version': row['version'] = '2021.1'
        else: row['state'] = 'proven_native_absence'
        with pytest.raises(ValueError, match='Exact installed applicability'):
            validate_mapping(proposed, ROOT)


def test_portable_applicability_join_keeps_unproved_births_assigned(tmp_path):
    from tests.maintenance.map_applicability_completion import main
    from tests.maintenance.branch_coverage_audit import portable_binding_inputs
    from tests.maintenance.branch_audit_completion import evaluate_coverage
    from tests.maintenance.branch_coverage_audit import digest, load
    from tests.maintenance.branch_audit_completion import installed_obligations
    base = tmp_path / 'join'
    assert main(['--output-directory', str(base)]) == 0
    result = {'requirements': load(base / 'requirements.json'), 'bindings': load(base / 'bindings.json'),
        'branches': [b for b in installed_obligations(ROOT, digest=digest, load=load)
            if b['kind'] in {'target_applicability', 'plugin_topology'}]}
    imported, base, inputs = portable_binding_inputs(tmp_path / 'join/evidence-index.json', result['requirements'])
    assert imported == result['bindings']
    assert inputs['installed_applicability']['exact_source_members'] == 1664
    subset = {'contract': result['requirements']['contract'],
        'branches': {r['id']: result['requirements']['branches'][r['id']] for r in result['branches']}}
    assessment = evaluate_coverage(ROOT, {'routes': [], 'native_coverage': {
        'candidate_sha256': 'c' * 64, 'catalogs': {}, 'routes': [], 'obligations': result['branches']}},
        imported, digest=digest, evidence_base=base, requirements_document=subset)
    assert assessment['completion']['complete'] is False
    assert assessment['completion']['obligations'] == 1664
    pending = [r for r in assessment['obligations'] if r['state'] == 'implementation_dependency']
    assert pending and all(r['implementation_dependencies'] for r in pending)
    assert any(r['business_dimensions']['class_name'] == 'WorkUnit' for r in pending)
    assert all(r.get('direct_recipient_native_effect') == 'not_observed' for r in assessment['obligations'])
    assert not any(r['state'] in {'verified', 'proven_native_absence'} for r in assessment['obligations'])
    assert load(base / 'assessment.json')['completion'] == assessment['completion']
    assert all(d.get('implementation_issue') == 205 for r in pending
        if r['business_dimensions']['class_name'] in {'WorkUnit', 'Query', 'SearchCriteria'}
        for d in r['implementation_dependencies'])
    previous = load(ROOT / 'docs/branch-coverage-requirements.json')['branches']
    assert all(result['requirements']['branches'][i] == p for i, p in previous.items()
        if i not in {b['id'] for b in result['branches']})


@pytest.mark.parametrize('source,damage', [
    ('skills/waapi-skill/wwise_waapi/documented_list_fields.py', 'changed'),
    ('skills/waapi-skill/resources/metadata/2021.1/installed-owned-list-fields.json', 'changed'),
    ('skills/waapi-skill/resources/metadata/2021.1/installed-owned-list-fields.json', 'missing'),
    ('skills/waapi-skill/wwise_waapi/operation_registry.py', 'removed-route')])
def test_changed_invoked_code_or_resource_invalidates_shared_proof(tmp_path, source, damage):
    from tests.support.platform_filesystem import create_symlink_or_skip
    from tests.support.applicability_completion_mapping import program_review
    for directory in ('tests', 'docs'):
        create_symlink_or_skip(tmp_path / directory, ROOT / directory, target_is_directory=True)
    for directory in ('scripts', 'wwise_waapi', 'resources'):
        for original in (ROOT / 'skills/waapi-skill' / directory).rglob('*'):
            if not original.is_file() or '__pycache__' in original.parts:
                continue
            relative = original.relative_to(ROOT)
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative.as_posix() == source:
                raw = original.read_bytes()
                if damage == 'missing':
                    continue
                if damage == 'removed-route':
                    lines = raw.splitlines(keepends=True)
                    selected = [line for line in lines if line.startswith(b'    ("object.createPlugin",')]
                    assert len(selected) == 1
                    raw = raw.replace(selected[0], b'', 1)
                else:
                    raw += b'\nchanged-proof-input\n'
                target.write_bytes(raw)
            else:
                create_symlink_or_skip(target, original)
    with pytest.raises(ValueError, match='source closure'):
        program_review(tmp_path)


def test_attachment_import_is_atomic_and_never_grants_native_credit(tmp_path):
    from tests.support.applicability_completion_mapping import export_mapping, attach_mappings
    from tests.maintenance.branch_audit_completion import evidence_result
    result = export_mapping(ROOT, tmp_path)
    identity = next(iter(result['bindings']['bindings']))
    branch = next(r for r in result['branches'] if r['id'] == identity)
    binding = result['bindings']['bindings'][identity]
    for category in ('native', 'live_metadata'):
        assert evidence_result(result['attachment'], branch, 'c' * 64, category, 'product', tmp_path, binding, ROOT)[0] == 'missing'
    for descriptors, retained in (([result['attachment']] * 2, {}),
            ([result['attachment']], {identity: {'original': 'preserve'}})):
        before = deepcopy(retained)
        with pytest.raises(ValueError):
            attach_mappings(descriptors, retained, tmp_path, ROOT)
        assert retained == before

"""New-object source mapping keeps constructor proof and applicability separate."""
from copy import deepcopy
from pathlib import Path
import gzip
import hashlib
import json
import os

import pytest

from tests.maintenance.branch_coverage_audit import digest, load
from tests.support.condition_completion_mapping import definition_mapping, validate_mapping_attachment

ROOT = Path(__file__).parents[2]


def test_new_condition_roster_preserves_mode_shapes_and_unproved_applicability():
    from tests.maintenance.branch_audit_completion import installed_obligations
    mapping = definition_mapping(ROOT, operation_mode='new-object')
    expected = {r['id']: r['shape_sha256'] for r in installed_obligations(ROOT, digest=digest, load=load)
                if r['owner_issue'] == 178 and r['kind'] == 'metadata_condition'}
    assert {m['id']: m['shape_sha256'] for r in mapping['occurrences'] for m in r['members']} == expected
    assert len(expected) == 7297
    assert mapping['owner_issue'] == 178 and mapping['operation_mode'] == 'new-object'
    association = [r for r in mapping['occurrences'] if r['source_attributes'].get('Context') == 'AssocParent']
    assert len(association) == 10
    assert all(r['construction_correspondence']['path'] == 'switch_assignment_owned_configuration' for r in association)
    assert all(r['applicability_obligations'] and not r['dependencies'] for r in association)
    assert len(mapping['source_forms']) == 9
    assert all(r['direct_recipient_native_effect'] == 'not_observed' for r in mapping['occurrences'])


@pytest.fixture(scope='module')
def bundle(tmp_path_factory):
    base = tmp_path_factory.mktemp('new-condition-map')
    from tests.maintenance.map_condition_completion import main
    assert main(['--output-directory', str(base), '--operation-mode', 'new-object']) == 0
    assessment = load(base / 'assessment.json')
    assert assessment['completion']['complete'] is True
    index = load(base / 'evidence-index.json')
    return base, {'attachment': index['condition_definition_attachments'][0],
        'mapping': load(base / 'mapping.json'), 'bindings': load(base / 'bindings.json'),
        'requirements': load(base / 'requirements.json')}


def test_same_completion_reader_retains_new_constructor_dependencies(bundle):
    from tests.maintenance.branch_audit_completion import evaluate_coverage
    from tests.maintenance.branch_coverage_audit import portable_binding_inputs
    from tests.support.condition_completion_mapping import attach_definition_mappings
    base, exported = bundle
    imported, actual_base, assessment = portable_binding_inputs(base / 'evidence-index.json', exported['requirements'])
    assert imported == exported['bindings'] and actual_base == base
    assert assessment['condition_source_definitions']['exact_source_members'] == 7297
    retained = {'unrelated-original': {'preserved': True}}
    with pytest.raises(ValueError, match='Duplicate'):
        attach_definition_mappings([exported['attachment']] * 2, retained, base, ROOT)
    assert retained == {'unrelated-original': {'preserved': True}}
    context = validate_mapping_attachment(exported['attachment'], base, ROOT)
    from tests.maintenance.branch_audit_completion import installed_obligations
    pending = [b for b in installed_obligations(ROOT, digest=digest, load=load)
        if b['kind'] in {'target_applicability', 'plugin_topology'}]
    inventory = {'routes': [], 'native_coverage': {'candidate_sha256': 'c' * 64, 'catalogs': {},
        'routes': [], 'obligations': [*context['branches'].values(), *pending]}}
    policies = {i: exported['requirements']['branches'][i] for i in context['branches']}
    result = evaluate_coverage(ROOT, inventory, exported['bindings'], digest=digest, evidence_base=base,
        requirements_document={'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': policies})
    assert result['completion']['complete'] is False
    assert result['completion']['states'] == {'approved_exclusion': 255,
        'source_definition_verified': 7042, 'unresolved': 1664}
    assert result['condition_source_definition_reuse']['original_native_witness_proofs'] == []
    assert all('native' not in b.get('requirements', []) for b in result['obligations'])
    previous = load(ROOT / 'docs/branch-coverage-requirements.json')['branches']
    assert all(exported['requirements']['branches'][i] == p for i, p in previous.items() if i not in context['branches'])


@pytest.mark.parametrize('damage', ['omitted-choice', 'mode', 'source', 'route', 'unassigned-recipient'])
def test_new_mode_mapping_cannot_omit_choices_or_borrow_existing_scope(bundle, damage):
    base, exported = bundle
    mapping = deepcopy(exported['mapping'])
    row = next(r for r in mapping['occurrences'] if r['source_pointer'].endswith('Property[EnvelopeStopPlayback]/Dependencies'))
    if damage == 'omitted-choice': row['members'].pop()
    elif damage == 'mode': row['occurrence_id'] = row['occurrence_id'].replace('|new-object|', '|existing-object|')
    elif damage == 'source': row['source_xml'] = '<PropertyDependency Name="invented" />'
    elif damage == 'route': row['construction_correspondence']['path'] = 'arbitrary_hierarchy_creation'
    else: row['applicability_obligations'] = []
    with pytest.raises(ValueError, match='exact source definition'):
        validate_mapping_attachment(exported['attachment'], base, ROOT, selected_mapping=mapping)


def test_new_source_mapping_cannot_claim_native_or_instance_metadata(bundle):
    from tests.maintenance.branch_audit_completion import evidence_result
    base, exported = bundle
    context = validate_mapping_attachment(exported['attachment'], base, ROOT)
    identity = next(i for i, r in context['members'].items() if r['source_pointer'].endswith('Property[EnvelopeStopPlayback]/Dependencies'))
    binding, branch = exported['bindings']['bindings'][identity], context['branches'][identity]
    for category in ('native', 'live_metadata'):
        assert evidence_result(exported['attachment'], branch, 'c' * 64, category, 'product', base, binding, ROOT)[0] == 'missing'



def test_non_object_condition_attachment_fails_closed(tmp_path):
    path = tmp_path / 'invalid.json'
    path.write_text('null')
    descriptor = {'artifact': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match='must be an object'):
        validate_mapping_attachment(descriptor, tmp_path, ROOT)


def test_changed_selected_constructor_helper_invalidates_program_proof(tmp_path):
    from tests.support.new_condition_completion import review
    (tmp_path / 'tests').symlink_to(ROOT / 'tests', target_is_directory=True)
    (tmp_path / 'docs').symlink_to(ROOT / 'docs', target_is_directory=True)
    for directory in ('scripts', 'wwise_waapi'):
        base = ROOT / 'skills/waapi-skill' / directory
        for source in base.rglob('*.py'):
            if '__pycache__' in source.parts:
                continue
            target = tmp_path / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.name == 'new_object_defaults.py':
                target.write_bytes(source.read_bytes() + b'\n# changed constructor dependency\n')
            else:
                target.symlink_to(source)
    (tmp_path / 'skills/waapi-skill/resources').symlink_to(ROOT / 'skills/waapi-skill/resources', target_is_directory=True)
    with pytest.raises(ValueError, match='source closure'):
        review(tmp_path)


def test_representative_new_condition_creation_and_verified_configuration(tmp_path, request):
    """Actual public Gateway code path; injected Wwise boundary, no native credit."""
    from tests.support.exact_evidence_finalization import register_exact_evidence_finalizer
    from tests.support.new_condition_completion import program_sources
    from tests.unit.test_new_object_conditions_gateway import ClassTask, restart, CREATED, EXISTING
    sources = program_sources(ROOT)
    observations = {}
    for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'):
        path = tmp_path / version; path.mkdir()
        task = ClassTask(path, version)
        before = deepcopy(task.objects[EXISTING])
        # Missing default requires user intent. Rejection is not constructor proof.
        del task.metadata['TimeModLoops']['default']
        task.declare(EnvelopeStopPlayback=False)
        code, rejected = task.step('draft-check')
        assert code == 2 and 'REFERENCE_ACTIVATION_REQUIRED' in str(rejected)
        assert CREATED not in task.objects
        restart(task, 'object.create')
        task.declare(EnvelopeStopPlayback=False, TimeModLoops=5)
        code, created = task.transaction('ask_before_changes')
        assert code == 0 and created['verified'] is True, created
        creation = created['transaction_id']
        restart(task, 'object.setProperty')
        code, bound = task.step('draft-bind-object', '--verified-created-from', creation)
        assert code == 0, bound
        handle = bound['bound_object']['handle']
        field = task.discover(handle, 'EnvelopeStopPlayback')
        code, declared = task.step('draft-declare-field-change', '--object-handle', handle,
            '--field-handle', field, '--business-value', 'true')
        assert code == 0, declared
        code, configured = task.transaction('ask_before_changes')
        assert code == 0 and configured['verified'] is True, configured
        assert configured['transaction_id'] != creation
        assert task.objects[EXISTING] == before
        assert task.objects[CREATED]['EnvelopeStopPlayback'] is True
        assert task.objects[CREATED]['TimeModLoops'] == 5
        writes = [{'uri': u, 'args': a, 'options': o} for u, a, o in task.calls
                  if u.endswith(('object.create', 'setProperty'))]
        assert len(writes) == 2
        observations[version] = {'class': {'name': task.class_name, 'classId': task.class_id},
            'missing_default': {'exit_code': 2, 'mutation_dispatched': False}, 'writes': writes,
            'created': deepcopy(task.objects[CREATED]), 'preserved_existing': task.objects[EXISTING] == before,
            'creation_verified': created['verified'], 'configuration_verified': configured['verified'],
            'distinct_transactions': creation != configured['transaction_id']}
    # Source shapes share the constructor compiler; these synthetic class
    # metadata models prove grammar and preserve the separate recipient ledger.
    mechanism_observations = {}
    enum = {'restriction': {'type': 'enum', 'values': [{'value': 1}]}}
    range_condition = {'restriction': {'type': 'range', 'min': 1, 'max': 100}}
    models = [
        ('OverrideDependency|Enable|Self|', {'type': 'override', 'action': 'Enable', 'context': 'Self', 'property': 'Gate'}, {'name': 'Gate', 'type': 'bool', 'default': False}),
        ('PropertyDependency|Enable|Self|Condition,Enumeration,Value', {'type': 'property', 'action': 'Enable', 'context': 'Self', 'property': 'Gate', 'conditions': [enum]}, {'name': 'Gate', 'type': 'int16', 'default': 1}),
        ('PropertyDependency|Show|Parent|Condition,Enumeration,Value', {'type': 'property', 'action': 'Show', 'context': 'Parent', 'property': 'Gate', 'conditions': [enum]}, None),
        ('PropertyDependency|Show|Self|Condition,Enumeration,Value', {'type': 'property', 'action': 'Show', 'context': 'Self', 'property': 'Gate', 'conditions': [enum]}, None),
        ('PropertyDependency|Show|Self|Condition,Max,Min,Range', {'type': 'property', 'action': 'Show', 'context': 'Self', 'property': 'Gate', 'conditions': [range_condition]}, None),
        ('ReferenceDependency|Enable|Self|Condition,ReferenceIsSet', {'type': 'reference', 'action': 'Enable', 'context': 'Self', 'property': 'Gate', 'conditions': [{'referenceIsSet': False}]}, {'name': 'Gate', 'type': 'Reference', 'default': None}),
    ]
    for index, (form, dependency, controller) in enumerate(models):
        path = tmp_path / ('grammar-' + str(index)); path.mkdir()
        task = ClassTask(path, '2025.1')
        task.metadata = {'EnvelopeStopPlayback': {'name': 'EnvelopeStopPlayback', 'type': 'bool',
            'default': True, 'dependencies': [deepcopy(dependency)]}}
        if controller is not None:
            task.metadata['Gate'] = controller
        task.declare(EnvelopeStopPlayback=False)
        code, verified = task.transaction('ask_before_changes')
        assert code == 0 and verified['verified'] is True, verified
        assert task.objects[CREATED]['EnvelopeStopPlayback'] is False
        writes = [{'uri': u, 'args': a, 'options': o} for u, a, o in task.calls if u.endswith('object.create')]
        assert len(writes) == 1
        if dependency['type'] == 'override':
            assert writes[0]['args']['@Gate'] is True and task.objects[CREATED]['Gate'] is True
        mechanism_observations[form] = {'verified': True, 'native_effect': 'not_observed',
            'metadata_model': deepcopy(task.metadata), 'writes': writes, 'scope': 'shared_class_default_compiler; not_recipient_applicability'}
    mechanism_observations['PropertyDependency|Enable|Self|Condition,Max,Min,Range'] = {
        'verified': True, 'native_effect': 'not_observed', 'observations': 'five-version range creation and verified configuration above'}
    from tests.unit.test_new_object_bus_conditions_gateway import _bus_children_task
    path = tmp_path / 'bus'; path.mkdir()
    task, writes = _bus_children_task(path)
    tx, shown = task.preview()
    code, verified = task.finish(tx, shown)
    assert code == 0 and verified['verified'] is True and len(writes) == 1
    mechanism_observations['IsMasterBusDependency|Enable|Self|'] = {
        'verified': True, 'native_effect': 'not_observed', 'scope': 'structurally proved non-master child', 'writes': writes}
    from tests.unit.test_switch_child_context_gateway import test_existing_type_absent_context_changes_property_through_owner_child_binding
    path = tmp_path / 'association'; path.mkdir()
    test_existing_type_absent_context_changes_property_through_owner_child_binding(path, '2025.1', False, 'ContinuePlay', True, None)
    mechanism_observations['PropertyDependency|Enable|AssocParent|Condition,Enumeration,Value'] = {
        'verified': True, 'native_effect': 'not_observed',
        'scope': 'shared exact owned-context configuration guard; constructor applicability remains in independent target obligations',
        'public_binding': 'draft-bind-switch-child-context --owner-handle --child-handle'}
    def finalized(reports):
        assert reports == {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}
        assert sources == program_sources(ROOT)
        record = {'contract': 'waapi-skill.new-condition-current-public-mechanism/v1',
            'evidence_kind': 'injected_client_program', 'scope_kind': 'product', 'reports': reports,
            'sources': sources, 'observations': observations, 'mechanism_observations': mechanism_observations, 'direct_recipient_native_effect': 'not_observed'}
        capture = Path(os.environ.get('WAAPI_NEW_CONDITION_CAPTURE', str(tmp_path / 'new-condition-program.json.gz')))
        assert not capture.exists()
        capture.write_bytes(gzip.compress(json.dumps(record, sort_keys=True).encode(), mtime=0))
    register_exact_evidence_finalizer(request.node, finalized)

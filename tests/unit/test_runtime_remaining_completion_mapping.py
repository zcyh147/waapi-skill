"""Exact remaining runtime mapping through the existing persisted consumer."""
from copy import deepcopy
import hashlib
import json
import pytest
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage


@pytest.fixture(scope='module')
def component():
    from tests.support.runtime_remaining_completion_mapping import runtime_component
    return runtime_component(audit.ROOT)


def test_runtime_remaining_maps_exact_sources_without_fabricating_native_proof(tmp_path, component):
    from tests.maintenance.map_runtime_remaining_completion import main
    from tests.support.runtime_remaining_completion_mapping import URIS
    assert main(['--output-directory', str(tmp_path)]) == 2
    requirements = audit.load(tmp_path / 'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(tmp_path / 'evidence-index.json', requirements)
    result = evaluate_coverage(audit.ROOT, component, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    assert len(URIS) == 20
    assert len(component['routes']) == 72
    assert len(component['native_coverage']['routes']) == 144
    assert len(bindings['bindings']) == len(component['native_coverage']['obligations']) == 5996
    assert {row['state'] for row in result['obligations']} == {'implemented_unverified'}
    assert sum('native' in row['requirements'] for row in result['obligations']) == 144
    assert any(row['runtime_native_anchor_status'] == 'missing' for row in result['obligations'])
    assert not any('unreviewed successor' in reason for row in result['obligations'] for reason in row['reasons'])
    mapped = [b['input']['correspondence'] for b in bindings['bindings'].values()]
    assert any(m.get('normalized_equivalent', {}).get('native_wire_omission_observed') is False for m in mapped)
    assert any(m.get('native_choice') == 'sound:convertedWemFilePath' and m['public_choices'] == ['sound:convertedWemFilePath'] for m in mapped)
    assert any(m.get('media_choice', {}).get('2023.1_omission') == 'accepted_explicit_choice_boundary_no_default_claim' for m in mapped)
    assert all(m['native_effect'] == 'not_claimed' for m in mapped)
    assert json.loads((tmp_path / 'requirements.json').read_bytes())['parts']


@pytest.mark.parametrize('damage', ['choice', 'host', 'version'])
def test_runtime_remaining_rejects_missing_native_roster(component, damage):
    from tests.support.runtime_remaining_completion_mapping import runtime_bindings
    broken = deepcopy(component)
    if damage == 'choice': broken['native_coverage']['obligations'].pop()
    elif damage == 'host': broken['native_coverage']['routes'].pop()
    else: broken['native_coverage']['obligations'] = [r for r in broken['native_coverage']['obligations'] if not r['id'].startswith('2021.1|')]
    with pytest.raises(ValueError, match='Runtime mapping.*roster'):
        runtime_bindings(audit.ROOT, broken)


@pytest.mark.parametrize('damage', ['field', 'choice', 'meter-choice'])
def test_runtime_remaining_rejects_removed_public_contract_member(component, monkeypatch, damage):
    from tests.support.runtime_remaining_completion_mapping import runtime_bindings
    from wwise_waapi import runtime_inspection_business_contracts as contracts
    from wwise_waapi import profiler_meter_objects as meter
    original = contracts.runtime_inspection_business_contract_data
    def missing(uri, version):
        value = original(uri, version)
        if uri.endswith('enableProfilerData'):
            if damage == 'field': value['declaration']['required_fields'].remove('capture_data_changes')
            elif damage == 'choice': value['declaration']['value_choices']['capture_data_changes.data_set'].remove('voices')
        return value
    monkeypatch.setattr(contracts, 'runtime_inspection_business_contract_data', missing)
    if damage == 'meter-choice':
        names = meter.meter_named_outputs
        monkeypatch.setattr(meter, 'meter_named_outputs', lambda v: {k:x for k,x in names(v).items() if k != 'sound:convertedWemFilePath'})
    with pytest.raises(ValueError, match='Runtime.*(disclosed|correspondence)'):
        runtime_bindings(audit.ROOT, component)


def test_runtime_remaining_missing_source_is_rejected_by_ordinary_reader(tmp_path, component):
    from tests.support.runtime_remaining_completion_mapping import export_mapping
    exported = export_mapping(audit.ROOT, tmp_path, inventory=component)
    requirements = deepcopy(exported['requirements'])
    for mechanism in requirements['representative_mechanisms'].values():
        mechanism['sources'].pop('skills/waapi-skill/wwise_waapi/profiler_meter_objects.py')
    index = json.loads(exported['index_path'].read_bytes())
    for descriptor in index['mapping_attachments']:
        path = tmp_path / descriptor['artifact']; attachment = json.loads(path.read_bytes())
        attachment['requirements_sha256'] = audit.digest(requirements)
        path.write_text(json.dumps(attachment)); descriptor['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    exported['index_path'].write_text(json.dumps(index))
    with pytest.raises(ValueError, match='source closure is incomplete'):
        audit.portable_binding_inputs(exported['index_path'], requirements)


def test_runtime_remaining_unfinalized_capture_is_not_code_proof(tmp_path, component):
    from tests.support.runtime_remaining_completion_mapping import program_anchors
    for name in ('run.plan.json', 'run.result.json', 'run.summary.json'):
        (tmp_path / name).write_text('{}')
    with pytest.raises(ValueError, match='missing or unfinalized'):
        program_anchors(audit.ROOT, component, tmp_path / 'out', tmp_path)


def test_runtime_remaining_imports_keep_original_receipts_without_current_native_credit():
    from tests.support.runtime_remaining_completion_mapping import BASE
    root = audit.ROOT / BASE
    for name, expected in [('retained-transport-r133', 14), ('retained-meter-r137', 1)]:
        base = root / name
        review = json.loads((base / 'import-review.json').read_bytes())
        raw = (base / 'original-index.json').read_bytes()
        assert hashlib.sha256(raw).hexdigest() == review['original_index_sha256']
        original, selected = json.loads(raw), json.loads((base / 'index.json').read_bytes())
        assert len(selected['entries']) == expected
        assert all(entry in original['entries'] for entry in selected['entries'])
        for kind in ('runtime_observation_attachments', 'qualified_runtime_read_attachments'):
            assert all(item in original.get(kind, []) for item in selected.get(kind, []))
        for name, seal in review['files'].items():
            assert hashlib.sha256((base / name).read_bytes()).hexdigest() == seal
        assert review['new_native_execution'] is False
        assert review['current_candidate_admission'].startswith('not_claimed;')
        imported, _, _ = audit.portable_binding_inputs(base / 'index.json', audit.load(base / 'requirements.json'))
        assert len(imported['bindings']) == (42 if expected == 14 else 3)


def test_runtime_proof_plan_joins_explicit_routes_and_retains_all_profile_identities(component):
    from tests.support.runtime_remaining_completion_mapping import build_retained_history, selected_proof_plan
    native = component['native_coverage']
    assert any('/patternProperties/' in row['pointer'] and '|' in row['pointer'] for row in native['obligations'])
    history = build_retained_history(audit.ROOT, native)
    plan = selected_proof_plan(native, history)
    meters = plan['rows']['ak.wwise.core.profiler.getMeters']
    assert set(meters['native_routes']) == {
        '2024.1|wwise-authoring|2024.1.13.9056|function|ak.wwise.core.profiler.getMeters',
        '2024.1|wwise-console|2024.1.13.9056|function|ak.wwise.core.profiler.getMeters',
        '2025.1|wwise-authoring|2025.1.7.9143|function|ak.wwise.core.profiler.getMeters',
        '2025.1|wwise-console|2025.1.7.9143|function|ak.wwise.core.profiler.getMeters'}
    assert len(meters['retained_native_profiles']) == 2
    names = ('getMeters', 'getCpuUsage', 'getPerformanceMonitor', 'getStreamedMedia')
    assert sum(len(plan['rows']['ak.wwise.core.profiler.' + name]['retained_native_profiles']) for name in names) == 20
    assert sum(len(row['retained_native_profiles']) for row in plan['rows'].values()) == 133
    assert sum(len(row['routes_without_profile']) for row in plan['rows'].values()) == 11
    assert sum(len(row['native_routes']) for row in plan['rows'].values()) == 144
    assert history['sources']['tests/fixtures/runtime-meter/support-review.json']['original_profile_ids'][0].endswith('|/resultSchema')
    assert len(meters['retained_profile_identities']) == 2
    from tests.support.runtime_remaining_completion_mapping import BASE
    assert plan == json.loads((audit.ROOT / BASE / 'selected-proof-plan.json').read_bytes())
    assert history == json.loads((audit.ROOT / BASE / 'accepted-history.json').read_bytes())


@pytest.mark.parametrize('damage', ['unknown-profile', 'mismatched-profile-route', 'unknown-member', 'mismatched-member-route', 'unknown-retained-profile'])
def test_runtime_proof_plan_rejects_unexpected_source_identities(component, damage):
    from tests.support.runtime_remaining_completion_mapping import build_retained_history, selected_proof_plan, retained_profile_mappings
    native = deepcopy(component['native_coverage'])
    if damage == 'unknown-retained-profile':
        history = build_retained_history(audit.ROOT, native)
        record = history['sources']['tests/fixtures/runtime-meter/support-review.json']
        identity = record['original_profile_ids'][0]
        record['original_profile_ids'][0] += '|unexpected'
        record['profile_mappings'][identity + '|unexpected'] = record['profile_mappings'].pop(identity)
        with pytest.raises(ValueError, match='profile identity'):
            selected_proof_plan(native, history)
        return
    if 'profile' in damage:
        source = 'tests/fixtures/runtime-meter/support-review.json'
        document = json.loads((audit.ROOT / source).read_bytes())
        identity = next(iter(document['profiles']))
        if damage == 'unknown-profile': document['profiles'][identity + '|unexpected'] = document['profiles'].pop(identity)
        else: document['profiles'][identity]['route'] = next(route['id'] for route in native['routes'] if route['uri'].endswith('getCpuUsage'))
        with pytest.raises(ValueError, match='profile identity'):
            retained_profile_mappings(native, source, document)
    else:
        history = build_retained_history(audit.ROOT, native)
        if damage == 'unknown-member': native['obligations'][0]['route'] += '|unexpected'
        else: native['obligations'][0]['id'] += '|unexpected'
        with pytest.raises(ValueError, match='member identity'):
            selected_proof_plan(native, history)

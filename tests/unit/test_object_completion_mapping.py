"""Exact object correspondence reaches ordinary portable completion readers."""
from copy import deepcopy
import json
import pytest
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage


@pytest.fixture(scope='module')
def object_inventory():
    from tests.support.object_completion_mapping import object_component
    return object_component(audit.ROOT)


def test_object_cohort_preserves_exact_sources_and_truthful_boundaries(tmp_path, object_inventory):
    from tests.support.object_completion_mapping import export_mapping
    exported = export_mapping(audit.ROOT, tmp_path, inventory=object_inventory)
    requirements = audit.load(exported['requirements_path'])
    bindings, base, _ = audit.portable_binding_inputs(exported['index_path'], requirements)
    report = evaluate_coverage(audit.ROOT, object_inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    assert len(object_inventory['native_coverage']['routes']) == 112
    assert len(object_inventory['routes']) == 56
    assert set(bindings['bindings']) == {r['id'] for r in object_inventory['native_coverage']['obligations']}
    assert {r['state'] for r in report['obligations']} == {'implemented_unverified'}
    mapped = [b['input']['correspondence'] for b in bindings['bindings'].values()]
    assert any(m.get('native_choice') == 'replaceAll' and m['public_choice'] == 'replace-all' for m in mapped)
    assert any(m['rule'] == 'native_internal_id_prohibited' for m in mapped)
    assert any(m['rule'] == 'metadata_authorized_native_value_union' for m in mapped)
    assert all(m['native_effect'] == 'not_claimed' for m in mapped)
    assert exported['summary']['non_uri_metadata_completion_claimed'] is False
    assert exported['summary']['requirements_parts']
    # The real component must admit the delivered source scope before its
    # ordinary portable readers can evaluate it. Discovery remains separate
    # from constructor authority and native execution evidence.
    lanes = object_inventory['business_correspondence']['lanes']
    for lane in lanes.values():
        assert lane['parent_choices']['Query'] == {'allowed_children': ['SearchCriteria']}
        assert lane['parent_choices']['ControlSurfaceSession'] == {'allowed_children': ['ControlSurfaceBindingGroup']}
        assert lane['parent_choices']['ControlSurfaceBindingGroup'] == {
            'allowed_children': ['ControlSurfaceBinding', 'ControlSurfaceBindingGroup']}
        assert lane['plugin_inputs']['source_owner_types'] == ['Sound', 'Voice']
        assert lane['native_effect'] == 'not_claimed'
    classes = {r['name']: r for r in lanes['2021.1']['owned_lists']['classes']}
    assert [r['name'] for r in classes['MusicSegment']['lists']] == ['Cues', 'Stingers', 'Metadata']
    assert [r['name'] for r in classes['MusicTrackSequence']['lists']] == ['Clips']
    assert lanes['2021.1']['owned_lists']['coverage']['installed_owned_list_declarations'] == 17
    assert all([r['name'] for r in next(c for c in lanes[version]['owned_lists']['classes']
        if c['name'] == 'AudioFileSource')['lists']] == ['Markers']
        for version in ('2023.1', '2024.1', '2025.1'))


@pytest.mark.parametrize('damage', ['field', 'choice', 'version'])
def test_object_mapping_rejects_missing_exact_native_member(object_inventory, damage):
    from tests.support.object_completion_mapping import object_bindings
    broken = deepcopy(object_inventory)
    if damage == 'version': broken['native_coverage']['routes'].pop()
    else:
        rows = broken['native_coverage']['obligations']
        rows.pop(next(i for i, r in enumerate(rows) if r['kind'] == ('enum_value' if damage == 'choice' else 'empty_string')))
    with pytest.raises(ValueError, match='Object mapping.*roster'):
        object_bindings(audit.ROOT, broken)


@pytest.mark.parametrize('damage', ['field', 'choice'])
def test_object_mapping_rejects_removed_public_input(object_inventory, monkeypatch, damage):
    import wwise_waapi.object_graph_business_contracts as business
    from tests.support.object_completion_mapping import object_bindings
    original = business.object_graph_business_contract_data
    def missing(operation, version):
        result = original(operation, version)
        if operation == 'object.create':
            if damage == 'field':
                result['declaration']['stable_fields'].pop('notes')
                result['declaration']['field_value_types'].pop('notes')
            else: result['settings']['name_conflict'].remove('replace')
        return result
    monkeypatch.setattr(business, 'object_graph_business_contract_data', missing)
    with pytest.raises(ValueError, match='Object public (field|conflict choice)'):
        object_bindings(audit.ROOT, object_inventory)


@pytest.fixture(scope='module')
def documented_catalogs():
    from wwise_waapi.documented_list_fields import load_catalog
    from tests.support.object_completion_mapping import VERSIONS
    return {version: load_catalog(version) for version in VERSIONS}


@pytest.mark.parametrize('damage', ['class', 'original-source-list', 'unlisted-list',
    'reviewed-list', 'reviewed-shape', 'overlay-version'])
def test_object_mapping_rejects_removed_business_list_member(monkeypatch, documented_catalogs, damage):
    from tests.support.object_completion_mapping import object_component
    import wwise_waapi.documented_list_fields as lists
    def missing(version):
        catalog = deepcopy(documented_catalogs[version])
        classes = {r['name']: r for r in catalog['classes']}
        if version == '2025.1':
            if damage == 'class': catalog['classes'].pop()
            elif damage == 'original-source-list': classes['AudioFileSource']['lists'].clear()
            elif damage == 'unlisted-list':
                foreign = deepcopy(classes['AudioFileSource']['lists'][0])
                foreign['name'] = 'UnreviewedMarkers'
                classes['AudioFileSource']['lists'].append(foreign)
        if version == '2021.1':
            if damage == 'reviewed-list': classes['MusicSegment']['lists'].pop(0)
            elif damage == 'reviewed-shape':
                classes['MusicSegment']['lists'][0]['element_classes'] = [{'name': 'Marker', 'class_id': 5373968}]
            elif damage == 'overlay-version': catalog['source']['build'] = '2022.1.19.8584'
        return catalog
    monkeypatch.setattr(lists, 'load_catalog', missing)
    error = ('DOCUMENTED_LIST_SELECTION_REQUIRED' if damage == 'original-source-list'
        else 'Object class/plugin/List source member roster')
    with pytest.raises(ValueError, match=error):
        object_component(audit.ROOT)


@pytest.mark.parametrize('source', [
    'tests/fixtures/branch-evidence/product/object-195-r1/business-source-roster.json',
    'tests/fixtures/branch-evidence/product/object-195-r1/business-source-reconciliation.json',
    'skills/waapi-skill/resources/metadata/control-surface-constructor-sources.json'])
def test_object_mapping_rejects_changed_review_predecessor_or_source(monkeypatch, source):
    from pathlib import Path
    from tests.support.object_completion_mapping import object_component
    original = Path.read_bytes
    selected = audit.ROOT / source
    def changed(path):
        raw = original(path)
        return raw + b'\n' if path == selected else raw
    monkeypatch.setattr(Path, 'read_bytes', changed)
    with pytest.raises(ValueError, match='Object class/plugin/List source member roster'):
        object_component(audit.ROOT)


@pytest.mark.parametrize('damage', ['missing-construction-source', 'changed-reconciliation-source'])
def test_object_mapping_missing_source_proof_is_rejected_by_ordinary_reader(tmp_path, object_inventory, monkeypatch, damage):
    import hashlib
    from pathlib import Path
    from tests.support.object_completion_mapping import export_mapping
    exported = export_mapping(audit.ROOT, tmp_path, inventory=object_inventory)
    requirements = deepcopy(exported['requirements'])
    if damage == 'changed-reconciliation-source':
        original = Path.read_bytes
        selected = audit.ROOT / 'tests/fixtures/branch-evidence/product/object-195-r1/business-source-reconciliation.json'
        def changed(path):
            raw = original(path)
            return raw + b'\n' if path == selected else raw
        monkeypatch.setattr(Path, 'read_bytes', changed)
        with pytest.raises(ValueError, match='representative reviewed source changed'):
            audit.portable_binding_inputs(exported['index_path'], requirements)
        return
    requirements['representative_mechanisms']['object195-graph-v1']['sources'].pop('skills/waapi-skill/wwise_waapi/object_graph_business.py')
    index = json.loads(exported['index_path'].read_bytes())
    for descriptor in index['mapping_attachments']:
        path = tmp_path / descriptor['artifact']
        attachment = json.loads(path.read_bytes())
        attachment['requirements_sha256'] = audit.digest(requirements)
        path.write_text(json.dumps(attachment))
        descriptor['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    exported['index_path'].write_text(json.dumps(index))
    with pytest.raises(ValueError, match='source closure is incomplete'):
        audit.portable_binding_inputs(exported['index_path'], requirements)


def test_object_program_anchor_rejects_unfinalized_proof(tmp_path, object_inventory):
    from tests.support.object_completion_mapping import program_anchors
    for name in ('run.plan.json', 'run.result.json', 'run.summary.json'): (tmp_path / name).write_text('{}')
    with pytest.raises(ValueError, match='Object selected code anchor is missing or unfinalized'):
        program_anchors(audit.ROOT, object_inventory, tmp_path / 'out', tmp_path)

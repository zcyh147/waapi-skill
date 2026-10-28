"""Exact #182 mapping remains distinct from representative execution proof."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_imports_mapping_tracks_row_defaults_source_language_and_accepted_guards():
    from tests.support.imports_completion_mapping import imports_component, imports_bindings
    component = imports_component(ROOT)
    bindings = imports_bindings(ROOT, component)
    def correspondence(ending):
        return next(b['input']['correspondence'] for key, b in bindings.items()
            if key.startswith('2025.1|wwise-console|') and '|ak.wwise.core.audio.import|' in key
            and key.endswith(ending))
    assert correspondence('/argsSchema/properties/default/properties/audioFile')['public_fields'] == ['defaults.media_file']
    assert correspondence('/argsSchema/properties/imports/items/properties/importLanguage')['public_fields'] == ['language']
    assert correspondence('/argsSchema/properties/importOperation')['mode_mapping'] == {
        'createNew': 'derived_create', 'useExisting': 'derived_reimport', 'replaceExisting': 'explicit_replace'}
    assert component['accepted_limits']['duplicate_source_guard'] == 'wwise-console|2025.1.7.9143'
    assert bindings and all(binding['evidence'] == {} for binding in bindings.values())

from copy import deepcopy
import json
import pytest


@pytest.fixture(scope='module')
def component():
    from tests.support.imports_completion_mapping import imports_component
    return imports_component(ROOT)


@pytest.fixture(scope='module')
def exported(component, tmp_path_factory):
    from tests.support.imports_completion_mapping import export_imports_mapping
    directory = tmp_path_factory.mktemp('imports-mapping')
    return directory, export_imports_mapping(ROOT, directory, inventory=component)


def test_imports_native_discovery_covers_only_exact_owner_and_all_reference_sites(component):
    from collections import Counter
    from tests.support.imports_completion_mapping import imports_bindings, OWNERS
    native = component['native_coverage']
    assert len(component['routes']) == 15
    assert len(native['catalogs']) == 10
    assert len(native['routes']) == 28
    assert len(native['obligations']) == 12990
    assert {r['uri'] for r in native['routes']} == set(OWNERS)
    assert Counter(r['version'] for r in native['routes']) == {'2021.1': 6, '2022.1': 6, '2023.1': 6, '2024.1': 5, '2025.1': 5}
    bindings = imports_bindings(ROOT, component)
    row = next(r for r in native['obligations'] if r['id'].startswith('2025.1|wwise-console|')
        and '|ak.wwise.core.audio.import|' in r['id']
        and r['pointer'].endswith('/@definition/<schema>/properties/default/properties/audioFile'))
    mapping = bindings[row['id']]['input']['correspondence']
    assert mapping['public_fields'] == ['media_file']
    assert mapping['native_addresses'][0]['native_path'] == ['imports', None, 'audioFile']
    identities = {r['id'] for r in native['obligations']}
    assert all(r['reference']['target'] in identities for r in native['obligations'] if 'reference' in r)


@pytest.mark.parametrize('damage', ['missing-choice', 'changed-choice', 'missing-version'])
def test_imports_mapping_rejects_native_omissions(component, damage):
    from tests.support.imports_completion_mapping import imports_bindings
    changed = deepcopy(component)
    rows = changed['native_coverage']['obligations']
    if damage == 'missing-version':
        changed['native_coverage']['obligations'] = [r for r in rows if not r['id'].startswith('2021.1|')]
    else:
        row = next(r for r in rows if r['kind'] == 'enum_value')
        if damage == 'missing-choice': rows.remove(row)
        else: row['shape_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='native field/choice/version'):
        imports_bindings(ROOT, changed)


@pytest.mark.parametrize('damage', ['row-media', 'defaults', 'checkout', 'table-mode', 'cli-language', 'target'])
def test_imports_mapping_rejects_removed_public_choices(component, monkeypatch, damage):
    import tests.support.imports_completion_mapping as mapping
    original = mapping._contract
    def changed(route):
        result = original(route)
        uri = route['uri']
        if uri.endswith('.import'):
            if damage == 'row-media': result['declaration_fields'].remove('media_file')
            if damage == 'defaults': result['settings'].remove('defaults')
            if damage == 'checkout': result['version_features']['check_out_from_source_control'] = False
            if damage == 'target': result['gateway_derivations'].remove('native_object_type')
        elif uri.endswith('importTabDelimited') and damage == 'table-mode':
            result['declaration']['schema']['properties']['mode']['enum'].remove('replace')
        elif '.cli.' in uri and damage == 'cli-language':
            result['declaration']['optional_fields'].remove('import_language')
        return result
    monkeypatch.setattr(mapping, '_contract', changed)
    with pytest.raises(ValueError, match='public.*(not disclosed|choice)'):
        mapping.imports_bindings(ROOT, component)


def test_imports_export_uses_standard_consumer_and_missing_proof_stays_incomplete(component, exported):
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance.branch_audit_completion import evaluate_coverage
    destination, output = exported
    requirements = audit.load(destination / 'requirements.json')
    assert requirements == output['requirements']
    bindings, base, _ = audit.portable_binding_inputs(output['index_path'], requirements)
    result = evaluate_coverage(ROOT, component, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    (destination / 'observed-assessment.json').write_text(json.dumps(result['completion']))
    assert json.loads((destination / 'observed-assessment.json').read_bytes())['complete'] is False
    assert len(result['obligations']) == 12990
    assert all(row['state'] == 'implemented_unverified' for row in result['obligations'])
    assert all(b['evidence'] == {} for b in bindings['bindings'].values())


@pytest.mark.parametrize('damage', ['missing-member', 'missing-source', 'changed-source'])
def test_imports_attachment_rejects_incomplete_mapping_or_source_drift(exported, damage):
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance.branch_audit_mapping import read_mapping_attachments
    directory, output = exported
    index = json.loads(output['index_path'].read_bytes())
    attachment = json.loads((directory / index['mapping_attachments'][0]['artifact']).read_bytes())
    requirements = deepcopy(output['requirements'])
    mechanism = attachment['mechanisms'][0]
    if damage == 'missing-member': attachment['bindings'].pop(next(iter(attachment['bindings'])))
    else:
        sources = requirements['representative_mechanisms'][mechanism]['sources']
        name = next(iter(attachment['bindings'].values()))['construction']['source'].split('#')[0]
        if damage == 'missing-source': sources.pop(name)
        else: sources[name] = '0' * 64
    attachment['requirements_sha256'] = audit.digest(requirements)
    with pytest.raises(ValueError):
        read_mapping_attachments([{}], requirements, lambda _: attachment, ROOT)


def test_imports_unfinalized_ordinary_run_cannot_manufacture_program_proof(tmp_path):
    from tests.support.imports_completion_mapping import imports_program_anchors
    run = tmp_path / 'run'; run.mkdir()
    for name in ('run.plan.json', 'run.result.json', 'run.summary.json'):
        (run / name).write_text('{}')
    with pytest.raises(ValueError, match='anchor is missing or unfinalized'):
        imports_program_anchors(ROOT, {}, tmp_path / 'out', run)


def test_imports_accepted_history_keeps_original_failures_and_native_scope():
    from tests.support.imports_completion_mapping import BASE
    history = json.loads((ROOT / BASE / 'accepted-history.json').read_bytes())
    assert history['new_native_or_fresh'] is False
    assert 'import182-tsv-distinct-source-2025-r1' in history['preserved_raw_failures']
    ordinary = next(row for row in history['retained_ordinary_native'] if row['root'] == 'import182-owner-source-2025-r4')
    assert ordinary['raw_outcome'] == 'PASS'
    assert 'Japanese Source' in ordinary['scope']
    assert 'not copied native receipts' in history['source_copy_and_native_reconciliation']


def test_imports_return_choices_join_exact_closed_read_outputs_without_exposing_mutation_options(component):
    from tests.support.imports_completion_mapping import imports_bindings
    bindings = imports_bindings(ROOT, component)
    row = next(b['input']['correspondence'] for key, b in bindings.items()
        if key.startswith('2025.1|wwise-console|') and '|ak.wwise.core.audio.import|' in key
        and '/optionsSchema/' in key and b['input']['correspondence']['choice'].get('value') == 'suppportsRandomizer')
    assert row['return_projection']['query_outputs'] == ['suppportsRandomizer']
    assert row['return_projection']['mutation_option_input'] is False

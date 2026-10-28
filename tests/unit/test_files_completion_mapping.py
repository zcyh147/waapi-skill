"""Finite #183/#184 accounting through the existing mapping consumer."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_files_mapping_preserves_nested_build_choice_and_conversion_boundary():
    from tests.support.files_completion_mapping import files_component, files_bindings
    component = files_component(ROOT)
    bindings = files_bindings(ROOT, component)
    prefix = '2025.1|wwise-authoring|2025.1.7.9143|function|'
    bank = bindings[prefix + 'ak.wwise.core.soundbank.generate|/argsSchema/properties/soundbanks/items/properties/inclusions/items/enum/0']
    assert bank['input']['correspondence']['public_fields'] == ['soundbanks[].inclusions']
    assert bank['input']['correspondence']['public_choice'] == 'events'
    setter = bindings[prefix + 'ak.wwise.core.audio.setConversionPlugin|/argsSchema/properties/plugin']
    assert setter['input']['correspondence']['public_fields'] == ['plugin_type_handle']
    assert setter['input']['correspondence']['verification']['business_state_verified'] is False
    assert setter['input']['correspondence']['verification']['codec_guid_returned'] is False
    assert bank['evidence'] == {}


from copy import deepcopy
import json
import pytest


@pytest.fixture(scope='module')
def component():
    from tests.support.files_completion_mapping import files_component
    return files_component(ROOT)


@pytest.fixture(scope='module')
def exported(component, tmp_path_factory):
    from tests.support.files_completion_mapping import export_files_mapping
    destination = tmp_path_factory.mktemp('files-map')
    return destination, export_files_mapping(ROOT, destination, inventory=component)


def test_files_roster_comes_from_each_host_catalog_and_reachable_definition(component):
    from collections import Counter
    native = component['native_coverage']
    assert len(native['catalogs']) == 10
    assert len(component['routes']) == 85
    assert len(native['routes']) == 144
    assert len(native['obligations']) == 10868
    assert Counter(r['version'] for r in native['routes']) == {
        '2021.1': 24, '2022.1': 30, '2023.1': 36, '2024.1': 27, '2025.1': 27}
    assert Counter(r['owner_issue'] for r in native['routes']) == {183: 70, 184: 74}
    identities = {row['id'] for row in native['obligations']}
    assert all(row['reference']['target'] in identities for row in native['obligations'] if 'reference' in row)
    # The two later Authoring catalogs omit CLI functions; their Console routes
    # remain represented. A five-version cartesian product would invent lanes.
    assert not any(r['version'] == '2025.1' and r['host'] == 'wwise-authoring' and '.cli.' in r['uri']
        for r in native['routes'])


@pytest.mark.parametrize('damage', ['missing-choice', 'wrong-choice', 'missing-version'])
def test_files_mapping_rejects_native_omission_or_changed_choice(component, damage):
    from tests.support.files_completion_mapping import files_bindings
    changed = deepcopy(component)
    rows = changed['native_coverage']['obligations']
    if damage == 'missing-version':
        changed['native_coverage']['obligations'] = [r for r in rows if not r['id'].startswith('2021.1|')]
    else:
        row = next(r for r in rows if r['kind'] == 'enum_value')
        if damage == 'missing-choice':
            rows.remove(row)
        else:
            row['shape_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='native field/choice/version'):
        files_bindings(ROOT, changed)


@pytest.mark.parametrize('damage', ['top-field', 'nested-field', 'nested-choice', 'base-choice'])
def test_files_mapping_rejects_missing_public_business_input(component, monkeypatch, damage):
    import tests.support.files_completion_mapping as mapping
    original = mapping._contract
    def removed(route):
        contract = original(route)
        if route['uri'] == 'ak.wwise.core.soundbank.generate':
            declaration = contract['declaration']
            if damage == 'top-field':
                declaration['optional_fields'].remove('write_to_disk')
            elif damage == 'nested-field':
                del declaration['schema']['properties']['soundbanks']['items']['properties']['event_handles']
            elif damage == 'nested-choice':
                declaration['schema']['properties']['soundbanks']['items']['properties']['inclusions']['items']['enum'].remove('events')
        elif damage == 'base-choice' and route['uri'] == 'ak.wwise.console.project.create':
            contract['declaration']['input_forms']['platforms']['base_platform_choices'].remove('Windows')
        return contract
    monkeypatch.setattr(mapping, '_contract', removed)
    with pytest.raises(ValueError, match='public.*not disclosed'):
        mapping.files_bindings(ROOT, component)


def test_files_shared_definitions_keep_all_reaching_fields(component):
    from tests.support.files_completion_mapping import files_bindings
    bindings = files_bindings(ROOT, component)
    native = next(row for row in component['native_coverage']['obligations']
        if row['id'].startswith('2025.1|wwise-console|') and '|ak.wwise.cli.generateSoundbank|' in row['id']
        and row['pointer'].endswith('/definitions/platformMappingArray'))
    correspondence = bindings[native['id']]['input']['correspondence']
    assert {item['native_path'][0] for item in correspondence['native_addresses']} == {
        'custom-post-gen-cmd', 'custom-pre-gen-cmd', 'output', 'soundbank-path', 'source-by-platform'}
    assert 'external_source_files_by_platform' in correspondence['public_fields']
    assert any(item['rule'] == 'prohibited_external_command_hook' for item in correspondence['native_addresses'])


def test_files_mapping_retains_results_and_accepted_limits(component):
    from tests.support.files_completion_mapping import files_bindings
    bindings = files_bindings(ROOT, component)
    def selected(uri, ending):
        return next(b['input']['correspondence'] for identity, b in bindings.items()
            if identity.startswith('2025.1|wwise-console|') and '|' + uri + '|' in identity and identity.endswith(ending))
    migration = selected('ak.wwise.cli.migrate', '/resultSchema/properties/result')
    assert migration['verification']['lossless_migration'] is False
    assert 'Soundcaster' in migration['verification']['accepted_limit']
    definition = selected('ak.wwise.core.soundbank.processDefinitionFiles', '/argsSchema/properties/files')
    assert definition['verification']['acceptance'] == 'lightweight_table_code_only'
    assert 'ordered hashed UTF-8 TSV' in definition['native_addresses'][0]['encoding']
    memory = selected('ak.wwise.core.soundbank.generate', '/argsSchema/properties/writeToDisk')
    assert 'business_state_verified_false' in memory['verification']['memory']
    result = selected('ak.wwise.core.soundbank.generate', '/resultSchema/properties/error')
    assert result['rule'] == 'bounded_native_result'
    assert result['public_fields'] == []


def test_files_export_roundtrips_standard_parts_and_requires_real_evidence(component, exported):
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
    assert len(result['obligations']) == 10868
    assert all(row['state'] == 'implemented_unverified' for row in result['obligations'])
    assert all(binding['evidence'] == {} for binding in bindings['bindings'].values())


@pytest.mark.parametrize('damage', ['missing-member', 'missing-source', 'stale-source'])
def test_files_attachment_consumer_rejects_omitted_members_and_source_drift(exported, damage):
    from tests.maintenance import branch_coverage_audit as audit
    from tests.maintenance.branch_audit_mapping import read_mapping_attachments
    destination, output = exported
    index = json.loads(output['index_path'].read_bytes())
    attachment = json.loads((destination / index['mapping_attachments'][0]['artifact']).read_bytes())
    requirements = deepcopy(output['requirements'])
    mechanism = attachment['mechanisms'][0]
    if damage == 'missing-member':
        attachment['bindings'].pop(next(iter(attachment['bindings'])))
    elif damage == 'missing-source':
        requirements['representative_mechanisms'][mechanism]['sources'].pop(
            next(iter(attachment['bindings'].values()))['construction']['source'].split('#')[0])
    else:
        sources = requirements['representative_mechanisms'][mechanism]['sources']
        sources[next(iter(sources))] = '0' * 64
    attachment['requirements_sha256'] = audit.digest(requirements)
    with pytest.raises(ValueError):
        read_mapping_attachments([{}], requirements, lambda _: attachment, ROOT)


def test_files_export_rejects_an_unfinalized_ordinary_anchor(tmp_path):
    from tests.support.files_completion_mapping import files_program_anchors
    run = tmp_path / 'run'
    run.mkdir()
    for filename in ('run.plan.json', 'run.result.json', 'run.summary.json'):
        (run / filename).write_text('{}')
    with pytest.raises(ValueError, match='anchor is missing or unfinalized'):
        files_program_anchors(ROOT, {}, tmp_path / 'out', run)


def test_files_retained_history_preserves_original_failed_outcomes():
    import hashlib
    from tests.support.files_completion_mapping import BASE
    directory = ROOT / BASE
    manifest = json.loads((directory / 'accepted-history.json').read_bytes())
    records = {Path(row['artifact']).stem: row for row in manifest['records']}
    assert manifest['new_native_or_fresh'] is False
    for row in records.values():
        raw = (directory / row['artifact']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert json.loads(raw)['candidate'] == row['original_candidate']
    latest = json.loads((directory / records['console184-native-batch-r3']['artifact']).read_bytes())
    assert latest['raw_outcomes'] == {'PASS': 1, 'FAIL': 1}
    assert next(case for case in latest['cases'] if case['case'] == 'D-migrate-committed-2024')['raw_outcome'] == 'FAIL'
    assert 'original FAIL' in manifest['accepted_limits']['migration']


def test_files_maintenance_entrypoint_consumes_original_code_proof_and_persists_completion(tmp_path, monkeypatch):
    from tests.maintenance.map_files_completion import main
    from tests.support.files_completion_mapping import BASE
    # Exercise the real CLI, source-seal reader, requirements parts, mapping
    # attachment merger, ordinary reader and persisted assessment together.
    run = ROOT / BASE / 'export-r2/original'
    monkeypatch.chdir(tmp_path)
    assert main(['--output-directory', 'relative-output', '--ordinary-run', str(run)]) == 0
    report = json.loads((tmp_path / 'relative-output/assessment.json').read_bytes())
    assert report['completion']['complete'] is True
    assert report['completion']['states'] == {'mapped_with_representative_proof': 10860, 'verified': 8}
    assert report['evidence_outcomes'] == ['reviewed_aggregate_code_mechanism', 'reviewed_representative_mechanism']
    assert report['summary']['native_or_fresh_started'] is False
    assert report['summary']['canonical_import_pending'] is True

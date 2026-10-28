"""Exact host correspondence reaches the existing persisted completion reader."""
from copy import deepcopy
import json
import pytest
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage

@pytest.fixture(scope='module')
def component():
    from tests.support.host_completion_mapping import host_component
    return host_component(audit.ROOT)


def test_host_cohort_retains_exact_scope_exclusions_and_no_native_credit(tmp_path, component):
    from tests.support.host_completion_mapping import OWNERS
    from tests.maintenance.map_host_completion import main
    assert len(OWNERS) == 30
    assert main(['--output-directory',str(tmp_path)]) == 2
    requirements = audit.load(tmp_path/'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(tmp_path/'evidence-index.json', requirements)
    report = evaluate_coverage(audit.ROOT, component, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    assert set(bindings['bindings']) == {r['id'] for r in component['native_coverage']['obligations'] if 'ui.cli.' not in r['route']}
    assert {r['state'] for r in report['obligations']} == {'approved_exclusion', 'implemented_unverified'}
    excluded = [r for r in report['obligations'] if r['state'] == 'approved_exclusion']
    assert {r['route'].rsplit('|',1)[1] for r in excluded} == {'ak.wwise.ui.cli.launch', 'ak.wwise.ui.cli.executeLuaScript'}
    assert all('native' not in r['requirements'] for r in report['obligations'])
    mapped = [b['input']['correspondence'] for b in bindings['bindings'].values()]
    assert all(m['native_effect'] == 'not_claimed' for m in mapped)
    assert any('markers[].position_seconds' in m['public_fields'] for m in mapped)
    assert any(m.get('native_choice') == 'whiteNoise' and m['public_choice'] == 'white_noise' for m in mapped)
    assert any(m.get('fresh_command_inventory') == 'gateway_owned_getCommands_before_dispatch' for m in mapped)
    assert json.loads((tmp_path/'requirements.json').read_bytes())['parts']

@pytest.mark.parametrize('damage', ['field','host','version'])
def test_host_mapping_rejects_native_roster_drift(component, damage):
    from tests.support.host_completion_mapping import host_bindings
    broken=deepcopy(component)
    native=broken['native_coverage']
    if damage=='field': native['obligations'].pop()
    elif damage=='host': native['routes'].pop()
    else: native['obligations']=[r for r in native['obligations'] if not r['id'].startswith('2021.1|')]
    with pytest.raises(ValueError,match='Host mapping.*roster'):
        host_bindings(audit.ROOT,broken)

@pytest.mark.parametrize('damage',['field','choice'])
def test_host_mapping_rejects_removed_tone_business_meaning(component, monkeypatch, damage):
    from tests.support.host_completion_mapping import host_bindings
    from wwise_waapi import host_ui_debug_business_contracts as c
    original=c.host_ui_debug_business_contract_data
    def missing(uri,version):
        result=original(uri,version)
        if uri.endswith('generateToneWAV'):
            if damage=='field': result['declaration']['public_fields'].remove('frequency_hz')
            else: result['declaration']['input_forms']['waveform']['choices'].remove('white_noise')
        return result
    monkeypatch.setattr(c,'host_ui_debug_business_contract_data',missing)
    with pytest.raises(ValueError,match='Host.*disclosed'):
        host_bindings(audit.ROOT,component)

def test_host_program_anchor_rejects_unfinalized_run(tmp_path,component):
    from tests.support.host_completion_mapping import program_anchors
    for name in ('run.plan.json','run.result.json','run.summary.json'): (tmp_path/name).write_text('{}')
    with pytest.raises(ValueError,match='Host selected code anchor is missing or unfinalized'):
        program_anchors(audit.ROOT,component,tmp_path/'out',tmp_path)


def test_host_mapping_removed_source_fails_existing_reader(tmp_path,component):
    import hashlib
    from tests.support.host_completion_mapping import export_mapping
    exported=export_mapping(audit.ROOT,tmp_path,inventory=component)
    requirements=deepcopy(exported['requirements'])
    for mechanism in requirements['representative_mechanisms'].values():
        mechanism['sources'].pop('skills/waapi-skill/wwise_waapi/host_ui_debug_business.py')
    index=json.loads(exported['index_path'].read_bytes())
    for descriptor in index['mapping_attachments']:
        path=tmp_path/descriptor['artifact']; attachment=json.loads(path.read_bytes())
        attachment['requirements_sha256']=audit.digest(requirements)
        path.write_text(json.dumps(attachment)); descriptor['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    exported['index_path'].write_text(json.dumps(index))
    with pytest.raises(ValueError,match='source closure is incomplete'):
        audit.portable_binding_inputs(exported['index_path'],requirements)


@pytest.fixture(scope='module')
def selected_code_review(tmp_path_factory, component):
    from tests.support.host_completion_mapping import BASE, host_bindings, program_anchors
    destination = tmp_path_factory.mktemp('host-source-equivalence')
    run = audit.ROOT / BASE / 'export-r1/original'
    anchors = program_anchors(audit.ROOT, component, destination, run)
    identity = next(key for key in anchors if 'generateToneWAV' in key)
    binding = host_bindings(audit.ROOT, component)[identity]
    binding.update(anchors[identity])
    branch = next(row for row in component['native_coverage']['obligations'] if row['id'] == identity)
    return destination, binding, branch, component['native_coverage']['candidate_sha256']


@pytest.mark.parametrize('helper', [
    'skills/waapi-skill/wwise_waapi/operation_tone.py',
    'skills/waapi-skill/wwise_waapi/console_project_operations.py',
    'skills/waapi-skill/wwise_waapi/operation_soundbank.py',
    'skills/waapi-skill/wwise_waapi/filesystem_security.py',
    'skills/waapi-skill/wwise_waapi/host_paths.py',
    'skills/waapi-skill/wwise_waapi/canonical.py',
    'tests/conftest.py',
    'tests/support/exact_evidence_finalization.py',
    'pyproject.toml',
])
def test_host_selected_code_reader_rejects_changed_execution_helper(selected_code_review, monkeypatch, helper):
    from pathlib import Path
    from tests.support.ordinary_test_run_evidence import read_ordinary_test_run, OUTCOME
    destination, binding, branch, candidate = selected_code_review
    arguments = (binding['evidence']['program'], branch, candidate, 'program', 'product',
        destination, binding, audit.ROOT)
    assert read_ordinary_test_run(*arguments) == (OUTCOME, None)
    original = Path.read_bytes
    changed = audit.ROOT / helper
    def changed_bytes(path):
        raw = original(path)
        return raw + b'\n# changed executed helper\n' if path == changed else raw
    monkeypatch.setattr(Path, 'read_bytes', changed_bytes)
    with pytest.raises(ValueError, match='current relevant source changed'):
        read_ordinary_test_run(*arguments)


@pytest.fixture(scope='module')
def mapping_review(tmp_path_factory, component):
    from tests.support.host_completion_mapping import export_mapping
    destination = tmp_path_factory.mktemp('host-mapping-source-review')
    exported = export_mapping(audit.ROOT, destination, inventory=component)
    return exported['index_path'], audit.load(exported['requirements_path'])


@pytest.mark.parametrize('helper', [
    'skills/waapi-skill/wwise_waapi/operation_tone.py',
    'skills/waapi-skill/wwise_waapi/console_project_operations.py',
])
def test_host_mapping_reader_rejects_changed_verifier_helper(mapping_review, monkeypatch, helper):
    from pathlib import Path
    index, requirements = mapping_review
    audit.portable_binding_inputs(index, requirements)
    original = Path.read_bytes
    changed = audit.ROOT / helper
    def changed_bytes(path):
        raw = original(path)
        return raw + b'\n# changed artifact verifier\n' if path == changed else raw
    monkeypatch.setattr(Path, 'read_bytes', changed_bytes)
    with pytest.raises(ValueError, match='representative reviewed source changed'):
        audit.portable_binding_inputs(index, requirements)


def test_host_source_reconciliation_keeps_original_run_and_reads_seven_selected_anchors(component):
    from tests.support.host_completion_mapping import BASE
    from tests.support.ordinary_test_run_evidence import read_ordinary_test_run, OUTCOME
    original = audit.ROOT / BASE / 'export-r1/original'
    companion = audit.ROOT / BASE / 'source-repair-r1'
    for name in ('run.plan.json', 'run.result.json', 'run.summary.json', 'run.log', 'run.exit'):
        assert (companion / 'original' / name).read_bytes() == (original / name).read_bytes()
    requirements = audit.load(companion / 'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(companion / 'evidence-index.json', requirements)
    rows = {row['id']: row for row in component['native_coverage']['obligations']}
    assert len(bindings['bindings']) == 7
    for identity, binding in bindings['bindings'].items():
        assert read_ordinary_test_run(binding['evidence']['program'], rows[identity],
            component['native_coverage']['candidate_sha256'], 'program', 'product', base,
            binding, audit.ROOT) == (OUTCOME, None)

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

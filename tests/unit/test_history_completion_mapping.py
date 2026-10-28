"""The accepted #192 correspondence reaches the ordinary completion reader."""
from copy import deepcopy
import json
import subprocess
import pytest
from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage


@pytest.fixture(scope='module')
def history_inventory():
    from tests.support.history_completion_mapping import history_component
    return history_component(audit.ROOT)


def test_history_mapping_retains_versioned_owned_lifecycle_and_result_only_scope(tmp_path, history_inventory):
    from tests.maintenance.map_history_completion import main
    assert main(['--output-directory', str(tmp_path)]) == 2
    published = json.loads((tmp_path / 'assessment.json').read_bytes())
    requirements = audit.load(tmp_path / 'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(tmp_path / 'evidence-index.json', requirements)
    report = evaluate_coverage(audit.ROOT, history_inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=requirements)
    assert report['completion'] == published['completion']
    assert len({row['uri'] for row in history_inventory['native_coverage']['routes']}) == 14
    assert len(history_inventory['routes']) == 49
    assert len(history_inventory['native_coverage']['routes']) == 98
    assert {row['state'] for row in report['obligations']} == {'implemented_unverified'}
    assert all(row['requirements'] == ['program'] and 'native' not in row['evidence_results'] for row in report['obligations'])
    mapped = [binding['input']['correspondence'] for binding in bindings['bindings'].values()]
    assert any(m['rule'] == 'owned_undo_group_lifecycle' and 'display_name' in m['public_fields'] for m in mapped)
    assert any(m.get('cancellation_choices') == {'native-default': {}, 'preserve-changes': {'undo': False}, 'undo-changes': {'undo': True}} for m in mapped)
    assert any(m.get('cancellation_choices') == {'native-default': {}} for m in mapped)
    assert any(m.get('provider_selection') == {'disabled': '', 'provider': 'exact configured provider name'} for m in mapped)
    assert any(m.get('source_file_defaults') == {'usage_scope': 'all', 'recursive': True, 'originals_folder': 'omitted_native_Originals_root'} for m in mapped)
    assert any(m['rule'] == 'empty_native_history_envelope' and m['public_fields'] == ['expectation_receipt', 'history_scope'] for m in mapped)
    assert all(m['native_effect'] == 'not_claimed' for m in mapped)
    assert published['summary']['canonical_import_pending'] is True


@pytest.mark.parametrize('damage', ['choice', 'host'])
def test_history_mapping_rejects_missing_native_member(history_inventory, damage):
    from tests.support.history_completion_mapping import history_bindings
    broken = deepcopy(history_inventory)
    broken['native_coverage']['obligations' if damage == 'choice' else 'routes'].pop()
    with pytest.raises(ValueError, match='History.*roster'):
        history_bindings(audit.ROOT, broken)


def test_history_mapping_rejects_removed_disclosed_usage_output(history_inventory, monkeypatch):
    import wwise_waapi.source_control_business_contracts as business
    from tests.support.history_completion_mapping import history_bindings
    original = business.source_control_business_contract_data
    def missing(operation, version):
        contract = original(operation, version)
        if operation.endswith('getSourceFiles'):
            contract['declaration']['usage_output_choices'].pop('short-id')
        return contract
    monkeypatch.setattr(business, 'source_control_business_contract_data', missing)
    with pytest.raises(ValueError, match='History.*public.*short-id'):
        history_bindings(audit.ROOT, history_inventory)


def test_history_mapping_rejects_removed_private_provider_field(history_inventory, monkeypatch):
    import wwise_waapi.source_control_business_contracts as business
    from tests.support.history_completion_mapping import history_bindings
    original = business.source_control_business_contract_data
    def missing(operation, version):
        contract = original(operation, version)
        if operation.endswith('setProvider'):
            contract['declaration']['provider_profile']['connection_fields'].remove('server')
        return contract
    monkeypatch.setattr(business, 'source_control_business_contract_data', missing)
    with pytest.raises(ValueError, match='History.*public.*server'):
        history_bindings(audit.ROOT, history_inventory)


def test_history_program_anchor_rejects_unfinalized_code_capture(tmp_path, history_inventory):
    from tests.support.history_completion_mapping import history_program_anchors
    for name in ('run.plan.json', 'run.result.json', 'run.summary.json'):
        (tmp_path / name).write_text('{}')
    with pytest.raises(ValueError, match='History selected code anchor is missing or unfinalized'):
        history_program_anchors(audit.ROOT, history_inventory, tmp_path / 'out', tmp_path)


def test_history_mapping_missing_source_is_rejected_by_ordinary_reader(tmp_path, history_inventory):
    from tests.support.history_completion_mapping import export_history_mapping
    from tests.maintenance.branch_audit_mapping import read_mapping_attachments
    output = export_history_mapping(audit.ROOT, tmp_path, inventory=history_inventory)
    index = json.loads(output['index_path'].read_bytes())
    attachment = json.loads((tmp_path / index['mapping_attachments'][0]['artifact']).read_bytes())
    requirements = deepcopy(output['requirements'])
    mechanism = attachment['mechanisms'][0]
    construction = next(iter(attachment['bindings'].values()))['construction']['source'].split('#')[0]
    requirements['representative_mechanisms'][mechanism]['sources'].pop(construction)
    attachment['requirements_sha256'] = audit.digest(requirements)
    with pytest.raises(ValueError, match='source closure is incomplete'):
        read_mapping_attachments([{'fixture_only': True}], requirements, lambda _: attachment, audit.ROOT)


@pytest.fixture(scope='module')
def history_reviewed_anchors(tmp_path_factory, history_inventory):
    from tests.support.history_completion_mapping import BASE, history_bindings, history_program_anchors
    destination = tmp_path_factory.mktemp('history-direct-dependencies')
    original = audit.ROOT / BASE / 'export-r1' / 'original'
    anchors = history_program_anchors(audit.ROOT, history_inventory, destination, original)
    bindings = history_bindings(audit.ROOT, history_inventory)
    rows = {row['id']: row for row in history_inventory['native_coverage']['obligations']}
    for identity, anchor in anchors.items():
        bindings[identity].update(anchor)
    return destination, {identity: bindings[identity] for identity in anchors}, rows


def test_history_code_review_seals_original_and_current_direct_test_dependencies(history_inventory, history_reviewed_anchors):
    from tests.support.ordinary_test_run_evidence import read_ordinary_test_run, OUTCOME
    base, bindings, rows = history_reviewed_anchors
    for identity, binding in bindings.items():
        assert {'tests/unit/test_operation_input_gateway.py', 'tests/unit/test_object_graph_business_gateway.py',
            'tests/conftest.py', 'tests/support/exact_evidence_finalization.py',
            'pyproject.toml', 'ci/test_readiness.py'} <= set(binding['relevant_sources'])
        assert read_ordinary_test_run(binding['evidence']['program'], rows[identity],
            history_inventory['native_coverage']['candidate_sha256'], 'program', 'product', base, binding, audit.ROOT) == (OUTCOME, None)


def test_history_source_review_companion_reaches_existing_portable_and_code_readers(history_inventory):
    from tests.support.history_completion_mapping import BASE, RUNTIME_SOURCES
    from tests.support.ordinary_test_run_evidence import read_ordinary_test_run, OUTCOME
    directory = audit.ROOT / BASE / 'source-review-r1'
    # This fixture records a component review, not the later combined candidate.
    # The ordinary reader still checks every reviewed source in the current tree.
    reviewed_candidate = json.loads((directory / 'summary.json').read_bytes())['candidate_sha256']
    requirements = audit.load(directory / 'requirements.json')
    bindings, base, _ = audit.portable_binding_inputs(directory / 'evidence-index.json', requirements)
    rows = {row['id']: row for row in history_inventory['native_coverage']['obligations']}
    assert len(bindings['bindings']) == 4
    for identity, binding in bindings['bindings'].items():
        assert set(binding['relevant_sources']) == RUNTIME_SOURCES
        proof = json.loads((base / binding['evidence']['program']['artifact']).read_bytes())
        assert proof['original_candidate'] == '59daee38fa92f4ad6610a5698be464334718585c'
        for descriptor in proof['files'].values():
            name = descriptor['artifact'].split('/')[-1]
            assert (base / descriptor['artifact']).read_bytes() == (audit.ROOT / BASE / 'export-r1/original' / name).read_bytes()
        assert read_ordinary_test_run(binding['evidence']['program'], rows[identity],
            reviewed_candidate, 'program', 'product', base, binding, audit.ROOT) == (OUTCOME, None)


@pytest.mark.parametrize('helper', ['tests/unit/test_operation_input_gateway.py',
    'tests/unit/test_object_graph_business_gateway.py', 'tests/conftest.py',
    'tests/support/exact_evidence_finalization.py', 'pyproject.toml', 'ci/test_readiness.py',
    'skills/waapi-skill/wwise_waapi/builders/properties.py',
    'skills/waapi-skill/wwise_waapi/builders/common.py',
    'skills/waapi-skill/wwise_waapi/builders/source_notes.py',
    'skills/waapi-skill/wwise_waapi/builders/identity.py',
    'skills/waapi-skill/wwise_waapi/waql.py',
    'skills/waapi-skill/wwise_waapi/canonical.py',
    'skills/waapi-skill/wwise_waapi/cli_console_business_cli.py'])
def test_history_code_reader_rejects_changed_direct_helper(tmp_path, history_inventory, history_reviewed_anchors, helper):
    from tests.support.ordinary_test_run_evidence import read_ordinary_test_run
    base, bindings, rows = history_reviewed_anchors
    identity, binding = next(iter(bindings.items()))
    root = tmp_path / 'current-sources'
    root.mkdir()
    # Original Git objects remain authoritative, while all reviewed current
    # sources below this temporary root are real ordinary files.
    git_directory = subprocess.check_output(['git', 'rev-parse', '--absolute-git-dir'], cwd=audit.ROOT, text=True).strip()
    (root / '.git').write_text('gitdir: ' + git_directory + '\n', encoding='utf-8')
    for name in set(binding['relevant_sources']) | {helper}:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((audit.ROOT / name).read_bytes())
    changed = root / helper
    changed.write_bytes(changed.read_bytes() + b'\n# changed selected test helper\n')
    with pytest.raises(ValueError, match='reviewed current relevant source changed'):
        read_ordinary_test_run(binding['evidence']['program'], rows[identity],
            history_inventory['native_coverage']['candidate_sha256'], 'program', 'product', base, binding, root)


def test_history_code_reader_rejects_missing_runtime_source(history_inventory, history_reviewed_anchors, monkeypatch):
    from pathlib import Path
    from tests.support.ordinary_test_run_evidence import read_ordinary_test_run
    base, bindings, rows = history_reviewed_anchors
    identity, binding = next(iter(bindings.items()))
    missing = audit.ROOT / 'skills/waapi-skill/wwise_waapi/builders/properties.py'
    original = Path.read_bytes
    def missing_bytes(path):
        if path == missing:
            raise FileNotFoundError('missing packaged runtime source')
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', missing_bytes)
    with pytest.raises(FileNotFoundError, match='missing packaged runtime source'):
        read_ordinary_test_run(binding['evidence']['program'], rows[identity],
            history_inventory['native_coverage']['candidate_sha256'], 'program', 'product', base, binding, audit.ROOT)

"""Topic mapping export reaches the existing completion reader, without effects."""
from copy import deepcopy

import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage


@pytest.fixture(scope='module')
def topic_inventory():
    from tests.support.topic_completion_mapping import topic_component
    return topic_component(audit.ROOT)


def test_topic_family_maps_native_choices_to_public_contract_and_reports_missing_proof(tmp_path, topic_inventory):
    from tests.support.topic_completion_mapping import topic_component, export_mapping
    inventory = topic_inventory
    exported = export_mapping(audit.ROOT, tmp_path, inventory=inventory)
    bindings, base, _ = audit.portable_binding_inputs(exported['index_path'], exported['requirements'])
    result = evaluate_coverage(audit.ROOT, inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=exported['requirements'])
    assert set(bindings['bindings']) == {row['id'] for row in inventory['native_coverage']['obligations']}
    field = ('2022.1|wwise-console|2022.1.19.8584|topic|ak.wwise.core.object.created|'
             '/optionsSchema/properties/return')
    mapping = bindings['bindings'][field]['input']['correspondence']
    assert mapping['public_inputs'] == [
        {'action': '--topic-option', 'field': 'include', 'native_path': ['return']},
        {'action': '--topic-option-empty', 'field': 'include', 'native_path': ['return']}]
    assert all(row['requirements'] == ['program'] for row in result['obligations'])
    assert result['completion']['complete'] is False
    assert {row['state'] for row in result['obligations']} == {'implemented_unverified'}
    assert all('native' not in row['evidence_results'] for row in result['obligations'])
    assert exported['summary']['mapping_is_not_execution_credit'] is True
    assert exported['summary']['largest_mapping_bytes'] < 100 * 1024 * 1024
    owned = bindings['bindings'][
        '2025.1|wwise-authoring|2025.1.7.9143|topic|ak.wwise.ui.signal.toggle|/optionsSchema/properties/handleID']
    assert owned['input']['correspondence']['public_inputs'] == [{
        'action': '--signal-model', 'with': '--signal-widget', 'native_path': ['handleID'],
        'binding': 'active_owned_model_widget_configuration_host_build_session_project'}]


@pytest.mark.parametrize('missing', ['choice', 'host'])
def test_topic_export_rejects_missing_native_choice_or_host(topic_inventory, missing):
    from tests.support.topic_completion_mapping import topic_bindings
    broken = {**topic_inventory, 'native_coverage': {**topic_inventory['native_coverage']}}
    if missing == 'choice':
        broken['native_coverage']['obligations'] = topic_inventory['native_coverage']['obligations'][1:]
    else:
        broken['native_coverage']['routes'] = topic_inventory['native_coverage']['routes'][1:]
    with pytest.raises(ValueError, match='Topic mapping.*(roster|choice)'):
        topic_bindings(audit.ROOT, broken)


def test_topic_export_rejects_a_removed_public_option_instead_of_inheriting_typed_support(topic_inventory, monkeypatch):
    from dataclasses import replace
    import wwise_waapi.topic_business as business
    from tests.support.topic_completion_mapping import topic_bindings
    original = business.topic_business_contract
    def missing_option(version, uri):
        contract = original(version, uri)
        if version == '2022.1' and uri == 'ak.wwise.core.object.created':
            return replace(contract,
                option_fields=tuple(field for field in contract.option_fields if field.token != 'include'),
                option_empty_fields=tuple(field for field in contract.option_empty_fields if field.token != 'include'))
        return contract
    monkeypatch.setattr(business, 'topic_business_contract', missing_option)
    with pytest.raises(ValueError, match='closed public correspondence: 2022.1.*object.created'):
        topic_bindings(audit.ROOT, topic_inventory)


def test_topic_attachment_rejects_missing_reviewed_source(topic_inventory):
    import hashlib
    from tests.maintenance.branch_audit_mapping import read_mapping_attachments
    row = topic_inventory['native_coverage']['obligations'][0]
    identity = row['id']
    # One real native pointer and closed source map suffice to check source
    # admission; this is a controlled corruption fixture, not product evidence.
    sources = ['skills/waapi-skill/wwise_waapi/topic_business.py',
               'skills/waapi-skill/scripts/gateway.py']
    mechanism = 'controlled-source-corruption'
    binding = {'branch_id': identity, 'native_shape_sha256': row['shape_sha256'],
        'public_route': '|'.join((identity.split('|')[0], 'topic', identity.split('|')[4])),
        'input': {'gateway_argv': ['topic-schema', identity.split('|')[4]], 'selector': row['pointer']},
        'construction': {'source': sources[0] + '#materialize_topic_business_inputs', 'selector': row['pointer']},
        'validation': {'source': sources[1] + '#validate_monitored_topic_event', 'selector': row['pointer']},
        'verifier': {'source': sources[1] + '#dispatch_topic_stream', 'selector': row['pointer']},
        'representative_mechanism': mechanism, 'evidence': {}}
    requirements = {'branches': {identity: {'native_shape_sha256': row['shape_sha256'],
        'categories': ['program'], 'representative_mechanism': mechanism}},
        'representative_mechanisms': {mechanism: {
            'contract': 'waapi-skill.representative-branch-mechanism/v1', 'scope_kind': 'controlled',
            'candidate_sha256': topic_inventory['native_coverage']['candidate_sha256'],
            'reviewed_reason': 'Controlled source corruption, no evidence credit.',
            'sources': {sources[0]: hashlib.sha256((audit.ROOT / sources[0]).read_bytes()).hexdigest()},
            'members': {identity: {'native_route': row['route'], 'native_shape_sha256': row['shape_sha256'],
                'mapping_sha256': audit.digest({k: v for k, v in binding.items() if k != 'evidence'})}},
            'selected_proofs': {'program': [identity]}}}}
    attachment = {'contract': 'waapi-skill.branch-mapping-attachment/v1', 'scope_kind': 'controlled',
        'requirements_sha256': audit.digest(requirements), 'mechanisms': [mechanism],
        'bindings': {identity: binding}, 'predecessors': {identity: None}}
    with pytest.raises(ValueError, match='source closure is incomplete'):
        read_mapping_attachments([{}], requirements, lambda _: attachment, audit.ROOT)


def test_topic_program_anchor_rejects_an_unfinalized_run(topic_inventory, tmp_path):
    import json
    from tests.support.topic_completion_mapping import program_anchors
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'record': {'contract': 'waapi-skill.ordinary-test-run-attachment/v1',
        'scope_kind': 'product', 'files': {}}, 'selected_tests': ['unobserved']}))
    with pytest.raises(ValueError, match='original finalized ordinary run'):
        program_anchors(audit.ROOT, topic_inventory, tmp_path / 'output', review)

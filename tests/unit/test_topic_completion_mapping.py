"""Topic mapping export reaches the existing completion reader, without effects."""
import pytest

from tests.maintenance import branch_coverage_audit as audit
from tests.maintenance.branch_audit_completion import evaluate_coverage


@pytest.fixture(scope='module')
def topic_inventory():
    from tests.support.topic_completion_mapping import topic_component
    return topic_component(audit.ROOT)


def test_topic_family_maps_native_choices_to_public_contract_and_reports_missing_proof(tmp_path, topic_inventory):
    from tests.support.topic_completion_mapping import export_mapping
    inventory = topic_inventory
    exported = export_mapping(audit.ROOT, tmp_path, inventory=inventory)
    bindings, base, _ = audit.portable_binding_inputs(exported['index_path'], exported['requirements'])
    result = evaluate_coverage(audit.ROOT, inventory, bindings, digest=audit.digest,
        evidence_base=base, requirements_document=exported['requirements'])
    assert set(bindings['bindings']) == {row['id'] for row in inventory['native_coverage']['obligations']}
    field = ('2022.1|wwise-console|2022.1.19.8584|topic|ak.wwise.core.object.created|'
             '/optionsSchema/properties/return')
    mapping = bindings['bindings'][field]['input']['correspondence']
    assert [{key: entry[key] for key in ('action', 'field', 'native_path')} for entry in mapping['public_inputs']] == [
        {'action': '--topic-option', 'field': 'include', 'native_path': ['return']},
        {'action': '--topic-option-empty', 'field': 'include', 'native_path': ['return']}]
    assert all(row['requirements'] == ['program'] for row in result['obligations'])
    assert result['completion']['complete'] is False
    assert {row['state'] for row in result['obligations']} == {'implemented_unverified'}
    assert all('native' not in row['evidence_results'] for row in result['obligations'])
    assert exported['summary']['mapping_is_not_execution_credit'] is True
    assert exported['summary']['largest_mapping_bytes'] < 100 * 1024 * 1024
    assert len(exported['summary']['requirements_parts']) == 5
    assert exported['summary']['canonical_requirements_import_ready'] is False
    assert max(path.stat().st_size for path in tmp_path.rglob('*.json')) < 100 * 1024 * 1024
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
    with pytest.raises(ValueError, match='closed public correspondence.*2022.1.*object.created'):
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


@pytest.mark.parametrize("relative_flavor", ["native", "windows"])
def test_topic_ordinary_copy_preserves_the_original_finalizer_receipt_name(topic_inventory, tmp_path, monkeypatch, relative_flavor):
    import hashlib
    import json
    from pathlib import Path
    from tests.support.topic_completion_mapping import program_anchors
    files = {}
    for name in ('plan', 'result', 'summary', 'log', 'exit'):
        path = tmp_path / ('run.' + name)
        path.write_text(json.dumps({'original_receipt': 'run.result'}) if name == 'summary' else '{}')
        files[name] = {'artifact': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'record': {'contract': 'waapi-skill.ordinary-test-run-attachment/v1',
        'scope_kind': 'product', 'files': files, 'review': {'sources': {}}},
        'selected_tests': ['controlled-copy-fixture-never-executed']}))
    output = tmp_path / 'bundle'
    if relative_flavor == 'windows':
        from pathlib import PureWindowsPath
        relative_to = Path.relative_to
        def windows_relative(path, *parents):
            result = relative_to(path, *parents)
            return PureWindowsPath(*result.parts) if path.parts[:len(output.parts)] == output.parts else result
        monkeypatch.setattr(Path, 'relative_to', windows_relative)
    anchors = program_anchors(audit.ROOT, topic_inventory, output, review)
    proof = json.loads((output / next(iter(anchors.values()))['evidence']['program']['artifact']).read_text())
    assert proof['files']['result']['artifact'] == 'original/run.result'
    assert Path(proof['files']['result']['artifact']).name == 'run.result'
    summary = json.loads((output / proof['files']['summary']['artifact']).read_text())
    assert summary['original_receipt'] == Path(proof['files']['result']['artifact']).name
    for name, descriptor in proof['files'].items():
        assert (output / descriptor['artifact']).read_bytes() == Path(files[name]['artifact']).read_bytes()


def topic_scope(inventory, version, uri):
    from tests.support.topic_completion_mapping import digest
    route_ids = {row['id'] for row in inventory['native_coverage']['routes']
                 if row['version'] == version and row['uri'] == uri}
    rows = [row for row in inventory['native_coverage']['obligations'] if row['route'] in route_ids]
    return {**inventory, 'routes': [row for row in inventory['routes'] if row['id'] == version + '|topic|' + uri],
        'native_coverage': {**inventory['native_coverage'], 'routes': [row for row in inventory['native_coverage']['routes']
            if row['id'] in route_ids], 'obligations': rows},
        'topic_roster_sha256': digest([(row['id'], row['shape_sha256']) for row in rows])}


def test_legacy_implicit_topic_members_keep_closed_row_correspondence(topic_inventory):
    from tests.support.topic_completion_mapping import topic_bindings
    bindings = topic_bindings(audit.ROOT, topic_scope(topic_inventory, '2021.1', 'ak.wwise.core.soundbank.generated'))
    prefix = '2021.1|wwise-console|2021.1.14.8108|topic|ak.wwise.core.soundbank.generated|'
    cases = [
        ('/publishSchema/properties/bankInfo/items/GameParameters/items/properties/Id',
         ['bankInfo', None, 'GameParameters', None, 'Id'], 'bank-info-game-parameters', 'id'),
        ('/publishSchema/properties/bankInfo/items/properties/IncludedEvents/items/SwitchContainers/items/properties/SwitchValue',
         ['bankInfo', None, 'IncludedEvents', None, 'SwitchContainers', None, 'SwitchValue'],
         'bank-info-included-events-switch-containers', 'switch-value'),
    ]
    for pointer, expected_path, collection, field in cases:
        mapped = bindings[prefix + pointer]['input']['correspondence']
        assert mapped['native_path'] == expected_path
        assert any(item['action'] == '--event-row' and item['collection'] == collection
                   and item['field'] == field for item in mapped['public_inputs'])


def test_exact_entry_native_members_map_scalar_object_list_and_choices(topic_inventory):
    from tests.support.topic_completion_mapping import topic_bindings
    bindings = topic_bindings(audit.ROOT, topic_scope(topic_inventory, '2021.1', 'ak.wwise.core.object.created'))
    prefix = ('2021.1|wwise-console|2021.1.14.8108|topic|ak.wwise.core.object.created|'
              '/publishSchema/@definition/waapi_definitions.json/definitions/objectReturn/patternProperties/')
    members = {key: value['input']['correspondence'] for key, value in bindings.items() if key.startswith(prefix)}
    scalar = next(value for key, value in members.items() if key.endswith('/anyOf/0'))
    assert scalar['native_path'] == ['object', '*']
    choice, = [entry for entry in scalar['public_inputs'] if entry['action'] == '--event-entry-as']
    assert choice['scope'] == 'object'
    assert {value['kind'] for value in choice['value_choices']} == {'text', 'number', 'toggle'}
    for suffix, expected_path, action in [
        ('/anyOf/3/properties/name', ['object', '*', 'name'], '--event-entry-object'),
        ('/anyOf/4/items/properties/name', ['object', '*', None, 'name'], '--event-entry-row'),
    ]:
        mapped = next(value for key, value in members.items() if key.endswith(suffix))
        assert mapped['native_path'] == expected_path
        assert any(entry['action'] == action and entry['scope'] == 'object'
                   and entry['field'] == 'name' for entry in mapped['public_inputs'])


@pytest.mark.parametrize('damage', ['entry', 'choice'])
def test_missing_exact_entry_or_choice_cannot_receive_projection_only_mapping(topic_inventory, monkeypatch, damage):
    from dataclasses import replace
    import wwise_waapi.topic_business as business
    from tests.support.topic_completion_mapping import topic_bindings
    original_contract = business.topic_business_contract
    original_choices = business.topic_business_value_choices
    def contract(version, uri):
        result = original_contract(version, uri)
        if damage == 'entry' and version == '2021.1' and uri == 'ak.wwise.core.object.created':
            return replace(result, entry_fields=tuple(item for item in result.entry_fields if item.token != 'object'))
        return result
    def choices(contract, *, channel, owner):
        result = original_choices(contract, channel=channel, owner=owner)
        if damage == 'choice' and contract.version == '2021.1' and contract.topic == 'ak.wwise.core.object.created' and channel == 'event-entry' and tuple(owner) == ('object',):
            return tuple(item for item in result if item._kind != 'number')
        return result
    monkeypatch.setattr(business, 'topic_business_contract', contract)
    monkeypatch.setattr(business, 'topic_business_value_choices', choices)
    with pytest.raises(ValueError, match='Topic.*(correspondence|choice)'):
        topic_bindings(audit.ROOT, topic_scope(topic_inventory, '2021.1', 'ak.wwise.core.object.created'))


def test_log_parameter_output_maps_to_exact_projection_without_invented_predicate(topic_inventory, tmp_path):
    from tests.support.topic_completion_mapping import topic_bindings
    from tests.unit.test_topic_monitoring_contracts import run
    uri = 'ak.wwise.core.soundbank.generationDone'
    scoped = topic_scope(topic_inventory, '2021.1', uri)
    bindings = topic_bindings(audit.ROOT, scoped)
    identity = ('2021.1|wwise-console|2021.1.14.8108|topic|' + uri
        + '|/publishSchema/@definition/waapi_definitions.json/definitions/logCentralItem/properties/parameters/items')
    mapped = bindings[identity]['input']['correspondence']
    assert mapped['native_path'] == ['logs', None, 'parameters', None]
    assert mapped['public_inputs'] == []
    assert mapped['input_role'] == 'output_only_no_predicate_required'
    event = {'logs': [{'severity': 'Message', 'time': 0, 'messageId': 'mapping-proof',
        'message': 'Parameters', 'parameters': ['雨', 'name "quoted" \\ value']}]}
    code, terminal, client, records = run(tmp_path, '2021.1', 'stream-topic', uri, [event], timeout_seconds=1.0)
    assert code == 0, terminal
    assert [record['event'] for record in records if record['record_type'] == 'event'] == [event]
    assert terminal['monitoring_outcome']['target_completed'] is True
    assert client.unsubscribed == 1

"""Audit through the maintainer generator and its independent source boundary."""
from __future__ import annotations

import pytest

from tests.maintenance.branch_coverage_audit import schema_branches
from tests.unit.test_branch_coverage_completion_cli import ping_scope, portable_representative_case


@pytest.fixture(scope="module")
def frozen_inventory():
    from tests.maintenance.branch_coverage_audit import build_inventory
    return build_inventory()


def test_layout_supplements_retain_exact_routes_definitions_and_unresolved_ownership(frozen_inventory):
    from wwise_waapi.authoring_layout import LAYOUT_READ_URIS
    from wwise_waapi.authoring_layout_business import LAYOUT_MUTATION_URIS, layout_mutation_uris

    expected = {f'{version}|function|{uri}' for version in ('2024.1', '2025.1')
                for uri in LAYOUT_READ_URIS | layout_mutation_uris(version)}
    routes = {row['id']: row for row in frozen_inventory['routes'] if row['id'] in expected}
    assert set(routes) == expected
    assert all(row['family'] == 'authoring-layout-partial' for row in routes.values())
    assert all(not row['reviewed_snapshot']['current_execution_credit'] for row in routes.values())
    for version in ('2024.1', '2025.1'):
        definitions = [row for row in frozen_inventory['branches']
                       if row['id'].startswith(f'{version}|')
                       and 'authoring-layout-read-supplement.json|waapi_ui_definitions.json|' in row['id']]
        assert definitions
        assert any(row['kind'] == 'native_keyword_semantics' and row['value'] == 'OneOf' for row in definitions)
    native_routes = {row['id'] for row in frozen_inventory['native_coverage']['routes']
                     if row['uri'] in LAYOUT_READ_URIS | LAYOUT_MUTATION_URIS}
    native = [row for row in frozen_inventory['native_coverage']['obligations']
              if row.get('route') in native_routes]
    assert native and all(row['owner_issue'] == 188 and row['state'] == 'unresolved' for row in native)


def test_schema_inventory_retains_optional_enum_union_and_nested_collection_branches():
    schema = {"type": "object", "properties": {
        "mode": {"enum": ["create", "replace"]},
        "children": {"type": "array", "items": {"oneOf": [
            {"type": "string"}, {"type": "integer"}]}}
    }, "required": ["children"]}
    branches = {row["pointer"]: row for row in schema_branches(schema)}
    assert branches["/properties/mode/enum/1"]["value"] == "replace"
    assert branches["/properties/mode/@presence/absent"]["value"] == "absent"
    assert "/properties/children/@presence/absent" not in branches
    assert branches["/properties/children/items/oneOf/1"]["value"] == {"type": "integer"}


def test_model_supplements_retain_original_native_obligations_without_family_credit(frozen_inventory):
    from wwise_waapi.authoring_model_business import MODEL_OPERATIONS
    expected = {f'{version}|function|{uri}' for version in ('2024.1', '2025.1')
                for uri in MODEL_OPERATIONS}
    routes = {row['id']: row for row in frozen_inventory['routes'] if row['id'] in expected}
    assert set(routes) == expected
    assert all(row['family'] == 'authoring-model-partial' for row in routes.values())
    assert all(not row['reviewed_snapshot']['current_execution_credit'] for row in routes.values())
    for version in ('2024.1', '2025.1'):
        assert any(row['id'].startswith(version + '|')
                   and 'authoring-model-supplement.json|' in row['id']
                   for row in frozen_inventory['branches'])
    native_routes = {row['id'] for row in frozen_inventory['native_coverage']['routes']
                     if row['uri'] in MODEL_OPERATIONS}
    native = [row for row in frozen_inventory['native_coverage']['obligations']
              if row.get('route') in native_routes]
    assert native and all(row['owner_issue'] == 189 and row['state'] == 'unresolved' for row in native)
    assert all(row['evidence_results'] == {} for row in native)


def test_independent_reflection_rejects_same_count_route_substitution():
    import json
    import pytest
    from tests.maintenance.branch_coverage_audit import ROOT, build_inventory
    surface = json.loads((ROOT / "skills/waapi-skill/resources/manifest/typed-request-surface.json").read_text())
    surface["lanes"][0]["uri"] = "ak.wwise.invented.sameCount"
    with pytest.raises(ValueError, match="route partition mismatch"):
        build_inventory(surface=surface)


def test_checker_rejects_removed_branch_mapping_and_shareset_false_completion(frozen_inventory):
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = frozen_inventory
    assert check_inventory(inventory, expected=frozen_inventory) == []
    missing = deepcopy(inventory)
    del missing["branches"][0]["mapping"]
    assert "branch ledger differs" in check_inventory(missing, expected=frozen_inventory)
    dishonest = deepcopy(inventory)
    shareset = next(row for row in dishonest["business_branches"] if row["id"] == "2025.1|independent-effect-shareset")
    shareset["implementation"] = "complete"
    assert "business ledger differs" in check_inventory(dishonest, expected=frozen_inventory)


def test_cli_distinguishes_reproducible_inventory_from_complete_coverage(tmp_path):
    import subprocess
    import sys
    from tests.maintenance.branch_coverage_audit import ROOT
    path = tmp_path / "audit.json"
    command = [sys.executable, str(ROOT / "tests/maintenance/branch_coverage_audit.py"), "--output", str(path)]
    generated = subprocess.run(command, capture_output=True, text=True)
    assert generated.returncode == 0, generated.stderr
    checked = subprocess.run(command + ["--check", "--require-complete"], capture_output=True, text=True)
    assert checked.returncode == 2, checked.stderr
    assert '"business_coverage": "incomplete"' in checked.stdout
    path.write_text('{"contract":"waapi-skill.branch-audit/v1"}')
    damaged = subprocess.run(command + ["--check"], capture_output=True, text=True)
    assert damaged.returncode == 1
    assert "branch ledger differs" in damaged.stdout


def test_schema_type_unions_and_unfamiliar_nested_keywords_cannot_disappear():
    branches = {row["pointer"]: row for row in schema_branches({
        "type": ["string", "null"], "futureBranch": {"enum": ["new"]}})}
    assert branches["/type/1"]["value"] == "null"
    assert branches["/futureBranch"]["kind"] == "unreviewed_keyword"


def test_audit_joins_selector_policy_without_inventing_branch_execution_credit(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    inventory = frozen_inventory
    assert inventory["summary"]["declared_selector_dispositions"] == 484
    branch = next(row for row in inventory["branches"] if row["route"] == "2025.1|function|ak.wwise.core.object.setReference" and row["pointer"] == "/argsSchema/properties/reference")
    mapping = inventory["mappings"][branch["mapping"]]
    assert mapping["basis"] == "native_surface_policy_selector"
    assert mapping["program_result"] == "not_established_by_source_mapping"
    route = next(row for row in inventory["routes"] if row["id"] == branch["route"])
    assert route["compiler"] != "unknown"
    assert route["public_contracts"]


def test_checker_rejects_lost_enum_union_and_policy_mapping_evidence(frozen_inventory):
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = frozen_inventory
    for kind in ('enum_value', 'type_variant'):
        changed = deepcopy(inventory)
        branch = next(row for row in changed['branches'] if row['kind'] == kind)
        changed['branches'].remove(branch)
        assert 'branch ledger differs' in check_inventory(changed, expected=frozen_inventory)
    changed = deepcopy(inventory)
    del changed['mappings'][next(iter(changed['mappings']))]
    assert 'selector mappings differs' in check_inventory(changed, expected=frozen_inventory)
    native_changed = deepcopy(inventory)
    native_enum = next(r for r in native_changed['native_coverage']['obligations'] if r['kind'] == 'enum_value')
    native_changed['native_coverage']['obligations'].remove(native_enum)
    assert 'native coverage differs' in check_inventory(native_changed, expected=frozen_inventory)

    assert inventory['current_business_branches'] != inventory['business_branches']
    assert all(row['residual_group'] in inventory['residual_groups'] for row in inventory['branches'])


def test_generator_rejects_policy_with_a_missing_selector():
    import json
    import pytest
    from tests.maintenance.branch_coverage_audit import ROOT, build_inventory
    policy = json.loads((ROOT / 'skills/waapi-skill/resources/native_surface_policy.json').read_text())
    classifications = policy['rules'][0]['scopes'][0]['classifications']
    selectors = next(value for value in classifications.values() if value)
    selectors.pop()
    with pytest.raises(ValueError):
        build_inventory(native_policy=policy)


def test_selector_attribution_requires_matching_profile_schema_occurrence(frozen_inventory):
    from copy import deepcopy
    from tests.maintenance.branch_coverage_audit import build_inventory, check_inventory
    inventory = frozen_inventory
    assert any(branch['mapping'] in inventory['mappings'] for branch in inventory['branches'])
    for branch in inventory['branches']:
        if branch['mapping'] not in inventory['mappings']:
            continue
        version, source, uri, _ = branch['id'].split('|', 3)
        occurrence = '|'.join((version, source, uri))
        expected = inventory['mappings'][branch['mapping']]['schema_sha256_by_version'][version]
        assert inventory['schema_occurrences'][occurrence] == expected
    changed = deepcopy(inventory)
    occurrence = next(iter(changed['schema_occurrences']))
    changed['schema_occurrences'][occurrence] = '0' * 64
    assert 'schema occurrences differs' in check_inventory(changed, expected=frozen_inventory)


def test_native_denominator_keeps_unimplemented_authoring_routes_and_exact_builds():
    from tests.maintenance.branch_coverage_audit import ROOT, digest, load
    from wwise_waapi.schema_inventory import build_typed_request_surface
    from tests.maintenance.branch_audit_completion import native_coverage

    surface = build_typed_request_surface()
    inventory = {'sources': {}, 'routes': [
        {'id': '|'.join((r['version'], r['item_type'], r['uri']))}
        for r in surface['lanes']]}
    native = native_coverage(ROOT, inventory, digest=digest,
                             schema_branches=schema_branches, load=load)
    assert len(native['catalogs']) == 10
    uri = 'ak.wwise.ui.layout.getLayoutNames'
    public_id = f'2025.1|function|{uri}'
    row = next(r for r in native['routes'] if r['version'] == '2025.1'
               and r['host'] == 'wwise-authoring' and r['uri'] == uri)
    assert row['build'] == '2025.1.7.9143'
    assert row['public_route'] == public_id
    obligations = [r for r in native['obligations'] if r['route'] == row['id']]
    assert obligations and all(r['owner_issue'] == 188 for r in obligations)
    assert all(r['state'] == 'unresolved' for r in obligations)
    assert native['completion']['complete'] is False

    # Remove only this public implementation in the test scope. The independent
    # native denominator and ownership must survive, now missing implementation.
    missing = native_coverage(ROOT, {'sources': {}, 'routes': [r for r in inventory['routes']
                                               if r['id'] != public_id]},
                              digest=digest, schema_branches=schema_branches, load=load)
    assert {(r['id'], r['shape_sha256'], r['owner_issue']) for r in missing['obligations']} == {
        (r['id'], r['shape_sha256'], r['owner_issue']) for r in native['obligations']}
    assert next(r for r in missing['routes'] if r['id'] == row['id'])['public_route'] is None
    assert all(r['state'] == 'missing_implementation' for r in missing['obligations']
               if r['route'] == row['id'])


def test_native_reference_graph_retains_capital_oneof_and_recursive_result_edges(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    native = frozen_inventory['native_coverage']
    layout = [r for r in native['obligations'] if '2025.1|wwise-authoring|' in r['id']
              and '|ak.wwise.ui.layout.getLayout|' in r['id']]
    assert any('/definitions/Element/OneOf/4' in r['pointer'] for r in layout)
    assert any(r['kind'] == 'reference' and r['reference']['recursive'] for r in layout)
    assert all(r['owner_issue'] == 188 for r in layout)
    assert any(r['kind'] == 'collection_cardinality' and r['value'] == 'empty' for r in layout)
    alternatives = list(schema_branches({'type': ['array', 'null'], 'default': [], 'items': {'OneOf': [{'enum': ['a', 'b']}, {'type': 'integer'}]}}))
    assert any(r['kind'] == 'default' and r['value'] == [] for r in alternatives)
    assert any(r['pointer'] == '/items/OneOf/0/enum/1' and r['value'] == 'b' for r in alternatives)


def test_installed_conditions_keep_existing_new_and_plugin_placement_obligations(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    native = frozen_inventory['native_coverage']
    conditions = [r for r in native['obligations'] if r['kind'] == 'metadata_condition']
    assert conditions
    sample = [r for r in conditions if 'LfoSmoothing' in r['pointer']]
    assert {r['owner_issue'] for r in sample} == {177, 178}
    assert {r['business_dimensions']['operation_mode'] for r in sample} == {'existing-object', 'new-object'}
    assert all(r['source_evidence_kind'] == 'installed_definition_only' and r['state'] == 'unresolved' for r in conditions)
    plugins = [r for r in native['obligations'] if r['kind'] == 'plugin_topology'
               and r['business_dimensions']['class_name'] == 'Wwise RoomVerb']
    assert {r['business_dimensions']['placement'] for r in plugins} == {'owner-local-effect', 'independent-shareset'}
    assert all(r['owner_issue'] == 179 for r in plugins)
    assert all(r['owner_issue'] in range(177, 194) for r in native['obligations'])


def test_existing_plugin_condition_grammar_does_not_depend_on_plugin_creation(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import ROOT, load
    rows = frozen_inventory['native_coverage']['obligations']
    original = load(ROOT / 'docs/branch-coverage-inventory.json')['native_coverage']['obligations']
    # Changing dependency scheduling must retain the independently enumerated
    # denominator, exact ownership, and unresolved proof obligations.
    assert {(r['id'], r['owner_issue']) for r in rows} == {(r['id'], r['owner_issue']) for r in original}
    for version in ('2021.1', '2022.1', '2023.1', '2024.1', '2025.1'):
        plugin_conditions = [r for r in rows if r['kind'] == 'metadata_condition'
                             and r.get('version') == version and '|plugin-condition|' in r['id']]
        existing = [r for r in plugin_conditions if r['business_dimensions']['operation_mode'] == 'existing-object']
        new = [r for r in plugin_conditions if r['business_dimensions']['operation_mode'] == 'new-object']
        assert existing and new
        assert all(r['owner_issue'] == 177 and r['dependencies'] == [] for r in existing)
        assert all(r['owner_issue'] == 178 and r['dependencies'] == [177, 179] for r in new)
        topology = [r for r in rows if r['kind'] == 'plugin_topology' and r.get('version') == version]
        assert topology and all(r['owner_issue'] == 179 and r['dependencies'] == [177, 178] for r in topology)
    assert all(r['state'] == 'unresolved' and not r['requirements']
               for r in rows if r['kind'] == 'metadata_condition')


def test_finite_and_unfamiliar_schema_alternatives_remain_explicit():
    rows = list(schema_branches({'type': 'object', 'properties': {
        'enabled': {'type': 'boolean', 'default': False},
        'future': {'futureCondition': {'enum': ['left', 'right']}},
        'level': {'type': 'integer', 'minimum': 0, 'maximum': 3}}}))
    assert {r['value'] for r in rows if r['kind'] == 'boolean_value'} == {True, False}
    assert any(r['kind'] == 'empty_object' for r in rows)
    assert any(r['pointer'] == '/properties/future/futureCondition/enum/1' and r['value'] == 'right' for r in rows)
    assert any(r['kind'] == 'constraint' and r['pointer'] == '/properties/level/maximum' and r['value'] == 3 for r in rows)


def test_target_applicability_does_not_inherit_create_or_edit_family_completion(frozen_inventory):
    from tests.maintenance.branch_coverage_audit import build_inventory
    rows = [r for r in frozen_inventory['native_coverage']['obligations'] if r['kind'] == 'target_applicability'
            and r['version'] == '2025.1' and r['business_dimensions']['class_name'] == 'GameParameter']
    assert {r['business_dimensions']['operation_mode'] for r in rows} == {'new-object', 'existing-object'}
    assert all(r['state'] == 'unresolved' for r in rows)
    assert {r['owner_issue'] for r in rows} == {178, 180}


def test_union_empty_values_have_distinct_branch_identities():
    rows = list(schema_branches({'type': ['object', 'string']}))
    assert len({r['pointer'] for r in rows}) == len(rows)


def test_cli_preserves_all_native_rows_in_a_sealed_companion(tmp_path, capsys):
    import json
    from tests.maintenance.branch_coverage_audit import main, load
    target = tmp_path / 'ledger.json'
    assert main(['--output', str(target), '--require-complete']) == 2
    raw = json.loads(target.read_text())
    descriptor = raw['native_coverage']['obligations_artifact']
    hydrated = load(target)
    assert len(hydrated['native_coverage']['obligations']) == descriptor['rows']
    assert len({r['id'] for r in hydrated['native_coverage']['obligations']}) == descriptor['rows']
    assert main(['--output', str(target), '--check', '--require-complete']) == 2
    artifact = target.parent / descriptor['path']
    artifact.write_bytes(artifact.read_bytes()[:-1])
    assert main(['--output', str(target), '--check']) == 1
    assert 'digest mismatch' in capsys.readouterr().out


def _copy_runtime_common_base_file(source, destination):
    """Stage exact existing bytes; a shared filename never authorizes overwrite."""
    raw = source.read_bytes()
    if destination.exists():
        if destination.read_bytes() != raw:
            raise ValueError('Runtime common-base path collision')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)


@pytest.fixture
def runtime_common_base_stage(tmp_path, portable_representative_case):
    """Disjoint current mappings, one retained packet and exact Source origins."""
    import hashlib
    import json
    import os
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.runtime_observation_evidence import write_runtime_composition
    source = audit.ROOT / 'tests/fixtures/branch-evidence/product'
    component = source / 'runtime-fixed-reads-r121'
    stage = tmp_path / 'runtime-common-base'
    stage.mkdir()
    selected = []
    for label, packet_index, identity in (
            ('source', 'source-r92-final-29b34d4c-2022.1/portable/index.json', 'source-r92-final-29b34d4c-2022.1'),
            ('retained-log', 'runtime-read-log-195-r1/native-index.json', 'runtime195-native-0')):
        packet = audit.load(source / packet_index)
        entry = next(e for e in packet['entries'] if e['id'] == identity)
        index = {'contract': packet['contract'], 'base': os.path.relpath(source, stage), 'entries': [entry]}
        policy = audit.load(source / entry['origin']['requirements']['artifact'])
        if label == 'source':
            for key in ('source_attachments', 'source_native_attachments'):
                index[key] = packet[key]
                assert len(index[key]) == 1
        else:
            index['qualified_runtime_read_attachments'] = [next(d for d in packet['qualified_runtime_read_attachments']
                if audit.load(source / d['artifact'])['branch_id'] in policy['branches'])]
            assert len(index['qualified_runtime_read_attachments']) == 1
        path = stage / (label + '-index.json')
        path.write_text(json.dumps(index), encoding='utf-8')
        selected.append((path, policy))
    case = portable_representative_case
    original, original_policy = write_runtime_composition(stage / 'existing',
        [(case['index_path'], case['requirements']), *selected])
    reader_index, reader_policy = write_runtime_composition(stage / 'reader-control',
        [(case['index_path'], case['requirements'])])
    source_index, source_policy = write_runtime_composition(stage / 'source-control', [selected[0]])
    freshness_index, freshness_policy = write_runtime_composition(stage / 'source-with-current-mapping',
        [(case['index_path'], case['requirements']), selected[0]])
    global_index = audit.load(original)
    original_base = original.parent / global_index['base']
    seen = {path.relative_to(original_base).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in original_base.rglob('*') if path.is_file()}
    fixed_index = audit.load(component / 'index.json')
    fixed_policy = audit.load(component / 'requirements.json')
    assert not (original_policy['branches'].keys() & fixed_policy['branches'].keys())
    index, policy = write_runtime_composition(stage / 'combined',
        [(case['index_path'], case['requirements']), *selected, (component / 'index.json', fixed_policy)])
    base = index.parent / 'evidence'
    # Preserve the original complete fixed-component publication as well as its
    # consumer-reachable closure. Existing path collisions still reject changes.
    for path in component.rglob('*'):
        if path.is_file():
            _copy_runtime_common_base_file(path, base / path.relative_to(component))
    fixed_only = index.parent / 'fixed-index.json'
    fixed_only.write_text(json.dumps({**fixed_index, 'base': 'evidence'}), encoding='utf-8')
    return {'index': index, 'fixed_only': fixed_only, 'policy': policy, 'fixed_policy': fixed_policy,
        'component': component, 'base': base, 'old_index': global_index, 'original_index': original,
        'original_policy': original_policy, 'reader_index': reader_index, 'reader_policy': reader_policy,
        'source_index': source_index, 'source_policy': source_policy,
        'freshness_index': freshness_index, 'freshness_policy': freshness_policy,
        'fixed_index': fixed_index, 'existing_closure': seen}


def test_runtime_fixed_component_imports_from_unchanged_common_base(runtime_common_base_stage):
    import hashlib
    import json
    from tests.maintenance import branch_coverage_audit as audit
    stage = runtime_common_base_stage
    document, base, inputs = audit.portable_binding_inputs(stage['fixed_only'], stage['fixed_policy'])
    expected = set(stage['fixed_policy']['branches'])
    assert set(document['bindings']) == expected
    assert {e['id'] for e in stage['old_index']['entries']} == {
        'original-0', 'original-1', 'original-2', 'original-3',
        'source-r92-final-29b34d4c-2022.1', 'runtime195-native-0'}
    assert len(stage['fixed_index']['entries']) == 334
    assert len({entry['id'] for entry in json.loads(stage['index'].read_bytes())['entries']}) == 340
    native = {identity for identity,binding in document['bindings'].items() if binding.get('runtime_observation_attachment')}
    assert len(native) == 445
    closure = {}
    for path in stage['component'].rglob('*'):
        if path.is_file():
            relative = path.relative_to(stage['component'])
            actual = (base / relative).read_bytes()
            assert actual == path.read_bytes()
            closure[str(relative)] = {'bytes':len(actual),'sha256':hashlib.sha256(actual).hexdigest()}
    assert len(closure) == 3127
    (stage['index'].parent / 'import-proof.json').write_text(json.dumps({
        'consumer':'branch_coverage_audit.portable_binding_inputs','selected_ids':sorted(expected),
        'selected_count':len(expected),'imported_entries':334,'composed_entries':340,
        'runtime_native_attachments':len(native),
        'original_component_relative_closure':closure,'existing_closure':stage['existing_closure'],
        'inventory_or_final_evaluator_run':False,'inputs':inputs},indent=2)+'\n')


def test_runtime_common_base_refuses_different_bytes_at_an_existing_profile_path(tmp_path, runtime_common_base_stage):
    stage = runtime_common_base_stage
    target = stage['base'] / 'r119-2021-category.json'
    original = target.read_bytes()
    foreign = tmp_path / 'foreign-category.json'
    foreign.write_bytes((stage['component'] / 'r119-2022-category.json').read_bytes())
    with pytest.raises(ValueError,match='Runtime common-base path collision'):
        _copy_runtime_common_base_file(foreign,target)
    assert target.read_bytes() == original


def test_runtime_common_base_preserves_existing_global_source_freshness(runtime_common_base_stage):
    from tests.maintenance import branch_coverage_audit as audit
    stage = runtime_common_base_stage
    # These retained Source bytes precede the current dependency review. Prove
    # the original reader rejection first: composition cannot freshen that seal.
    reason = '^Complete reviewed Source successor context differs$'
    with pytest.raises(ValueError, match=reason):
        audit.portable_binding_inputs(stage['source_index'], stage['source_policy'])
    with pytest.raises(ValueError, match=reason):
        audit.portable_binding_inputs(stage['freshness_index'], stage['freshness_policy'])


def test_runtime_prefixed_families_share_one_base_without_overwrite_or_duplicate_credit(tmp_path):
    """One fixed packet and one qualified RTPC packet use the ordinary importer."""
    import json
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support import runtime_observation_evidence as runtime
    from tests.support import qualified_runtime_read_evidence as qualified
    from tests.unit.test_console_runtime_read_evidence import packet_case
    from tests.unit.test_qualified_runtime_read_evidence import rtpc_program
    import gzip
    stored = json.loads((audit.ROOT / 'docs/branch-coverage-inventory.json').read_bytes())
    packed = json.loads(gzip.decompress((audit.ROOT / 'docs/branch-coverage-inventory.native-obligations.json.gz').read_bytes()))
    inventory, fixed_index, fixed_policy, _, _, fixed_ids = packet_case(tmp_path / 'fixed', '2021.1', 'busses', (stored, packed), bundle_prefix='console-2021-busses-')
    capture, original = rtpc_program(tmp_path / 'rtpc', '2023.1')
    # The accepted R114 original packet owns this scalar, not a synthetic row.
    route = next(r for r in stored['native_coverage']['routes'] if r['version'] == '2023.1'
        and r['host'] == 'wwise-authoring' and r['uri'] == runtime.RTPC_URI)
    identity = route['id'] + '|/resultSchema/properties/return/items/properties/value'
    # Include the route's committed reference edges in the ordinary portable input.
    rows = []
    for encoded in packed['rows']:
        if encoded.get('route') is None or packed['routes'][encoded['route']] != route['id']: continue
        branch = dict(encoded); branch.update(packed['contexts'][branch.pop('context')])
        branch.update(route=route['id'], id=route['id'] + '|' + branch['pointer'], shape_sha256=packed['shapes'][branch.pop('shape')]); rows.append(branch)
    rtpc_inventory = {'routes': [r for r in stored['routes'] if r['id'] == route['public_route']],
        'native_coverage': {'candidate_sha256': 'e' * 64, 'catalogs': stored['native_coverage']['catalogs'], 'routes': [route], 'obligations': rows}}
    rtpc_index = qualified.write_qualified_read_bundle(tmp_path / 'qualified', capture, original,
        inventory=rtpc_inventory, version='2023.1', category='profiler-rtpcs-observation', selected={identity}, name_prefix='qualified-2023-rtpc-')
    rtpc_policy = json.loads((rtpc_index.parent / 'qualified-2023-rtpc-requirements.json').read_bytes())
    # Reuse this one public packet to check stage-level prefix forwarding and
    # selection. Unselected flow keys confer no binding or native credit.
    from copy import deepcopy
    stage_inventory=deepcopy(rtpc_inventory)
    stage_inventory['native_coverage']['routes']=[r for r in stored['native_coverage']['routes'] if r['uri']==runtime.RTPC_URI]
    stage_inventory['routes']=[r for r in stored['routes'] if r['id'] in {n['public_route'] for n in stage_inventory['native_coverage']['routes']}]
    capture_keys={(v,h,m):capture for v in ('2021.1','2022.1','2023.1','2024.1','2025.1')
        for h in ('wwise-console','wwise-authoring') for m in ('construction','data')}
    stage_index=runtime.write_field_stage(tmp_path/'rtpc-stage',capture_keys,{},inventory=stage_inventory,
        family_prefix='rtpc-',selected_ids={identity})
    stage_document=json.loads(stage_index.read_bytes())
    assert len(stage_document['entries'])==1
    assert stage_document['entries'][0]['bindings']['artifact'].startswith('rtpc-2023.1-wwise-authoring-data-')
    stage_policy=json.loads((stage_index.parent/'requirements.json').read_bytes())
    assert set(stage_policy['branches'])=={identity}
    stage_bindings,_,_=audit.portable_binding_inputs(stage_index,stage_policy)
    assert set(stage_bindings['bindings'])=={identity}
    components = [(fixed_index, fixed_policy), (rtpc_index, rtpc_policy)]
    combined, policy = runtime.write_runtime_composition(tmp_path / 'combined', components)
    document, base, _ = audit.portable_binding_inputs(combined, policy)
    assert set(document['bindings']) == fixed_ids | {identity}
    assert policy['branches'] == {**fixed_policy['branches'], **rtpc_policy['branches']}
    # Every original gzip and reader artifact keeps its exact relative identity/bytes.
    original_bytes = (base / 'qualified-2023-rtpc-qualified-original.json.gz').read_bytes()
    assert original_bytes == original.read_bytes()
    foreign = tmp_path / 'different'; foreign.mkdir()
    path = foreign / 'qualified-2023-rtpc-qualified-original.json.gz'; path.write_bytes(b'foreign')
    with pytest.raises(ValueError, match='common-base path collision'):
        runtime.copy_runtime_common_base_file(path, base / path.name)
    assert (base / path.name).read_bytes() == original_bytes
    with pytest.raises(ValueError, match='duplicates an exact branch'):
        runtime.write_runtime_composition(tmp_path / 'duplicate', [*components, components[0]])


def test_runtime_publication_plan_assigns_native_facts_before_unique_program_rows():
    from tests.support.runtime_observation_evidence import runtime_publication_plan
    plan = runtime_publication_plan()
    assert len(plan['native_owners']) == 272
    counts = {}
    for owner in plan['native_owners'].values(): counts[owner] = counts.get(owner, 0) + 1
    assert counts == {'console': 106, 'qualified': 85, 'strict-seed': 12, 'existing-fixed': 48,
        'existing-rtpc': 6, 'existing-contribution': 15}
    assert len(plan['console_packets']) == 25 and len(plan['qualified_packets']) == 19
    assert len(plan['strict_seed_packets']) == 2
    assigned = [identity for family in plan['program_ids'].values() for identity in family]
    assigned += [identity for packet in plan['console_packets'] + plan['qualified_packets'] + plan['strict_seed_packets'] for identity in packet['ids']]
    assert len(assigned) == len(set(assigned)) == 6292
    # The four older R125 Voices packets remain seed provenance only.
    assert all(p['version'] == '2025.1' for p in plan['console_packets'] if p['category'] == 'voices')


def test_runtime_common_base_keeps_existing_global_attachment_rosters_and_bytes(tmp_path, runtime_common_base_stage):
    """Current composition keeps reviewed mappings and immutable origin bytes."""
    import hashlib
    import json
    import os
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.runtime_observation_evidence import write_runtime_composition
    stage = runtime_common_base_stage
    source = stage['reader_index']
    original = audit.load(source)
    policy = stage['reader_policy']
    target, observed_policy = write_runtime_composition(tmp_path / 'projection', [(source, policy)])
    observed = audit.load(target)
    assert observed['entries'] == original['entries']
    assert observed_policy == policy
    assert observed_policy['representative_mechanisms']
    original_base = source.parent / original['base']
    base = target.parent / observed['base']
    # The consumer owns indexed origins, not unreachable sidecars left over
    # from an earlier composition. Every selected original keeps its bytes.
    for entry in original['entries']:
        for descriptor in [entry['bindings'], *entry['origin'].values()]:
            name = descriptor['artifact']
            assert (base / name).read_bytes() == (original_base / name).read_bytes()
    # Packet-local proof remains under its exact packet namespace, with no root alias.
    proof = 'runtime-read-log-195-r1/packets/packet-8/195-successor-retained-log-support.json'
    original_packet = audit.ROOT / 'tests/fixtures/branch-evidence/product' / proof
    assert (stage['base'] / proof).read_bytes() == original_packet.read_bytes()
    assert not (stage['base'] / '195-successor-retained-log-support.json').exists()
    transported = audit.load(stage['index'])
    assert transported['qualified_runtime_read_attachments'] == stage['old_index']['qualified_runtime_read_attachments']
    mapping = audit.load(base / observed['mapping_attachments'][0]['artifact'])
    assert mapping['requirements_sha256'] == audit.digest(policy)
    original_mapping = audit.load(original_base / original['mapping_attachments'][0]['artifact'])
    assert mapping == original_mapping
    bindings, consumed_base, _ = audit.portable_binding_inputs(target, observed_policy)
    assert consumed_base == base and len(bindings['bindings']) == 44
    # A structurally valid mapping still needs its actual original predecessor.
    wrong_mapping = json.loads(json.dumps(original_mapping))
    prior = next(value for value in wrong_mapping['predecessors'].values() if value is not None)
    prior['binding_sha256'] = '0' * 64
    wrong_path = original_base / 'invalid-predecessor.json'
    wrong_path.write_text(json.dumps(wrong_mapping), encoding='utf-8')
    wrong_index = dict(original, base=os.path.relpath(original_base, tmp_path), mapping_attachments=[{
        'artifact': wrong_path.name, 'sha256': hashlib.sha256(wrong_path.read_bytes()).hexdigest()}])
    wrong_source = tmp_path / 'invalid-predecessor-index.json'
    wrong_source.write_text(json.dumps(wrong_index), encoding='utf-8')
    with pytest.raises(ValueError, match='mapping successor lacks its exact original binding/policy'):
        write_runtime_composition(tmp_path / 'invalid-predecessor', [(wrong_source, policy)])
    # A missing sealed origin cannot be replaced by the composed mapping.
    origin = observed['entries'][0]['origin']['program']
    (base / origin['artifact']).unlink()
    with pytest.raises(FileNotFoundError):
        audit.portable_binding_inputs(target, observed_policy)
    changed_policy = json.loads(json.dumps(policy))
    first = next(iter(changed_policy['branches'].values()))
    first['reason'] += ' Unreviewed input policy.'
    with pytest.raises(ValueError, match='closed reviewed mapping attachment required'):
        write_runtime_composition(tmp_path / 'unreviewed-policy', [(source, changed_policy)])


def test_runtime_composition_retains_sealed_applicability_transport_without_admission(tmp_path):
    """Transport existing proof bytes; this is not a current applicability join."""
    import hashlib
    import json
    import os
    from tests.maintenance import branch_coverage_audit as audit
    from tests.support.applicability_completion_mapping import PROOF_PATH, PROOF_SHA256
    from tests.support.runtime_observation_evidence import write_runtime_composition
    original = (audit.ROOT / PROOF_PATH).read_bytes()
    assert hashlib.sha256(original).hexdigest() == PROOF_SHA256
    descriptor = {'artifact': PROOF_PATH, 'sha256': PROOF_SHA256}
    index = {'contract': 'waapi-skill.branch-evidence-index/v1',
        'base': os.path.relpath(audit.ROOT, tmp_path), 'entries': [],
        'installed_applicability_attachments': [descriptor]}
    source = tmp_path / 'transport-index.json'
    source.write_text(json.dumps(index), encoding='utf-8')
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    target, observed_policy = write_runtime_composition(tmp_path / 'projection', [(source, policy)])
    composed = audit.load(target)
    assert observed_policy == policy
    assert composed['installed_applicability_attachments'] == [descriptor]
    assert (target.parent / composed['base'] / PROOF_PATH).read_bytes() == original


@pytest.mark.parametrize('locator', (
    r'packets\packet-8',
    r'packets/packet-8\proof',
    'packets/../packet-8',
    r'packets\..\packet-8',
    r'C:\packets\packet-8',
    r'C:packets\packet-8',
    r'\\server\share\packet-8',
    '/packets/packet-8',
), ids=('backslash-relative', 'mixed-separators', 'posix-traversal', 'windows-traversal',
        'drive-absolute', 'drive-relative', 'unc', 'posix-absolute'))
def test_runtime_composition_rejects_noncanonical_native_packet_locator(tmp_path, locator):
    """Portable packet identities reject before host filesystem interpretation."""
    import json
    from tests.semantic.support.codex_archive_paths import ArchiveRelativePathError
    from tests.support.runtime_observation_evidence import write_json, write_runtime_composition
    source = tmp_path / 'source'
    source.mkdir()
    packet = source / 'packets/packet-8'
    packet.mkdir(parents=True)
    (packet / 'proof.json').write_text('{"controlled_transport_only":true}', encoding='utf-8')
    policy = {'contract': 'waapi-skill.branch-evidence-requirements/v1', 'branches': {}}
    binding = write_json(source / 'bindings.json', {'contract': 'waapi-skill.branch-bindings/v1',
        'bindings': {'controlled-namespace': {'native_only_base': locator}}})
    index = {'contract': 'waapi-skill.branch-evidence-index/v1', 'base': 'source',
        'entries': [{'id': 'controlled-namespace', 'bindings': binding,
            'origin': {'bindings': binding,
                'requirements': write_json(source / 'requirements.json', policy),
                'program': write_json(source / 'program.json', {'controlled_transport_only': True}),
                'capture': write_json(source / 'capture.json', {'controlled_transport_only': True})}}]}
    index_path = tmp_path / 'index.json'
    index_path.write_text(json.dumps(index), encoding='utf-8')
    with pytest.raises(ArchiveRelativePathError):
        write_runtime_composition(tmp_path / 'projection', [(index_path, policy)])
    assert not (tmp_path / 'projection/index.json').exists()

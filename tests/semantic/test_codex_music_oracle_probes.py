from pathlib import Path

import pytest

from tests.semantic.support.codex_filesystem_security import CodexFileSecurityError
from tests.semantic.support.codex_music_oracle_probes import (
    FADE, MAX_CALLS, MusicOracleProbeError, compare_music_read_receipts,
    music_read_plan, run_music_read_plan, xml_music_witness, xml_project_platform,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_real_committed_xml_witness_retains_complete_mapping_and_existing_fade(version):
    relative = (Path("Interactive Music Hierarchy") / "Music.wwu" if version == "2022.1"
                else Path("Containers") / "Music" / "Music.wwu")
    witness = xml_music_witness(ROOT / "tests" / "_org" / version / relative, version)
    assert len(witness["music_switch"]["mappings"]) == 9
    assert len(witness["music_switch"]["groups"]) == 2
    assert witness["transition"]["fade"] == FADE
    assert len(witness["transition"]["rules"]) == 15
    assert len(witness["playlist"]["items"]) == 3
    assert witness["saved_order_is_live_order_proof"] is False
    assert witness["project_platform"]["name"] == "Mac"
    assert len(witness["project_platform"]["project_sha256"]) == 64
    for family in ("playlist", "transition", "music-switch"):
        plan = music_read_plan(family, witness, version)
        assert len(plan) <= MAX_CALLS
        assert {argv[0] for argv in plan} <= {"query-schema", "describe", "query-object", "metadata"}
        assert all(argv.count("--meaning") <= 8 and argv.count("--include-field") <= 8 for argv in plan)


def test_rejected_and_clarifying_queries_remain_explicit_findings_without_business_credit():
    replies = iter([(2, {"ok": False, "status": "error"}),
                    (0, {"ok": True, "status": "needs_clarification"}),
                    (0, {"ok": True, "status": "ok", "objects": [], "count": 0,
                         "query_bound": {"mode": "take", "value": 2}})])
    argv = ("query-object", "--exact-id", "{11111111-1111-1111-1111-111111111111}",
            "--relationship", "parent", "--max-results", "2")
    result = run_music_read_plan([argv] * 3, lambda _: next(replies))
    assert [row["finding"] for row in result["receipts"]] == ["gateway_rejected", "needs_clarification", "read_returned"]
    assert result["agent_pass"] is False and result["business_effect_verified"] is False
    assert result["complete_order_or_unit_oracle_proven"] is False


@pytest.mark.parametrize("plan", [[], [("execute", "tx")], [("query-schema",)] * (MAX_CALLS + 1)])
def test_invalid_plan_rejected_before_dispatch(plan):
    with pytest.raises(MusicOracleProbeError):
        run_music_read_plan(plan, lambda _: pytest.fail("dispatched"))


@pytest.mark.parametrize("payload", [
    {"ok": True, "status": "ok", "objects": [], "count": 1},
    {"ok": True, "status": "ok", "objects": "wrong", "count": 0},
    {"ok": False, "message": "x" * 1_048_576},
])
def test_malformed_or_oversized_gateway_receipt_fails_closed(payload):
    with pytest.raises(MusicOracleProbeError):
        run_music_read_plan([("query-object",)], lambda _: (0, payload))


def test_query_ceiling_is_a_finding_not_complete_inventory_proof():
    result = run_music_read_plan([("query-object", "--advanced-waql", "from objects", "--max-results", "2")], lambda _: (0, {
        "ok": True, "status": "ok", "objects": [], "count": 0, "limit_reached": True,
        "query_bound": {"mode": "gateway-appended-take", "value": 2}}))
    assert result["receipts"][0]["finding"] == "row_limit_reached"


def test_order_permutation_preserves_membership_but_cannot_prove_authoritative_order():
    path = ROOT / "tests/_org/2025.1/Containers/Music/Music.wwu"
    witness = xml_music_witness(path, "2025.1")
    data = witness["playlist"]
    rows = [{"id": row["id"]} for row in reversed(data["items"])]
    receipt = {"argv": ["query-object", "--exact-id", data["root"], "--relationship", "children"],
               "finding": "read_returned", "payload": {"objects": rows}}
    checks = compare_music_read_receipts(witness, [receipt])[0]["checks"]
    assert checks == {"member_set_matches": True, "observed_order_matches_saved_xml": False,
                      "order_is_authoritative": False}


def test_missing_and_wrong_reference_are_distinct_investigation_findings():
    path = ROOT / "tests/_org/2025.1/Containers/Music/Music.wwu"
    witness = xml_music_witness(path, "2025.1")
    entry = witness["music_switch"]["mappings"][1]
    receipt = {"argv": ["query-object", "--exact-id", entry["entry_id"]],
               "finding": "read_returned", "payload": {"objects": [{"id": entry["entry_id"]}]}}
    assert compare_music_read_receipts(witness, [receipt])[0]["checks"]["AudioNode"] is None
    receipt["payload"]["objects"][0]["references"] = {"AudioNode": {"id": "wrong-target"}}
    assert compare_music_read_receipts(witness, [receipt])[0]["checks"]["AudioNode"] is False


def test_business_receipt_without_limit_flag_at_bound_is_incomplete_and_not_compared():
    witness = xml_music_witness(ROOT / "tests/_org/2025.1/Containers/Music/Music.wwu", "2025.1")
    data = witness["playlist"]
    argv = ("query-object", "--exact-id", data["root"], "--relationship", "children", "--max-results", "3")
    rows = [{"id": item["id"]} for item in data["items"]]
    result = run_music_read_plan([argv], lambda _: (0, {
        "ok": True, "status": "ok", "objects": rows, "count": 3,
        "query_bound": {"mode": "take", "value": 3}}))
    assert result["receipts"][0]["finding"] == "row_limit_reached"
    assert compare_music_read_receipts(witness, result["receipts"])[0]["checks"] == {}


@pytest.mark.parametrize("bound", (None, {"mode": "take", "value": 4}, {"mode": "exact-object"}))
def test_business_receipt_requires_bound_matching_the_declared_read_plan(bound):
    payload = {"ok": True, "status": "ok", "objects": [], "count": 0}
    if bound is not None:
        payload["query_bound"] = bound
    argv = ("query-object", "--exact-id", "{11111111-1111-1111-1111-111111111111}",
            "--relationship", "children", "--max-results", "3")
    with pytest.raises(MusicOracleProbeError, match="bound"):
        run_music_read_plan([argv], lambda _: (0, payload))


def test_exact_identity_one_row_is_complete_without_limit_flag():
    identifier = "{11111111-1111-1111-1111-111111111111}"
    result = run_music_read_plan([("query-object", "--exact-id", identifier)], lambda _: (0, {
        "ok": True, "status": "ok", "objects": [{"id": identifier}], "count": 1,
        "query_bound": {"mode": "exact-object"}}))
    assert result["receipts"][0]["finding"] == "read_returned"


@pytest.mark.parametrize("field", ("Arguments", "Entries"))
def test_2022_empty_collection_is_representation_gap_not_matching_inventory(field):
    witness = xml_music_witness(ROOT / "tests/_org/2022.1/Interactive Music Hierarchy/Music.wwu", "2022.1")
    expression = f'from object "{witness["music_switch"]["owner"]}" select @{field}'
    receipt = {"argv": ["query-object", "--advanced-waql", expression, "--max-results", "16"],
               "finding": "read_returned", "payload": {"objects": [], "count": 0,
                   "query_bound": {"mode": "gateway-appended-take", "value": 16}}}
    compared = compare_music_read_receipts(witness, [receipt])[0]
    assert compared["finding"] == "expected_representation_unavailable"
    assert compared["checks"] == {}


@pytest.mark.parametrize("route,expected_bound", (
    ("exact", {"mode": "exact-object"}),
    ("relationship", {"mode": "take", "value": 2}),
    ("advanced", {"mode": "gateway-appended-take", "value": 2}),
))
def test_probe_accepts_actual_public_gateway_bound_projection(tmp_path, route, expected_bound):
    from tests.unit.test_waapi_gateway import FakeClient, gateway_env, live_info, waapi_gateway

    identifier = "{11111111-1111-1111-1111-111111111111}"
    row = {"id": identifier, "name": "Known", "type": "Sound", "path": r"\Known"}
    client = FakeClient({"ak.wwise.core.getInfo": live_info(),
                         "ak.wwise.core.object.get": {"return": [row]}})
    argv = ["query-object", "--exact-id", identifier]
    if route == "relationship":
        argv.extend(("--relationship", "children", "--max-results", "2"))
    elif route == "advanced":
        argv = ["query-object", "--advanced-waql", f'from object "{identifier}" select children',
                "--max-results", "2"]
    code, payload = waapi_gateway.execute_gateway(
        argv, env=gateway_env(tmp_path), client_factory=lambda _url: client,
    )
    assert code == 0, payload
    assert payload["query_bound"] == expected_bound
    if route == "exact":
        # Builder metadata is not the public receipt shape. Keep the probe
        # pinned to the actual Gateway projection, not its internal preview.
        assert payload["query_bound"] != {"mode": "exact-object", "value": 1}
        from wwise_waapi.builders.query import STRUCTURED_QUERY_CONTRACT, build_structured_object_get_query
        preview = build_structured_object_get_query({"contract": STRUCTURED_QUERY_CONTRACT,
            "source": {"kind": "object", "objects": [{"kind": "id", "value": identifier}]},
            "transforms": [], "return": ["id", "name", "type", "path"]}, version="2022.1")
        assert preview.envelope.metadata["query_bound"] == {"mode": "exact-object", "value": 1}
    result = run_music_read_plan([argv], lambda _: (code, payload))
    assert result["receipts"][0]["finding"] == "read_returned"


@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
@pytest.mark.parametrize('field', ('FadeTime', 'FadeOffset'))
@pytest.mark.parametrize('exact', (False, True))
def test_transition_property_state_plan_passes_public_preflight_and_live_metadata(tmp_path, version, field, exact):
    from tests.unit.test_metadata_discovery_gateway import (
        FakeClient, _gateway_env, _metadata_responses, waapi_gateway, IS_PROPERTY_ENABLED_URI,
    )
    relative = (Path('Interactive Music Hierarchy/Music.wwu') if version == '2022.1'
        else Path('Containers/Music/Music.wwu'))
    witness = xml_music_witness(ROOT / 'tests/_org' / version / relative, version)
    commands = [argv for argv in music_read_plan('transition', witness, version)
        if argv[:2] == ('metadata', 'property-state')]
    command = commands[('FadeTime', 'FadeOffset').index(field)]
    meaning = 'time' if field == 'FadeTime' else 'offset'
    assert command == ('metadata', 'property-state', '--exact-id', FADE, '--meaning', meaning, '--platform', 'Mac')
    if exact:
        # An exact field token narrows before fuzzy display-label matches.
        command = (*command[:5], field, *command[6:])
    responses = _metadata_responses(tmp_path, version=version, names=('FadeTime', 'FadeOffset', 'FadeCurve', 'FadeType'))
    responses[IS_PROPERTY_ENABLED_URI] = {'return': True}
    client = FakeClient(responses)
    code, payload = waapi_gateway.execute_gateway(list(command), env=_gateway_env(tmp_path, version=version),
        client_factory=lambda _url: client)
    assert code == 0, payload
    assert client.calls  # Actual public preflight reached only the injected fake.
    assert payload['agent_result'] == {'meaning': field if exact else meaning, 'platform': 'Mac', 'enabled': True}
    assert client.calls[-1] == (IS_PROPERTY_ENABLED_URI, {'object': FADE, 'platform': 'Mac', 'property': field}, {})


@pytest.mark.parametrize('version', ('2022.1', '2025.1'))
@pytest.mark.parametrize('enabled', (False, True, 'native-error'))
def test_playlist_condition_reads_retain_exact_inventory_and_native_state_without_business_credit(tmp_path, version, enabled):
    from tests.unit.test_metadata_discovery_gateway import (
        FakeClient, _gateway_env, _metadata_responses, waapi_gateway,
        GET_NAMES_URI, GET_PROPERTY_INFO_URI, IS_PROPERTY_ENABLED_URI,
    )
    relative = (Path('Interactive Music Hierarchy/Music.wwu') if version == '2022.1'
        else Path('Containers/Music/Music.wwu'))
    witness = xml_music_witness(ROOT / 'tests/_org' / version / relative, version)
    plan = music_read_plan('playlist', witness, version)
    identifier = '{DE090E27-2F5C-436F-A239-D02F8D5016B2}'
    commands = [argv for argv in plan if argv[:2] in {
        ('metadata', 'list'), ('metadata', 'property-state')}]
    assert commands == [
        ('metadata', 'list', '--exact-id', identifier, '--page-size', '64'),
        ('metadata', 'property-state', '--exact-id', identifier,
         '--meaning', 'LoopCount', '--platform', 'Mac'),
    ]
    # Existing controller-discovery attempts are not duplicated or replaced.
    assert sum(argv[:2] == ('metadata', 'discover') for argv in plan) == 3
    names = ('Color', 'LoopCount', 'NormalOrShuffle', 'OverrideColor', 'PlayMode',
             'PlaylistItemType', 'RandomAvoidRepeatingCount', 'Weight', 'Segment')
    responses = _metadata_responses(tmp_path, version=version, names=names)
    # Retained 2025 metadata names an unavailable controller; the test does
    # not supply controller metadata or derive a Boolean from UI infinity.
    responses[GET_PROPERTY_INFO_URI] = {
        'name': 'LoopCount', 'type': 'int16', 'default': 1,
        'display': {'name': 'No. of Loops'},
        'restriction': {'type': 'range', 'min': 0, 'max': 32767},
        'dependencies': [{'type': 'property', 'action': 'Enable', 'context': 'Self',
            'property': 'IsLoopingInfinite',
            'conditions': [{'restriction': {'type': 'enum',
                'values': [{'displayName': 'False', 'value': False}]}}]}],
        'ui': {'value': {'infinity': 0}},
    }
    responses[IS_PROPERTY_ENABLED_URI] = {'return': enabled}
    errors = ({IS_PROPERTY_ENABLED_URI: RuntimeError('native LoopCount state unavailable')}
              if enabled == 'native-error' else {})
    client = FakeClient(responses, errors=errors)
    env = _gateway_env(tmp_path, version=version)
    returned = []

    def gateway(argv):
        code, payload = waapi_gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
        returned.append((code, payload))
        return code, payload

    report = run_music_read_plan(commands, gateway)
    inventory, state = report['receipts']
    fields = inventory['payload']['agent_result']['fields']
    assert len(fields) == 9
    assert {row['name'] for row in fields} == set(names)
    assert inventory['payload']['agent_result']['complete'] is True
    assert 'IsLoopingInfinite' not in {row['name'] for row in fields}
    assert all(args == {'object': identifier} for uri, args, _ in client.calls if uri == GET_NAMES_URI)
    assert all(args == {'object': identifier, 'property': 'LoopCount'}
               for uri, args, _ in client.calls if uri == GET_PROPERTY_INFO_URI)
    assert client.calls[-1] == (IS_PROPERTY_ENABLED_URI,
        {'object': identifier, 'platform': 'Mac', 'property': 'LoopCount'}, {})
    assert [(row['exit_code'], row['payload']) for row in report['receipts']] == returned
    if enabled == 'native-error':
        assert state['exit_code'] == 2
        assert state['finding'] == 'gateway_rejected'
        assert state['payload']['ok'] is False
        assert state['payload']['call']['api'] == IS_PROPERTY_ENABLED_URI
    else:
        assert state['exit_code'] == 0
        assert state['finding'] == 'read_returned'
        assert state['payload']['agent_result'] == {
            'meaning': 'LoopCount', 'platform': 'Mac', 'enabled': enabled}
    assert report['agent_pass'] is False
    assert report['business_effect_verified'] is False
    assert report['complete_order_or_unit_oracle_proven'] is False
    assert compare_music_read_receipts(witness, report['receipts']) == []


@pytest.mark.parametrize('outcome', ('disabled', 'native-error', 'owned-readback-failure'))
def test_actual_playlist_maintenance_report_persists_condition_read_outcomes(tmp_path, monkeypatch, outcome):
    import json
    from types import SimpleNamespace
    from tests.unit.test_metadata_discovery_gateway import (
        FakeClient, _gateway_env, _metadata_responses, waapi_gateway,
        GET_PROPERTY_INFO_URI, IS_PROPERTY_ENABLED_URI,
    )
    monkeypatch.setenv('WWISE_LIVE', '1')
    monkeypatch.setenv('WWISE_DESTRUCTIVE', '1')
    from tests.maintenance import probe_music_expansion_oracles as node
    from tests.destructive.support.category_evidence import append_category_evidence

    version = '2025.1'
    owned = tmp_path / 'project'
    relative = Path('Containers/Music/Music.wwu')
    music = owned / relative
    music.parent.mkdir(parents=True)
    music.write_bytes((ROOT / 'tests/_org' / version / relative).read_bytes())
    project = owned / 'SampleProject.wproj'
    project.write_bytes((ROOT / 'tests/_org' / version / 'SampleProject.wproj').read_bytes())
    names = ('Color', 'LoopCount', 'NormalOrShuffle', 'OverrideColor', 'PlayMode',
             'PlaylistItemType', 'RandomAvoidRepeatingCount', 'Weight', 'Segment')
    responses = _metadata_responses(tmp_path, version=version, names=names)
    responses[GET_PROPERTY_INFO_URI] = {
        'name': 'LoopCount', 'type': 'int16', 'default': 1,
        'restriction': {'type': 'range', 'min': 0, 'max': 32767},
        'dependencies': [{'type': 'property', 'action': 'Enable', 'context': 'Self',
            'property': 'IsLoopingInfinite', 'conditions': [{'restriction': {
                'type': 'enum', 'values': [{'displayName': 'False', 'value': False}]}}]}],
        'ui': {'value': {'infinity': 0}},
    }
    responses[IS_PROPERTY_ENABLED_URI] = {'return': False}
    errors = ({IS_PROPERTY_ENABLED_URI: RuntimeError('native LoopCount state unavailable')}
              if outcome == 'native-error' else {})
    client = FakeClient(responses, errors=errors)
    env = _gateway_env(tmp_path, version=version)
    condition_replies = []

    def raw_gateway(argv):
        if argv[:2] in (['metadata', 'list'], ['metadata', 'property-state']):
            result = waapi_gateway.execute_gateway(argv, env=env, client_factory=lambda _: client)
            condition_replies.append(result)
            return result
        # Unrelated external reads remain bounded diagnostic rejections. The
        # changed reads above use the actual Gateway with external WAAPI faked.
        if (outcome == 'owned-readback-failure' and argv[:2] == ['metadata', 'discover']
                and argv[3] == '{898C3D43-E6A9-4327-8029-61E657048399}'):
            music.write_bytes(music.read_bytes() + b'\n')
        return 2, {'ok': False, 'status': 'error', 'agent_result': None,
                   'error_code': 'unrelated_fake_read_unavailable'}

    runtime = SimpleNamespace(version=version,
        sandbox=SimpleNamespace(sandbox_path=owned, sandbox_project=project),
        category_results=[], raw_gateway=raw_gateway, port=31337,
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    if outcome == 'owned-readback-failure':
        with pytest.raises(AssertionError, match='read-only probe changed its owned WWU'):
            node.test_music_complete_oracle_public_read_investigation(runtime, 'playlist')
    else:
        node.test_music_complete_oracle_public_read_investigation(runtime, 'playlist')
    failed = outcome == 'owned-readback-failure'
    nodeid = ('tests/maintenance/probe_music_expansion_oracles.py::'
              'test_music_complete_oracle_public_read_investigation[playlist]')
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    append_category_evidence(repo_root=tmp_path, candidate='a' * 40, version=version,
        host={'display_name': 'fake-only'}, categories=runtime.category_results,
        source={'hash_before': 'same', 'hash_after': 'same'},
        residual_state={'residual_processes': [], 'sandbox': 'retained' if failed else 'deleted'},
        invocation={'selected_test_nodeids': [nodeid], 'started_at_unix_ns': 1,
            'finished_at_unix_ns': 2, 'outcome': 'FAIL' if failed else 'PASS',
            'node_outcomes': [{'nodeid': nodeid, 'outcome': 'FAIL' if failed else 'PASS'}],
            'phase': 'final'}, transactions=[])
    persisted = json.loads(target.read_text())
    assert persisted['contract'] == 'waapi-skill.host-category-evidence/v3'
    assert persisted['invocation']['phase'] == 'final'
    assert persisted['transactions'] == []
    sealed, = persisted['categories']
    assert sealed['status'] == ('FAIL' if failed else 'PASS')
    assert sealed['category'] == 'music-complete-oracle-read-playlist'
    assert sealed['verifier_strength'] == 'bounded_public_read_findings_not_music_configuration_acceptance'
    assert sealed['agent_pass'] is False and sealed['business_effect_verified'] is False
    assert sealed['complete_order_or_unit_oracle_proven'] is False
    assert sealed['transaction_ids'] == []
    assert len(sealed['receipts']) == 13
    assert any(row['finding'] == 'gateway_rejected' for row in sealed['receipts'])
    inventory, state = [row for row in sealed['receipts'] if row['argv'][:2] in (
        ['metadata', 'list'], ['metadata', 'property-state'])]
    assert [(row['exit_code'], row['payload']) for row in (inventory, state)] == condition_replies
    fields = inventory['payload']['agent_result']['fields']
    assert len(fields) == 9 and {row['name'] for row in fields} == set(names)
    assert inventory['payload']['agent_result']['complete'] is True
    if outcome == 'native-error':
        assert state['finding'] == 'gateway_rejected' and state['exit_code'] == 2
        assert state['payload']['call']['api'] == IS_PROPERTY_ENABLED_URI
    else:
        assert state['finding'] == 'read_returned' and state['exit_code'] == 0
        assert state['payload']['agent_result'] == {
            'meaning': 'LoopCount', 'platform': 'Mac', 'enabled': False}
    if not failed:
        assert sealed['scope'] == 'read_transport_and_retained_findings_only_not_complete_oracle_or_mutation_pass'


@pytest.mark.parametrize('damage', ('missing', 'duplicate', 'entity', 'oversized', 'too_many'))
def test_project_platform_binding_rejects_unproven_or_unbounded_xml(tmp_path, damage):
    project = tmp_path / 'SampleProject.wproj'
    platform = '<Platform Name="Mac" ID="{9C6217D5-DD11-4795-87C1-6CE02853C541}"/>'
    if damage == 'missing':
        platform = platform.replace('Name="Mac"', 'Name="Windows"')
    elif damage == 'duplicate':
        platform += platform
    elif damage == 'too_many':
        platform += ''.join(f'<Platform Name="Other{index}" ID="other"/>' for index in range(32))
    text = '<WwiseDocument><ProjectInfo><Project><Platforms>' + platform + '</Platforms></Project></ProjectInfo></WwiseDocument>'
    if damage == 'entity':
        text = '<!DOCTYPE WwiseDocument [<!ENTITY external SYSTEM "file:///forbidden">]>' + text
    elif damage == 'oversized':
        text += ' ' * 1_048_576
    project.write_text(text)
    with pytest.raises((ValueError, CodexFileSecurityError)):
        xml_project_platform(project)

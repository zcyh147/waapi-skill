"""Matching-host PlaylistSlot read using the existing owned sandbox fixture."""
import hashlib
import json
import os

import pytest

from tests.destructive.test_gateway_workflow_transaction_matrix import (
    _bind_business_object,
    _complete_business_draft,
    _complete_object_metadata_business_transaction,
    _discover_business_type,
    discovered_business_field_handle,
    _start_business_draft,
    _update_business_draft,
    workflow_sandbox_runtime,
)
from tests.support.playlist_reference_observation import (
    collect_playlist_instance_identities,
    collect_playlist_slot_reference_metadata,
)


pytestmark = [
    pytest.mark.live,
    pytest.mark.destructive,
    pytest.mark.skipif(
        os.environ.get("WWISE_VERSION") != "2025.1",
        reason="Exact 2025 PlaylistSlot reference observation; older Playlist list semantics remain separate work",
    ),
]


def test_playlist_slot_reference_native_metadata(workflow_sandbox_runtime):
    version = workflow_sandbox_runtime.sandbox.metadata.get_info_version
    assert isinstance(version, dict) and tuple(
        version.get(key) for key in ("year", "major", "minor", "build")
    ) == (2025, 1, 7, 9143), version
    collect_playlist_slot_reference_metadata(workflow_sandbox_runtime)


def test_playlist_slot_native_identity(workflow_sandbox_runtime):
    version = workflow_sandbox_runtime.sandbox.metadata.get_info_version
    assert isinstance(version, dict) and tuple(
        version.get(key) for key in ("year", "major", "minor", "build")
    ) == (2025, 1, 7, 9143), version
    collect_playlist_instance_identities(workflow_sandbox_runtime)


def test_existing_playlist_slot_reference_change_preserves_peer_and_order(workflow_sandbox_runtime):
    _observe_existing_playlist_reference_change(workflow_sandbox_runtime)


def test_existing_playlist_slot_rename_preserves_peer_order_and_references(workflow_sandbox_runtime):
    """One ordinary public rename attempt; native support awaits this outcome."""
    runtime = workflow_sandbox_runtime
    version = runtime.sandbox.metadata.get_info_version
    assert isinstance(version, dict) and tuple(version.get(key) for key in ('year', 'major', 'minor', 'build')) == (2025, 1, 7, 9143), version
    identities = {'slot': '{7571D6B0-D614-40B5-B02D-0012FE3743A7}',
        'peer': '{6298C41E-F7C6-40B6-BFFE-E0B02EE7DC72}', 'owner': '{8C0FD1AD-E45D-408D-9BF3-874970CCC123}',
        'old_target': '{0DD1BBE3-BB1E-424A-9648-BEBFBB212426}', 'target': '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}'}
    output = runtime.state_dir / 'playlist-rename-effect.json'
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'operation': 'object.setName',
        'requested_name': 'RenamedSlot', 'calls': [], 'reads': [], 'transactions': [], 'business_effect_verified': False}
    category = {'category': 'existing-playlist-slot-rename', 'status': 'FAIL',
        'verifier_strength': 'independent_name_class_owner_order_peer_reference_readback',
        'observation_path': str(output), 'business_effect_verified': False}
    runtime.category_results.append(category)
    status = 'FAIL'

    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(observation['calls']) < 48, 'Inner rename public command bound exceeded'
            record = {'argv': list(argv)}
            observation['calls'].append(record)
            try:
                code, payload = runtime.raw_gateway(argv)
                record.update(exit_code=code, payload=payload)
                return code, payload
            except BaseException as exc:
                record['error'] = f'{type(exc).__name__}: {exc}'
                raise

        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            return payload

    gateway = ReceiptGateway()

    def read(label, selector):
        assert len(observation['reads']) < 16
        observation['reads'].append({'label': label, 'call_index': len(observation['calls'])})
        payload = gateway.gateway(['query-object', *selector, '--max-results', '4', '--include', 'class-id',
            '--include', 'owner', '--include', 'parent', '--include', 'notes'], live=True)
        rows = payload.get('objects', payload.get('agent_result'))
        assert payload.get('projection_complete') is not False and payload.get('status') != 'partial', payload
        assert isinstance(rows, list) and len(rows) < 4, payload
        return rows

    def observe(phase):
        result = {}
        for role, identity in identities.items():
            rows = read(phase + '-' + role, ['--exact-id', identity])
            assert len(rows) == 1 and rows[0]['id'] == identity, rows
            result[role] = rows[0]
        result['members'] = read(phase + '-playlist', ['--advanced-waql', f'from object "{identities["owner"]}" select @Playlist'])
        result['references'] = {}
        for role in ('slot', 'peer'):
            rows = read(phase + '-' + role + '-target', ['--advanced-waql', f'from object "{identities[role]}" select @PlaylistObject'])
            assert len(rows) == 1, rows
            result['references'][role] = rows[0]
        return result

    try:
        before = observe('before')
        observation['before'] = before
        for role in ('slot', 'peer'):
            assert before[role]['name'] == '' and before[role]['type'] == 'PluginInnerObject', before[role]
            assert before[role]['class_id'] == 5636096 and before[role]['owner']['id'] == identities['owner'], before[role]
        assert before['owner']['type'] == 'RandomSequenceContainer' and before['owner']['class_id'] == 589840
        for role in ('target', 'old_target'):
            assert before[role]['type'] == 'Sound' and before[role]['class_id'] == 65552, before[role]
            assert before[role]['parent']['id'] == identities['owner'], before[role]
        assert [row['id'] for row in before['members']] == [identities['slot'], identities['peer']]
        assert before['references']['slot'] == before['old_target'] and before['references']['peer'] == before['target']
        draft = _start_business_draft(gateway, 'object.setName')
        _bind_business_object(gateway, draft, object_id=identities['slot'])
        _update_business_draft(gateway, draft, 'draft-declare-object-change', ['--new-name', 'RenamedSlot'], live=False)
        observation['transactions'].append(_complete_business_draft(gateway, draft))
        after = observe('after')
        observation['after'] = after
        assert after['slot'] == {**before['slot'], 'name': 'RenamedSlot'}, after['slot']
        assert after['members'] == [{**before['members'][0], 'name': 'RenamedSlot'}, before['members'][1]], after['members']
        assert after['references'] == before['references']
        assert all(after[role] == before[role] for role in ('peer', 'owner', 'target', 'old_target'))
        observation['business_effect_verified'] = True
        status = 'PASS'
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 8 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, business_effect_verified=observation['business_effect_verified'],
            observation_sha256=hashlib.sha256(body).hexdigest())


def _observe_existing_playlist_reference_change(runtime, *, staged_notes=None):
    """One reference change on existing objects in the copied SampleProject."""
    version = runtime.sandbox.metadata.get_info_version
    assert isinstance(version, dict) and tuple(
        version.get(key) for key in ("year", "major", "minor", "build")
    ) == (2025, 1, 7, 9143), version
    slot = "{7571D6B0-D614-40B5-B02D-0012FE3743A7}"
    peer = "{6298C41E-F7C6-40B6-BFFE-E0B02EE7DC72}"
    owner = "{8C0FD1AD-E45D-408D-9BF3-874970CCC123}"
    old_target = "{0DD1BBE3-BB1E-424A-9648-BEBFBB212426}"
    target = "{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}"
    staged = staged_notes is not None
    output = runtime.state_dir / ("playlist-staged-notes-effect.json" if staged else "playlist-reference-effect.json")
    observation = {"candidate": runtime.candidate, "version": runtime.version,
        "operation": "object.setNotes_then_setReference" if staged else "object.setReference",
        "reads": [], "transactions": [], "business_effect_verified": False}
    category = {"category": "existing-playlist-staged-reference-notes" if staged else "existing-playlist-reference-change", "status": "FAIL",
        "verifier_strength": "independent_reference_membership_and_peer_readback",
        "observation_path": str(output)}
    runtime.category_results.append(category)
    status = "FAIL"

    def read(label, selector):
        assert len(observation["reads"]) < (16 if staged else 14)
        argv = ["query-object", *selector, "--max-results", "4", "--include", "class-id",
                "--include", "owner", "--include", "parent",
                *(["--include", "notes"] if staged else [])]
        code, payload = runtime.raw_gateway(argv)
        observation["reads"].append({"label": label, "argv": argv, "exit_code": code, "payload": payload})
        assert code == 0 and payload.get("ok") is True, payload
        assert payload.get("projection_complete") is not False and payload.get("status") != "partial", payload
        rows = payload.get("objects", payload.get("agent_result"))
        assert isinstance(rows, list) and len(rows) < 4, payload
        return rows

    def exact(label, identity):
        rows = read(label, ["--exact-id", identity])
        assert len(rows) == 1 and rows[0]["id"] == identity, rows
        return rows[0]

    def reference(label, identity):
        rows = read(label, ["--advanced-waql", f'from object "{identity}" select @PlaylistObject'])
        assert len(rows) == 1, rows
        return rows[0]["id"]

    def members(label):
        return read(label, ["--advanced-waql", f'from object "{owner}" select @Playlist'])

    try:
        before = {"slot": exact("before-slot", slot), "peer": exact("before-peer", peer),
                  "owner": exact("before-owner", owner), "target": exact("before-target", target)}
        observation["before"] = before
        for key in ("slot", "peer"):
            assert before[key]["name"] == "" and before[key]["type"] == "PluginInnerObject", before[key]
            assert before[key]["class_id"] == 5636096 and before[key]["owner"]["id"] == owner, before[key]
        assert before["owner"]["type"] == "RandomSequenceContainer" and before["owner"]["class_id"] == 589840
        assert before["target"]["type"] == "Sound" and before["target"]["class_id"] == 65552
        assert before["target"]["parent"]["id"] == owner
        assert reference("before-slot-target", slot) == old_target
        assert reference("before-peer-target", peer) == target
        before_members = members("before-playlist")
        assert [row["id"] for row in before_members] == [slot, peer], before_members

        if staged:
            assert isinstance(staged_notes, str) and staged_notes != before["slot"].get("notes")
            draft = _start_business_draft(runtime, "object.setNotes")
            _bind_business_object(runtime, draft, object_id=slot)
            _update_business_draft(runtime, draft, "draft-declare-object-change",
                ["--notes", staged_notes], live=False)
            notes_receipt = _complete_business_draft(runtime, draft)
            observation["transactions"].append(notes_receipt)
            assert exact("after-notes-slot", slot) == {**before["slot"], "notes": staged_notes}
            assert reference("after-notes-slot-target", slot) == old_target
        # A fresh Draft binds the independently observed post-notes object.
        # Each stage has its own immutable Preview and explicit authorization.
        receipt = _complete_object_metadata_business_transaction(
            runtime, operation="object.setReference", object_id=slot,
            field_name="PlaylistObject", target_id=target,
        )
        observation["transactions"].append(receipt)
        assert reference("after-slot-target", slot) == target
        assert reference("after-peer-target", peer) == target
        after_members = members("after-playlist")
        # Native slot display paths depend on their selected target. Material
        # identity, membership and class/owner must remain stable independently.
        stable = lambda row: {key: row[key] for key in ("id", "name", "type", "class_id", "owner")}
        assert [stable(row) for row in after_members] == [stable(row) for row in before_members]
        for key, identity in (("peer", peer), ("owner", owner), ("target", target)):
            assert exact("after-" + key, identity) == before[key]
        if staged:
            after_slot = exact("after-slot", slot)
            expected_slot = {**before["slot"], "notes": staged_notes}
            expected_path = before["owner"]["path"] + "\\[PlaylistSlot: (" + before["target"]["name"] + ")]"
            assert after_slot["path"] in {before["slot"]["path"], expected_path}, after_slot
            assert {**after_slot, "path": before["slot"]["path"]} == expected_slot
            assert len(observation["transactions"]) == 2
        observation["business_effect_verified"] = True
        status = "PASS"
    except BaseException as exc:
        observation["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode("utf-8")
        assert len(body) <= 8 * 1024 * 1024
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        category.update(status=status, observation_sha256=hashlib.sha256(body).hexdigest())


def test_new_playlist_slot_append_preserves_existing_peers(workflow_sandbox_runtime):
    _observe_new_playlist_slot_append(workflow_sandbox_runtime)


def test_new_playlist_slot_root_create_preserves_existing_peers(workflow_sandbox_runtime):
    _observe_new_playlist_slot_append(workflow_sandbox_runtime, root_create_only=True)


def _observe_new_playlist_slot_append(runtime, *, root_create_only=False):
    """Observe root-list create alone, or the original three-phase workflow."""
    from uuid import UUID
    version = runtime.sandbox.metadata.get_info_version
    assert runtime.version == '2025.1' and tuple(version.get(key) for key in
        ('year', 'major', 'minor', 'build')) == (2025, 1, 7, 9143), version
    owner = '{8C0FD1AD-E45D-408D-9BF3-874970CCC123}'
    target = '{DB017C8E-EC99-415B-93CF-F7A6136D1AC2}'
    peers = ['{7571D6B0-D614-40B5-B02D-0012FE3743A7}', '{6298C41E-F7C6-40B6-BFFE-E0B02EE7DC72}']
    output = runtime.state_dir / ('playlist-new-slot-root-create-effect.json' if root_create_only else 'playlist-new-slot-append-effect.json')
    assert not output.exists(), 'Never overwrite a prior new-slot observation'
    output.parent.mkdir(parents=True, exist_ok=True)
    observation = {'candidate': runtime.candidate, 'version': runtime.version, 'build': version,
        'operations': ['object.create'] if root_create_only else ['object.set', 'object.set', 'object.create'],
        'calls': [], 'reads': [], 'transactions': [], 'business_effect_verified': False}
    category = {'category': 'playlist-slot-root-create' if root_create_only else 'playlist-slot-append-replace-root-create',
        'status': 'FAIL', 'observation_path': str(output),
        'verifier_strength': 'independent_new_GUID_class_owner_reference_ordered_peers_and_target_readback'}
    runtime.category_results.append(category)
    status = 'FAIL'

    class ReceiptGateway:
        def raw_gateway(self, argv):
            assert len(observation['calls']) < 96, 'Playlist public command bound exceeded'
            record = {'argv': list(argv)}
            observation['calls'].append(record)
            try:
                code, payload = runtime.raw_gateway(argv)
                record.update(exit_code=code, payload=payload)
                return code, payload
            except BaseException as exc:
                record['error'] = f'{type(exc).__name__}: {exc}'
                raise

        def gateway(self, argv, *, live):
            code, payload = self.raw_gateway(argv)
            assert code == 0 and payload.get('ok') is True, payload
            return payload

    gateway = ReceiptGateway()

    def read(label, selector):
        assert len(observation['reads']) < 32
        observation['reads'].append({'label': label, 'call_index': len(observation['calls'])})
        payload = gateway.gateway(['query-object', *selector, '--max-results', '4',
            '--include', 'class-id', '--include', 'owner', '--include', 'parent', '--include', 'notes'], live=True)
        assert payload.get('projection_complete') is not False and payload.get('status') != 'partial', payload
        assert payload.get('limit_reached') is not True and list(payload)[-1] == 'agent_result', payload
        rows = payload['agent_result']
        assert isinstance(rows, list) and len(rows) < 4 and len({row['id'] for row in rows}) == len(rows), payload
        return rows

    def exact(label, identity):
        rows = read(label, ['--exact-id', identity])
        assert len(rows) == 1, rows
        row = rows[0]
        assert row['id'] == identity, row
        return row

    def reference(label, identity):
        rows = read(label, ['--advanced-waql', f'from object "{identity}" select @PlaylistObject'])
        assert len(rows) == 1, rows
        return rows[0]

    def absent(identity):
        # As in the owned-history collector, this exact pinned host rejects a
        # missing GUID source. Only its complete, query-bound native failure
        # proves absence; an arbitrary invalid_query remains a failure.
        assert identity in removed_ids and len(observation['reads']) < 32
        observation['reads'].append({'label': 'removed-slot', 'call_index': len(observation['calls'])})
        code, payload = gateway.raw_gateway(['query-object', '--exact-id', identity, '--max-results', '4', '--detail',
            '--include', 'class-id', '--include', 'owner', '--include', 'parent', '--include', 'notes'])
        query = f'from object "{identity}" take 4'
        uri = 'ak.wwise.core.object.get'
        assert code == 2 and payload['ok'] is False and payload['status'] == 'error', payload
        assert payload['endpoint'] == observation['calls'][0]['payload']['endpoint'] and payload['detected_version'] == runtime.version, payload
        preview = payload['semantic_preview']
        assert preview['version'] == runtime.version and preview['envelope']['uri'] == uri, payload
        assert preview['envelope']['args'] == {'waql': query}, payload
        assert preview['envelope']['options'] == {'return': ['id', 'name', 'type', 'path', 'classId', 'owner', 'parent', 'notes']}, payload
        assert payload['query_bound'] == {'mode': 'take', 'value': 4}, payload
        call = payload['call']
        assert call['api'] == uri and call['version'] == runtime.version and call['ok'] is False, payload
        assert call['error_code'] == 'WaapiRequestFailed' and call['waapi_error_uri'] == 'ak.wwise.query.invalid_query', payload
        assert call['waapi_error_details'] == {'details': {'procedureUri': uri}, 'message': query + ' - Object not found'}, payload
        assert payload['count'] is None and payload['objects'] is None and payload['agent_result'] is None, payload

    def construct(operation='object.set', behavior='append'):
        draft = _start_business_draft(gateway, operation)
        owner_handle = _bind_business_object(gateway, draft, object_id=owner)
        target_handle = _bind_business_object(gateway, draft, object_id=target)
        if behavior == 'replace-all':
            _update_business_draft(gateway, draft, 'draft-business-configure',
                ['--list-behavior', behavior], live=False)
        kind = _discover_business_type(gateway, draft, meaning='PlaylistSlot', role='object', expected_label='PlaylistSlot')
        listing = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--object-handle', owner_handle, '--field-source', 'documented-lists', '--list'], live=True)
        choice, = [row for row in listing['agent_result']['items'] if row['name'] == 'Playlist']
        assert choice['element_classes'] == [{'name': 'PlaylistSlot', 'class_id': 5636096}], choice
        selected = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--object-handle', owner_handle, '--field-source', 'documented-lists', '--selection', choice['selection']], live=True)
        list_candidate, = [row for result in selected['meaning_results'] for row in result['candidates']]
        assert list_candidate['field_kind'] == 'list' and list_candidate['evidence']['declaration']['name'] == 'Playlist'
        list_field = list_candidate['handle']
        field = _update_business_draft(gateway, draft, 'draft-discover-fields',
            ['--type-handle', kind, '--meaning', 'Playlist Object'], live=True)
        reference_field = discovered_business_field_handle(field, 'Playlist Object')
        _update_business_draft(gateway, draft, 'draft-declare-new', ['--declaration-id', 'playlist-slot',
            '--parent-handle', owner_handle, '--name', 'Requested occurrence', '--kind', kind,
            '--field', 'object_list', list_field, '--field-value', reference_field, target_handle], live=False)
        receipt = {}
        observation['transactions'].append(receipt)
        receipt.update(_complete_business_draft(gateway, draft))
        assert receipt['execute']['automatic_retry'] is False
        return receipt

    try:
        before_owner = observation['before_owner'] = exact('before-owner', owner)
        before_target = observation['before_target'] = exact('before-target', target)
        before = observation['before_members'] = read('before-members', ['--advanced-waql', f'from object "{owner}" select @Playlist'])
        assert before_owner['type'] == 'RandomSequenceContainer' and before_owner['class_id'] == 589840
        assert before_target['type'] == 'Sound' and before_target['class_id'] == 65552 and before_target['parent']['id'] == owner
        assert [row['id'] for row in before] == peers, before
        assert all(row['class_id'] == 5636096 and row['type'] == 'PluginInnerObject'
            and row['name'] == '' and row['owner']['id'] == owner and 'parent' not in row for row in before), before
        old_references = observation['before_references'] = [reference('before-peer-reference', identity) for identity in peers]
        if not root_create_only:
            receipt = construct()
            created, = receipt['verify']['agent_result']['business_result']['created_objects']
            identity = created['object']['id']
            assert UUID(identity).int != 0 and identity not in {*peers, owner, target}
            assert created['name_role'] == 'declaration_label' and created['native_name'] == ''
            actual = exact('new-slot', identity)
            observation['created'] = actual
            assert actual['name'] == '' and actual['type'] == 'PluginInnerObject' and actual['class_id'] == 5636096
            assert actual['owner']['id'] == owner and 'parent' not in actual
            new_reference = observation['new_reference'] = reference('new-reference', identity)
            assert new_reference == before_target
            after = observation['after_members'] = read('after-members', ['--advanced-waql', f'from object "{owner}" select @Playlist'])
            assert [row['id'] for row in after] == [*peers, identity] and after[:len(peers)] == before
            assert after[-1] == actual
            after_references = observation['after_references'] = [reference('after-peer-reference', identity) for identity in peers]
            assert after_references == old_references
            assert exact('after-owner', owner) == before_owner and exact('after-target', target) == before_target
            observation['append_business_effect_verified'] = True
            replacement_before = observation['replacement_before'] = read('before-replacement',
                ['--advanced-waql', f'from object "{owner}" select @Playlist'])
            assert replacement_before == after
            replacement_receipt = construct(behavior='replace-all')
            replaced, = replacement_receipt['verify']['agent_result']['business_result']['created_objects']
            replacement_id = replaced['object']['id']
            removed_ids = [row['id'] for row in replacement_before]
            assert UUID(replacement_id).int != 0 and replacement_id not in {*removed_ids, owner, target}
            replacement = exact('replacement-slot', replacement_id)
            observation['replacement_created'] = replacement
            assert replacement['name'] == '' and replacement['type'] == 'PluginInnerObject' and replacement['class_id'] == 5636096
            assert replacement['owner']['id'] == owner and 'parent' not in replacement
            assert reference('replacement-reference', replacement_id) == before_target
            replacement_members = observation['replacement_members'] = read('after-replacement',
                ['--advanced-waql', f'from object "{owner}" select @Playlist'])
            assert replacement_members == [replacement]
            for removed in removed_ids:
                absent(removed)
            observation['removed_member_ids'] = removed_ids
            assert exact('replacement-owner', owner) == before_owner and exact('replacement-target', target) == before_target
            observation['replacement_business_effect_verified'] = True
        root_create_before = observation['root_create_before'] = read('before-root-create',
            ['--advanced-waql', f'from object "{owner}" select @Playlist'])
        assert root_create_before == (before if root_create_only else replacement_members)
        root_receipt = construct(operation='object.create')
        root_result = root_receipt['verify']['agent_result']['business_result']
        assert root_result['identity_status'] == 'verified_owned_list_member' and root_result['verified_root'] is None
        assert root_result['configuration_operations'] == ['object.setReference', 'object.setNotes']
        root_member, = root_result['created_objects']
        root_id = root_member['object']['id']
        assert UUID(root_id).int != 0 and root_id not in {*peers, *[row['id'] for row in root_create_before], owner, target}
        root_created = exact('root-created-slot', root_id)
        observation['root_created'] = root_created
        assert root_created['name'] == '' and root_created['type'] == 'PluginInnerObject' and root_created['class_id'] == 5636096
        assert root_created['owner']['id'] == owner and 'parent' not in root_created
        assert reference('root-created-reference', root_id) == before_target
        root_members = observation['root_members'] = read('after-root-create',
            ['--advanced-waql', f'from object "{owner}" select @Playlist'])
        assert root_members == [*root_create_before, root_created]
        retained_references = observation['root_peer_references'] = [reference('retained-peer-reference', row['id']) for row in root_create_before]
        assert retained_references == (old_references if root_create_only else [before_target])
        assert exact('root-create-owner', owner) == before_owner and exact('root-create-target', target) == before_target
        observation['root_create_business_effect_verified'] = True
        observation['business_effect_verified'] = True
        status = 'PASS'
    except BaseException as exc:
        observation['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        body = json.dumps(observation, ensure_ascii=False, indent=2).encode('utf-8')
        assert len(body) <= 8 * 1024 * 1024
        output.write_bytes(body)
        category.update(status=status, business_effect_verified=observation['business_effect_verified'],
            observation_sha256=hashlib.sha256(body).hexdigest())

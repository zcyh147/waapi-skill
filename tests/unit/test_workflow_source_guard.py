from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support.sandbox_fixture import hash_project
from tests.destructive.support import exact_real_evidence
from tests.support.platform_filesystem import create_symlink_or_skip


@pytest.fixture
def workflow(monkeypatch):
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    return importlib.import_module("tests.destructive.test_gateway_workflow_transaction_matrix")


def _existing_bus_send_runtime(tmp_path, workflow, version, *, fault=None):
    """Actual Gateway parsing/dispatch; fake native state honors each exact request."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_existing_bus_override_applicability_gateway import existing_task
    from tests.unit.test_object_graph_owned_choices_gateway import CHILD

    task, _mutations = existing_task(tmp_path, version=version,
        operation='object.create' if version == '2021.1' else 'object.set')
    parent = deepcopy(task.objects[CHILD])
    parent['path'] = ('\\Busses' if version == '2025.1' else '\\Master-Mixer Hierarchy') + '\\Default Work Unit'
    parent['parent'] = None
    task.objects = {CHILD: parent}
    original = task.call
    writes, commands = [], []
    independent_read = False
    ids = {name: '{' + str(uuid.UUID(int=index)).upper() + '}' for index, name in enumerate(
        ('WAAPI_EXISTING_SEND_TEST', 'Destination', 'Sender', 'BatchSender'), 11)}

    def call(uri, args=None, options=None):
        if uri.endswith(('object.create', 'object.set', 'setReference', 'setProperty')):
            writes.append((uri, deepcopy(args)))
            if len(writes) > 1 and fault == 'native-error':
                raise RuntimeError('Existing-source write refused; never retry')
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args == {'parent': CHILD, 'type': 'Bus', 'name': 'WAAPI_EXISTING_SEND_TEST',
                'notes': 'Keep routing', 'children': [
                    {'type': 'AuxBus', 'name': name, 'notes': 'Keep ' + name}
                    for name in ('Destination', 'Sender', 'BatchSender')],
                'onNameConflict': 'fail', 'autoAddToSourceControl': False}, args
            def create(node, owner):
                identity = ids[node['name']]
                task.objects[identity] = {'id': identity, 'name': node['name'], 'type': node['type'],
                    'classId': 1376272 if node['type'] == 'Bus' else 3997712,
                    'path': task.objects[owner]['path'] + '\\' + node['name'], 'parent': {'id': owner},
                    'notes': node['notes'], '@UserAuxSend0': None, '@UserAuxSendVolume0': 0}
                return {'id': identity, 'name': node['name'],
                    'children': [create(child, identity) for child in node.get('children', [])]}
            return create(args, CHILD)
        if uri.endswith('object.get') and args.get('waql', '').startswith('from object "'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            identity = args['waql'].split('"')[1]
            rows = [row for row in task.objects.values() if identity in {row['id'], row['path']}]
            projected = [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]
            if independent_read and len(writes) > 1 and fault == 'independent-guid':
                for row in projected:
                    if row.get('id') == ids['Sender'] and 'UserAuxSend0' in row:
                        row['UserAuxSend0'] = {'id': ids['WAAPI_EXISTING_SEND_TEST']}
            if independent_read and len(writes) == 3 and fault == 'independent-value':
                for row in projected:
                    if row.get('id') == ids['Sender'] and '@UserAuxSendVolume0' in row:
                        row['@UserAuxSendVolume0'] = -4
            return {'return': projected}
        result = original(uri, args, options)
        if len(writes) > 1 and uri.endswith(('object.set', 'setReference', 'setProperty')):
            source = task.objects[args['objects'][0]['object'] if 'objects' in args else args['object']]
            if fault == 'wrong-guid': source['@UserAuxSend0'] = {'id': ids['WAAPI_EXISTING_SEND_TEST']}
            if fault == 'wrong-value': source['@UserAuxSendVolume0'] = -1
            if fault == 'notes': source['notes'] = 'Not requested'
            if fault == 'parent': source['parent'] = {'id': CHILD}
            if fault == 'batch-wrong-guid' and len(writes) == 4:
                source['@UserAuxSend0'] = {'id': ids['Sender']}
            if fault == 'scalar-effect' and len(writes) == 3:
                source['@UserAuxSendVolume0'] = -4
        return result

    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='fixture-candidate', category_results=[])
    def raw(command):
        nonlocal independent_read
        commands.append(list(command))
        independent_read = command[0] == 'query-object'
        return workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


@pytest.mark.parametrize('version', ['2022.1', '2023.1', '2024.1', '2025.1'])
def test_existing_bus_send_acceptance_uses_three_exact_public_mutations(tmp_path, workflow, version):
    runtime, commands, writes, task = _existing_bus_send_runtime(tmp_path, workflow, version)
    category = workflow._collect_existing_bus_send_acceptance(runtime, root_name='WAAPI_EXISTING_SEND_TEST')
    assert category['status'] == 'PASS', category
    assert [uri.rsplit('.', 1)[1] for uri, _ in writes] == ['create', 'setReference', 'setProperty', 'set']
    assert [cmd[0] for cmd in commands].count('execute') == 4
    assert [cmd[0] for cmd in commands].count('verify') == 4
    assert 'OverrideUserAuxSends' not in json.dumps(writes)
    assert writes[1][1]['value'] == next(row['id'] for row in task.objects.values() if row['name'] == 'Destination')
    assert writes[2][1]['value'] == -9
    assert writes[3][1]['objects'][0]['@UserAuxSendVolume0'] == -12


@pytest.mark.parametrize('fault', ['wrong-guid', 'wrong-value', 'notes', 'parent', 'independent-guid', 'batch-wrong-guid', 'native-error', 'scalar-effect', 'independent-value'])
def test_existing_bus_send_acceptance_rejects_wrong_effect_and_never_retries(tmp_path, workflow, fault):
    runtime, commands, writes, _task = _existing_bus_send_runtime(tmp_path, workflow, '2025.1', fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_existing_bus_send_acceptance(runtime, root_name='WAAPI_EXISTING_SEND_TEST')
    receipt = json.loads((runtime.state_dir / 'existing-bus-send-acceptance.json').read_text())
    assert runtime.category_results[-1]['status'] == 'FAIL'
    assert receipt['business_effect_verified'] is False
    assert len(writes) == (4 if fault == 'batch-wrong-guid' else 3 if fault in {'scalar-effect', 'independent-value'} else 2)
    assert [cmd[0] for cmd in commands].count('execute') == len(writes)
    if fault == 'native-error':
        assert [cmd[0] for cmd in commands].count('verify') == 1
        assert receipt['transactions'][-1]['native_outcome'] == 'indeterminate'


def test_existing_bus_send_2021_retains_two_effects_and_pending_merge_wrapper(tmp_path, workflow):
    runtime, commands, writes, _task = _existing_bus_send_runtime(tmp_path, workflow, '2021.1')
    category = workflow._collect_existing_bus_send_acceptance(runtime, root_name='WAAPI_EXISTING_SEND_TEST')
    receipt = json.loads((runtime.state_dir / 'existing-bus-send-acceptance.json').read_text())
    assert category['status'] == 'incomplete'
    assert receipt['business_effect_verified'] is False
    assert [phase['effect_verified'] for phase in receipt['transactions']] == [True, True, True]
    assert receipt['remaining'][0]['phase'] == 'samebatch_reference_scalar'
    assert receipt['remaining'][0]['candidate'] == 'object.create/on_name_conflict=merge'
    assert [uri.rsplit('.', 1)[1] for uri, _ in writes] == ['create', 'setReference', 'setProperty']
    assert [cmd[0] for cmd in commands].count('execute') == 3


def test_existing_auxbus_2021_merge_requires_actual_source_dependency_binding(tmp_path):
    from tests.unit.test_existing_bus_override_applicability_gateway import existing_task, select_field
    from tests.unit.test_object_graph_owned_choices_gateway import FIRST, SECOND, ROOT
    task, writes = existing_task(tmp_path, version='2021.1', operation='object.create')
    source, parent, target = task.bind(FIRST), task.bind(SECOND), task.bind(ROOT)
    code, types = task.step('draft-discover-types', '--role', 'object', '--meaning', 'AuxBus')
    assert code == 0, types
    reference = select_field(task, owner=source, token='UserAuxSend0')
    scalar = select_field(task, owner=source, token='UserAuxSendVolume0')
    code, configured = task.step('draft-business-configure', '--name-conflict', 'merge')
    assert code == 0, configured
    code, declared = task.step('draft-declare-new', '--declaration-id', 'source', '--parent-handle', parent,
        '--name', 'Sender', '--kind', types['type_candidates'][0]['handle'],
        '--field-value', reference, target, '--field-value', scalar, '-12')
    assert code == 2 and declared['error_code'] == 'FIELD_HANDLE_SCOPE_MISMATCH', declared
    # Class discovery reaches the collision check. Current create-merge does
    # not pass its observed classId into that check; fixing this and replacing
    # prospective defaults with actual-source proof remains #180 work.
    reference = select_field(task, kind=types['type_candidates'][0]['handle'], token='UserAuxSend0')
    scalar = select_field(task, kind=types['type_candidates'][0]['handle'], token='UserAuxSendVolume0')
    code, declared = task.step('draft-declare-new', '--declaration-id', 'source', '--parent-handle', parent,
        '--name', 'Sender', '--kind', types['type_candidates'][0]['handle'],
        '--field-value', reference, target, '--field-value', scalar, '-12')
    assert code == 0, declared
    code, checked = task.step('draft-check')
    assert code == 2, checked
    assert checked['error_code'] == 'INVALID_TARGET_TYPE', checked
    assert checked['details']['expected'] == checked['details']['actual'] == 'AuxBus', checked
    assert not writes


def _new_result_reference_runtime(tmp_path, workflow, version, *, fault=None, noisy_fields=False, native_conditions=False):
    """The real public Gateway above an exact, independently mutated native tree."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask

    operation = "object.create" if version == "2021.1" else "object.set"
    task = OwnedGraphTask(tmp_path, version, operation)
    parent = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
    root, target, source = ("{" + str(uuid.UUID(int=value)) + "}" for value in (3, 5, 6))
    task.types = [{"name": name, "classId": value, "type": "WObject"} for name, value in (
        ("WorkUnit", 1638416), ("Bus", 1376272), ("AuxBus", 3997712))]
    parent_path = (r"\Busses\Default Work Unit" if version == "2025.1"
                   else r"\Master-Mixer Hierarchy\Default Work Unit")
    task.objects = {parent: {"id": parent, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
        "path": parent_path, "parent": None, "notes": "Keep parent"}}
    commands, writes = [], []
    independent_read = False
    original = task.call
    base = parent_path + r"\WAAPI_RESULT_REFERENCE_TEST"
    # Exact names from the owned 2025 receipt; target metadata below stays a unit fixture.
    task.reference_field_names = [
        'Attenuation', '3DPosition', '3DSpatialization', 'AttenuationDistanceScaling',
        'BusChannelConfig', 'BusVolume', 'BypassEffect', 'CenterPercentage',
        'Color', 'EnableAttenuation', 'EnableDiffraction', 'GameAuxSendHPF',
        'GameAuxSendDSF', 'GameAuxSendLPF', 'GameAuxSendVolume', 'Highpass',
        'HoldEmitterPositionOrientation', 'HoldListenerOrientation', 'ListenerRelativeRouting', 'Lowpass',
        'OutputBusHighpass', 'OutputBusDualshelf', 'OutputBusLowpass', 'OutputBusVolume',
        'OverrideColor', 'Pitch', 'ReflectionsVolume', 'SpeakerPanning',
        'SpeakerPanning3DSpatializationMix', 'UseGameAuxSends', 'UserAuxSendHPF0', 'UserAuxSendHPF1',
        'UserAuxSendHPF2', 'UserAuxSendHPF3', 'UserAuxSendLPF0', 'UserAuxSendLPF1',
        'UserAuxSendLPF2', 'UserAuxSendLPF3', 'UserAuxSendVolume0', 'UserAuxSendVolume1',
        'UserAuxSendVolume2', 'UserAuxSendVolume3', 'Volume', 'ReflectionsAuxSend',
        'UserAuxSend0', 'UserAuxSend1', 'UserAuxSend2', 'UserAuxSend3',
    ] if noisy_fields else ["UserAuxSend0"]

    def call(uri, args=None, options=None):
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args.get("classId") == 3997712 or args.get("object") == source, args
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": task.reference_field_names}
            if args["property"].startswith(("UserAuxSendHPF", "UserAuxSendLPF")):
                name = args["property"]
                band, index = ("HPF" if "HPF" in name else "LPF"), name[-1]
                return {"name": name, "type": "int16", "default": 0,
                    "display": {"name": "User-Defined Auxiliary " + band + " " + index},
                    "restriction": {"type": "range", "min": 0, "max": 100},
                    "dependencies": [{"action": "Show", "context": "Self", "type": "isMasterBus", "value": False},
                        {"action": "Enable", "context": "Self", "property": "OverrideUserAuxSends", "type": "override"}]}
            if native_conditions and args["property"] == "OverrideUserAuxSends":
                raise RuntimeError("Literal native 553: controller property does not exist on AuxBus")
            assert args["property"] == "UserAuxSend0", args
            if native_conditions:
                # Literal relevant 2025 native shape; older program lanes use their XML group grammar, not claimed native observations.
                return {"name": "UserAuxSend0", "type": "", "default": None,
                    "supports": {"unlink": False, "randomizer": False, "rtpc": "None"},
                    "display": {"name": "User-Defined Auxiliary Send 0"},
                    "restriction": {"type": "reference", "restrictions": [{"type": ["Auxiliary Bus"], "sharedOnlyTypes": []}]},
                    "dependencies": ([{"type": "isMasterBus", "value": False, "action": "Show", "context": "Self"}]
                        if version in {"2024.1", "2025.1"} else []) + [
                        {"type": "override", "action": "Enable", "context": "Self", "property": "OverrideUserAuxSends"}]}
            return {"name": "UserAuxSend0", "type": "Reference", "display": {"name": "User-Defined Auxiliary Send 0"},
                "restriction": {"type": "reference", "restrictions": [{"type": ["AuxBus"]}]}}
        if uri in {"ak.wwise.core.object.create", "ak.wwise.core.object.set"}:
            writes.append((uri, deepcopy(args), deepcopy(options)))
            children = [{"type": "AuxBus", "name": "Destination"},
                {"type": "AuxBus", "name": "Sender", "@UserAuxSend0": base + r"\Destination"}]
            if operation == "object.create":
                assert args == {"parent": parent, "type": "Bus", "name": "WAAPI_RESULT_REFERENCE_TEST",
                    "children": children, "onNameConflict": "fail", "autoAddToSourceControl": False}
            else:
                assert args == {"objects": [{"object": parent, "children": [{"type": "Bus",
                    "name": "WAAPI_RESULT_REFERENCE_TEST", "children": children}]}], "onNameConflict": "fail",
                    "autoAddToSourceControl": False, "listMode": "append"}
            if fault == "native-error":
                raise RuntimeError("Frozen native graph rejection; never replay")
            task.objects[root] = {"id": root, "name": "WAAPI_RESULT_REFERENCE_TEST", "type": "Bus", "classId": 1376272,
                "path": base, "parent": {"id": parent}, "notes": ""}
            for identity, name in ((target, "Destination"), (source, "Sender")):
                task.objects[identity] = {"id": identity, "name": name, "type": "AuxBus", "classId": 3997712,
                    "path": base + "\\" + name, "parent": {"id": root}, "notes": ""}
            task.objects[source]["@UserAuxSend0"] = {"id": root if fault == "wrong-guid" else target}
            if native_conditions:
                if fault == "wrong-parent-effect":
                    task.objects[source]["parent"] = {"id": parent}
            result = {"id": root, "name": "WAAPI_RESULT_REFERENCE_TEST", "children": [
                {"id": target, "name": "Destination"}, {"id": source, "name": "Sender"}]}
            return result if operation == "object.create" else {"objects": [{"id": parent, "name": "Default Work Unit", "children": [result]}]}
        if uri.endswith("object.get") and args.get("waql", "").startswith('from object "') and not args["waql"].endswith(" take 1"):
            expression = args["waql"]
            identity = expression.split('"')[1]
            assert expression == f'from object "{identity}"', expression
            result = {"return": [deepcopy(row) for row in task.objects.values() if identity in {row["id"], row["path"]}]}
        else:
            result = original(uri, args, options)
        if uri.endswith("object.get") and args.get("waql") != "from type Project take 1":
            # Honor the literal native return projection, including reference spelling.
            rows = []
            for row in result["return"]:
                projected = {key: deepcopy(row.get(key, row.get("@" + key))) for key in options["return"]
                    if key in row or "@" + key in row}
                if independent_read and fault == "independent-path" and row["id"] == target:
                    projected["path"] = base + r"\NotRequested"
                if independent_read and fault == "independent-guid" and row["id"] == source and "UserAuxSend0" in projected:
                    projected["UserAuxSend0"] = {"id": root}
                if independent_read and fault == "independent-class" and row["id"] == target and "classId" in projected:
                    projected["classId"] = True
                if independent_read and fault == "independent-parent" and row["id"] == target and "parent" in projected:
                    projected["parent"] = {"id": parent}
                rows.append(projected)
            return {"return": rows}
        return result

    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / "state", env=task.env,
        candidate="fixture-candidate", category_results=[])
    def raw(command):
        nonlocal independent_read
        commands.append(list(command))
        independent_read = command[0] == "query-object"
        return workflow.waapi_gateway.execute_gateway(["--state-dir", str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


def test_new_result_reference_exact_selection_and_native_condition_share_one_write(tmp_path, workflow):
    runtime, commands, writes, task = _new_result_reference_runtime(
        tmp_path, workflow, "2025.1", noisy_fields=True, native_conditions=True)
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "PASS", category
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    assert {args["property"] for uri, args, _ in task.calls if uri.endswith("getPropertyInfo")} == {
        "UserAuxSend0"}
    sender = writes[0][1]["objects"][0]["children"][0]["children"][1]
    assert "@OverrideUserAuxSends" not in sender
    assert sender["@UserAuxSend0"].endswith(r"\Destination")


def test_new_result_reference_acceptance_selects_exact_listed_reference_amid_native_neighbours(tmp_path, workflow):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", noisy_fields=True)
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "PASS", category
    assert len(writes) == 1
    discovery = [command for command in commands if command[0] == "draft-discover-fields"]
    assert "--list" in discovery[0] and "--selection" in discovery[1], discovery
    assert not any("--meaning" in command for command in discovery)
    assert {args["property"] for uri, args, _ in task.calls if uri.endswith("getPropertyInfo")} == {"UserAuxSend0"}
    exact_read = next(command for command in commands if command[0] == "query-object" and "--include-field" in command)
    assert exact_read[exact_read.index("--include-field") + 1] == "UserAuxSend0"


def test_new_result_reference_acceptance_copies_opaque_field_list_page(tmp_path, workflow):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", noisy_fields=True)
    # Synthetic preceding names force a second real Gateway page; their metadata is never requested.
    task.reference_field_names = [f"AA_Field{index:02}" for index in range(70)] + task.reference_field_names
    raw = runtime.raw_gateway
    pages = []

    def capture(command):
        code, payload = raw(command)
        if command[0] == "draft-discover-fields" and "--list" in command:
            pages.append(payload["agent_result"])
        return code, payload

    runtime.raw_gateway = capture
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "PASS" and len(writes) == 1, category
    listed_commands = [command for command in commands if command[0] == "draft-discover-fields" and "--list" in command]
    assert len(listed_commands) == len(pages) == 2
    assert pages[0]["complete"] is False and pages[1]["complete"] is True
    assert listed_commands[1][listed_commands[1].index("--page") + 1] == pages[0]["next_page"]
    assert {args["property"] for uri, args, _ in task.calls if uri.endswith("getPropertyInfo")} == {"UserAuxSend0"}


@pytest.mark.parametrize("fault", ("missing-target", "selection-drift"))
def test_new_result_reference_acceptance_rejects_unavailable_exact_selection_without_write(tmp_path, workflow, fault):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", noisy_fields=True)
    raw = runtime.raw_gateway
    if fault == "missing-target":
        task.reference_field_names.remove("UserAuxSend0")

    def drift(command):
        if command[0] == "draft-discover-fields" and "--selection" in command:
            task.reference_field_names.remove("UserAuxSend0")
        return raw(command)

    runtime.raw_gateway = drift
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    category, = runtime.category_results
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "FAIL" and receipt["native_outcome"] == "not_executed", receipt
    assert receipt["business_effect_verified"] is False
    assert not writes and not any(command[0] == "execute" for command in commands)
    assert not any(uri.endswith("getPropertyInfo") for uri, _args, _options in task.calls)
    if fault == "selection-drift":
        assert receipt["calls"][-1]["exit_code"] != 0
        assert receipt["calls"][-1]["payload"]["error_code"] == "METADATA_SELECTION_SCOPE_CHANGED"


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_new_result_reference_acceptance_handles_native_non_master_bus_condition_in_same_write(tmp_path, workflow, version):
    runtime, commands, writes, _task = _new_result_reference_runtime(tmp_path, workflow, version, native_conditions=True)
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "PASS", category
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    tree = writes[0][1] if version == "2021.1" else writes[0][1]["objects"][0]["children"][0]
    sender = tree["children"][1]
    assert "@OverrideUserAuxSends" not in sender
    assert sender["@UserAuxSend0"].endswith(r"\Destination")


@pytest.mark.parametrize("fault", ("controller-appears-after-write", "wrong-guid", "wrong-source-class", "wrong-parent-class", "wrong-parent-effect"))
def test_new_result_native_condition_needs_controller_class_parent_and_reference_effect(tmp_path, workflow, fault):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", native_conditions=True, fault=fault)
    original = task.call
    def effect(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith("getPropertyAndReferenceNames") and fault == "controller-appears-after-write" and writes:
            result["return"].append("OverrideUserAuxSends")
        if uri.endswith("object.set"):
            rows = {row["name"]: row for row in task.objects.values()}
            if fault == "wrong-source-class":
                rows["Sender"]["classId"] = True
            if fault == "wrong-parent-class":
                rows["WAAPI_RESULT_REFERENCE_TEST"]["classId"] = 65552
        return result
    task.call = effect
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    receipt = json.loads(Path(runtime.category_results[0]["observation_path"]).read_text())
    assert receipt["gateway_verification"]["payload"].get("verified") is not True, receipt


@pytest.mark.parametrize("fault", ("value-true", "value-number", "action-enable", "context-parent", "extra-key", "controller-present"))
def test_new_result_native_condition_rejects_unproved_or_malformed_grammar_without_write(tmp_path, workflow, fault):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", native_conditions=True)
    original = task.call
    def metadata(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith("getPropertyInfo") and args["property"] == "UserAuxSend0":
            dependency = result["dependencies"][0]
            if fault == "value-true": dependency["value"] = True
            if fault == "value-number": dependency["value"] = 0
            if fault == "action-enable": dependency["action"] = "Enable"
            if fault == "context-parent": dependency["context"] = "Parent"
            if fault == "extra-key": dependency["property"] = "OverrideUserAuxSends"
        if uri.endswith("getPropertyAndReferenceNames") and fault == "controller-present":
            result["return"].append("OverrideUserAuxSends")
        return result
    task.call = metadata
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert not writes and not any(command[0] == "execute" for command in commands)


@pytest.mark.parametrize("fault", ("condition-drift", "controller-appears", "type-drift", "type-ambiguous"))
def test_new_result_native_condition_revalidates_metadata_and_types_before_only_write(tmp_path, workflow, fault):
    runtime, commands, writes, task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", native_conditions=True)
    raw, original = runtime.raw_gateway, task.call
    executing = False
    def metadata(uri, args=None, options=None):
        result = original(uri, args, options)
        if executing and uri.endswith("getPropertyInfo"):
            if args["property"] == "UserAuxSend0" and fault == "condition-drift": result["dependencies"][0]["value"] = True
        if executing and uri.endswith("getPropertyAndReferenceNames") and fault == "controller-appears":
            result["return"].append("OverrideUserAuxSends")
        return result
    def drift(command):
        nonlocal executing
        if command[0] == "execute":
            executing = True
            if fault == "type-drift":
                task.types[1]["classId"] = 65552
            if fault == "type-ambiguous":
                task.types.append({"name": "bus", "classId": 65552, "type": "WObject"})
        return raw(command)
    task.call, runtime.raw_gateway = metadata, drift
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    assert category["status"] == "FAIL" and not writes, category
    assert [command[0] for command in commands].count("execute") == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_new_result_reference_acceptance_uses_real_gateway_and_one_graph_write(tmp_path, workflow, version):
    runtime, commands, writes, _task = _new_result_reference_runtime(tmp_path, workflow, version)
    workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    category, = runtime.category_results
    assert category["status"] == "PASS", category
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert receipt["native_outcome"] == "accepted" and receipt["reference_effect"] == "proven", receipt
    assert receipt["independent_source"]["references"]["UserAuxSend0"]["id"] == receipt["independent_target"]["id"]
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    assert writes[0][0] == "ak.wwise.core.object." + ("create" if version == "2021.1" else "set")
    declaration = next(command for command in commands if command[0] == "draft-declare-new" and "source" in command)
    assert declaration[declaration.index("--field-value") + 1].startswith("bfh1-")
    assert declaration[declaration.index("--field-value") + 2].startswith("bnh1-")
    assert any(command[:1] == ["query-object"] and "--include-field" in command for command in commands)
    assert not any(flag in command for command in commands for flag in ("--advanced-waql", "--args", "--request-file"))


@pytest.mark.parametrize("version,fault", (("2021.1", "wrong-guid"), ("2025.1", "wrong-guid"),
    ("2021.1", "independent-path"), ("2025.1", "independent-guid"),
    ("2025.1", "independent-class"), ("2025.1", "independent-parent")))
def test_new_result_reference_acceptance_rejects_wrong_effect_or_independent_drift(tmp_path, workflow, version, fault):
    runtime, commands, writes, _task = _new_result_reference_runtime(tmp_path, workflow, version, fault=fault)
    with pytest.raises(AssertionError):
        workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    category, = runtime.category_results
    assert category["status"] == "FAIL", category
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert receipt["native_outcome"] == "accepted" and receipt["reference_effect"] != "proven", receipt
    assert receipt["business_effect_verified"] is False
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    assert receipt["gateway_verification"]["payload"].get("verified") is (fault != "wrong-guid"), receipt
    if fault in {"wrong-guid", "independent-guid"}:
        assert receipt["independent_source"]["references"]["UserAuxSend0"]["id"] != receipt["independent_target"]["id"]


def test_new_result_reference_acceptance_retains_native_failure_without_retry(tmp_path, workflow):
    runtime, commands, writes, _task = _new_result_reference_runtime(tmp_path, workflow, "2025.1", fault="native-error")
    category = workflow._collect_new_result_scalar_reference_acceptance(runtime, root_name="WAAPI_RESULT_REFERENCE_TEST")
    receipt = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "FAIL" and receipt["native_outcome"] in {"rejected", "indeterminate"}, receipt
    assert receipt["reference_effect"] == "not_observed" and receipt["business_effect_verified"] is False
    assert "Frozen native graph rejection" in json.dumps(receipt["native_response"])
    assert len(writes) == 1 and [command[0] for command in commands].count("execute") == 1
    assert not any(command[0] in {"verify", "query-object"} for command in commands[commands.index(next(command for command in commands if command[0] == "execute")) + 1:])


@pytest.mark.parametrize("state", ("execution_failed", "indeterminate"))
def test_inline_wav_probe_keeps_terminal_receipt_without_retry(tmp_path, workflow, state):
    calls = []
    native_error = {"ok": False, "state": state, "dispatch_result": {
        "ok": False, "waapi_error_uri": "ak.wwise.invalid_arguments",
        "waapi_error_details": {"message": "exact original native error"},
    }, "error": {
        "code": "NATIVE_REJECTION" if state == "execution_failed" else "TIMEOUT",
        "message": "original native diagnostic", "details": {"unmodified": [1, 2]},
    }}
    runtime = _inline_probe_runtime(tmp_path, workflow, calls, terminal=native_error)
    receipt = {"calls": [], "lifecycle_final_reference": {"transaction_id": None, "phase": "final"}}
    workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    retained = json.loads((tmp_path / "inline-wav-probe.json").read_text())
    assert retained["calls"][-1]["payload"] == native_error
    assert retained["native_outcome"] == ("rejected" if state == "execution_failed" else "indeterminate")
    assert retained["media_effect"] == "not_observed"
    assert retained["gateway_terminal_state"] == state
    assert retained["native_response"] == native_error["dispatch_result"]
    assert retained["lifecycle_final_reference"] == {"transaction_id": "transaction", "phase": "final"}
    assert [command[0] for command in calls].count("execute") == 1
    assert not any(command[0] in {"verify", "query-object"} for command in calls[calls.index(["execute", "transaction"]) + 1:])
    media = next(command for command in calls if command[0] == "draft-add-media")
    assert media[media.index("--inline-wav") + 1] == (
        "InlineProbe.wav|UklGRigAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAAAA"
    )
    assert retained["compiled_native_request"]["args"]["objects"][0]["children"][0]["import"]["files"][0]["audioFileBase64"] == media[media.index("--inline-wav") + 1]


def _inline_probe_runtime(tmp_path, workflow, calls, *, terminal=None, corrupt=False):
    parent = "{11111111-1111-1111-1111-111111111111}"
    sound = "{22222222-2222-2222-2222-222222222222}"
    source = "{33333333-3333-3333-3333-333333333333}"
    project = tmp_path / "sandbox"
    original = project / "Originals" / "SFX" / "InlineProbe.wav"
    original.parent.mkdir(parents=True)
    native = {"uri": "ak.wwise.core.object.set", "args": {"objects": [{"children": [{"import": {"files": [{
        "audioFileBase64": "InlineProbe.wav|UklGRigAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAAAA",
    }]}}]}]}, "options": {}}
    revision = 0
    executed = False

    def raw(command):
        nonlocal revision, executed
        calls.append(list(command))
        kind = command[0]
        revision += 1
        payload = {"ok": True, "draft": {"draft_id": "draft", "revision": revision},
                   "task_authority": "authority"}
        if kind == "draft-bind-object":
            payload["bound_object"] = {"handle": "parent-handle"}
        elif kind == "preview-from-draft":
            payload.update(transaction_id="transaction", artifact_hash="a" * 64)
        elif kind == "transaction-show":
            payload.update(artifact={"prepared_operation": {"dispatch": native}},
                           confirmation={"token": "confirmation"})
        elif kind == "execute":
            executed = True
            original.write_bytes(bytes.fromhex(
                "524946462800000057415645666d7420100000000100010044ac00008858010002001000646174610400000000000000"
            ) if not corrupt else b"wrong media")
            return (1, terminal) if terminal else (0, {"ok": True, "state": "executed_unverified", "dispatch_result": {"ok": True, "result": {"objects": [{"id": sound}]}}})
        elif kind == "verify":
            payload = {"ok": True, "state": "verified", "verification": {"business_state_verified": True}}
        elif kind == "query-object":
            if "--relationship" in command:
                rows = [] if not executed else ([{"id": sound, "name": "InlineProbe", "type": "Sound", "path": r"\Containers\Default Work Unit\Probe\InlineProbe"}]
                        if command[command.index("--exact-id") + 1] == parent else
                        [{"id": source, "type": "AudioFileSource"}])
            elif command[command.index("--exact-id") + 1] == sound:
                rows = [{"id": sound, "name": "InlineProbe", "type": "Sound", "path": r"\Containers\Default Work Unit\Probe\InlineProbe", "active_source": {"id": source}}]
            else:
                rows = [{"id": source, "name": "InlineProbe", "type": "AudioFileSource", "path": r"\Containers\Default Work Unit\Probe\InlineProbe\InlineProbe", "parent": {"id": sound}, "original_file_path": str(original), "source_language": {"id": "{44444444-4444-4444-4444-444444444444}", "name": "SFX"}}]
            payload = {"ok": True, "count": len(rows), "objects": rows}
        return 0, payload

    return SimpleNamespace(raw_gateway=raw, state_dir=tmp_path / "state", version="2025.1",
                           sandbox=SimpleNamespace(sandbox_path=project))


@pytest.mark.parametrize("corrupt", (False, True), ids=("exact-original", "corrupt-original"))
def test_inline_wav_probe_requires_linked_exact_original_media(tmp_path, workflow, corrupt):
    calls = []
    runtime = _inline_probe_runtime(tmp_path, workflow, calls, corrupt=corrupt)
    receipt = {"calls": []}
    if corrupt:
        with pytest.raises(AssertionError):
            workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    else:
        workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    retained = json.loads((tmp_path / "inline-wav-probe.json").read_text())
    assert retained["native_outcome"] == "accepted"
    assert retained["media_effect"] == ("incomplete" if corrupt else "proven")
    assert [command[0] for command in calls].count("execute") == 1
    if not corrupt:
        assert retained["original_wav"]["sha256"] == "0588c6a627c6603830a9e5d87ab258d4977c02876b9bac8f9598fccef098c1cf"
        assert retained["original_wav"]["pcm"] == {"channels": 1, "sample_width_bytes": 2, "sample_rate_hz": 44100, "frame_count": 2}


@pytest.mark.parametrize("fault", ("wrong-source-parent", "converted-media", "read-error",
                                   "wrong-language", "malformed-language-id", "string-language"))
def test_inline_wav_probe_does_not_credit_unlinked_or_unreadable_media(tmp_path, workflow, fault):
    calls = []
    runtime = _inline_probe_runtime(tmp_path, workflow, calls)
    raw_gateway = runtime.raw_gateway

    def broken_read(command):
        code, payload = raw_gateway(command)
        if command[0] == "query-object" and "original-file-path" in command:
            if fault == "read-error":
                return 1, {"ok": False, "error_code": "READ_FAILED", "message": "retained read failure"}
            if fault == "wrong-source-parent":
                payload["objects"][0]["parent"]["id"] = "{99999999-9999-9999-9999-999999999999}"
            elif fault == "wrong-language":
                payload["objects"][0]["source_language"]["name"] = "English(US)"
            elif fault == "malformed-language-id":
                payload["objects"][0]["source_language"]["id"] = "not-a-guid"
            elif fault == "string-language":
                payload["objects"][0]["source_language"] = "SFX"
            else:
                payload["objects"][0]["original_file_path"] = str(tmp_path / "sandbox" / ".cache" / "InlineProbe.wav")
        return code, payload

    runtime.raw_gateway = broken_read
    receipt = {"calls": []}
    with pytest.raises((AssertionError, ValueError)):
        workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    retained = json.loads((tmp_path / "inline-wav-probe.json").read_text())
    assert retained["native_outcome"] == "accepted" and retained["media_effect"] == "incomplete"
    assert retained["diagnostic_error"]
    assert [command[0] for command in calls].count("execute") == 1
    if fault == "read-error":
        assert retained["calls"][-1]["payload"]["message"] == "retained read failure"


def test_inline_wav_probe_preserves_failed_gateway_verdict_beside_proven_effect(tmp_path, workflow):
    calls = []
    runtime = _inline_probe_runtime(tmp_path, workflow, calls)
    raw_gateway = runtime.raw_gateway
    failure = {"ok": False, "state": "verification_failed", "verification": {"business_state_verified": False}}

    def failed_verifier(command):
        code, payload = raw_gateway(command)
        return (2, failure) if command[0] == "verify" else (code, payload)

    runtime.raw_gateway = failed_verifier
    receipt = {"calls": []}
    workflow._run_inline_wav_probe(runtime, "{11111111-1111-1111-1111-111111111111}", "InlineProbe", receipt)
    retained = json.loads((tmp_path / "inline-wav-probe.json").read_text())
    assert retained["media_effect"] == "proven"
    assert retained["gateway_verification"] == {
        "exit_code": 2, "ok": False, "state": "verification_failed", "business_state_verified": False,
    }
    assert next(row["payload"] for row in retained["calls"] if row["argv"][0] == "verify") == failure
    assert [command[0] for command in calls].count("execute") == 1


def _source(root: Path) -> Path:
    root.mkdir()
    (root / "SampleProject.wproj").write_bytes(b"project")
    (root / "Music.wwu").write_bytes(b"workunit")
    media = root / "Originals" / "music.wav"
    media.parent.mkdir()
    media.write_bytes(b"original media")
    return media


def test_full_source_hash_detects_media_tamper_with_identical_size_and_mtime(tmp_path, workflow):
    root = tmp_path / "source"
    media = _source(root)
    before = workflow._hash_mutation_bearing_project_files(root)
    metadata_before = workflow._source_tree_inventory(root)
    info = media.stat()
    media.write_bytes(b"modified media")
    os.utime(media, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert media.stat().st_size == info.st_size
    assert workflow._source_tree_inventory(root) == metadata_before
    after = workflow._hash_mutation_bearing_project_files(root)
    assert before[1:] == after[1:]
    assert before[0] != after[0]


def test_full_source_hash_counts_all_files_and_matches_existing_full_digest(tmp_path, workflow):
    root = tmp_path / "source"
    _source(root)
    (root / "notes.txt").write_bytes(b"non-project content")
    expected = hash_project(root, preferred_strategy="full")
    observed = workflow._hash_mutation_bearing_project_files(root)
    assert observed == (expected.digest, 4, expected.bytes_hashed)
    assert workflow._hash_mutation_bearing_project_files(root) == observed


@pytest.mark.parametrize("target_is_directory", (False, True))
def test_full_source_hash_rejects_links_before_reading_content(tmp_path, workflow, monkeypatch, target_is_directory):
    root = tmp_path / "source"
    _source(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside if target_is_directory else outside / "media.wav"
    if not target_is_directory:
        target.write_bytes(b"outside")
    create_symlink_or_skip(root / "link", target, target_is_directory=target_is_directory)
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: pytest.fail("link must stop before content reads"))
    with pytest.raises(workflow.SandboxFixtureError, match="link|reparse"):
        workflow._hash_mutation_bearing_project_files(root)


@pytest.mark.parametrize("bound", ("SOURCE_HASH_MAX_FILES", "SOURCE_HASH_MAX_BYTES"))
def test_full_source_hash_preflights_bounds_before_content_reads(tmp_path, workflow, monkeypatch, bound):
    root = tmp_path / "source"
    _source(root)
    monkeypatch.setattr(workflow, bound, 1, raising=False)
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: pytest.fail("bounds must stop before content reads"))
    with pytest.raises(workflow.SandboxFixtureError, match="bound"):
        workflow._hash_mutation_bearing_project_files(root)


def test_full_source_hash_rejects_linked_root(tmp_path, workflow):
    source = tmp_path / "source"
    _source(source)
    linked = tmp_path / "linked"
    create_symlink_or_skip(linked, source, target_is_directory=True)
    with pytest.raises(workflow.SandboxFixtureError, match="link|reparse"):
        workflow._hash_mutation_bearing_project_files(linked)


def test_full_source_hash_rejects_windows_reparse_metadata(tmp_path, workflow, monkeypatch):
    source = tmp_path / "source"
    _source(source)
    lstat = Path.lstat

    def marked_root(path, *args, **kwargs):
        info = lstat(path, *args, **kwargs)
        return (SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
                if path == source else info)

    monkeypatch.setattr(Path, "lstat", marked_root)
    with pytest.raises(workflow.SandboxFixtureError, match="reparse"):
        workflow._hash_mutation_bearing_project_files(source)


def _fixture_run(tmp_path, workflow, monkeypatch, *, tamper_on_shutdown=False):
    source = tmp_path / "source"
    media = _source(source)
    events, records = [], []
    lock_root = tmp_path / "sandboxes"
    lock_root.mkdir()
    task_root = tmp_path / "task"
    task_root.mkdir()

    class Lock:
        def __init__(self, root):
            self.root = root

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            events.append("release")

    def prepare(_env, *, sandbox_root, hash_strategy):
        assert hash_strategy == "bounded"  # Copy audit is separate from the full guard.
        copied = sandbox_root / "copy"
        copied.mkdir(parents=True)
        project = copied / "SampleProject.wproj"
        project.write_bytes(b"project")
        return SimpleNamespace(
            source_root=source, source_project=source / "SampleProject.wproj",
            sandbox_path=copied, sandbox_root=sandbox_root, sandbox_project=project,
            env={}, metadata=SimpleNamespace(
                selected_port=7312, launch_project_path=str(project),
                get_info_display_name="WwiseConsole", get_info_version="2023.1",
                process_cleanup_result="cleaned", process_cleanup_details={"residual_processes": []},
            ),
        )

    def launch(*_args, **_kwargs):
        events.append("launch")
        return SimpleNamespace(host="127.0.0.1", port=7312)

    def shutdown(*_args):
        events.append("shutdown")
        if tamper_on_shutdown:
            info = media.stat()
            media.write_bytes(b"modified media")
            os.utime(media, ns=(info.st_atime_ns, info.st_mtime_ns))

    def append(**record):
        events.append("record:" + record["invocation"]["phase"])
        records.append(record)

    def quarantine(sandbox, **_kwargs):
        destination = tmp_path / "quarantine"
        sandbox.sandbox_path.rename(destination)
        return destination

    monkeypatch.setenv("WWISE_VERSION", "2023.1")
    monkeypatch.setattr(workflow, "_safe_lock_root", lambda _env: lock_root)
    monkeypatch.setattr(workflow, "LiveSandboxLock", Lock)
    monkeypatch.setattr(workflow, "exact_git_candidate", lambda _root: "a" * 40)
    monkeypatch.setattr(workflow, "prepare_sample_project_sandbox", prepare)
    monkeypatch.setattr(workflow, "launch_sandboxed_wwise", launch)
    monkeypatch.setattr(workflow, "shutdown_sandboxed_wwise", shutdown)
    monkeypatch.setattr(exact_real_evidence, "exact_transaction_outcomes", lambda _path: [])
    monkeypatch.setattr(exact_real_evidence, "cleanup_sandbox", quarantine)
    monkeypatch.setattr(exact_real_evidence, "append_category_evidence", append)
    item = SimpleNamespace(
        path=workflow.__file__, nodeid="tests/native.py::test_source",
        _waapi_phase_reports={"setup": "passed", "call": "passed"},
    )
    request = SimpleNamespace(module=workflow, session=SimpleNamespace(items=[item]))
    factory = SimpleNamespace(mktemp=lambda _name: task_root)
    return workflow.workflow_sandbox_runtime.__wrapped__(request, factory), events, records


@pytest.mark.parametrize("tamper", (False, True))
def test_source_full_guard_runs_after_shutdown_and_before_final_pass(tmp_path, workflow, monkeypatch, tamper):
    fixture, events, records = _fixture_run(
        tmp_path, workflow, monkeypatch, tamper_on_shutdown=tamper,
    )
    next(fixture)
    if tamper:
        with pytest.raises(AssertionError, match="source hash changed"):
            next(fixture)
    else:
        with pytest.raises(StopIteration):
            next(fixture)
    assert events.index("shutdown") < events.index("record:final")
    final = records[-1]
    assert final["invocation"]["outcome"] == ("FAIL" if tamper else "PASS")
    source = final["source"]
    assert source["hash_scope"] == "all-source-regular-file-content"
    assert source["hash_algorithm"] == "sha256"
    assert source["file_count_before"] == source["file_count_after"] == 3
    assert source["bytes_hashed_before"] == source["bytes_hashed_after"] == 29
    assert (source["hash_before"] == source["hash_after"]) is (not tamper)
    assert source["tree_metadata_before"] == source["tree_metadata_after"]


def test_source_hash_bound_stops_fixture_before_launch(tmp_path, workflow, monkeypatch):
    fixture, events, records = _fixture_run(tmp_path, workflow, monkeypatch)
    monkeypatch.setattr(workflow, "SOURCE_HASH_MAX_BYTES", 1)
    with pytest.raises(workflow.SandboxFixtureError, match="bound"):
        next(fixture)
    assert "launch" not in events
    assert "release" in events
    assert records == []


@pytest.mark.parametrize("after_read", (False, True))
def test_full_source_hash_rejects_changed_open_file_identity(
    tmp_path, workflow, monkeypatch, after_read,
):
    root = tmp_path / "source"
    _source(root)
    original_fstat = os.fstat
    calls = 0

    def switched_identity(descriptor):
        nonlocal calls
        calls += 1
        info = original_fstat(descriptor)
        fields = {name: getattr(info, name) for name in (
            "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns",
        )}
        if calls == (2 if after_read else 1):
            fields["st_ino"] += 1
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "fstat", switched_identity)
    with pytest.raises(workflow.SandboxFixtureError, match="changed.*hashing"):
        workflow._hash_mutation_bearing_project_files(root)


def _curve_probe_runtime(tmp_path, workflow, *, version="2025.1", curve_query_error=False,
                         repeat_names_page=False):
    import json
    import uuid

    state = tmp_path / "state"
    evidence = tmp_path / "dispatcher"
    evidence.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
                                  "waapi_port": 31337, "project_modification_policy": "read_only"}))
    commands = []
    owner = "{11111111-1111-1111-1111-111111111111}"
    curve = "{22222222-2222-2222-2222-222222222222}"

    def gateway(command):
        command = list(command)
        commands.append(command)
        assert command[0] in {"config-show", "status", "metadata", "query-object", "query-schema"}
        payload = {"ok": True, "fixture_only": True, "detected_version": version,
                   "endpoint": {"host": "127.0.0.1", "port": 31337, "url": "ws://127.0.0.1:31337/waapi"}}
        if command[:2] == ["metadata", "types"]:
            payload["agent_result"] = {"complete": True, "types": [
                {"name": "RTPC", "type": "WObject", "classId": 655360, "selection": "rtpc-type"},
                {"name": "Curve", "type": "WObject", "classId": 917520, "selection": "curve-type"},
            ]}
        elif command[:2] == ["metadata", "list"]:
            payload["agent_result"] = {"complete": not repeat_names_page, "fields": [
                {"name": "Curve", "selection": "selected-Curve"},
            ]}
            if repeat_names_page:
                payload["agent_result"]["next_command"] = {"gateway_argv": command + ["--page", "fixture-page"]}
        elif command[:2] == ["metadata", "detail"]:
            assert command[-2:] == ["--selection", "selected-Curve"]
            payload["agent_result"] = {"complete": True, "metadata": {
                # Preserve genuine omission of optional name/type in the result.
                "restriction": {"type": "reference", "restrictions": [{"type": ["Curve"]}]},
                "nativeOptionalNull": None,
            }}
        elif command[0] == "query-object":
            if "--advanced-waql" in command or "--exact-id" in command:
                if "--advanced-waql" in command:
                    assert command[2] == f'from object "{owner}" select @Curve'
                    assert command[command.index("--max-results") + 1] == "1"
                else:
                    assert command[2] == curve
                if curve_query_error:
                    return 2, {"ok": False, "error_code": "fixture-native-unavailable",
                               "native_observation": {"fixture_only": True}}
                payload["objects"] = [{"id": curve, "name": "", "type": "Curve", "path": "\\Curve",
                                       "class_id": 917520, "curve_points": [{"x": 0, "y": -6, "shape": "Linear"}]}]
            else:
                assert command == ["query-object", "--type-selection", "rtpc-type", "--max-results", "2"]
                payload["objects"] = [{"id": owner, "name": "", "type": "RTPC", "path": "\\RTPC"}]
        (evidence / (uuid.uuid4().hex + ".json")).write_text(json.dumps({"fixture_only": True,
                                            "command": command, "result": payload}))
        return 0, payload

    return SimpleNamespace(state_dir=state, env={"WWISE_EVIDENCE_DIR": str(evidence),
                          "WAAPI_SKILL_CONFIG_PATH": str(config)}, version=version,
                          candidate="a" * 40, lifecycle=SimpleNamespace(host="127.0.0.1", waapi_url="ws://127.0.0.1:31337/waapi"),
                          port=31337, category_results=[], raw_gateway=gateway), commands


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_curve_probe_retains_exact_read_only_observations_without_native_launch(
    tmp_path, workflow, version,
):
    import hashlib
    import json
    from wwise_waapi.object_query_outputs import available_query_outputs

    runtime, commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    # Collector fixture only; no real category publisher ran.
    assert category["status"] == ("blocked" if version == "2021.1" else "PASS")
    assert observed["candidate"] == "a" * 40 and observed["version"] == version
    assert ("curve-points" in available_query_outputs(version)) is (version != "2021.1")
    if version == "2021.1":
        assert "curve-points" not in commands[-1]
        assert any(row["reason"] == "curve_points_output_unavailable_in_public_version" for row in observed["boundaries"])
    assert observed["mutation_authority"] is False and observed["business_effect_verified"] is False
    details = [row for row in observed["calls"] if row["stage"].endswith("-detail")]
    assert len(details) == 2
    for row in details:
        metadata = row["payload"]["agent_result"]["metadata"]
        assert "name" not in metadata and "type" not in metadata
        assert metadata["nativeOptionalNull"] is None
    assert details[0]["gateway_argv"][2:4] == ["--type-selection", "rtpc-type"]
    assert details[1]["gateway_argv"][2:4] == ["--exact-id", "{11111111-1111-1111-1111-111111111111}"]
    assert len(observed["native_evidence"]) == len(commands)
    assert hashlib.sha256(Path(category["observation_path"]).read_bytes()).hexdigest() == category["observation_sha256"]
    assert all(Path(row["path"]).is_file() for row in observed["native_evidence"])


def test_curve_probe_records_failed_public_curve_read_as_boundary(tmp_path, workflow):
    import json
    runtime, _commands = _curve_probe_runtime(tmp_path, workflow, curve_query_error=True)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    assert any(row.get("error_code") == "fixture-native-unavailable" for row in observed["boundaries"])
    assert observed["calls"][-1]["payload"]["native_observation"] == {"fixture_only": True}


def test_curve_probe_stops_incomplete_name_paging_at_owned_bound(tmp_path, workflow):
    import json
    runtime, commands = _curve_probe_runtime(tmp_path, workflow, repeat_names_page=True)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    assert any(row["reason"] == "eight_page_bound_reached" for row in observed["boundaries"])
    assert len([command for command in commands if command[:2] == ["metadata", "list"]]) == 16
    assert not any(command[:2] == ["metadata", "detail"] for command in commands)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_curve_probe_reference_read_uses_existing_public_gateway_contract(tmp_path, workflow, version):
    from tests.unit.test_object_graph_business_gateway import _info

    runtime, _commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    calls = []
    owner = "{11111111-1111-1111-1111-111111111111}"
    curve = "{22222222-2222-2222-2222-222222222222}"

    class Client:
        def call(self, uri, args=None, options=None):
            calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            assert args == {"waql": f'from object "{owner}" select @Curve take 1'}
            assert options["return"] == ["id", "name", "type", "path", "classId", *(["points"] if version != "2021.1" else [])]
            return {"return": [{"id": curve, "name": "", "type": "Curve", "path": "\\Curve",
                                "classId": 917520, "points": [{"x": 0, "y": -6, "shape": "Linear"}]}]}

        def disconnect(self):
            pass

    code, payload = workflow.waapi_gateway.execute_gateway([
        "--state-dir", str(runtime.state_dir), "query-object", "--advanced-waql",
        f'from object "{owner}" select @Curve', "--max-results", "1", "--include", "class-id",
        *(["--include", "curve-points"] if version != "2021.1" else []),
    ], env=runtime.env, client_factory=lambda _url: Client())
    assert code == 0, payload
    assert payload["objects"][0]["id"] == curve and payload["objects"][0]["type"] == "Curve"
    if version != "2021.1":
        assert payload["objects"][0]["curve_points"] == [{"x": 0, "y": -6, "shape": "Linear"}]
    assert all(uri in {"ak.wwise.core.getInfo", "ak.wwise.core.object.get"} for uri, _args, _options in calls)


def _owned_probe_runtime(tmp_path, workflow, *, version="2025.1", missing_list=False, overflow=False):
    import json
    import uuid

    runtime, commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    ids = {name: "{" + str(uuid.UUID(int=index)) + "}" for index, name in enumerate(
        ("sound", "rtpc", "bus", "effect", "music", "group", "slot"), start=1)}
    def row(name, kind, owner=None):
        return {"id": ids[name], "name": name, "type": kind, "path": "\\" + name,
                "parent": None, "owner": {"id": ids[owner]} if owner else None, "class_id": 1234}
    sound, music = row("sound", "Sound"), row("music", "MusicSwitchContainer")
    rtpc, bus = row("rtpc", "RTPC", "sound"), row("bus", "Bus")
    effect = row("effect", "Effect" if version < "2023.1" else "EffectSlot", "sound")
    group, slot = row("group", "SwitchGroup"), row("slot", "MusicArgumentsSlot", "music")
    rows = {value["id"]: value for value in (sound, music, rtpc, bus, effect, group, slot)}
    effect_field = "Effect0" if version < "2023.1" else "Effects"
    hops = {(ids["sound"], "OutputBus"): [bus], (ids["sound"], "RTPC"): [rtpc],
            (ids["sound"], effect_field): [effect], (ids["music"], "Arguments"): [slot if version == "2025.1" else group],
            (ids["slot"], "Argument"): [group]}

    def gateway(command):
        command = list(command)
        commands.append(command)
        assert command[0] in {"config-show", "status", "metadata", "query-object", "query-schema"}
        payload = {"ok": True, "detected_version": version,
                   "endpoint": {"host": "127.0.0.1", "port": 31337, "url": "ws://127.0.0.1:31337/waapi"}}
        if command[:2] == ["metadata", "types"]:
            payload["agent_result"] = {"complete": True, "types": [
                {"name": kind, "selection": kind + "-type"} for kind in ("Sound", "MusicSwitchContainer", "RTPC")]}
        elif command[:2] == ["metadata", "list"]:
            fields = ["OutputBus", effect_field, *([] if missing_list else ["RTPC"])] if command[3] == ids["sound"] else (
                ["Arguments"] if command[3] == ids["music"] else ["Argument"])
            payload["agent_result"] = {"complete": True, "fields": [{"name": name, "selection": name + "-field"} for name in fields]}
        elif command[:2] == ["metadata", "detail"]:
            payload["agent_result"] = {"complete": True, "metadata": {"restriction": {"type": "reference"}, "fixtureOptional": None}}
        elif command[0] == "query-object":
            if "--exact-id" in command:
                found = [rows[command[command.index("--exact-id") + 1]]]
            elif "--type-selection" in command:
                found = [music if command[2] == "MusicSwitchContainer-type" else sound]
            else:
                expression = command[command.index("--advanced-waql") + 1]
                if expression.startswith("from type RTPC"):
                    found = [sound]
                elif expression.startswith("from project where owner.id"):
                    found = [rtpc, effect] if ids["sound"] in expression else ([slot] if version == "2025.1" else [])
                else:
                    owner = expression.split('"')[1]
                    field = expression.split("select @")[1]
                    found = hops[owner, field]
                    if overflow and field == "RTPC":
                        found = found * 5
            payload.update(objects=found, limit_reached=len(found) == int(command[command.index("--max-results") + 1])
                           if "--max-results" in command else False)
        path = Path(runtime.env["WWISE_EVIDENCE_DIR"]) / (uuid.uuid4().hex + ".json")
        path.write_text(json.dumps({"fixture_only": True, "command": command, "result": payload}))
        return 0, payload

    runtime.raw_gateway = gateway
    return runtime, commands, ids


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_owned_list_probe_retains_sample_only_graph_and_fresh_metadata(tmp_path, workflow, version):
    import json
    runtime, commands, ids = _owned_probe_runtime(tmp_path, workflow, version=version)
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "PASS", observed
    assert observed["complete_owned_list_discovery_proven"] is False
    assert observed["field_cardinality_permission_proven"] is False
    assert observed["mutation_authority"] is False
    assert observed["owner_comparisons"][0]["missing_known_owned_ids"] == []
    assert observed["native_evidence"] and observed["calls"]
    assert all("class-id" in command for command in commands if command[0] == "query-object")
    details = [call for call in observed["calls"] if call["gateway_argv"][:2] == ["metadata", "detail"]]
    assert "name" not in details[0]["payload"]["agent_result"]["metadata"]
    assert "type" not in details[0]["payload"]["agent_result"]["metadata"]
    assert all("Curve" not in " ".join(command) for command in commands)
    if version == "2025.1":
        assert any(f'from object "{ids["slot"]}" select @Argument' in command for command in commands)
    else:
        assert not any(part.endswith("select @Argument") for command in commands for part in command)


@pytest.mark.parametrize("fault", ("missing-list", "row-overflow", "metadata-error", "paging-overflow", "owner-filter"))
def test_owned_list_probe_keeps_incomplete_observation_blocked(tmp_path, workflow, fault):
    import json
    runtime, commands, ids = _owned_probe_runtime(tmp_path, workflow,
        missing_list=fault == "missing-list", overflow=fault == "row-overflow")
    original = runtime.raw_gateway

    def gateway(command):
        code, payload = original(command)
        if fault == "metadata-error" and list(command[:2]) == ["metadata", "detail"]:
            return 2, {"ok": False, "error_code": "fixture-metadata-rejected", "original_raw_error": {"fixture": None}}
        if fault == "paging-overflow" and list(command[:2]) == ["metadata", "list"]:
            payload["agent_result"].update(complete=False, next_command={"gateway_argv": list(command)})
        if fault == "owner-filter" and any(str(value).startswith("from project where owner.id") for value in command):
            payload["objects"][0]["owner"] = None
        return code, payload

    runtime.raw_gateway = gateway
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked", observed
    expected = {"missing-list": "field_not_uniquely_listed_gateway_discovery_boundary",
                "row-overflow": "query_row_bound_reached", "metadata-error": "public_read_rejected",
                "paging-overflow": "metadata_page_bound_reached", "owner-filter": "owner_filter_readback_mismatch"}[fault]
    assert any(row["reason"] == expected for row in observed["boundaries"])
    assert len(commands) <= 96 and len(observed["calls"]) == len(commands)
    if fault == "missing-list":
        assert not any(command[-1] == "RTPC-field" for command in commands)
        assert any(f'from object "{ids["sound"]}" select @RTPC' in command for command in commands)
    if fault == "metadata-error":
        assert any(row["payload"].get("original_raw_error") == {"fixture": None} for row in observed["calls"])


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_owned_probe_reads_use_existing_public_gateway_with_owned_projection(tmp_path, workflow, version):
    from tests.unit.test_object_graph_business_gateway import _info

    runtime, _commands, ids = _owned_probe_runtime(tmp_path, workflow, version=version)
    effect = "Effect0" if version < "2023.1" else "Effects"
    expressions = ['from type RTPC select owner where type = "Sound"',
                   f'from object "{ids["sound"]}" select @RTPC',
                   f'from object "{ids["sound"]}" select @OutputBus',
                   f'from object "{ids["sound"]}" select @{effect}',
                   f'from project where owner.id = "{ids["sound"]}"']
    if version >= "2023.1":
        expressions.append(f'from object "{ids["music"]}" select @Arguments')
    if version == "2025.1":
        expressions.append(f'from object "{ids["slot"]}" select @Argument')
    observed = []

    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            observed.append(args["waql"])
            assert options["return"] == ["id", "name", "type", "path", "parent", "owner", "classId"]
            slot = version == "2025.1" and "select @Arguments" in args["waql"]
            return {"return": [{"id": ids["slot"] if slot else ids["rtpc"], "name": "",
                                "type": "PluginInnerObject" if slot else "RTPC", "path": "\\RTPC",
                                "parent": None, "owner": {"id": ids["sound"]},
                                "classId": 5832704 if slot else 1441808}]}

        def disconnect(self):
            pass

    for expression in expressions:
        code, payload = workflow.waapi_gateway.execute_gateway([
            "--state-dir", str(runtime.state_dir), "query-object", "--advanced-waql", expression,
            "--max-results", "5", "--include", "parent", "--include", "owner", "--include", "class-id"],
            env=runtime.env, client_factory=lambda _url: Client())
        assert code == 0, payload
        rows = payload.get("objects", payload.get("agent_result"))
        assert rows[0]["owner"]["id"] == ids["sound"] and rows[0]["parent"] is None
        slot = version == "2025.1" and "select @Arguments" in expression
        assert rows[0]["class_id"] == (5832704 if slot else 1441808)
        assert rows[0]["type"] == ("PluginInnerObject" if slot else "RTPC")
    assert observed == [expression + " take 5" for expression in expressions]


def _short_id_probe_runtime(tmp_path, *, version="2021.1", fault=None):
    state = tmp_path / "short-id-state"
    state.mkdir()
    config = tmp_path / "short-id-config.json"
    config.write_text(json.dumps({"project_modification_policy": "ask_before_changes"}))
    evidence_root = tmp_path / "short-id-dispatcher"
    evidence_root.mkdir()
    commands = []
    endpoint = {"host": "127.0.0.1", "port": 8080, "url": "ws://127.0.0.1:8080/waapi"}
    event = {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "name": "Play_Example",
             "type": "Event", "path": "\\Events\\Play_Example", "short_id": 123}
    dialogue = {"id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}", "name": "Dialogue_Example",
                "type": "DialogueEvent", "path": "\\Events\\Dialogue_Example", "short_id": 456}

    def gateway(command):
        command = list(command)
        commands.append(command)
        assert command[0] in {"status", "query-object"}, command
        payload = {"ok": True, "endpoint": endpoint, "detected_version": version}
        if command[0] == "query-object":
            selected = dialogue if "DialogueEvent" in command or "dialogue-event" in command else event
            if "--exact-id" in command:
                selected = dialogue if dialogue["id"] in command else event
            payload["agent_result"] = [dict(selected)]
            if "--short-id" in command:
                payload["source_resolution"] = {"complete": True, "candidate_count": 1}
        code = 0
        if fault == "missing-dialogue" and "DialogueEvent" in command:
            payload["agent_result"] = []
        if "--short-id" in command:
            if fault == "native-error":
                code, payload = 2, {"ok": False, "error_code": "native-fixture-rejection",
                                    "call": {"waapi_error_uri": "ak.fixture.invalidQuery", "raw_error": {"fixture": None}}}
            if fault == "incomplete":
                payload["source_resolution"]["complete"] = False
        if fault == "exact-drift" and "--exact-id" in command:
            payload["agent_result"][0]["name"] = "Changed"
        if fault == "endpoint" and command == ["status"]:
            payload["endpoint"] = {**endpoint, "port": 9999}
        if fault == "version" and command == ["status"]:
            payload["detected_version"] = "2025.1"
        path = evidence_root / f"{len(commands)}.json"
        path.write_text(json.dumps({"fixture_only": True, "argv": command, "payload": payload}))
        return code, payload

    runtime = SimpleNamespace(version=version, candidate="a" * 40, state_dir=state,
        category_results=[], env={"WAAPI_SKILL_CONFIG_PATH": str(config),
                                  "WWISE_EVIDENCE_DIR": str(evidence_root)},
        lifecycle=SimpleNamespace(host=endpoint["host"], waapi_url=endpoint["url"]),
        port=endpoint["port"], raw_gateway=gateway)
    return runtime, commands, config


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_short_id_probe_reuses_shared_runtime_without_policy_change(tmp_path, workflow, version):
    import hashlib
    runtime, commands, config = _short_id_probe_runtime(tmp_path, version=version)
    config_before = config.read_bytes()
    workflow.test_read_only_short_id_native_observation(runtime)
    category, = runtime.category_results
    assert category["status"] == "PASS", category
    body = Path(category["observation_path"]).read_bytes()
    observed = json.loads(body)
    assert category["observation_sha256"] == hashlib.sha256(body).hexdigest()
    assert observed["candidate"] == runtime.candidate and observed["version"] == version
    assert observed["project_mutation_count"] == 0 and observed["mutation_authority"] is False
    assert observed["observations"] == [
        {"kind": "event", "short_id": 123, "canonical_id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
         "outcome": "NATIVE_SUCCESS", "candidate_count": 1},
        {"kind": "dialogue-event", "short_id": 456, "canonical_id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
         "outcome": "NATIVE_SUCCESS", "candidate_count": 1},
    ]
    assert len(commands) == len(observed["receipts"]) == len(observed["native_evidence"]) == 7
    assert config.read_bytes() == config_before
    assert all(command[0] in {"status", "query-object"} for command in commands)


@pytest.mark.parametrize("fault", ["missing-dialogue", "native-error", "incomplete", "exact-drift", "endpoint", "version"])
def test_short_id_shared_probe_retains_failure_without_retry(tmp_path, workflow, fault):
    runtime, commands, config = _short_id_probe_runtime(tmp_path, fault=fault)
    config_before = config.read_bytes()
    with pytest.raises(AssertionError):
        workflow.test_read_only_short_id_native_observation(runtime)
    category, = runtime.category_results
    assert category["status"] == "FAIL", category
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert observed["error"].startswith("AssertionError:")
    assert observed["business_effect_verified"] is False
    assert config.read_bytes() == config_before
    assert len(commands) == len(observed["receipts"]) == len(observed["native_evidence"])
    assert len(commands) <= 7 and commands.count(commands[-1]) == 1
    if fault == "native-error":
        receipt = observed["receipts"][-1]
        assert receipt["exit_code"] == 2
        assert receipt["payload"]["call"] == {
            "waapi_error_uri": "ak.fixture.invalidQuery", "raw_error": {"fixture": None}}
    if fault == "missing-dialogue":
        assert "DialogueEvent populated fixture prerequisite missing" in observed["error"]
        assert not any("dialogue-event" in command for command in commands)


def test_standalone_short_id_observation_keeps_lifecycle_and_original_evidence(tmp_path, monkeypatch):
    import tests.live.test_full_coverage_query_native as standalone

    fake, commands, _config = _short_id_probe_runtime(tmp_path)
    root = tmp_path / "standalone-native-root"
    finished = []
    bindings = []

    class Lifecycle:
        def __init__(self, **kwargs):
            bindings.append(kwargs)

        def start(self):
            root.mkdir()
            return SimpleNamespace(evidence_root=root, host="127.0.0.1", port=8080)

        def finish(self, status, *, reason):
            finished.append((status, reason))
            return SimpleNamespace(final_status=status, as_dict=lambda: {"status": status})

    def fixture_gateway(*, skill_source, runtime, version, receipts):
        assert version == "2021.1" and runtime.evidence_root == root
        assert skill_source.name == "waapi-skill"

        def gateway(command):
            if command[0] == "config-set":
                assert command[-2:] == ["--project-modification-policy", "read_only"]
                code, payload = 0, {"ok": True}
            else:
                code, payload = fake.raw_gateway(command)
            receipts.append({"argv": list(command), "exit_code": code, "payload": payload})
            assert code == 0 and payload["ok"] is True
            return payload

        return gateway

    monkeypatch.setenv("WAAPI_SHORT_ID_NATIVE_ROOT", str(root))
    monkeypatch.setenv("WWISE_VERSION", "2021.1")
    monkeypatch.setattr(standalone, "ScenarioLifecycle", Lifecycle)
    monkeypatch.setattr(standalone, "fixture_gateway", fixture_gateway)
    standalone.test_short_id_typed_native_read_observations()
    evidence = json.loads((root / "short-id-native-observations.json").read_text())
    assert set(evidence) == {"agent_started", "project_mutation_count", "version", "scope", "receipts", "observations", "status"}
    assert len(evidence["receipts"]) == 8 and len(commands) == 7
    assert [row["kind"] for row in evidence["observations"]] == ["event", "dialogue-event"]
    assert evidence["project_mutation_count"] == 0
    assert finished == [("PASS", "")]
    assert bindings[0]["scenario_id"] == "full-coverage-short-id-typed-observations"
    assert bindings[0]["scenario_root"] == root


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_short_id_collector_executes_all_commands_through_public_gateway(tmp_path, workflow, version):
    from tests.unit.test_object_graph_business_gateway import _info, _project

    runtime, commands, config = _short_id_probe_runtime(tmp_path, version=version)
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
        "waapi_port": 8080, "project_modification_policy": "ask_before_changes"}))
    rows = [
        {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}", "name": "Play_Example",
         "type": "Event", "path": "\\Events\\Play_Example", "shortId": 123},
        {"id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}", "name": "Dialogue_Example",
         "type": "DialogueEvent", "path": "\\Events\\Dialogue_Example", "shortId": 456},
    ]
    dispatches = []
    dialogue_literal = "456.0" if version in {"2021.1", "2022.1", "2023.1"} else "456"

    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.getProjectInfo":
                return _project(tmp_path)
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [{"classId": 100, "name": "Event", "type": "WObject"},
                                   {"classId": 101, "name": "DialogueEvent", "type": "WObject"}]}
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            if args == {"waql": "from type Project take 1"}:
                assert version == "2021.1"
                assert options == {"return": ["id", "name", "type", "path"]}
                return {"return": [{**_project(tmp_path), "type": "Project"}]}
            dispatches.append((args, options))
            if "waql" in args:
                expression = args["waql"]
                selected = rows[1] if "DialogueEvent" in expression or rows[1]["id"] in expression else rows[0]
                assert expression in {
                    "from type Event take 1", "from type DialogueEvent take 1",
                    "from type Event where shortId = 123.0 take 65",
                    f"from type DialogueEvent where shortId = {dialogue_literal} take 65",
                    *(f'from object "{row["id"]}"' + suffix for row in rows for suffix in ("", " take 64")),
                }, expression
            else:
                assert version != "2021.1"
                assert args == {"from": {"id": [{"shortId": 123, "type": 10}]},
                                "transform": [{"range": [0, 65]}]}, args
                selected = rows[0]
            source_lookup = "shortId =" in args.get("waql", "") or "from" in args
            expected_fields = ["id", "name", "type", "path"] + ([] if source_lookup else ["shortId"])
            assert options == {"return": expected_fields}, options
            return {"return": [{key: selected[key] for key in options["return"]}]}

        def disconnect(self):
            pass

    def gateway(command):
        commands.append(list(command))
        workflow.waapi_gateway.build_parser().parse_args(list(command))
        return workflow.waapi_gateway.execute_gateway(
            ["--state-dir", str(runtime.state_dir), *command], env=runtime.env,
            client_factory=lambda _url: Client())

    runtime.raw_gateway = gateway
    workflow.test_read_only_short_id_native_observation(runtime)
    category, = runtime.category_results
    evidence = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "PASS" and len(commands) == 7
    assert [row["short_id"] for row in evidence["observations"]] == [123, 456]
    assert [row["canonical_id"] for row in evidence["observations"]] == [row["id"] for row in rows]
    assert len(dispatches) == 8
    assert any(args == {"waql": f"from type DialogueEvent where shortId = {dialogue_literal} take 65"}
               for args, _options in dispatches)
    if version == "2021.1":
        assert any(args == {"waql": "from type Event where shortId = 123.0 take 65"}
                   for args, _options in dispatches)


@pytest.mark.parametrize(("projection", "fault"), [("full", None), ("compact", None),
    ("compact", "verification-digest"), ("compact", "assertion-count")])
def test_legacy_transaction_create_uses_public_draft_and_compact_verify_evidence(tmp_path, workflow, projection, fault):
    matrix = importlib.import_module("tests.destructive.test_gateway_transaction_matrix")
    from copy import deepcopy
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, ROOT
    from tests.unit.test_field_interface_closure_gateway import SECOND

    class Client(OwnedGraphTask):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getProjectInfo":
                # Existing large-project native response fixture forces the
                # real bounded stdout producer to compact verification evidence.
                response = super().call(uri, args, options)
                return ({**response, "directories": {"cache": "x" * 13_000}}
                        if projection == "compact" else response)
            if uri == "ak.wwise.core.object.create":
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                assert args["parent"] == SECOND
                assert args["type"] == "ActorMixer" and args["name"] == "LegacyProbe"
                assert args["notes"] == "Created once through public Draft"
                self.objects[ROOT] = {"id": ROOT, "name": "LegacyProbe", "type": "ActorMixer",
                    "path": self.objects[SECOND]["path"] + "\\LegacyProbe",
                    "parent": {"id": SECOND}, "notes": args["notes"]}
                return {"id": ROOT, "name": "LegacyProbe"}
            return super().call(uri, args, options)

    client = Client(tmp_path, "2023.1", "object.create")
    commands = []

    def gateway(command, *, live):
        commands.append(list(command))
        code, payload = matrix.waapi_gateway.execute_gateway(
            ["--state-dir", str(tmp_path / "state"), *command], env=client.env,
            client_factory=lambda _url: client)
        assert code == 0, payload
        if command[0] == "verify" and fault is not None:
            if fault == "verification-digest":
                payload["stdout_projection"]["verification_canonical_sha256"] = "0" * 64
            else:
                payload["verification"]["passed_assertion_count"] += 1
        return payload

    runtime = SimpleNamespace(version="2023.1", state_dir=tmp_path / "state", gateway=gateway)
    def complete():
        return matrix._complete_business_object_create(runtime,
            parent_segments=("Actor-Mixer Hierarchy", "Default Work Unit"),
            name="LegacyProbe", notes="Created once through public Draft")

    if fault is not None:
        with pytest.raises(AssertionError):
            complete()
    else:
        result = complete()
        assert result["verify"]["verified"] is True
        assert ("assertions" in result["verify"]["verification"]) is (projection == "full")
        assert result["verification_evidence"]["assertions"]
        assert all(item["passed"] is True for item in result["verification_evidence"]["assertions"])
    assert client.objects[ROOT]["parent"] == {"id": SECOND}
    assert len([uri for uri, _args, _options in client.calls if uri.endswith("object.create")]) == 1
    assert len([command for command in commands if command[0] == "execute"]) == 1


@pytest.mark.parametrize("version,number,signed", [
    (version, 3970659059, -324308237) for version in ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"]
] + [("2021.1", 0, 0), ("2021.1", 2147483648, -2147483648), ("2021.1", 4294967295, -1)])
@pytest.mark.parametrize("fault", [None, "native-error", "exact-drift"])
def test_short_id_diagnostic_uses_actual_gateway_and_retains_unsigned_miss(tmp_path, workflow, version, number, signed, fault):
    from tests.unit.test_object_graph_business_gateway import _info, _project

    runtime, commands, config = _short_id_probe_runtime(tmp_path, version=version)
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
        "waapi_port": 8080, "project_modification_policy": "ask_before_changes"}))
    before = config.read_bytes()
    row = {"id": "{3C874205-5335-4290-830F-A8BFF3AE8A6B}", "name": "Objective_Status",
        "type": "DialogueEvent", "path": "\\Dynamic Dialogue\\Dialogue\\Objective_Status", "shortId": number}
    dispatches = []
    expected = {
        "from type DialogueEvent take 1",
        f'from object "{row["id"]}"',
        f"from type DialogueEvent where shortId = {number} take 65",
        f'from object "{row["id"]}" where shortId = {number} take 65',
        f"from type DialogueEvent where shortId = {signed} take 65",
        f"from type DialogueEvent where shortId = {number}.0 take 65",
        f'from object "{row["id"]}" take 65',
    }

    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            if uri == "ak.wwise.core.getProjectInfo":
                return _project(tmp_path)
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [{"classId": 101, "name": "DialogueEvent", "type": "WObject"}]}
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            if args == {"waql": "from type Project take 1"}:
                assert version == "2021.1"
                return {"return": [{**_project(tmp_path), "type": "Project"}]}
            expression = args["waql"]
            assert expression in expected, expression
            dispatches.append((expression, options))
            if options == {"return": ["id", "name", "type", "path"]}:
                literal = f"{number}.0" if version in {"2021.1", "2022.1", "2023.1"} else str(number)
                assert expression == f"from type DialogueEvent where shortId = {literal} take 65"
                return {"return": []}  # Keep a baseline-miss control after the repair, too.
            if fault == "native-error" and f"{number}.0" in expression:
                raise RuntimeError("diagnostic decimal literal rejected")
            if f"shortId = {number} " in expression:
                return {"return": []}  # Trace-shaped baseline miss, not a native semantics claim.
            selected = dict(row)
            if fault == "exact-drift" and expression == f'from object "{row["id"]}"':
                selected["name"] = "Changed"
            assert options == {"return": ["id", "name", "type", "path", "shortId"]}, options
            return {"return": [selected]}

        def disconnect(self):
            pass

    def gateway(command):
        commands.append(list(command))
        workflow.waapi_gateway.build_parser().parse_args(list(command))
        return workflow.waapi_gateway.execute_gateway(["--state-dir", str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: Client())

    runtime.raw_gateway = gateway
    if fault == "exact-drift":
        with pytest.raises(AssertionError):
            workflow.test_read_only_short_id_native_diagnostic(runtime)
    else:
        workflow.test_read_only_short_id_native_diagnostic(runtime)
    category, = runtime.category_results
    evidence = json.loads(Path(category["observation_path"]).read_text())
    assert config.read_bytes() == before
    assert evidence["business_effect_verified"] is False and evidence["mutation_authority"] is False
    if fault == "exact-drift":
        assert category["status"] == "FAIL" and len(commands) == 3
        return
    assert category["status"] == "PASS"  # Diagnostic collection only, never resolver acceptance.
    assert evidence["baseline_contains_chosen_identity"] is False
    assert len(commands) == 10 and commands.count(["query-schema", "--advanced"]) == 1
    assert all(command[0] in {"status", "query-schema", "query-object"} for command in commands)
    baseline = next(receipt for receipt in evidence["receipts"] if "--short-id" in receipt["argv"])
    assert baseline["payload"]["source_resolution"]["short_id"] == number
    assert baseline["payload"]["agent_result"] == []
    assert len(evidence["variants"]) == 5
    assert {variant["name"] for variant in evidence["variants"]} == {
        "typed-unsigned", "guid-unsigned", "typed-signed32", "typed-decimal", "guid-no-predicate"}
    assert all(variant["hypothesis"] for variant in evidence["variants"])
    assert all(expression.endswith((" take 1", " take 65")) or expression == f'from object "{row["id"]}"'
               for expression, _ in dispatches)
    if fault == "native-error":
        failed = next(variant for variant in evidence["variants"] if variant["name"] == "typed-decimal")
        assert failed["status"] == "query_failed"
        receipt = next(receipt for receipt in evidence["receipts"] if f"{number}.0" in str(receipt["argv"]))
        assert receipt["exit_code"] == 2
        assert receipt["payload"]["call"]["error_code"] == "RuntimeError"


def _prospective_native_runtime(tmp_path, workflow, version, family, *, fault=None):
    from copy import deepcopy
    from tests.unit.test_new_object_conditions_gateway import (
        ProspectiveReferenceTask, HIERARCHY_GROUP, HIERARCHY_TARGET, CREATED,
    )
    from tests.unit.test_field_interface_closure_gateway import FIRST

    class Client(ProspectiveReferenceTask):
        def call(self, uri, args=None, options=None):
            if uri.endswith("object.get"):
                expression = args.get("waql", "")
                if expression == f"from type {family} take 1":
                    self.calls.append((uri, deepcopy(args), deepcopy(options)))
                    rows = [] if fault == "missing-target" else [self.objects[HIERARCHY_TARGET]]
                elif expression.startswith('from object "'):
                    self.calls.append((uri, deepcopy(args), deepcopy(options)))
                    identity = expression.split('"')[1]
                    if identity.startswith("\\"):
                        assert identity == self.objects[FIRST]["path"], expression
                        rows = [deepcopy(self.objects[FIRST])]
                    else:
                        rows = [deepcopy(self.objects[identity])]
                    if fault == "independent-reference" and rows[0]["id"] == CREATED:
                        rows[0]["DefaultSwitchOrState"] = HIERARCHY_GROUP
                else:
                    result = super().call(uri, args, options)
                    rows = result["return"]
                return {"return": [{key: deepcopy(row[key[1:] if key.startswith("@") else key])
                    for key in options["return"] if (key[1:] if key.startswith("@") else key) in row}
                    for row in rows]}
            result = super().call(uri, args, options)
            if fault == "ignored-default" and uri.endswith("object.create"):
                self.objects[CREATED]["DefaultSwitchOrState"] = None
            return result

    client = Client(tmp_path, version, state=family == "State")
    client.types += [{"classId": 10, "name": family, "type": "WObject"},
                     {"classId": 11, "name": family + "Group", "type": "WObject"}]
    client.objects[FIRST]["path"] = (workflow.CONTAINERS_PARENT if version == "2025.1"
                                      else workflow.ACTOR_MIXER_PARENT)
    client.calls.clear()
    evidence_root = tmp_path / "dispatcher"
    evidence_root.mkdir()
    runtime = SimpleNamespace(version=version, candidate="a" * 40, state_dir=tmp_path / "state",
        category_results=[], env={**client.env, "WWISE_EVIDENCE_DIR": str(evidence_root)},
        lifecycle=SimpleNamespace(host="127.0.0.1", waapi_url="ws://127.0.0.1:31337/waapi"),
        port=31337, sandbox=SimpleNamespace(metadata=SimpleNamespace(get_info_version={"fixture": version})))
    commands = []

    def gateway(command):
        commands.append(list(command))
        workflow.waapi_gateway.build_parser().parse_args(list(command))
        return workflow.waapi_gateway.execute_gateway(["--state-dir", str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: client)

    runtime.raw_gateway = gateway
    return runtime, client, commands


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("family", ("Switch", "State"))
def test_prospective_reference_native_collector_uses_public_gateway(tmp_path, workflow, version, family):
    from tests.unit.test_new_object_conditions_gateway import HIERARCHY_GROUP, HIERARCHY_TARGET, CREATED

    runtime, client, commands = _prospective_native_runtime(tmp_path, workflow, version, family)
    workflow.test_prospective_group_default_native_acceptance(runtime, family)
    category, = runtime.category_results
    evidence = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "PASS"
    assert evidence["independent_readback"]["id"] == CREATED
    assert evidence["selected_target"]["id"] == HIERARCHY_TARGET
    assert evidence["selected_group"]["id"] == HIERARCHY_GROUP
    assert evidence["source_rule"]["version"] == version
    assert len(evidence["source_rule"]["sha256"]) == 64
    writes = [(uri, args) for uri, args, _ in client.calls if uri.endswith(
        ("object.create", "object.set", "setReference", "setProperty"))]
    assert len(writes) == 1 and writes[0][0].endswith("object.create")
    assert writes[0][1]["@SwitchGroupOrStateGroup"] == HIERARCHY_GROUP
    assert writes[0][1]["@DefaultSwitchOrState"] == HIERARCHY_TARGET
    assert sum(command[0] == "execute" for command in commands) == 1
    assert any(command[:3] == ["query-object", "--custom-kind", family] for command in commands)
    independent = next(i for i, command in enumerate(commands) if command[:3] == ["query-object", "--exact-id", CREATED])
    assert independent > next(i for i, command in enumerate(commands) if command[0] == "verify")
    assert commands[independent].count("--include-field") == 2
    assert evidence["lifecycle_acceptance"].startswith("Requires the final")


@pytest.mark.parametrize("fault", ("missing-target", "ignored-default", "independent-reference"))
def test_prospective_reference_native_collector_retains_failure_without_retry(tmp_path, workflow, fault):
    runtime, client, commands = _prospective_native_runtime(tmp_path, workflow, "2025.1", "State", fault=fault)
    with pytest.raises(AssertionError):
        workflow.test_prospective_group_default_native_acceptance(runtime, "State")
    category, = runtime.category_results
    evidence = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "FAIL" and evidence["error"]
    expected_creates = 0 if fault == "missing-target" else 1
    assert sum(command[0] == "execute" for command in commands) == expected_creates
    assert sum(uri.endswith("object.create") for uri, _, _ in client.calls) == expected_creates
    if fault == "ignored-default":
        last = evidence["receipts"][-1]
        assert last["argv"][0] == "verify" and last["exit_code"] == 2
        assert last["payload"].get("verified") is not True
    elif fault == "independent-reference":
        assert any(row["argv"][0] == "verify" and row["payload"].get("state") == "verified"
                   for row in evidence["receipts"])
        assert evidence["receipts"][-1]["argv"][0] == "query-object"
    if expected_creates:
        assert evidence["lifecycle_final_reference"]["transaction_id"] == category["transaction_id"]
        assert category["transaction_id"]


def test_owned_list_probe_keeps_generic_member_type_and_exact_class_id_observation(tmp_path, workflow):
    runtime, commands, ids = _owned_probe_runtime(tmp_path, workflow)
    original = runtime.raw_gateway

    def gateway(command):
        code, payload = original(command)
        if command[0] == "query-object":
            for row in payload["objects"]:
                if row["id"] == ids["slot"]:
                    row.update(type="PluginInnerObject", class_id=5832704)
        return code, payload

    runtime.raw_gateway = gateway
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    members = next(row["members"] for row in observed["relationships"] if row["field"] == "Arguments")
    assert members[0]["type"] == "PluginInnerObject" and members[0]["class_id"] == 5832704
    assert any(row["reason"] == "Arguments_member_type_differs_from_matching_source" for row in observed["boundaries"])
    assert observed["complete_owned_list_discovery_proven"] is False
    assert observed["field_cardinality_permission_proven"] is False and observed["mutation_authority"] is False
    assert all("class-id" in command for command in commands if command[0] == "query-object")


@pytest.mark.parametrize("missing", ("owner", "class_id"))
def test_owned_probe_projection_preserves_missing_outputs_and_explicit_null(tmp_path, workflow, missing):
    runtime, _commands, ids = _owned_probe_runtime(tmp_path, workflow)
    original = runtime.raw_gateway

    def gateway(command):
        code, payload = original(command)
        if command[0] == "query-object":
            for row in payload["objects"]:
                if row["id"] == ids["slot"]:
                    row.pop(missing, None)
        return code, payload

    runtime.raw_gateway = gateway
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    members = next(row["members"] for row in observed["relationships"] if row["field"] == "Arguments")
    assert missing not in members[0] and members[0]["parent"] is None
    expected = "relationship_output_missing" if missing == "owner" else "class_id_output_missing"
    assert any(row["reason"] == expected for row in observed["boundaries"])


@pytest.mark.parametrize("version,migrated,wrong_open", [("2025.1", False, False), ("2023.1", True, False),
    ("2024.1", True, False), ("2025.1", True, False), ("2023.1", True, True)])
@pytest.mark.parametrize("wrong_media", [False, True])
def test_media_native_collector_saves_baseline_and_retains_failed_artifacts(tmp_path, workflow, wrong_media, version, migrated, wrong_open):
    from xml.etree import ElementTree as ET
    from tests.unit.test_console_project_alternatives_gateway import CliProjectTask, saved_fixture_project, WaapiRequestFailed, OPEN

    class Client(CliProjectTask):
        def __init__(self, *args):
            self.loaded, self.reopened, self.absence_errors = True, False, []
            super().__init__(*args)

        def call(self, uri, args=None, options=None):
            if not self.loaded and (uri.endswith('getProjectInfo') or (
                    uri.endswith('object.get') and args.get('waql', '').startswith('from type Project '))):
                self.calls.append((uri, args, options))
                self.absence_errors.append(WaapiRequestFailed(uri))
                raise self.absence_errors[-1]
            if uri.endswith('object.get') and args.get('waql') == 'from type Project take 2':
                self.calls.append((uri, args, options))
                return {'return': [{'id': ('{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}' if wrong_open and self.reopened
                    else '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}'), 'name': 'Fixture',
                    'type': 'Project', 'path': '\\', 'filePath': str(self.project_file)}]}
            if uri.endswith('getProjectInfo') and wrong_open and self.reopened:
                return {**super().call(uri, args, options), 'id': '{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}'}
            if uri == OPEN:
                self.calls.append((uri, args, options))
                assert not self.loaded and args == {'path': str(self.project_file)}
                self.loaded = True
                self.reopened = True
                return {}
            if uri.endswith("project.save"):
                self.calls.append((uri, args, options))
                tree = ET.parse(self.unit)
                tree.find(".//MediaID").set("ID", "123456")
                tree.write(self.unit)
                return {}
            if uri == "ak.wwise.cli.migrate":
                self.calls.append((uri, args, options))
                tree = ET.parse(self.unit)
                tree.find('.//Property[@Name="Volume"]/ValueList/Value').text = '-3'
                tree.write(self.unit)
                self.loaded = False
                return {"result": 0}
            if uri == self.operation:
                self.project_file.with_suffix(".mediaid").write_text('''<WwiseDocument Type="MediaIDs">
<MediaIDInfo><MediaIDs><Language ID="393239870" Name="SFX"><File Name="Keep.wav">
<WObject ID="{33333333-3333-3333-3333-333333333333}"><MediaID ID="123456"/></WObject>
</File></Language></MediaIDs></MediaIDInfo></WwiseDocument>'''.replace("123456", "654321" if wrong_media else "123456"))
                tree = ET.parse(self.unit)
                source = tree.find(".//AudioFileSource")
                source.remove(source.find("MediaIDList"))
                tree.write(self.unit)
                tree = ET.parse(self.project_file)
                ET.SubElement(tree.find("./ProjectInfo/Project/PropertyList"), "Property",
                              Name="MediaIDsInSingleFile", Type="bool", Value="True")
                tree.write(self.project_file)
            return super().call(uri, args, options)

    # Native migrate leaves the same Console instance alive with no active project.
    client = Client(tmp_path, version, "ak.wwise.cli.moveMediaIdsToSingleFile")
    client.unit = saved_fixture_project(client)
    tree = ET.parse(client.unit)
    source = ET.SubElement(ET.SubElement(tree.find(".//Sound"), "ChildrenList"),
        "AudioFileSource", Name="Keep", ID="{33333333-3333-3333-3333-333333333333}")
    ET.SubElement(source, "Language").text = "SFX"
    ET.SubElement(source, "AudioFile").text = "Keep.wav"
    ET.SubElement(ET.SubElement(source, "MediaIDList"), "MediaID", ID="111")
    tree.write(client.unit)
    commands = []

    def gateway(command, *, live):
        commands.append(list(command))
        code, payload = client.run(*command)
        assert code == 0, json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return payload

    runtime = SimpleNamespace(gateway=gateway, version=version, category_results=[],
        sandbox=SimpleNamespace(sandbox_project=client.project_file),
        restart=lambda: pytest.fail('Collector must reopen the same Console instance without a host restart'))
    collect = (workflow.test_cli_console_media_id_migrated_project_acceptance if migrated
               else workflow.test_cli_console_media_id_file_observation)
    if wrong_media or wrong_open:
        with pytest.raises(AssertionError):
            collect(runtime)
    else:
        collect(runtime)
    category, = runtime.category_results
    if wrong_open:
        assert category['status'] == 'FAIL' and 'baseline_media_pairs' not in category
        assert category['setup_migration']['status'] == 'complete'
        assert category['setup_reopen']['status'] == 'FAIL'
        # The existing runtime gateway asserts with the complete serialized
        # failure; pytest may append its assertion rendering to that diagnostic.
        assert 'verification_failed' in str(category['setup_reopen']['failure'])
        assert 'business_state_verified' in str(category['setup_reopen']['failure'])
        assert category['setup_reopen']['coverage_credit'] == 'none; baseline preparation only'
        assert not any(uri == client.operation for uri, _, _ in client.calls)
        assert [uri for uri, _, _ in client.calls].count(OPEN) == 1
        return
    assert category["status"] == ("FAIL" if wrong_media else "PASS")
    assert category["mapping_file"]["content_base64"]
    assert category["source_work_unit_after"]["content_base64"]
    assert category["baseline_media_pairs"] == [["{33333333-3333-3333-3333-333333333333}", "123456"]]
    writes = [uri for uri, _, _ in client.calls if uri.endswith("project.save") or uri in {client.operation, "ak.wwise.cli.migrate", OPEN}]
    assert writes == ["ak.wwise.core.project.save", *(["ak.wwise.cli.migrate", OPEN] if migrated else []), client.operation]
    assert sum(command[0] == "execute" for command in commands) == (4 if migrated else 2)
    if migrated:
        assert category["baseline_setup"] == "public_gateway_save_then_migrate_then_reopen_before_capture"
        assert category["setup_migration"]["state"] == "result_schema_checked"
        assert category["setup_migration"]["business_state_verified"] is False
        assert client.absence_errors and all(error.uri == 'ak.wwise.no_project_loaded' for error in client.absence_errors)
        assert any(error.kwargs['details']['procedureUri'] == 'ak.wwise.core.getProjectInfo' for error in client.absence_errors)
        reopened = category['setup_reopen']
        assert reopened['state'] == 'verified' and reopened['business_state_verified'] is True
        assert reopened['coverage_credit'] == 'none; baseline preparation only'
        assert reopened['project_file'] == str(client.project_file)
        code, shown = client.run('transaction-show', reopened['transaction_id'])
        assert code == 0, shown
        dispatch = shown['artifact']['prepared_operation']['dispatch']
        assert dispatch == {'uri': OPEN, 'args': {'path': str(client.project_file)}, 'options': {}}
        assert reopened['verification']['business_state_verified'] is True
        assert '{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}' in json.dumps(reopened['verification'])
        assert str(client.project_file) in json.dumps(reopened['verification'])
    else:
        assert not client.absence_errors and 'setup_reopen' not in category


@pytest.mark.parametrize('version', ['2021.1', '2022.1'])
def test_migrated_media_collector_retains_legacy_owned_fixture_boundary_without_synthesizing_open(tmp_path, workflow, version):
    from tests.unit.test_waapi_gateway import gateway_env, waapi_gateway as gateway
    from tests.support.gateway_config import set_gateway_config
    from wwise_waapi.native_catalog import load_native_catalog
    operation = 'ak.wwise.console.project.open'
    native = load_native_catalog(version, 'wwise-console')
    assert operation not in native['functions']
    assert 'ak.wwise.ui.project.open' in native['functions']
    env = gateway_env(tmp_path)
    set_gateway_config(env, wwise_version=version)
    code, schema = gateway.execute_gateway(['request-schema', operation], env=env,
        client_factory=lambda _: pytest.fail('Absent public Console open discovery must stay offline'))
    assert code != 0, schema
    runtime = SimpleNamespace(version=version, category_results=[],
        sandbox=SimpleNamespace(sandbox_project=tmp_path / 'Owned.wproj'),
        gateway=lambda *a, **kw: pytest.fail('Legacy preparation must not migrate or synthesize an unavailable open URI'))
    with pytest.raises(AssertionError, match='legacy_migrated_project_reopen_fixture'):
        workflow.test_cli_console_media_id_migrated_project_acceptance(runtime)
    category, = runtime.category_results
    assert category['status'] == 'blocked' and category['boundary'] == 'legacy_migrated_project_reopen_fixture'
    assert category['media_effect'] == 'not_executed'
    assert category['selected_reopen_uri'] == operation
    assert 'ak.wwise.ui.project.open' in category['unassessed_alternative']
    assert 'owned lifecycle fixture work' in category['reason']

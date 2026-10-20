"""Class/default planning through the public Draft/Preview seam; native API is fake.

Models deliberately vary class identities and defaults. Native class-condition
captures support grammar only; these tests claim no native creation effect.
"""
from copy import deepcopy
import json

import pytest

from tests.unit.test_gameparameter_class_fields_gateway import ParameterTask, CREATED, EXISTING
from tests.unit.test_field_interface_closure_gateway import FIRST, VERSIONS


class ClassTask(ParameterTask):
    def __init__(self, path, version, class_name="ModulatorTime"):
        super().__init__(path, version)
        self.class_name = class_name
        self.class_id = 5111824
        if class_name == "GameParameter":
            self.types[1]["classId"] = self.class_id
            self.objects[EXISTING]["classId"] = self.class_id
        else:
            self.types.append({"name": class_name, "classId": self.class_id, "type": "WObject"})
        self.metadata = {
            "EnvelopeStopPlayback": {"name": "EnvelopeStopPlayback", "type": "bool", "default": True,
                "dependencies": [{"type": "property", "action": "Enable", "context": "Self",
                    "property": "TimeModLoops", "conditions": [{"restriction": {"type": "range", "min": 1, "max": 100}}]}]},
            "TimeModLoops": {"name": "TimeModLoops", "type": "int32", "default": 1,
                "restriction": {"type": "range", "min": 0, "max": 100}},
        }

    def call(self, uri, args=None, options=None):
        if uri.endswith("object.set"):
            self.calls.append((uri, args, options))
            child = args["objects"][0]["children"][0]
            row = {"id": CREATED, "name": child["name"], "type": self.class_name, "classId": self.class_id,
                "path": self.objects[FIRST]["path"] + "\\" + child["name"], "parent": {"id": FIRST}}
            row.update({name: deepcopy(info["default"]) for name, info in self.metadata.items() if "default" in info})
            row.update({key[1:]: value for key, value in child.items() if key.startswith("@")})
            self.objects[CREATED] = row
            return {"objects": [{**{key: self.objects[FIRST][key] for key in ("id", "name", "type", "path")},
                "children": [{key: row[key] for key in ("id", "name", "type", "path")}]}]}
        result = super().call(uri, args, options)
        if uri.endswith("getPropertyInfo"):
            return deepcopy(result)
        if uri.endswith("object.create"):
            row = self.objects[CREATED]
            row.update(type=self.class_name, classId=self.class_id)
            for name, metadata in self.metadata.items():
                if "default" in metadata:
                    row[name] = deepcopy(metadata["default"])
            for key, value in args.items():
                if key.startswith("@"):
                    row[key[1:]] = value
            return {key: row[key] for key in ("id", "name", "type", "path")}
        return result

    def declare(self, *, expected_code=0, **values):
        parent = self.bind(FIRST)
        kind = self.discover_kind(self.class_name)
        fields = []
        for meaning, value in values.items():
            code, found = self.step("draft-discover-fields", "--type-handle", kind, "--meaning", meaning)
            assert code == 0, found
            candidates = found.get("field_candidates") or found["meaning_results"][0]["candidates"]
            fields.extend(["--field-value", candidates[0]["handle"], value if isinstance(value, str) else json.dumps(value)])
        code, declared = self.step("draft-declare-new", "--declaration-id", "new", "--parent-handle", parent,
            "--name", "OwnedNew", "--kind", kind, *fields)
        assert code == expected_code, declared
        return declared


def test_new_class_preserves_satisfied_authoritative_default_in_one_creation(tmp_path):
    task = ClassTask(tmp_path, "2025.1")
    preserved = deepcopy(task.objects[EXISTING])
    task.declare(EnvelopeStopPlayback=False)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0, verified
    assert task.objects[CREATED]["EnvelopeStopPlayback"] is False
    assert task.objects[CREATED]["TimeModLoops"] == 1
    assert task.objects[EXISTING] == preserved
    writes = [(uri, args) for uri, args, _ in task.calls if uri.endswith(("object.create", "setProperty"))]
    assert len(writes) == 1
    assert writes[0][1]["@EnvelopeStopPlayback"] is False
    assert "@TimeModLoops" not in writes[0][1]


def test_creation_does_not_verify_when_native_ignores_the_sealed_default(tmp_path):
    task = ClassTask(tmp_path, "2025.1")
    task.declare(EnvelopeStopPlayback=False)
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    task.objects[CREATED]["TimeModLoops"] = 0
    code, failed = task.run("verify", tx)
    assert code == 2 and failed.get("verified") is not True, failed
    assert not failed.get("agent_result")
    code, replay = task.run("execute", tx)
    assert code == 2, replay
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


def test_new_reference_uses_class_default_instead_of_inventing_a_scalar_prerequisite(tmp_path):
    task = ClassTask(tmp_path, "2025.1", "Sound")
    task.metadata["OutputBus"] = {"name": "OutputBus", "type": "Reference",
        "dependencies": deepcopy(task.metadata["EnvelopeStopPlayback"]["dependencies"])}
    task.set_object_type(EXISTING, "Bus", 30)
    parent = task.bind(FIRST)
    target = task.bind(EXISTING)
    kind = task.discover_kind("Sound")
    code, found = task.step("draft-discover-fields", "--type-handle", kind, "--meaning", "OutputBus")
    assert code == 0, found
    field = found["field_candidates"][0]["handle"]
    code, declared = task.step("draft-declare-new", "--declaration-id", "new", "--parent-handle", parent,
        "--name", "OwnedNew", "--kind", kind, "--field-value", field, target)
    assert code == 0, declared
    code, checked = task.step("draft-check")
    assert code == 0, checked


class ConditionalPluginClient:
    """Delegate the ordinary fake native plugin boundary, adding class metadata."""
    def __init__(self, version, mode=0):
        from tests.unit.test_plugin_shareset_gateway import ShareSetClient
        self.base = ShareSetClient(version)
        self.mode = mode
        self.metadata = {
            "RoomSize": {"name": "RoomSize", "type": "Real32", "default": 0.5,
                "dependencies": [{"type": "property", "action": "Enable", "context": "Self", "property": "Mode",
                    "conditions": [{"restriction": {"type": "enum", "values": [{"value": 0}, {"value": 1}]}}]}]},
            "Mode": {"name": "Mode", "type": "int32", "default": mode},
        }

    @property
    def calls(self):
        return self.base.calls

    def disconnect(self):
        return self.base.disconnect()

    def call(self, uri, args=None, options=None):
        if uri.endswith("getPropertyAndReferenceNames"):
            self.base.calls.append((uri, args, options))
            return {"return": list(self.metadata)}
        if uri.endswith("getPropertyInfo"):
            self.base.calls.append((uri, args, options))
            return deepcopy(self.metadata[args["property"]])
        result = self.base.call(uri, args, options)
        if uri.endswith("object.get") and self.base.created:
            from tests.unit.test_plugin_shareset_gateway import PLUGIN
            if PLUGIN in json.dumps(args):
                for row in result["return"]:
                    if "@Mode" in options["return"]:
                        row["@Mode"] = self.mode
        return result


def test_plugin_class_default_conflict_rejects_without_creation(tmp_path):
    from tests.unit.test_plugin_shareset_gateway import declare_plugin
    client = ConditionalPluginClient("2025.1", mode=2)
    code, declared, step, _ = declare_plugin(tmp_path, "2025.1", client, with_property=True)
    assert code == 0, declared
    code, rejected = step("draft-check")
    assert code == 2, rejected
    assert "REFERENCE_ACTIVATION_REQUIRED" in str(rejected)
    assert not any(uri.endswith("object.set") for uri, _, _ in client.calls)


def preview_and_confirm(task):
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = task.run("transaction-show", tx)
    assert code == 0, shown
    code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    return tx, shown


def test_reference_default_omission_drift_blocks_before_creation(tmp_path):
    task = ClassTask(tmp_path, "2025.1")
    task.metadata["EnvelopeStopPlayback"]["dependencies"] = [{"type": "reference", "action": "Enable",
        "context": "Self", "property": "Target", "conditions": [{"referenceIsSet": False}]}]
    task.metadata["Target"] = {"name": "Target", "type": "Reference", "default": None}
    task.declare(EnvelopeStopPlayback=False)
    tx, _ = preview_and_confirm(task)
    del task.metadata["Target"]["default"]
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert CREATED not in task.objects
    assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)


def restart(task, operation):
    code, started = task.run("draft-start", operation)
    assert code == 0, started
    task.draft, task.authority, task.revision = started["draft"]["draft_id"], started["task_authority"], started["draft"]["revision"]
    return started


def test_staged_binding_uses_the_durable_verified_creation_identity(tmp_path):
    task = ClassTask(tmp_path, "2025.1")
    task.declare()
    code, created = task.transaction("ask_before_changes")
    assert code == 0, created
    tx = created["transaction_id"]
    restart(task, "object.setProperty")
    code, bound = task.step("draft-bind-object", "--verified-created-from", tx)
    assert code == 0, bound
    assert bound["bound_object"]["name"] == "OwnedNew"
    field = task.discover(bound["bound_object"]["handle"], "EnvelopeStopPlayback")
    code, declared = task.step("draft-declare-field-change", "--object-handle", bound["bound_object"]["handle"],
        "--field-handle", field, "--business-value", "false")
    assert code == 0, declared
    code, verified = task.transaction("ask_before_changes")
    assert code == 0, verified
    assert verified["transaction_id"] != tx
    assert task.objects[CREATED]["EnvelopeStopPlayback"] is False
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("class_name", ["Sound", "ModulatorTime", "GameParameter"])
@pytest.mark.parametrize("explicit", [None, 50])
def test_class_default_or_explicit_prerequisite_reaches_verified_creation(tmp_path, version, class_name, explicit):
    task = ClassTask(tmp_path, version, class_name)
    values = {"EnvelopeStopPlayback": False}
    if explicit is not None:
        task.metadata["TimeModLoops"]["default"] = 0
        values["TimeModLoops"] = explicit
    task.declare(**values)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0, verified
    assert task.objects[CREATED]["TimeModLoops"] == (1 if explicit is None else explicit)
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("value", [0, 101])
def test_explicit_incompatible_prerequisite_cannot_create(tmp_path, version, value):
    task = ClassTask(tmp_path, version)
    declared = task.declare(expected_code=2 if value == 101 else 0, EnvelopeStopPlayback=False, TimeModLoops=value)
    if value == 101:
        assert declared["error_code"] == "FIELD_VALUE_OUT_OF_RANGE"
    else:
        code, rejected = task.step("draft-check")
        assert code == 2, rejected
    assert CREATED not in task.objects
    assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("phase", ["preview", "execute"])
def test_class_default_drift_rejects_without_creation(tmp_path, version, phase):
    task = ClassTask(tmp_path, version)
    task.declare(EnvelopeStopPlayback=False)
    code, checked = task.step("draft-check")
    assert code == 0, checked
    if phase == "execute":
        tx, _ = preview_and_confirm(task)
    task.metadata["TimeModLoops"]["default"] = 2  # Still satisfies range; the exact sealed fact changed.
    code, rejected = task.step("preview-from-draft") if phase == "preview" else task.run("execute", tx)
    assert code == 2, rejected
    assert CREATED not in task.objects


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", ["read_only", "ask_before_changes", "allow_changes"])
def test_class_default_creation_preserves_each_modification_policy(tmp_path, version, policy):
    task = ClassTask(tmp_path, version)
    code, configured = task.run("config-set", "--project-modification-policy", policy)
    assert code == 0, configured
    task.declare(EnvelopeStopPlayback=False)
    code, result = task.transaction(policy)
    if policy == "read_only":
        assert code == 2 and CREATED not in task.objects
    else:
        assert code == 0 and result["verified"] is True, result
        assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_partial_field_verification_still_allows_identity_bound_repair(tmp_path, version):
    task = ClassTask(tmp_path, version)
    task.declare(EnvelopeStopPlayback=False)
    tx, _ = preview_and_confirm(task)
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    task.objects[CREATED]["TimeModLoops"] = 0
    code, failed = task.run("verify", tx)
    assert code == 2 and failed["verified"] is False, failed
    assert failed["creation_result"]["identity_status"] == "verified"
    assert failed["creation_result"]["configuration_complete"] is False
    restart(task, "object.setProperty")
    code, bound = task.step("draft-bind-object", "--verified-created-from", tx)
    assert code == 0, bound
    handle = bound["bound_object"]["handle"]
    field = task.discover(handle, "TimeModLoops")
    code, declared = task.step("draft-declare-field-change", "--object-handle", handle,
        "--field-handle", field, "--business-value", "1")
    assert code == 0, declared
    code, repaired = task.transaction("ask_before_changes")
    assert code == 0 and repaired["verified"] is True, repaired
    assert task.objects[CREATED]["EnvelopeStopPlayback"] is False
    assert task.objects[CREATED]["TimeModLoops"] == 1
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("drift", ["name", "type", "path", "missing", "ambiguous", "unverified"])
def test_staged_binding_refuses_unproved_or_changed_root_identity(tmp_path, drift):
    task = ClassTask(tmp_path, "2025.1")
    task.declare()
    tx, _ = preview_and_confirm(task)
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    if drift != "unverified":
        code, verified = task.run("verify", tx)
        assert code == 0, verified
    if drift in {"name", "type", "path"}:
        task.objects[CREATED][drift] += "Changed"
    elif drift == "missing":
        del task.objects[CREATED]
    elif drift == "ambiguous":
        task.ambiguous_created_readback = True
    restart(task, "object.setProperty")
    revision = task.revision
    code, rejected = task.step("draft-bind-object", "--verified-created-from", tx)
    assert code == 2, rejected
    assert task.revision == revision
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_plugin_creation_preserves_and_verifies_the_class_default(tmp_path, version):
    from tests.unit.test_plugin_shareset_gateway import execute_shareset
    client = ConditionalPluginClient(version, mode=1)
    code, verified = execute_shareset(tmp_path, version, client, with_property=True)
    assert code == 0 and verified["verified"] is True, verified
    assert any("@Mode" in (options or {}).get("return", []) for uri, _, options in client.calls if uri.endswith("object.get"))


@pytest.mark.parametrize("version", VERSIONS)
def test_recursive_class_conditions_accumulate_before_defaults_are_chosen(tmp_path, version):
    def scalar_condition(name, values):
        return {"type": "property", "action": "Enable", "context": "Self", "property": name,
            "conditions": [{"restriction": {"type": "enum", "values": [{"value": value} for value in values]}}]}
    task = ClassTask(tmp_path, version, "ModulatorLfo")
    task.metadata = {
        "Value": {"name": "Value", "type": "Real64", "default": 0,
            "dependencies": [scalar_condition("GateA", [True]), scalar_condition("GateB", [True])]},
        "GateA": {"name": "GateA", "type": "bool", "default": True,
            "dependencies": [scalar_condition("Mode", [1, 2])]},
        "GateB": {"name": "GateB", "type": "bool", "default": True,
            "dependencies": [scalar_condition("Mode", [2, 3])]},
        "Mode": {"name": "Mode", "type": "int32", "default": 2},
    }
    task.declare(Value=3)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CREATED]["Mode"] == 2
    write = next(args for uri, args, _ in task.calls if uri.endswith("object.create"))
    assert not any("@" + field in write for field in ["GateA", "GateB", "Mode"])


@pytest.mark.parametrize("version", VERSIONS)
def test_explicit_reference_prerequisite_and_dependent_field_share_the_creation(tmp_path, version):
    task = ClassTask(tmp_path, version, "Sound")
    task.metadata["EnvelopeStopPlayback"]["dependencies"] = [{"type": "reference", "action": "Enable",
        "context": "Self", "property": "Target", "conditions": [{"referenceIsSet": True}]}]
    task.metadata["Target"] = {"name": "Target", "type": "Reference"}
    target = task.bind(EXISTING)
    task.declare(EnvelopeStopPlayback=False, Target=target)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CREATED]["Target"] == EXISTING
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_missing_class_default_requires_explicit_intent_but_not_a_new_object(tmp_path, version):
    task = ClassTask(tmp_path, version)
    del task.metadata["TimeModLoops"]["default"]
    task.declare(EnvelopeStopPlayback=False)
    code, rejected = task.step("draft-check")
    assert code == 2 and "REFERENCE_ACTIVATION_REQUIRED" in str(rejected), rejected
    assert CREATED not in task.objects
    # A new declaration can explicitly provide the absent class fact.
    restart(task, "object.create")
    task.declare(EnvelopeStopPlayback=False, TimeModLoops=5)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0 and verified["verified"] is True, verified
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("damage", ["cycle", "wrong_controller", "unsupported_nested_condition", "wrong_controller_type"])
def test_unproved_class_metadata_never_creates_an_object(tmp_path, damage):
    task = ClassTask(tmp_path, "2025.1")
    if damage == "cycle":
        task.metadata["TimeModLoops"]["dependencies"] = deepcopy(task.metadata["EnvelopeStopPlayback"]["dependencies"])
        task.metadata["TimeModLoops"]["dependencies"][0]["property"] = "EnvelopeStopPlayback"
    elif damage == "wrong_controller":
        task.metadata["TimeModLoops"]["name"] = "Unrelated"
    elif damage == "unsupported_nested_condition":
        task.metadata["EnvelopeStopPlayback"]["dependencies"][0]["conditions"] = [{"and": []}]
    else:
        task.metadata["TimeModLoops"]["type"] = "Reference"
    task.bind(FIRST)
    kind = task.discover_kind(task.class_name)
    revision = task.revision
    code, rejected = task.step("draft-discover-fields", "--type-handle", kind, "--meaning", "EnvelopeStopPlayback")
    assert code == 2, rejected
    assert task.revision == revision
    assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1", "2025.1"])
def test_plugin_default_drift_prevents_native_creation(tmp_path, version):
    from tests.unit.test_plugin_shareset_gateway import declare_plugin, gateway
    client = ConditionalPluginClient(version, mode=1)
    code, declared, step, env = declare_plugin(tmp_path, version, client, with_property=True)
    assert code == 0, declared
    code, checked = step("draft-check")
    assert code == 0, checked
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = gateway.execute_gateway(["transaction-show", tx], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway(["confirm", tx, "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, confirmed
    client.metadata["Mode"]["default"] = 0
    code, rejected = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert code == 2, rejected
    assert not any(uri.endswith("object.set") for uri, _, _ in client.calls)


def test_malformed_reference_default_refuses_creation_before_dispatch(tmp_path):
    task = ClassTask(tmp_path, "2025.1")
    task.metadata["EnvelopeStopPlayback"]["dependencies"] = [{"type": "reference", "action": "Enable",
        "context": "Self", "property": "Target", "conditions": [{"referenceIsSet": True}]}]
    task.metadata["Target"] = {"name": "Target", "type": "Reference", "default": "guessed-target"}
    parent = task.bind(FIRST)
    kind = task.discover_kind(task.class_name)
    code, found = task.step("draft-discover-fields", "--type-handle", kind, "--meaning", "EnvelopeStopPlayback")
    if code == 0:
        code, declared = task.step("draft-declare-new", "--declaration-id", "new", "--parent-handle", parent,
            "--name", "OwnedNew", "--kind", kind, "--field-value", found["field_candidates"][0]["handle"], "false")
        assert code == 0, declared
        code, found = task.step("draft-check")
    assert code == 2, found
    assert CREATED not in task.objects


@pytest.mark.parametrize("version", VERSIONS[1:])
def test_atomic_tree_creation_uses_the_same_class_default_plan(tmp_path, version):
    task = ClassTask(tmp_path, version)
    restart(task, "object.set")
    task.declare(EnvelopeStopPlayback=False)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CREATED]["EnvelopeStopPlayback"] is False
    assert task.objects[CREATED]["TimeModLoops"] == 1
    writes = [(uri, args) for uri, args, _ in task.calls if uri.endswith(("object.create", "object.set"))]
    assert len(writes) == 1 and writes[0][0].endswith("object.set")
    assert "@TimeModLoops" not in writes[0][1]["objects"][0]["children"][0]


@pytest.mark.parametrize("version", ["2021.1", "2025.1"])
def test_exact_recorded_time_modulator_class_shape_accepts_explicit_prerequisite(tmp_path, version):
    from tests.unit.test_time_modulator_range_gateway import FACTS
    task = ClassTask(tmp_path, version)
    facts = FACTS["versions"][version]
    resolved = deepcopy(facts["metadata_scope"]["resolved"])
    task.types = [resolved if row["name"] == task.class_name else row for row in task.types]
    task.class_id = resolved["classId"]
    task.metadata = {"EnvelopeStopPlayback": deepcopy(facts["field_metadata"]),
                     "TimeModLoops": deepcopy(facts["controller_metadata_model"])}
    task.declare(EnvelopeStopPlayback=False, TimeModLoops=7)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CREATED]["TimeModLoops"] == 7
    assert task.objects[CREATED]["EnvelopeStopPlayback"] is False


def test_failed_root_identity_never_authorizes_a_repair_binding(tmp_path):
    task = ClassTask(tmp_path, "2025.1")
    task.declare(EnvelopeStopPlayback=False)
    tx, _ = preview_and_confirm(task)
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    task.objects[CREATED]["name"] = "UnreviewedRoot"
    code, failed = task.run("verify", tx)
    assert code == 2 and failed["creation_result"]["identity_status"] == "unavailable", failed
    restart(task, "object.setProperty")
    code, rejected = task.step("draft-bind-object", "--verified-created-from", tx)
    assert code == 2, rejected
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


def test_staged_binding_rejects_creation_configuration_drift(tmp_path):
    task = ClassTask(tmp_path, "2025.1")
    task.declare()
    code, created = task.transaction("ask_before_changes")
    assert code == 0, created
    code, configured = task.run("config-set", "--waapi-port", "31338")
    assert code == 0, configured
    restart(task, "object.setProperty")
    code, rejected = task.step("draft-bind-object", "--verified-created-from", created["transaction_id"])
    assert code == 2, rejected
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1
    assert not any(uri.endswith("setProperty") for uri, _, _ in task.calls)


def test_plugin_prerequisite_effect_is_not_inferred_from_creation_success(tmp_path):
    from tests.unit.test_plugin_shareset_gateway import declare_plugin, gateway
    client = ConditionalPluginClient("2025.1", mode=1)
    code, declared, step, env = declare_plugin(tmp_path, "2025.1", client, with_property=True)
    assert code == 0, declared
    code, checked = step("draft-check")
    assert code == 0, checked
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    tx = preview["transaction_id"]
    code, shown = gateway.execute_gateway(["transaction-show", tx], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway(["confirm", tx, "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, confirmed
    code, executed = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert code == 0, executed
    client.mode = 2
    code, failed = gateway.execute_gateway(["verify", tx], env=env, client_factory=lambda _: client)
    assert code == 2 and failed["verified"] is False, failed
    assert sum(uri.endswith("object.set") for uri, _, _ in client.calls) == 1


HIERARCHY_GROUP = "{66666666-6666-6666-6666-666666666666}"
HIERARCHY_TARGET = "{77777777-7777-7777-7777-777777777777}"
HIERARCHY_OTHER = "{88888888-8888-8888-8888-888888888888}"


class ProspectiveReferenceTask(ClassTask):
    """Same five-version rule as the sealed existing DefaultSwitch model."""
    def __init__(self, path, version, *, state=False):
        super().__init__(path, version, "SwitchContainer")
        self.objects[FIRST]["path"] = r"\Actor-Mixer Hierarchy\Default Work Unit"
        group_type, target_type = ("StateGroup", "State") if state else ("SwitchGroup", "Switch")
        self.types.extend([{"name": group_type, "classId": 40, "type": "WObject"},
                           {"name": target_type, "classId": 41, "type": "WObject"}])
        for identity, name in ((HIERARCHY_GROUP, "Surface"), (HIERARCHY_OTHER, "Weather")):
            self.objects[identity] = {"id": identity, "name": name, "type": group_type, "classId": 40,
                "path": "\\Switches\\Default Work Unit\\" + name, "parent": {"id": FIRST}}
        self.objects[HIERARCHY_TARGET] = {"id": HIERARCHY_TARGET, "name": "Concrete", "type": target_type, "classId": 41,
            "path": r"\Switches\Default Work Unit\Surface\Concrete", "parent": {"id": HIERARCHY_GROUP}}
        self.metadata = {
            "DefaultSwitchOrState": {"name": "DefaultSwitchOrState", "type": "", "default": None,
                "restriction": {"type": "reference", "restrictions": [
                    {"childOfReference": "SwitchGroupOrStateGroup"}, {"type": ["Switch", "State"]}]},
                "dependencies": [{"type": "reference", "action": "Enable", "context": "Self",
                    "property": "SwitchGroupOrStateGroup", "conditions": [{"referenceIsSet": True}]}]},
            "SwitchGroupOrStateGroup": {"name": "SwitchGroupOrStateGroup", "type": "", "default": None,
                "restriction": {"type": "reference", "restrictions": [{"type": ["SwitchGroup", "StateGroup"]}]}},
        }

    def declare_hierarchy(self, *, reverse=False, expected_code=0):
        target, group = self.bind(HIERARCHY_TARGET), self.bind(HIERARCHY_GROUP)
        values = [("DefaultSwitchOrState", target), ("SwitchGroupOrStateGroup", group)]
        if reverse:
            values.reverse()
        return self.declare(expected_code=expected_code, **dict(values))


@pytest.mark.parametrize("version", VERSIONS)
def test_new_reference_hierarchy_accepts_an_explicit_controlling_group(tmp_path, version):
    task = ProspectiveReferenceTask(tmp_path, version)
    task.declare_hierarchy()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("state", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_new_reference_hierarchy_creates_and_verifies_both_explicit_edges(tmp_path, version, state, reverse):
    task = ProspectiveReferenceTask(tmp_path, version, state=state)
    preserved = deepcopy(task.objects)
    task.declare_hierarchy(reverse=reverse)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CREATED]["SwitchGroupOrStateGroup"] == HIERARCHY_GROUP
    assert task.objects[CREATED]["DefaultSwitchOrState"] == HIERARCHY_TARGET
    assert {key: row for key, row in task.objects.items() if key != CREATED} == preserved
    writes = [(uri, args) for uri, args, _ in task.calls if uri.endswith(("object.create", "object.set", "setReference", "setProperty"))]
    assert len(writes) == 1 and writes[0][0].endswith("object.create")
    assert writes[0][1]["@SwitchGroupOrStateGroup"] == HIERARCHY_GROUP
    assert writes[0][1]["@DefaultSwitchOrState"] == HIERARCHY_TARGET
    code, rejected = task.run("execute", verified["transaction_id"])
    assert code == 2
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("fault", ["wrong-parent", "missing-group", "wrong-target-type"])
def test_new_reference_hierarchy_rejects_invalid_prospective_relationship_without_creation(tmp_path, version, fault):
    task = ProspectiveReferenceTask(tmp_path, version)
    if fault == "wrong-parent":
        task.objects[HIERARCHY_TARGET]["parent"] = {"id": HIERARCHY_OTHER}
    if fault == "wrong-target-type":
        task.set_object_type(HIERARCHY_TARGET, "Sound", 42)
    if fault == "missing-group":
        task.declare(DefaultSwitchOrState=task.bind(HIERARCHY_TARGET))
    elif fault == "wrong-target-type":
        rejected = task.declare_hierarchy(expected_code=2)
        assert rejected["error_code"] == "REFERENCE_TARGET_TYPE_MISMATCH", rejected
        assert CREATED not in task.objects
        assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)
        return
    else:
        task.declare_hierarchy()
    code, rejected = task.step("draft-check")
    assert code == 2 and rejected["error_code"] in {"INVALID_REFERENCE_TARGET", "REFERENCE_ACTIVATION_REQUIRED"}, rejected
    assert CREATED not in task.objects
    assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("drift", ["target-parent", "selected-metadata", "controller-metadata"])
def test_new_reference_hierarchy_revalidates_relationship_and_class_metadata_before_creation(tmp_path, version, drift):
    task = ProspectiveReferenceTask(tmp_path, version)
    task.declare_hierarchy()
    tx, _ = preview_and_confirm(task)
    if drift == "target-parent":
        task.objects[HIERARCHY_TARGET]["parent"] = {"id": HIERARCHY_OTHER}
    else:
        name = "DefaultSwitchOrState" if drift == "selected-metadata" else "SwitchGroupOrStateGroup"
        task.metadata[name]["restriction"]["restrictions"].append("notNull")
    code, rejected = task.run("execute", tx)
    assert code == 2, rejected
    assert CREATED not in task.objects
    assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("fault", ["default-reference", "group-reference", "target-parent"])
def test_new_reference_hierarchy_never_verifies_ignored_fields_or_changed_target_parent(tmp_path, version, fault):
    task = ProspectiveReferenceTask(tmp_path, version)
    task.declare_hierarchy()
    tx, _ = preview_and_confirm(task)
    original = task.call
    def call(uri, args=None, options=None):
        result = original(uri, args, options)
        if uri.endswith("object.create"):
            if fault == "target-parent":
                task.objects[HIERARCHY_TARGET]["parent"] = {"id": HIERARCHY_OTHER}
            else:
                name = "DefaultSwitchOrState" if fault == "default-reference" else "SwitchGroupOrStateGroup"
                task.objects[CREATED][name] = None  # Native accepted the request but ignored this field.
        return result
    task.call = call
    code, executed = task.run("execute", tx)
    assert code == 0, executed
    code, failed = task.run("verify", tx)
    assert code == 2 and failed.get("verified") is not True, failed
    assert not failed.get("agent_result")
    assert failed["creation_result"]["identity_status"] == "verified"
    assert failed["creation_result"]["configuration_complete"] is False
    code, replay = task.run("execute", tx)
    assert code == 2
    assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1


def test_set_new_node_reuses_prospective_reference_hierarchy_proof(tmp_path):
    task = ProspectiveReferenceTask(tmp_path, "2025.1")
    restart(task, "object.set")
    task.declare_hierarchy(reverse=True)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0 and verified["verified"] is True, verified
    assert task.objects[CREATED]["SwitchGroupOrStateGroup"] == HIERARCHY_GROUP
    assert task.objects[CREATED]["DefaultSwitchOrState"] == HIERARCHY_TARGET
    assert sum(uri.endswith("object.set") for uri, _, _ in task.calls) == 1
    assert not any(uri.endswith("object.create") for uri, _, _ in task.calls)


@pytest.mark.parametrize("version", ["2021.1", "2025.1"])
@pytest.mark.parametrize("policy", ["read_only", "allow_changes"])
def test_new_reference_hierarchy_retains_creation_policy_authority(tmp_path, version, policy):
    task = ProspectiveReferenceTask(tmp_path, version)
    code, configured = task.run("config-set", "--project-modification-policy", policy)
    assert code == 0, configured
    task.declare_hierarchy()
    code, result = task.transaction(policy)
    if policy == "read_only":
        assert code == 2 and CREATED not in task.objects, result
        assert not any(uri.endswith(("object.create", "object.set")) for uri, _, _ in task.calls)
    else:
        assert code == 0 and result["verified"] is True, result
        assert task.objects[CREATED]["SwitchGroupOrStateGroup"] == HIERARCHY_GROUP
        assert task.objects[CREATED]["DefaultSwitchOrState"] == HIERARCHY_TARGET
        assert sum(uri.endswith("object.create") for uri, _, _ in task.calls) == 1

"""Dependent new-object fields have a usable public continuation, not a guessed scope."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from tests.unit.test_field_interface_closure_gateway import CreateTask, FIRST, VERSIONS


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", ["read_only", "ask_before_changes", "allow_changes"])
def test_dependent_class_field_explains_create_then_configure(tmp_path: Path, version: str, policy: str):
    task = CreateTask(tmp_path, version)
    code, configured = task.run("config-set", "--project-modification-policy", policy)
    assert code == 0, configured
    task.objects[FIRST].update({"type": "WorkUnit", "name": "Default Work Unit", "path": r"\Game Parameters\Default Work Unit"})
    task.types.append({"classId": 20, "name": "GameParameter", "type": "WObject"})
    # Synthetic dependency shape establishes the existing object-only boundary;
    # native GameParameter dependency evidence is recorded by the isolated probe.
    task.metadata = {
        "InitialValue": {"name": "InitialValue", "type": "Real64", "dependencies": [{"property": "ControlMode"}]},
        "ControlMode": {"name": "ControlMode", "type": "int32", "default": 0},
    }
    task.bind(FIRST)
    kind = task.discover_kind("GameParameter")
    revision = task.revision
    code, failed = task.step("draft-discover-fields", "--type-handle", kind, "--meaning", "InitialValue")
    assert code == 2, failed
    row = failed["details"]["rejected_candidates"][0]
    assert row["error_code"] == "FIELD_OBJECT_SCOPE_REQUIRED"
    recovery = row["details"]["new_object_workflow"]
    assert recovery["configuration_operation"] == "object.setProperty"
    assert recovery["configuration_identity"] == "verified_created_object_GUID"
    assert recovery["field_selection"] == "rediscover_in_object_scope_and_copy_Field_Handle"
    assert recovery["configuration_meaning"] == "InitialValue"
    assert recovery["creation_is_not_configuration_completion"] is True
    assert recovery["repeat_creation_after_success"] is False
    assert recovery["authorization"] == "each_Preview_uses_current_modification_policy"
    assert task.revision == revision
    assert not any(uri in {"ak.wwise.core.object.create", "ak.wwise.core.object.setProperty"} for uri, _, _ in task.calls)


CREATED = "{33333333-3333-3333-3333-333333333333}"
EXISTING = "{44444444-4444-4444-4444-444444444444}"


class ParameterTask(CreateTask):
    def __init__(self, path, version):
        super().__init__(path, version)
        self.objects = {
            FIRST: {"id": FIRST, "name": "Default Work Unit", "type": "WorkUnit",
                    "path": r"\Game Parameters\Default Work Unit", "parent": {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"}},
        }
        self.objects[EXISTING] = {"id": EXISTING, "name": "KeepExisting", "type": "GameParameter",
                                  "path": self.objects[FIRST]["path"] + r"\KeepExisting", "parent": {"id": FIRST},
                                  "Min": 11.0, "Max": 23.0, "InitialValue": 17.0}
        self.types = [{"classId": 1, "name": "WorkUnit", "type": "WObject"},
                      {"classId": 20, "name": "GameParameter", "type": "WObject"}]
        self.metadata = {name: {"name": name, "type": "Real64", "dependencies": [{"property": "ControlMode"}]}
                         for name in ("Min", "Max", "InitialValue")}
        self.metadata["ControlMode"] = {"name": "ControlMode", "type": "int32", "default": 0}
        self.fail_property = None

    def call(self, uri, args=None, options=None):
        if uri == "ak.wwise.core.object.create":
            self.calls.append((uri, args, options))
            assert CREATED not in self.objects, "duplicate creation"
            self.objects[CREATED] = {"id": CREATED, "name": args["name"], "type": "GameParameter",
                                    "path": self.objects[FIRST]["path"] + "\\" + args["name"],
                                    "parent": {"id": FIRST}, "Min": 0.0, "Max": 100.0, "InitialValue": 0.0}
            return {key: self.objects[CREATED][key] for key in ("id", "name", "type", "path")}
        if uri == "ak.wwise.core.object.isPropertyEnabled":
            self.calls.append((uri, args, options))
            assert args["object"] == CREATED
            return {"return": True}
        if uri == "ak.wwise.core.object.setProperty":
            self.calls.append((uri, args, options))
            if args["property"] == self.fail_property:
                raise RuntimeError("fixture configuration failure")
            self.objects[args["object"]][args["property"]] = args["value"]
            return {}
        result = super().call(uri, args, options)
        if (getattr(self, "ambiguous_created_readback", False)
                and uri == "ak.wwise.core.object.get" and args.get("from", {}).get("id") == [CREATED]
                and not args.get("transform")):
            result["return"] = result["return"] * 2
        return result

    def start_configuration(self, created_id, meaning, value):
        code, started = self.run("draft-start", "object.setProperty")
        assert code == 0, started
        self.draft, self.authority, self.revision = started["draft"]["draft_id"], started["task_authority"], started["draft"]["revision"]
        target = self.bind(created_id)
        field = self.discover(target, meaning)
        code, declared = self.step("draft-declare-field-change", "--object-handle", target,
                                   "--field-handle", field, "--business-value", str(value))
        assert code == 0, declared

    def transaction(self, policy):
        code, checked = self.step("draft-check")
        assert code == 0, checked
        code, preview = self.step("preview-from-draft", *(["--apply"] if policy == "allow_changes" else []))
        if policy == "read_only":
            assert code == 2, preview
            return code, preview
        assert code == 0, preview
        tx = preview["transaction_id"]
        if policy == "ask_before_changes":
            code, shown = self.run("transaction-show", tx)
            assert code == 0, shown
            code, confirmed = self.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
            assert code == 0, confirmed
        code, executed = self.run("execute", tx)
        if code:
            return code, executed
        code, verified = self.run("verify", tx)
        assert code == 0 and verified["verified"] is True, verified
        return code, verified


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", ["read_only", "ask_before_changes", "allow_changes"])
def test_explicit_stages_configure_verified_created_object_once(tmp_path: Path, version: str, policy: str):
    task = ParameterTask(tmp_path, version)
    code, configured = task.run("config-set", "--project-modification-policy", policy)
    assert code == 0, configured
    preserved = deepcopy(task.objects[EXISTING])
    parent = task.bind(FIRST)
    kind = task.discover_kind("GameParameter")
    code, failed = task.step("draft-discover-fields", "--type-handle", kind, "--meaning", "InitialValue")
    assert code == 2, failed
    recovery = failed["details"]["rejected_candidates"][0]["details"]["new_object_workflow"]
    code, declared = task.step("draft-declare-new", "--declaration-id", "control", "--parent-handle", parent,
                               "--name", "WeatherIntensity", "--kind", kind)
    assert code == 0, declared
    code, created = task.transaction(policy)
    if policy == "read_only":
        assert CREATED not in task.objects
        return
    assert code == 0, created
    assert list(created)[-1] == "agent_result"
    # Use the exact independently verified creation identity, not a repeated class lookup.
    created_id = created["agent_result"]["business_result"]["verified_root"]["id"]
    assert created_id == CREATED
    assert recovery["configuration_identity"] == "verified_created_object_GUID"
    calls_before_configuration = len(task.calls)
    for meaning, value in (("Min", -12), ("Max", 36), ("InitialValue", 7)):
        task.start_configuration(created_id, meaning, value)
        code, configured = task.transaction(policy)
        assert code == 0, configured
    assert (task.objects[CREATED]["Min"], task.objects[CREATED]["Max"], task.objects[CREATED]["InitialValue"]) == (-12, 36, 7)
    assert task.objects[EXISTING] == preserved
    assert sum(uri == "ak.wwise.core.object.create" for uri, _, _ in task.calls) == 1
    assert not any("classId" in (args or {}) for uri, args, _ in task.calls[calls_before_configuration:])


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("policy", ["ask_before_changes", "allow_changes"])
def test_partial_configuration_does_not_recreate_or_claim_completion(tmp_path: Path, version: str, policy: str):
    task = ParameterTask(tmp_path, version)
    code, configured = task.run("config-set", "--project-modification-policy", policy)
    assert code == 0, configured
    parent = task.bind(FIRST)
    kind = task.discover_kind("GameParameter")
    code, declared = task.step("draft-declare-new", "--declaration-id", "control", "--parent-handle", parent,
                               "--name", "WeatherIntensity", "--kind", kind)
    assert code == 0, declared
    code, created = task.transaction(policy)
    assert code == 0, created
    created_id = created["agent_result"]["business_result"]["verified_root"]["id"]
    task.start_configuration(created_id, "Min", -12)
    code, completed_min = task.transaction(policy)
    assert code == 0, completed_min
    task.fail_property = "Max"
    task.start_configuration(created_id, "Max", 36)
    code, failed = task.transaction(policy)
    assert code == 2 and failed.get("verified") is not True, failed
    assert failed["automatic_retry"] is False
    assert task.objects[CREATED]["Min"] == -12
    assert task.objects[CREATED]["Max"] == 100
    assert sum(uri == "ak.wwise.core.object.create" for uri, _, _ in task.calls) == 1
    assert task.objects[EXISTING]["InitialValue"] == 17


@pytest.mark.parametrize("version", VERSIONS)
def test_ambiguous_creation_verification_discloses_no_root_identity(tmp_path: Path, version: str):
    task = ParameterTask(tmp_path, version)
    parent = task.bind(FIRST)
    kind = task.discover_kind("GameParameter")
    code, declared = task.step("draft-declare-new", "--declaration-id", "control", "--parent-handle", parent,
                               "--name", "WeatherIntensity", "--kind", kind)
    assert code == 0, declared
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
    task.ambiguous_created_readback = True
    code, failed = task.run("verify", tx)
    assert code == 2 and failed.get("verified") is not True, failed
    assert not failed.get("agent_result")
    assert sum(uri == "ak.wwise.core.object.create" for uri, _, _ in task.calls) == 1


class NativeParameterTask(ParameterTask):
    def __init__(self, path, version):
        super().__init__(path, version)
        import json
        fixture = Path(__file__).parents[1] / "fixtures" / "gameparameter-metadata" / f"{version}.json"
        self.metadata = json.loads(fixture.read_text(encoding="utf-8"))["metadata"]

    def call(self, uri, args=None, options=None):
        result = super().call(uri, args, options)
        if uri == "ak.wwise.core.object.getPropertyInfo":
            return deepcopy(result)
        if uri == "ak.wwise.core.object.create":
            self.objects[CREATED]["BindToBuiltInParam"] = self.metadata["BindToBuiltInParam"]["default"]
            for key, value in args.items():
                if key.startswith("@"):
                    self.objects[CREATED][key[1:]] = value
        return result

    def declare_complete_parameter(self, *, builtin=None):
        parent = self.bind(FIRST)
        kind = self.discover_kind("GameParameter")
        fields = []
        settings = [("Min", -12), ("Max", 36), ("InitialValue", 7)]
        if builtin is not None:
            settings.append(("BindToBuiltInParam", builtin))
        for meaning, value in settings:
            code, found = self.step("draft-discover-fields", "--type-handle", kind, "--meaning", meaning)
            assert code == 0, found
            fields.extend(["--field-value", found["field_candidates"][0]["handle"], str(value)])
        code, declared = self.step("draft-declare-new", "--declaration-id", "parameter", "--parent-handle", parent,
                                   "--name", "WeatherIntensity", "--kind", kind, *fields)
        assert code == 0, declared


@pytest.mark.parametrize("version", VERSIONS)
def test_live_default_conditions_allow_same_call_creation(tmp_path: Path, version: str):
    task = NativeParameterTask(tmp_path, version)
    task.declare_complete_parameter()
    code, verified = task.transaction("ask_before_changes")
    assert code == 0, verified
    assert (task.objects[CREATED]["Min"], task.objects[CREATED]["Max"], task.objects[CREATED]["InitialValue"]) == (-12, 36, 7)
    writes = [(uri, args) for uri, args, _ in task.calls if uri in {"ak.wwise.core.object.create", "ak.wwise.core.object.setProperty"}]
    assert len(writes) == 1
    assert writes[0][0] == "ak.wwise.core.object.create"
    assert writes[0][1]["@Min"] == -12
    assert writes[0][1]["@Max"] == 36
    assert writes[0][1]["@InitialValue"] == 7


@pytest.mark.parametrize("version", VERSIONS)
def test_explicit_sibling_builtin_conflict_rejects_before_preview(tmp_path: Path, version: str):
    task = NativeParameterTask(tmp_path, version)
    task.declare_complete_parameter(builtin=1)
    code, failed = task.step("draft-check")
    assert code == 2, failed
    assert "NEW_OBJECT_DEPENDENCY_CONFLICT" in str(failed)
    assert CREATED not in task.objects

@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("phase", ["preview", "execute"])
def test_new_parameter_default_drift_blocks_without_creation(tmp_path: Path, version: str, phase: str):
    task = NativeParameterTask(tmp_path, version)
    task.declare_complete_parameter()
    code, checked = task.step("draft-check")
    assert code == 0, checked
    if phase == "execute":
        code, preview = task.step("preview-from-draft")
        assert code == 0, preview
        tx = preview["transaction_id"]
        code, shown = task.run("transaction-show", tx)
        assert code == 0, shown
        code, confirmed = task.run("confirm", tx, "--confirmation-token", shown["confirmation"]["token"])
        assert code == 0, confirmed
    task.metadata["BindToBuiltInParam"]["default"] = 1
    code, rejected = task.step("preview-from-draft") if phase == "preview" else task.run("execute", tx)
    assert code == 2, rejected
    assert CREATED not in task.objects
    assert not any(uri == "ak.wwise.core.object.create" for uri, _, _ in task.calls)

@pytest.mark.parametrize("version", VERSIONS)
def test_explicit_compatible_builtin_preserves_same_call(tmp_path: Path, version: str):
    task = NativeParameterTask(tmp_path, version)
    preserved = deepcopy(task.objects[EXISTING])
    task.declare_complete_parameter(builtin=0)
    code, verified = task.transaction("ask_before_changes")
    assert code == 0, verified
    assert task.objects[CREATED]["BindToBuiltInParam"] == 0
    assert task.objects[EXISTING] == preserved
    assert sum(uri == "ak.wwise.core.object.create" for uri, _, _ in task.calls) == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_unknown_class_condition_keeps_actionable_staged_boundary(tmp_path: Path, version: str):
    task = NativeParameterTask(tmp_path, version)
    task.metadata["Min"]["dependencies"][0]["context"] = "Parent"
    task.bind(FIRST)
    kind = task.discover_kind("GameParameter")
    code, rejected = task.step("draft-discover-fields", "--type-handle", kind, "--meaning", "Min")
    assert code == 2, rejected
    row = rejected["details"]["rejected_candidates"][0]
    assert row["error_code"] == "FIELD_OBJECT_SCOPE_REQUIRED"
    assert row["details"]["new_object_workflow"]["repeat_creation_after_success"] is False

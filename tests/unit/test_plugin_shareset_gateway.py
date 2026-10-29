from __future__ import annotations

import json

import pytest

from test_gateway_connection_binding import BindingClient
from test_gateway_session_context import configured_env, waapi_gateway as gateway

PARENT = "{22222222-2222-2222-2222-222222222222}"
PLUGIN = "{44444444-4444-4444-4444-444444444444}"
CLASS_ID = 7733251
VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")


class ShareSetClient(BindingClient):
    def __init__(self, version, *, target_type="WorkUnit", target_path="\\Effects\\Default Work Unit"):
        super().__init__(version)
        self.target = {"id": PARENT, "name": "Default Work Unit", "type": target_type, "path": target_path}
        self.calls = []
        self.created = False
        self.children = []
        self.available = True
        self.empty_result = False
        self.plugin_overrides = {}
        self.property_value = 0.5

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": [{"classId": CLASS_ID, "name": "Wwise RoomVerb", "type": "Effect"}] if self.available else []}
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            return {"return": ["RoomSize"]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            return {"name": "RoomSize", "type": "Real32", "default": 0.5, "min": 0.0, "max": 1.0}
        if uri == "ak.wwise.core.object.set":
            self.created = True
            if self.empty_result:
                return {"objects": []}
            return {"objects": [{"id": PARENT, "children": [{"id": PLUGIN, "name": "Room", "type": "Effect"}]}]}
        if uri == "ak.wwise.core.object.get" and "from type Project" not in args.get("waql", ""):
            if "@IsVoice" in options.get("return", []):
                return {"return": [{**self.target, "@IsVoice": False}]}
            if PLUGIN in json.dumps(args):
                plugin = {"id": PLUGIN, "name": "Room", "type": "Effect", "classId": CLASS_ID, "parent": {"id": PARENT}, "path": self.target["path"] + "\\Room"}
                plugin["@RoomSize"] = self.property_value
                plugin.update(self.plugin_overrides)
                return {"return": [{field: plugin[field] for field in options["return"] if field in plugin}]}
            if args.get("transform"):
                return {"return": self.children + ([{"id": PLUGIN, "name": "Room", "type": "Effect", "parent": {"id": PARENT}}] if self.created else [])}
            return {"return": [self.target]}
        return super().call(uri, args, options)


def declare_plugin(tmp_path, version, client, placement="shareset", with_property=False):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, result = gateway.execute_gateway(["draft-start", "object.createPlugin"], env=env)
    assert code == 0, result
    draft_id, authority = result["draft"]["draft_id"], result["task_authority"]
    def step(command, *fields):
        nonlocal result
        code, result = gateway.execute_gateway([command, draft_id, "--task-authority", authority, "--expected-revision", str(result["draft"]["revision"]), *fields], env=env, client_factory=lambda _: client)
        return code, result
    code, bound = step("draft-bind-object", "--object-id", PARENT)
    assert code == 0, bound
    code, types = step("draft-discover-types", "--role", "effect", "--meaning", "Wwise RoomVerb")
    assert code == 0, types
    extra = []
    if with_property:
        code, fields = step("draft-discover-fields", "--type-handle", types["type_candidates"][0]["handle"], "--meaning", "room size")
        assert code == 0, fields
        extra = ["--field-value", fields["field_candidates"][0]["handle"], "0.5"]
    code, declared = step("draft-declare-existing", "--declaration-id", "reverb", "--object-handle", bound["bound_object"]["handle"], "--field", "plugin_role", "effect", "--field", "plugin_placement", placement, "--field", "plugin_name", "Room", "--field", "plugin_type_handle", types["type_candidates"][0]["handle"], *extra)
    return code, declared, step, env


@pytest.mark.parametrize("version", VERSIONS)
def test_shareset_placement_is_a_public_business_declaration(tmp_path, version):
    code, declared, _, _ = declare_plugin(tmp_path, version, ShareSetClient(version))
    assert code == 0, declared


def test_2021_plugin_creation_is_explicitly_unavailable(tmp_path):
    code, result = gateway.execute_gateway(["draft-start", "object.createPlugin"], env=configured_env(tmp_path, version="2021.1"))
    assert code == 2
    assert result["error_code"] == "UNAVAILABLE_IN_VERSION"


@pytest.mark.parametrize("version", VERSIONS)
def test_shareset_preview_uses_work_unit_children_without_owner_effect_reads(tmp_path, version):
    client = ShareSetClient(version)
    code, declared, step, env = declare_plugin(tmp_path, version, client)
    assert code == 0, declared
    code, checked = step("draft-check")
    assert code == 0, checked
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    code, shown = gateway.execute_gateway(["transaction-show", preview["transaction_id"]], env=env)
    assert code == 0, shown
    dispatch = shown["artifact"]["prepared_operation"]["dispatch"]
    assert dispatch["args"]["objects"] == [{"object": PARENT, "onNameConflict": "fail", "children": [{"type": "Effect", "name": "Room", "classId": CLASS_ID}]}]
    assert not any("@Effect" in json.dumps((args, options)) for uri, args, options in client.calls if uri == "ak.wwise.core.object.get")


@pytest.mark.parametrize("version", VERSIONS)
def test_work_unit_is_not_an_owner_effect_target(tmp_path, version):
    client = ShareSetClient(version)
    code, result, step, _ = declare_plugin(tmp_path, version, client, placement="owner")
    if code == 0:
        code, result = step("draft-check")
    assert code == 2, result
    assert result["error_code"] == "INVALID_EFFECT_TARGET"
    assert not any("@Effect" in json.dumps((args, options)) for uri, args, options in client.calls if uri == "ak.wwise.core.object.get")


def execute_shareset(tmp_path, version, client, *, with_property=False):
    code, declared, step, env = declare_plugin(tmp_path, version, client, with_property=with_property)
    assert code == 0, declared
    code, checked = step("draft-check")
    assert code == 0, checked
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    transaction_id = preview["transaction_id"]
    code, shown = gateway.execute_gateway(["transaction-show", transaction_id], env=env)
    assert code == 0, shown
    code, confirmed = gateway.execute_gateway(["confirm", transaction_id, "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, confirmed
    if getattr(client, "disappear_before_execute", False):
        client.available = False
    code, executed = gateway.execute_gateway(["execute", transaction_id], env=env, client_factory=lambda _: client)
    if code != 0:
        return code, executed
    code, verified = gateway.execute_gateway(["verify", transaction_id], env=env, client_factory=lambda _: client)
    assert sum(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls) == 1
    return code, verified


@pytest.mark.parametrize("version", VERSIONS)
def test_shareset_executes_once_and_verifies_its_own_identity(tmp_path, version):
    code, verified = execute_shareset(tmp_path, version, ShareSetClient(version))
    assert code == 0, verified
    assert verified["state"] == "verified"


@pytest.mark.parametrize("version", VERSIONS)
def test_shareset_properties_use_field_handles_and_readback(tmp_path, version):
    code, verified = execute_shareset(tmp_path, version, ShareSetClient(version), with_property=True)
    assert code == 0, verified
    assert verified["state"] == "verified"


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("failure", ["empty", "parent", "class", "name", "type", "property"])
def test_shareset_never_claims_success_without_exact_result_and_readback(tmp_path, version, failure):
    client = ShareSetClient(version)
    client.empty_result = failure == "empty"
    client.plugin_overrides = {
        "parent": {"parent": {"id": "{55555555-5555-5555-5555-555555555555}"}},
        "class": {"classId": 1}, "name": {"name": "Wrong"}, "type": {"type": "Sound"},
    }.get(failure, {})
    if failure == "property":
        client.property_value = 0.75
    code, result = execute_shareset(tmp_path, version, client, with_property=failure == "property")
    assert code == 2, result
    assert result["state"] == "verification_failed"


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("failure", ["hierarchy", "type", "conflict", "unavailable"])
def test_shareset_preflight_rejects_incompatible_or_stale_targets(tmp_path, version, failure):
    client = ShareSetClient(version, target_type="Sound" if failure == "type" else "WorkUnit", target_path="\\Actor-Mixer Hierarchy\\Default Work Unit" if failure == "hierarchy" else "\\Effects\\Default Work Unit")
    code, result, step, _ = declare_plugin(tmp_path, version, client)
    assert code == 0, result
    if failure == "conflict":
        client.children = [{"id": PLUGIN, "name": "Room", "type": "Effect", "parent": {"id": PARENT}}]
    if failure == "unavailable":
        client.available = False
    code, result = step("draft-check")
    assert code == 2, result
    assert result["error_code"] in {"INVALID_SHARESET_TARGET", "SHARESET_NAME_CONFLICT", "PLUGIN_TYPE_UNAVAILABLE", "TYPE_HANDLE_STALE"}
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


class OwnerClient(ShareSetClient):
    def __init__(self, version):
        super().__init__(version, target_type="Sound", target_path="\\Actor-Mixer Hierarchy\\Default Work Unit\\Sound")

    def call(self, uri, args=None, options=None):
        fields = (options or {}).get("return", [])
        if uri == "ak.wwise.core.object.get" and any(field.startswith("@Effect") for field in fields):
            self.calls.append((uri, args, options))
            return {"return": [{"id": PARENT, **{field: [] if field == "@Effects" else None for field in fields if field.startswith("@Effect")}}]}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS)
def test_owner_effect_preview_retains_its_versioned_slot_topology(tmp_path, version):
    client = OwnerClient(version)
    code, declared, step, env = declare_plugin(tmp_path, version, client, placement="owner")
    assert code == 0, declared
    code, checked = step("draft-check")
    assert code == 0, checked
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    code, shown = gateway.execute_gateway(["transaction-show", preview["transaction_id"]], env=env)
    assert code == 0, shown
    target = shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"][0]
    assert "children" not in target
    if version == "2022.1":
        assert target["@Effect0"]["classId"] == CLASS_ID
    else:
        assert target["@Effects"][0]["type"] == "EffectSlot"
        assert target["@Effects"][0]["@Effect"]["classId"] == CLASS_ID


@pytest.mark.parametrize("version", VERSIONS)
def test_shareset_plugin_disappearing_after_preview_prevents_dispatch(tmp_path, version):
    client = ShareSetClient(version)
    client.disappear_before_execute = True
    code, result = execute_shareset(tmp_path, version, client)
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)

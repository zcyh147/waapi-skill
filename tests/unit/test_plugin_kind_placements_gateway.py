"""Public plugin-kind placement contracts; native effects need separate evidence."""
from __future__ import annotations

import json
import pytest

from test_plugin_shareset_gateway import ShareSetClient, PARENT, PLUGIN
from test_gateway_session_context import configured_env, waapi_gateway as gateway

VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")
# Exact IDs from the independently reflected getTypes resources, never calculated.
KINDS = {
    "sink": (11403271, "System", "AudioDevice", "\\Audio Devices\\Default Work Unit"),
    "metadata": (58982409, "Wwise System Output Settings", "Metadata", "\\Metadata\\Default Work Unit"),
}


class KindClient(ShareSetClient):
    def __init__(self, version, kind):
        self.kind = kind
        self.class_id, self.plugin_label, self.native_type, path = KINDS[kind]
        super().__init__(version, target_path=path)
        self.drop_existing = False
        self.mix = 1

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == "ak.wwise.core.object.getTypes":
            self.calls.append((uri, args, options))
            return {"return": [{"classId": self.class_id, "name": self.plugin_label, "type": self.native_type}] if self.available else []}
        if uri == "ak.wwise.core.object.get" and args.get("transform") and self.created:
            self.calls.append((uri, args, options))
            return {"return": ([] if self.drop_existing else self.children) + [{"id": PLUGIN, "name": "Created", "type": self.native_type, "parent": {"id": PARENT}}]}
        if self.kind == "metadata" and uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            self.calls.append((uri, args, options))
            return {"return": ["Mix"]}
        if self.kind == "metadata" and uri == "ak.wwise.core.object.getPropertyInfo":
            self.calls.append((uri, args, options))
            return {"name": "Mix", "type": "int32", "default": 0,
                "restriction": {"type": "enum", "values": [
                    {"value": 0, "displayName": "Use Default"}, {"value": 1, "displayName": "Mix to Main"},
                    {"value": 2, "displayName": "Mix to Passthrough"}]}}
        if uri == "ak.wwise.core.object.set":
            self.calls.append((uri, args, options))
            self.created = True
            return {"objects": [{"id": PARENT, "children": [{"id": PLUGIN, "name": "Created", "type": self.native_type}]}]}
        if uri == "ak.wwise.core.object.get" and PLUGIN in json.dumps(args):
            self.calls.append((uri, args, options))
            row = {"id": PLUGIN, "name": "Created", "type": self.native_type, "classId": self.class_id,
                   "parent": {"id": PARENT}, "path": self.target["path"] + "\\Created", "@Mix": self.mix}
            row.update(self.plugin_overrides)
            return {"return": [{field: row[field] for field in options["return"] if field in row}]}
        return super().call(uri, args, options)


def declare(tmp_path, version, client, *, kind=None, placement="shareset", mix=None):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, result = gateway.execute_gateway(["draft-start", "object.createPlugin"], env=env)
    assert code == 0, result
    draft_id, authority = result["draft"]["draft_id"], result["task_authority"]
    def step(command, *args):
        nonlocal result
        code, result = gateway.execute_gateway([command, draft_id, "--task-authority", authority,
            "--expected-revision", str(result["draft"]["revision"]), *args], env=env, client_factory=lambda _: client)
        return code, result
    code, target = step("draft-bind-object", "--object-id", PARENT)
    assert code == 0, target
    code, types = step("draft-discover-types", "--role", client.kind, "--meaning", client.plugin_label)
    assert code == 0, types
    extra = []
    if mix is not None:
        code, fields = step("draft-discover-fields", "--type-handle", types["type_candidates"][0]["handle"], "--meaning", "Mix")
        assert code == 0, fields
        extra = ["--field-value", fields["field_candidates"][0]["handle"], str(mix)]
    code, result = step("draft-declare-existing", "--declaration-id", "plugin", "--object-handle", target["bound_object"]["handle"],
        "--field", "plugin_role", kind or client.kind, "--field", "plugin_name", "Created", "--field", "plugin_placement", placement,
        "--field", "plugin_type_handle", types["type_candidates"][0]["handle"], *extra)
    return code, result, step, env


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("kind", KINDS)
def test_independent_plugin_kind_uses_exact_live_class_and_hierarchy(tmp_path, version, kind):
    client = KindClient(version, kind)
    code, result, step, env = declare(tmp_path, version, client)
    assert code == 0, result
    code, result = step("draft-check")
    assert code == 0, result
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    code, shown = gateway.execute_gateway(["transaction-show", preview["transaction_id"]], env=env)
    assert code == 0, shown
    dispatch = shown["artifact"]["prepared_operation"]["dispatch"]
    assert dispatch["args"]["objects"] == [{"object": PARENT, "onNameConflict": "fail", "children": [
        {"type": client.native_type, "name": "Created", "classId": client.class_id}]}]
    code, result = gateway.execute_gateway(["confirm", preview["transaction_id"], "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, result
    code, result = gateway.execute_gateway(["execute", preview["transaction_id"]], env=env, client_factory=lambda _: client)
    assert code == 0, result
    code, result = gateway.execute_gateway(["verify", preview["transaction_id"]], env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, indent=2)
    assert result["state"] == "verified"
    assert sum(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls) == 1
    assert not any("@Effect" in json.dumps((args, options)) for uri, args, options in client.calls if uri == "ak.wwise.core.object.get")


def test_creation_rejects_verification_when_an_unrelated_child_disappears(tmp_path):
    client = KindClient("2025.1", "sink")
    client.children = [{"id": "{55555555-5555-5555-5555-555555555555}", "name": "Existing", "type": "AudioDevice", "parent": {"id": PARENT}}]
    code, result, step, env = declare(tmp_path, "2025.1", client)
    assert code == 0, result
    code, result = step("draft-check")
    assert code == 0, result
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    transaction_id = preview["transaction_id"]
    code, shown = gateway.execute_gateway(["transaction-show", transaction_id], env=env)
    assert code == 0, shown
    code, result = gateway.execute_gateway(["confirm", transaction_id, "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, result
    code, result = gateway.execute_gateway(["execute", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 0, result
    client.drop_existing = True
    code, result = gateway.execute_gateway(["verify", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert result["state"] == "verification_failed"
    assert sum(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls) == 1


class ReferencePluginClient(ShareSetClient):
    TARGET = "{66666666-6666-6666-6666-666666666666}"
    def __init__(self, version):
        super().__init__(version)
        self.omit_reference_type = False
        self.reference_value = self.TARGET

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == "ak.wwise.core.object.getTypes":
            self.calls.append((uri, args, options))
            return {"return": [{"classId": 8454147, "name": "Wwise Meter", "type": "Effect"}]}
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            self.calls.append((uri, args, options))
            return {"return": ["GameParameter"]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            self.calls.append((uri, args, options))
            return {**({} if self.omit_reference_type else {"name": "GameParameter", "type": "Reference"}), "displayName": "Target Game Parameter", "default": None,
                    "restriction": {"type": "reference", "restrictions": [{"type": ["GameParameter"]}]}}
        if uri == "ak.wwise.core.object.get" and self.TARGET in json.dumps(args):
            self.calls.append((uri, args, options))
            rows = [{"id": self.TARGET, "name": "MeterValue", "type": "GameParameter", "path": "\\Game Parameters\\Default Work Unit\\MeterValue"}]
            if PARENT in json.dumps(args):
                rows.append(self.target)
            return {"return": rows}
        result = super().call(uri, args, options)
        if uri == "ak.wwise.core.object.get" and PLUGIN in json.dumps(args) and self.created:
            for row in result["return"]:
                if "classId" in options["return"]:
                    row["classId"] = 8454147
                if "@GameParameter" in options["return"]:
                    row["@GameParameter"] = {"id": self.reference_value}
        return result


def reference_declaration(tmp_path, version, client):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, result = gateway.execute_gateway(["draft-start", "object.createPlugin"], env=env)
    assert code == 0, result
    draft_id, authority = result["draft"]["draft_id"], result["task_authority"]
    def step(command, *args):
        nonlocal result
        code, result = gateway.execute_gateway([command, draft_id, "--task-authority", authority,
            "--expected-revision", str(result["draft"]["revision"]), *args], env=env, client_factory=lambda _: client)
        return code, result
    code, owner = step("draft-bind-object", "--object-id", PARENT)
    assert code == 0, owner
    code, reference = step("draft-bind-object", "--object-id", client.TARGET)
    assert code == 0, reference
    code, types = step("draft-discover-types", "--role", "effect", "--meaning", "Wwise Meter")
    assert code == 0, types
    code, fields = step("draft-discover-fields", "--type-handle", types["type_candidates"][0]["handle"], "--meaning", "GameParameter")
    assert code == 0, fields
    code, declared = step("draft-declare-existing", "--declaration-id", "plugin", "--object-handle", owner["bound_object"]["handle"],
        "--field", "plugin_role", "effect", "--field", "plugin_name", "Room", "--field", "plugin_placement", "shareset",
        "--field", "plugin_type_handle", types["type_candidates"][0]["handle"],
        "--field-value", fields["field_candidates"][0]["handle"], reference["bound_object"]["handle"])
    return code, declared, step, env


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("omit_type", [False, True])
def test_plugin_reference_field_handle_materializes_one_exact_native_reference(tmp_path, version, omit_type):
    client = ReferencePluginClient(version)
    client.omit_reference_type = omit_type
    code, result, step, env = reference_declaration(tmp_path, version, client)
    assert code == 0, result
    code, checked = step("draft-check")
    assert code == 0, checked
    code, preview = step("preview-from-draft")
    assert code == 0, preview
    code, shown = gateway.execute_gateway(["transaction-show", preview["transaction_id"]], env=env)
    assert code == 0, shown
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"]["objects"][0]["children"][0]["@GameParameter"] == client.TARGET
    code, result = gateway.execute_gateway(["confirm", preview["transaction_id"], "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, result
    code, result = gateway.execute_gateway(["execute", preview["transaction_id"]], env=env, client_factory=lambda _: client)
    assert code == 0, result
    code, result = gateway.execute_gateway(["verify", preview["transaction_id"]], env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, indent=2)
    assert result["state"] == "verified"


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("failure", ["hierarchy", "owner", "role", "conflict", "unavailable"])
def test_kind_placement_conflicts_reject_before_any_write(tmp_path, version, kind, failure):
    client = KindClient(version, kind)
    if failure == "hierarchy":
        client.target["path"] = "\\Effects\\Default Work Unit" if kind == "sink" else "\\Audio Devices\\Default Work Unit"
    if failure == "conflict":
        client.children = [{"id": PLUGIN, "name": "Created", "type": client.native_type, "parent": {"id": PARENT}}]
    code, result, step, _ = declare(tmp_path, version, client,
        kind="effect" if failure == "role" else None, placement="owner" if failure == "owner" else "shareset")
    if code == 0:
        if failure == "unavailable":
            client.available = False
        code, result = step("draft-check")
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


def confirmed_preview(step, env):
    code, result = step("draft-check")
    assert code == 0, result
    code, result = step("preview-from-draft")
    assert code == 0, result
    transaction_id = result["transaction_id"]
    code, shown = gateway.execute_gateway(["transaction-show", transaction_id], env=env)
    assert code == 0, shown
    code, result = gateway.execute_gateway(["confirm", transaction_id, "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, result
    return transaction_id


@pytest.mark.parametrize("version", VERSIONS)
def test_reference_effect_is_independent_of_native_creation_success(tmp_path, version):
    client = ReferencePluginClient(version)
    code, result, step, env = reference_declaration(tmp_path, version, client)
    assert code == 0, result
    transaction_id = confirmed_preview(step, env)
    code, result = gateway.execute_gateway(["execute", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 0, result
    client.reference_value = "{77777777-7777-7777-7777-777777777777}"
    code, result = gateway.execute_gateway(["verify", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert result["state"] == "verification_failed"
    code, retry = gateway.execute_gateway(["execute", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 2, retry
    assert sum(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("version", ("2021.1", *VERSIONS))
@pytest.mark.parametrize("role,label", [("source", "Wwise Tone Generator"), ("effect", "Wwise Meter"), ("sink", "System"), ("conversion", "PCM"), ("metadata", "Wwise System Output Settings")])
def test_all_five_live_plugin_kinds_have_distinct_type_handle_discovery(tmp_path, version, role, label):
    class CatalogClient(ShareSetClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.getTypes":
                return {"return": [
                    {"classId": 6684674, "name": "Wwise Tone Generator", "type": "Source"},
                    {"classId": 8454147, "name": "Wwise Meter", "type": "Effect"},
                    {"classId": 11403271, "name": "System", "type": "AudioDevice"},
                    {"classId": 65537, "name": "PCM", "type": "Conversion"},
                    {"classId": 58982409, "name": "Wwise System Output Settings", "type": "Metadata"}]}
            return super().call(uri, args, options)
    client = CatalogClient(version)
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    # This discovery is read-only even where createPlugin's native constructor
    # still has an explicit implementation boundary (notably 2021.1).
    code, start = gateway.execute_gateway(["draft-start", "object.create"], env=env)
    assert code == 0, start
    code, bound = gateway.execute_gateway(["draft-bind-object", start["draft"]["draft_id"],
        "--task-authority", start["task_authority"], "--expected-revision", str(start["draft"]["revision"]),
        "--object-id", PARENT], env=env, client_factory=lambda _: client)
    assert code == 0, bound
    code, result = gateway.execute_gateway(["draft-discover-types", start["draft"]["draft_id"],
        "--task-authority", start["task_authority"], "--expected-revision", str(bound["draft"]["revision"]),
        "--role", role, "--meaning", label], env=env, client_factory=lambda _: client)
    assert code == 0, result
    assert [row["label"] for row in result["type_candidates"]] == [label]
    assert result["type_candidates"][0]["role"] == role
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("kind", KINDS)
def test_kind_disappearing_after_preview_blocks_execution(tmp_path, version, kind):
    client = KindClient(version, kind)
    code, result, step, env = declare(tmp_path, version, client)
    assert code == 0, result
    transaction_id = confirmed_preview(step, env)
    client.available = False
    code, result = gateway.execute_gateway(["execute", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", VERSIONS)
def test_reference_metadata_drift_blocks_execution(tmp_path, version):
    client = ReferencePluginClient(version)
    code, result, step, env = reference_declaration(tmp_path, version, client)
    assert code == 0, result
    transaction_id = confirmed_preview(step, env)
    client.omit_reference_type = True  # Equivalent reference meaning still changes the sealed metadata observation.
    code, result = gateway.execute_gateway(["execute", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", VERSIONS)
def test_system_output_metadata_uses_class_field_handles_and_independent_mix_readback(tmp_path, version):
    client = KindClient(version, "metadata")
    code, result, step, env = declare(tmp_path, version, client, mix=1)
    assert code == 0, result
    transaction_id = confirmed_preview(step, env)
    code, result = gateway.execute_gateway(["execute", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 0, result
    code, result = gateway.execute_gateway(["verify", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 0, result
    dispatch = next(args for uri, args, _ in client.calls if uri == "ak.wwise.core.object.set")
    assert dispatch["objects"][0]["children"][0]["@Mix"] == 1


@pytest.mark.parametrize("version", VERSIONS)
def test_source_class_disappearing_after_preview_cannot_create_a_child(tmp_path, version):
    class SourceClient(KindClient):
        def __init__(self, version):
            ShareSetClient.__init__(self, version, target_type="Sound", target_path="\\Actor-Mixer Hierarchy\\Default Work Unit\\Sound")
            self.kind, self.class_id, self.plugin_label, self.native_type = "source", 6684674, "Wwise Tone Generator", "Source"
            self.drop_existing, self.mix = False, 1
    client = SourceClient(version)
    code, result, step, env = declare(tmp_path, version, client, placement="owner")
    assert code == 0, result
    transaction_id = confirmed_preview(step, env)
    client.available = False
    code, result = gateway.execute_gateway(["execute", transaction_id], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)

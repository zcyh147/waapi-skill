"""2025 custom Metadata uses the public plugin Draft and exact owned slot."""
from __future__ import annotations

import json

import pytest

from test_plugin_kind_placements_gateway import KindClient, declare, confirmed_preview
from test_plugin_shareset_gateway import PARENT, PLUGIN
from test_gateway_session_context import waapi_gateway as gateway

SLOT = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
OLD_SLOTS = ["{99999999-9999-9999-9999-999999999999}", "{77777777-7777-7777-7777-777777777777}"]
OLD_PLUGINS = ["{88888888-8888-8888-8888-888888888888}", "{66666666-6666-6666-6666-666666666666}"]


class LocalMetadataClient(KindClient):
    def __init__(self, version="2025.1"):
        super().__init__(version, "metadata")
        self.target.update(name="Sound", type="Sound", classId=65552,
            path="\\Actor-Mixer Hierarchy\\Default Work Unit\\Sound")
        self.slots = list(OLD_SLOTS)
        self.references = dict(zip(OLD_SLOTS, OLD_PLUGINS))
        self.slot_overrides = {}
        self.slot_reference_overrides = {}
        self.mix_metadata_type = "int32"
        self.result_override = None
        self.slot_metadata = {"name": "Metadata", "type": "Reference", "restriction": {
            "type": "reference", "restrictions": [{"type": ["Metadata"]}, "notNull"]}}

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == "ak.wwise.core.object.getPropertyInfo" and args.get("property") == "Mix":
            result = super().call(uri, args, options)
            return {**result, "type": self.mix_metadata_type}
        if uri == "ak.wwise.core.object.getPropertyInfo" and args.get("classId") == 5570560:
            self.calls.append((uri, args, options))
            return self.slot_metadata
        if uri == "ak.wwise.core.object.set":
            self.calls.append((uri, args, options))
            self.created = True
            self.slots.append(SLOT)
            self.references[SLOT] = PLUGIN
            return self.result_override or {"objects": [{"id": PARENT, "@Metadata": [
                {"id": SLOT, "name": "", "type": "PluginInnerObject", "@Metadata": [{"id": PLUGIN}]}]}]}
        if uri == "ak.wwise.core.object.get" and "from type Project" not in args.get("waql", ""):
            ids = args.get("from", {}).get("id", [])
            if ids and all(identity in [*OLD_SLOTS, SLOT] for identity in ids):
                self.calls.append((uri, args, options))
                rows = []
                for identity in reversed(ids):  # Native detail order is not membership order.
                    row = {"id": identity, "name": "", "type": "PluginInnerObject", "classId": 5570560,
                        "owner": {"id": PARENT}, "@Metadata": [{"id": self.references.get(identity)}]}
                    row.update(self.slot_overrides)
                    row.update(self.slot_reference_overrides.get(identity, {}))
                    rows.append({field: row[field] for field in options["return"] if field in row})
                return {"return": rows}
            if ids == [PARENT]:
                self.calls.append((uri, args, options))
                row = {**self.target, "@IsVoice": False, "@Metadata": [{"id": slot} for slot in self.slots]}
                return {"return": [{field: row[field] for field in options["return"] if field in row}]}
            if ids == [PLUGIN]:
                self.calls.append((uri, args, options))
                row = {"id": PLUGIN, "name": "Created", "type": "Metadata", "classId": self.class_id,
                    "owner": {"id": SLOT}, "@Mix": self.mix, **self.plugin_overrides}
                return {"return": [{field: row[field] for field in options["return"] if field in row}]}
        return super().call(uri, args, options)


def test_local_metadata_appends_one_owned_custom_plugin_and_preserves_ordered_slots(tmp_path):
    client = LocalMetadataClient()
    code, result, step, env = declare(tmp_path, "2025.1", client, placement="owner", mix=1)
    assert code == 0, result
    transaction = confirmed_preview(step, env)
    code, shown = gateway.execute_gateway(["transaction-show", transaction], env=env)
    assert code == 0, shown
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == {
        "objects": [{"object": PARENT, "listMode": "append", "@Metadata": [
            {"type": "MetadataSlot", "name": "", "@Metadata": {
                "type": "Metadata", "name": "Created", "classId": 58982409, "@Mix": 1}}]}],
        "autoAddToSourceControl": False}
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 0, result
    code, result = gateway.execute_gateway(["verify", transaction], env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, indent=2)
    assert result["state"] == "verified"
    assert client.slots == [*OLD_SLOTS, SLOT]
    code, replay = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 2, replay
    assert sum(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls) == 1


def test_local_metadata_live_reference_restriction_drift_blocks_execution(tmp_path):
    client = LocalMetadataClient()
    code, result, step, env = declare(tmp_path, "2025.1", client, placement="owner")
    assert code == 0, result
    transaction = confirmed_preview(step, env)
    client.slot_metadata["restriction"]["restrictions"] = [{"type": ["Metadata"], "sharedOnlyTypes": ["Metadata"]}, "notNull"]
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault", ["owner-class", "slot-owner", "duplicate-slot", "missing-reference", "wrong-reference-type"])
def test_local_metadata_requires_exact_owner_slot_and_reference_authority_before_preview(tmp_path, fault):
    client = LocalMetadataClient()
    code, result, step, _ = declare(tmp_path, "2025.1", client, placement="owner")
    assert code == 0, result
    if fault == "owner-class":
        client.target["classId"] = 1376272  # Source names Bus, not the bound Sound.
    elif fault == "slot-owner":
        client.slot_overrides["owner"] = {"id": PLUGIN}
    elif fault == "duplicate-slot":
        client.slots.append(OLD_SLOTS[0])
    elif fault == "missing-reference":
        client.references[OLD_SLOTS[0]] = None
    else:
        client.slot_metadata["type"] = "int32"
        client.slot_metadata["restriction"] = {}
    code, result = step("draft-check")
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault", ["installed-class", "property-metadata", "owner-class", "slot-reference", "slot-order"])
def test_local_metadata_revalidates_every_authority_and_order_before_one_write(tmp_path, fault):
    client = LocalMetadataClient()
    code, result, step, env = declare(tmp_path, "2025.1", client, placement="owner", mix=1)
    assert code == 0, result
    transaction = confirmed_preview(step, env)
    if fault == "installed-class":
        client.available = False
    elif fault == "property-metadata":
        client.mix_metadata_type = "int16"
    elif fault == "owner-class":
        client.target["classId"] = 1376272
    elif fault == "slot-reference":
        client.references[OLD_SLOTS[0]] = PLUGIN
    else:
        client.slots.reverse()
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault", ["slot-owner", "plugin-owner", "plugin-class", "plugin-guid", "reused-plugin",
    "old-reference", "old-order", "extra-slot", "duplicate-slot", "result-slot", "result-plugin"])
def test_local_metadata_never_confuses_native_success_with_owned_custom_state(tmp_path, fault):
    client = LocalMetadataClient()
    code, result, step, env = declare(tmp_path, "2025.1", client, placement="owner", mix=1)
    assert code == 0, result
    transaction = confirmed_preview(step, env)
    if fault == "result-slot":
        client.result_override = {"objects": [{"id": PARENT, "@Metadata": [{"id": OLD_SLOTS[0]}]}]}
    elif fault == "result-plugin":
        client.result_override = {"objects": [{"id": PARENT, "@Metadata": [{"id": SLOT, "@Metadata": [{"id": OLD_PLUGINS[0]}]}]}]}
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 0, result
    if fault == "slot-owner":
        client.slot_reference_overrides[SLOT] = {"owner": {"id": PLUGIN}}
    elif fault == "plugin-owner":
        client.plugin_overrides["owner"] = {"id": PARENT}
    elif fault == "plugin-class":
        client.plugin_overrides["classId"] = 11403271
    elif fault == "plugin-guid":
        client.plugin_overrides["id"] = OLD_PLUGINS[0]
    elif fault == "reused-plugin":
        client.references[SLOT] = OLD_PLUGINS[0]
    elif fault == "old-reference":
        client.references[OLD_SLOTS[0]] = PLUGIN
    elif fault == "old-order":
        client.slots[:2] = reversed(client.slots[:2])
    elif fault == "extra-slot":
        client.slots.append("{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}")
    elif fault == "duplicate-slot":
        client.slots.append(SLOT)
    code, result = gateway.execute_gateway(["verify", transaction], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert result["state"] == "verification_failed"
    code, replay = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 2, replay
    assert sum(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls) == 1




def test_local_metadata_can_start_an_empty_list_with_immediate_plugin_ownership(tmp_path):
    client = LocalMetadataClient()
    client.slots = []
    client.references = {}
    client.plugin_overrides["parent"] = None
    code, result, step, env = declare(tmp_path, "2025.1", client, placement="owner")
    assert code == 0, result
    transaction = confirmed_preview(step, env)
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 0, result
    code, result = gateway.execute_gateway(["verify", transaction], env=env, client_factory=lambda _: client)
    assert code == 0 and result["state"] == "verified", result


class DirectMetadataClient(KindClient):
    def __init__(self, version="2023.1"):
        super().__init__(version, "metadata")
        self.target.update(name="Sound", type="Sound", classId=65552,
            path="\\Actor-Mixer Hierarchy\\Default Work Unit\\Sound")
        self.members = list(OLD_PLUGINS)
        self.omit_empty = False
        self.empty_probe_rows = []
        self.member_rows = {
            OLD_PLUGINS[0]: {"id": OLD_PLUGINS[0], "name": "Existing selected class", "type": "Metadata",
                "classId": self.class_id, "parent": {"id": OLD_SLOTS[0]}, "notes": "Keep shared parent"},
            OLD_PLUGINS[1]: {"id": OLD_PLUGINS[1], "name": "Existing base", "type": "Metadata", "classId": 5308432,
                "owner": None, "parent": None},
            PLUGIN: {"id": PLUGIN, "name": "Created", "type": "Metadata", "classId": self.class_id, "@Mix": 1}}
        self.result_override = None

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == "ak.wwise.core.object.set":
            self.calls.append((uri, args, options))
            self.created = True
            self.members.append(PLUGIN)
            return self.result_override or {"objects": [{"id": PARENT, "@Metadata": [{"id": PLUGIN, "name": "Created", "type": "Metadata"}]}]}
        if uri == "ak.wwise.core.object.get" and "select @Metadata take 1" in args.get("waql", ""):
            self.calls.append((uri, args, options))
            return {"return": self.empty_probe_rows}
        if uri == "ak.wwise.core.object.get" and "from type Project" not in args.get("waql", ""):
            ids = args.get("from", {}).get("id", [])
            if ids == [PARENT]:
                self.calls.append((uri, args, options))
                row = {**self.target, "@IsVoice": False, "@Metadata": [{"id": identity} for identity in self.members]}
                if self.omit_empty and not self.members:
                    row.pop("@Metadata")
                return {"return": [{field: row[field] for field in options["return"] if field in row}]}
            if ids and all(identity in self.member_rows for identity in ids):
                self.calls.append((uri, args, options))
                return {"return": [{field: self.member_rows[identity][field] for field in options["return"]
                    if field in self.member_rows[identity]} for identity in reversed(ids)]}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", ["2022.1", "2023.1", "2024.1"])
def test_older_metadata_appends_direct_selected_class_and_discloses_ownership_observation(tmp_path, version):
    client = DirectMetadataClient(version)
    code, result, step, env = declare(tmp_path, version, client, placement="owner", mix=1)
    assert code == 0, result
    code, result = step("draft-check")
    assert code == 0, result
    code, result = step("preview-from-draft")
    assert code == 0, result
    transaction = result["transaction_id"]
    code, shown = gateway.execute_gateway(["transaction-show", transaction, "--summary-only"], env=env)
    assert code == 0, shown
    preview = shown["preview_summary"]
    assert preview["metadata_placement_verification"]["intrinsic_ownership"] == "observed_key_presence_and_value_only"
    code, full = gateway.execute_gateway(["transaction-show", transaction], env=env)
    assert code == 0, full
    code, result = gateway.execute_gateway(["confirm", transaction, "--confirmation-token", full["confirmation"]["token"]], env=env)
    assert code == 0, result
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 0, result
    code, result = gateway.execute_gateway(["verify", transaction], env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, indent=2)
    assert result["verification"]["business_state_verified"] is False
    assert result["verification"]["verification_strength"] == "direct_metadata_list_and_plugin_fields"
    assert result["agent_result"]["verified"] is False
    assert next(args for uri, args, _ in client.calls if uri == "ak.wwise.core.object.set") == {
        "objects": [{"object": PARENT, "listMode": "append", "@Metadata": [
        {"type": "Metadata", "name": "Created", "classId": 58982409, "@Mix": 1}]}], "autoAddToSourceControl": False}
    assert client.members == [*OLD_PLUGINS, PLUGIN]
    code, replay = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 2, replay
    assert sum(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls) == 1


def test_older_metadata_requires_native_owner_type_to_match_its_source_class(tmp_path):
    client = DirectMetadataClient()
    code, result, step, _ = declare(tmp_path, client.version, client, placement="owner")
    assert code == 0, result
    client.target["classId"] = 1376272  # Bus class with a Sound type is not authority.
    code, result = step("draft-check")
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault", ["wrong-kind", "unknown-class", "duplicate-member"])
def test_older_metadata_refuses_unproved_or_duplicate_current_members(tmp_path, fault):
    client = DirectMetadataClient()
    code, result, step, _ = declare(tmp_path, client.version, client, placement="owner")
    assert code == 0, result
    if fault == "wrong-kind":
        client.member_rows[OLD_PLUGINS[0]]["type"] = "Effect"
    elif fault == "unknown-class":
        client.member_rows[OLD_PLUGINS[0]]["classId"] = 8454147
    else:
        client.members.append(OLD_PLUGINS[0])
    code, result = step("draft-check")
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault", ["member-order", "observed-ownership", "installed-class"])
def test_older_metadata_rechecks_source_member_state_and_installed_class_before_write(tmp_path, fault):
    client = DirectMetadataClient()
    code, result, step, env = declare(tmp_path, client.version, client, placement="owner")
    assert code == 0, result
    transaction = confirmed_preview(step, env)
    if fault == "member-order":
        client.members.reverse()
    elif fault == "observed-ownership":
        client.member_rows[OLD_PLUGINS[0]]["owner"] = None  # Absent differs from explicit null.
    else:
        client.available = False
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault", ["wrong-result-member", "wrong-created-class", "wrong-created-guid", "prior-order", "prior-parent", "extra-member"])
def test_older_metadata_requires_exact_new_member_and_preserved_direct_list_after_native_success(tmp_path, fault):
    client = DirectMetadataClient()
    code, result, step, env = declare(tmp_path, client.version, client, placement="owner", mix=1)
    assert code == 0, result
    transaction = confirmed_preview(step, env)
    if fault == "wrong-result-member":
        client.result_override = {"objects": [{"id": PARENT, "@Metadata": [{"id": OLD_PLUGINS[0]}]}]}
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 0, result
    if fault == "wrong-created-class":
        client.member_rows[PLUGIN]["classId"] = 5308432
    elif fault == "wrong-created-guid":
        client.member_rows[PLUGIN]["id"] = OLD_PLUGINS[0]
    elif fault == "prior-order":
        client.members[:2] = reversed(client.members[:2])
    elif fault == "prior-parent":
        client.member_rows[OLD_PLUGINS[0]]["parent"] = None
    elif fault == "extra-member":
        client.members.append(OLD_PLUGINS[0])
    code, result = gateway.execute_gateway(["verify", transaction], env=env, client_factory=lambda _: client)
    assert code == 2 and result["state"] == "verification_failed", result
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert sum(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("contradiction", [False, True])
def test_older_metadata_omitted_empty_list_needs_independent_bounded_source_proof(tmp_path, contradiction):
    client = DirectMetadataClient("2022.1")
    client.members = []
    client.omit_empty = True
    if contradiction:
        client.empty_probe_rows = [{"id": OLD_PLUGINS[0]}]
    code, result, step, env = declare(tmp_path, client.version, client, placement="owner")
    assert code == 0, result
    if contradiction:
        code, result = step("draft-check")
        assert code == 2, result
        assert any("select @Metadata take 1" in args.get("waql", "") for _, args, _ in client.calls)
        assert not any(uri == "ak.wwise.core.object.set" for uri, _, _ in client.calls)
    else:
        transaction = confirmed_preview(step, env)
        code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
        assert code == 0, result
        code, result = gateway.execute_gateway(["verify", transaction], env=env, client_factory=lambda _: client)
        assert code == 0 and result["verification"]["business_state_verified"] is False, result


def test_older_metadata_uses_existing_actor_mixer_property_container_source_equivalence(tmp_path):
    client = DirectMetadataClient()
    client.target.update(type="ActorMixer", classId=524304)
    code, result, step, env = declare(tmp_path, client.version, client, placement="owner")
    assert code == 0, result
    transaction = confirmed_preview(step, env)
    code, result = gateway.execute_gateway(["execute", transaction], env=env, client_factory=lambda _: client)
    assert code == 0, result
    code, result = gateway.execute_gateway(["verify", transaction], env=env, client_factory=lambda _: client)
    assert code == 0 and result["verification"]["business_state_verified"] is False, result

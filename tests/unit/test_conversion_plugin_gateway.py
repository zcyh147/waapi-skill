"""Bounded codec setter invocation through the public Draft/transaction interface."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import pytest

from test_gateway_connection_binding import BindingClient
from test_gateway_session_context import configured_env, waapi_gateway as gateway

URI = "ak.wwise.core.audio.setConversionPlugin"
CONVERSION = "{22222222-2222-2222-2222-222222222222}"
WINDOWS = "{33333333-3333-3333-3333-333333333333}"
MAC = "{44444444-4444-4444-4444-444444444444}"
CODEC = "{55555555-5555-5555-5555-555555555555}"
OTHER_CODEC = "{66666666-6666-6666-6666-666666666666}"
OLD_CODEC = "{99999999-9999-9999-9999-999999999999}"


class ConversionClient(BindingClient):
    def __init__(self, version, conversion_id=CONVERSION):
        super().__init__(version)
        self.calls = []
        self.available = True
        self.attached = False
        self.no_effect = False
        self.change_other = False
        self.codec_owner = conversion_id
        self.quality = 3.0
        self.codec_class = 262145
        self.platforms = [{"id": WINDOWS, "name": "Windows"}, {"id": MAC, "name": "Mac"}]
        self.target = {"id": conversion_id, "name": "Voice", "type": "Conversion", "classId": 3604496,
                       "path": "\\Conversion Settings\\Default Work Unit\\Voice"}

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": [{"classId": self.codec_class, "name": "Vorbis", "type": "Conversion"}] if self.available else []}
        if uri == "ak.wwise.core.getProjectInfo":
            return {**super().call(uri, args, options), "platforms": deepcopy(self.platforms)}
        if uri == URI:
            self.attached = True
            return {}
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            return {"return": ["QualityFactor"] if args["object"] == CODEC and self.attached and not self.no_effect else ["MaxBitDepth"]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            if args["property"] == "MaxBitDepth":
                return {"name": "MaxBitDepth", "type": "int32", "default": 16,
                    "restriction": {"type": "enum", "values": [{"value": 16}, {"value": 24}]}}
            return {"name": "QualityFactor", "type": "Real32", "default": 3.0,
                "restriction": {"type": "range", "min": -2.0, "max": 10.0}}
        if uri == "ak.wwise.core.object.isPropertyEnabled":
            return {"return": True}
        if uri == "ak.wwise.core.object.setProperty":
            self.quality = args["value"]
            return {}
        if uri == "ak.wwise.core.object.get" and "conversionplugin" in args.get("waql", "").lower():
            is_windows = options["platform"] in {WINDOWS, "Windows"}
            selected = (self.attached and not self.no_effect) if is_windows else self.change_other
            row = {"id": (CODEC if selected else OLD_CODEC) if is_windows else OTHER_CODEC, "name": "", "type": "ConversionPlugin", "path": self.target["path"],
                "owner": {"id": self.codec_owner}, "classId": 262145 if selected else 65537,
                "pluginName": "Vorbis" if selected else "PCM"}
            return {"return": [{field: row[field] for field in options["return"] if field in row}]}
        if uri == "ak.wwise.core.object.get" and "from type Project" not in args.get("waql", ""):
            if any(identity in json.dumps(args) for identity in (CODEC, OTHER_CODEC, OLD_CODEC)):
                is_windows = any(identity in json.dumps(args) for identity in (CODEC, OLD_CODEC))
                selected = (self.attached and not self.no_effect) if is_windows else self.change_other
                row = {"id": (CODEC if selected else OLD_CODEC) if is_windows else OTHER_CODEC, "name": "", "type": "ConversionPlugin",
                    "path": self.target["path"], "owner": {"id": self.codec_owner},
                    "classId": 262145 if selected else 65537, "pluginName": "Vorbis" if selected else "PCM",
                    "@QualityFactor": self.quality, "QualityFactor": self.quality, "@MaxBitDepth": 16, "MaxBitDepth": 16}
                return {"return": [{field: row[field] for field in options["return"] if field in row}]}
            return {"return": [self.target]}
        return super().call(uri, args, options)


def declare(tmp_path, version, client, *, platform="Windows", type_role="conversion"):
    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, schema = gateway.execute_gateway(["request-schema", URI], env=env)
    assert code == 0, schema
    assert schema["business_adapter"]["declaration"]["field_types"]["plugin_type_handle"] == "bound_type_handle"
    semantics = schema["business_adapter"]["declaration"]["field_semantics"]
    assert semantics["platform_name"]["verification"] == "result_schema_checked"
    assert semantics["platform_name"]["business_state_verified"] is False
    assert "no codec GUID" in semantics["plugin_type_handle"]["configuration"]
    code, result = gateway.execute_gateway(schema["continuation"]["gateway_argv"], env=env)
    assert code == 0, result
    draft_id, authority = result["draft"]["draft_id"], result["task_authority"]

    def step(command, *args):
        nonlocal result
        code, result = gateway.execute_gateway([command, draft_id, "--task-authority", authority,
            "--expected-revision", str(result["draft"]["revision"]), *args], env=env, client_factory=lambda _: client)
        return code, result

    code, target = step("draft-bind-object", "--object-id", CONVERSION, "--role", "conversion")
    assert code == 0, target
    code, types = step("draft-discover-types", "--role", type_role, "--meaning", "Vorbis")
    assert code == 0, types
    code, result = step("draft-declare-core-plan", "--role", "conversion_handle", target["bound_object"]["handle"],
        "--value", "platform_name", platform, "--type", "plugin_type_handle", types["type_candidates"][0]["handle"])
    assert code == 0, result
    return step, env


def preview(step, env):
    code, result = step("draft-check")
    assert code == 0, json.dumps(result, indent=2)
    code, result = step("preview-from-draft")
    assert code == 0, result
    tx = result["transaction_id"]
    code, shown = gateway.execute_gateway(["transaction-show", tx], env=env)
    assert code == 0, shown
    if "conversion_plugin" in shown["artifact"]["prepared_operation"]["pre_state"]:
        code, summary = gateway.execute_gateway(["transaction-show", tx, "--summary-only"], env=env)
        assert code == 0, summary
        notice = summary["preview_summary"]["conversion_plugin"]
        assert notice["verification"] == "result_schema_checked"
        assert notice["business_state_verified"] is False
        assert "no codec GUID" in notice["configuration"]
    code, result = gateway.execute_gateway(["confirm", tx, "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, result
    return tx, shown


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_conversion_type_handle_invokes_setter_without_claiming_codec_or_platform_effect(tmp_path, version):
    client = ConversionClient(version)
    native_call = client.call

    def no_codec_enumeration(uri, args=None, options=None):
        if uri == "ak.wwise.core.object.get" and "conversionplugin" in (args or {}).get("waql", "").lower():
            pytest.fail("Setter must not infer a platform codec from enumeration")
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            pytest.fail("Setter has no authority to select an anonymous codec for field discovery")
        return native_call(uri, args, options)

    client.call = no_codec_enumeration
    step, env = declare(tmp_path, version, client)
    tx, shown = preview(step, env)
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == {
        "conversion": CONVERSION, "platform": "Windows", "plugin": "Vorbis"}
    assert shown["artifact"]["prepared_operation"]["dispatch"]["options"] == {}
    notice = shown["artifact"]["prepared_operation"]["semantic_preview"]["envelope"]["metadata"]["conversion_plugin"]
    assert notice["verification"] == "result_schema_checked"
    assert notice["business_state_verified"] is False
    assert notice["unverified"] == ["actual codec replacement", "platform-to-codec GUID association",
        "other platform codec and field preservation"]
    code, result = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, indent=2)
    code, result = gateway.execute_gateway(["verify", tx], env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, indent=2)
    assert result["state"] == "result_schema_checked"
    assert result["verified"] is False
    assert result["verification"]["business_state_verified"] is False
    assert result["agent_result"]["verified"] is False
    assert "conversion_codec" not in result["agent_result"].get("business_result", {})
    assert list(result)[-1] == "agent_result"
    assert sum(uri == URI for uri, _, _ in client.calls) == 1
    assert not any(uri == "ak.wwise.core.object.setProperty" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault", ["no_effect", "change_other"])
def test_native_acknowledgement_does_not_prove_conversion_or_other_platform_preservation(tmp_path, fault):
    client = ConversionClient("2025.1")
    step, env = declare(tmp_path, "2025.1", client)
    tx, _ = preview(step, env)
    code, result = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert code == 0, result
    setattr(client, fault, True)
    code, result = gateway.execute_gateway(["verify", tx], env=env, client_factory=lambda _: client)
    assert code == 0, result
    assert result["state"] == "result_schema_checked"
    assert result["verified"] is False
    assert result["verification"]["business_state_verified"] is False
    assert "conversion_codec" not in result.get("agent_result", {}).get("business_result", {})
    assert sum(uri == URI for uri, _, _ in client.calls) == 1


def test_conversion_rejects_unknown_platform_before_write(tmp_path):
    client = ConversionClient("2025.1")
    step, _ = declare(tmp_path, "2025.1", client, platform="Imaginary")
    code, result = step("draft-check")
    assert code == 2, result
    assert not any(uri == URI for uri, _, _ in client.calls)


@pytest.mark.parametrize("drift", ["uninstalled_codec", "class", "platform", "conversion"])
def test_conversion_revalidates_exact_authority_after_preview(tmp_path, drift):
    client = ConversionClient("2025.1")
    step, env = declare(tmp_path, "2025.1", client)
    tx, _ = preview(step, env)
    if drift == "uninstalled_codec":
        client.available = False
    elif drift == "class":
        client.codec_class = 65537
    elif drift == "platform":
        client.platforms[0]["id"] = OTHER_CODEC
    else:
        client.target["name"] = "Renamed"
    code, result = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert not any(uri == URI for uri, _, _ in client.calls)


def test_conversion_rejects_historical_placement_preview_before_write(tmp_path):
    from wwise_waapi.transactions import TransactionStore, new_transaction_id

    client = ConversionClient("2025.1")
    step, env = declare(tmp_path, "2025.1", client)
    _, shown = preview(step, env)
    historical = deepcopy(shown["artifact"])
    prepared = historical["prepared_operation"]
    prepared["pre_state"]["conversion_plugin"].pop("contract")
    prepared["verification_plan"]["kind"] = "conversion-plugin"
    old_tx = new_transaction_id()
    store = TransactionStore(tmp_path / "state")
    store.create_preview(old_tx, historical)
    store.submit_for_confirmation(old_tx)
    code, old_shown = gateway.execute_gateway(["transaction-show", old_tx], env=env)
    assert code == 0, old_shown
    code, result = gateway.execute_gateway(["confirm", old_tx, "--confirmation-token", old_shown["confirmation"]["token"]], env=env)
    assert code == 0, result
    code, result = gateway.execute_gateway(["execute", old_tx], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert "result-only Preview" in result["message"]
    assert not any(uri == URI for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1"])
def test_conversion_setter_retains_older_version_boundary(tmp_path, version):
    code, result = gateway.execute_gateway(["request-schema", URI], env=configured_env(tmp_path, version=version),
        client_factory=lambda _: pytest.fail("Unavailable setter schema must remain offline"))
    assert code == 2, result


@pytest.mark.parametrize("fault", ["native_error", "unexpected_result"])
def test_conversion_native_failure_or_invalid_result_never_claims_business_success(tmp_path, fault):
    client = ConversionClient("2025.1")
    native_call = client.call

    def call(uri, args=None, options=None):
        if uri == URI:
            client.calls.append((uri, args, options))
            if fault == "native_error":
                raise RuntimeError("Native setter unsupported for this codec/platform")
            return {"unexpected": True}
        return native_call(uri, args, options)

    client.call = call
    step, env = declare(tmp_path, "2025.1", client)
    tx, _ = preview(step, env)
    code, result = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    if code == 0:
        code, result = gateway.execute_gateway(["verify", tx], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert result.get("verified") is not True
    assert result.get("state") != "result_schema_checked"
    assert sum(uri == URI for uri, _, _ in client.calls) == 1
    assert "conversion_codec" not in result.get("agent_result", {}).get("business_result", {})


def test_separately_chosen_exact_codec_can_be_configured_with_live_field_handles(tmp_path):
    client = ConversionClient("2025.1")
    # This existing exact GUID is explicitly chosen independently of the setter.
    client.attached = True
    env = configured_env(tmp_path, version="2025.1")
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, result = gateway.execute_gateway(["draft-start", "object.setProperty"], env=env)
    assert code == 0, result
    draft_id, authority = result["draft"]["draft_id"], result["task_authority"]

    def field_step(command, *args):
        nonlocal result
        code, result = gateway.execute_gateway([command, draft_id, "--task-authority", authority,
            "--expected-revision", str(result["draft"]["revision"]), *args], env=env, client_factory=lambda _: client)
        return code, result

    code, bound = field_step("draft-bind-object", "--object-id", CODEC)
    assert code == 0, json.dumps(bound, indent=2)
    code, fields = field_step("draft-discover-fields", "--object-handle", bound["bound_object"]["handle"],
        "--platform", "Windows", "--meaning", "quality")
    assert code == 0, json.dumps(fields, indent=2)
    code, result = field_step("draft-declare-field-change", "--object-handle", bound["bound_object"]["handle"],
        "--field-handle", fields["field_candidates"][0]["handle"], "--business-value", "6")
    assert code == 0, json.dumps(result, indent=2)
    field_tx, shown = preview(field_step, env)
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == {
        "object": CODEC, "property": "QualityFactor", "value": 6.0, "platform": "Windows"}
    for command in ("execute", "verify"):
        code, result = gateway.execute_gateway([command, field_tx], env=env, client_factory=lambda _: client)
        assert code == 0, json.dumps(result, indent=2)
    assert result["state"] == "verified"
    assert sum(uri == "ak.wwise.core.object.setProperty" for uri, _, _ in client.calls) == 1
    assert not any(uri == URI for uri, _, _ in client.calls)


@pytest.mark.parametrize("version, altered_path, object_type, expected", [
    ("2025.1", None, "ConversionPlugin", 0), ("2024.1", "<插件显示名称>", "ConversionPlugin", 0),
    ("2025.1", "<Unnamed Conversion plugin>\n", "ConversionPlugin", 2),
    ("2025.1", "<Unnamed Conversion plugin>", "Sound", 2),
])
def test_retained_2025_codec_identity_can_be_bound_without_a_reconstructed_path(tmp_path, version, altered_path, object_type, expected):
    observed = json.loads((Path(__file__).parents[1] / "fixtures/metadata/conversion-plugin-native-2025.json").read_text())
    row = observed["rows"][0]
    assert row["name"] == "" and row["path"] == "<Unnamed Conversion plugin>"
    if altered_path is not None:
        row["path"] = altered_path
    row["type"] = object_type
    if object_type == "Sound":
        row["name"] = "Named ordinary object"

    class RetainedIdentityClient(BindingClient):
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.object.get" and row["id"] in json.dumps(args):
                return {"return": [{key: row[key] for key in ("id", "name", "type", "path")}]}
            return super().call(uri, args, options)

    env = configured_env(tmp_path, version=version)
    env["WAAPI_SKILL_STATE_DIR"] = str(tmp_path / "state")
    code, started = gateway.execute_gateway(["draft-start", "object.setProperty"], env=env)
    assert code == 0, started
    code, bound = gateway.execute_gateway(["draft-bind-object", started["draft"]["draft_id"],
        "--task-authority", started["task_authority"], "--expected-revision", str(started["draft"]["revision"]),
        "--object-id", row["id"]], env=env, client_factory=lambda _: RetainedIdentityClient(version))
    assert code == expected, json.dumps(bound, indent=2)
    if code == 0:
        assert bound["bound_object"]["name"] == ""
        assert bound["bound_object"]["handle"].startswith("boh1-")
    else:
        assert bound["error_code"] == "BUSINESS_OBJECT_BINDING_MISMATCH"

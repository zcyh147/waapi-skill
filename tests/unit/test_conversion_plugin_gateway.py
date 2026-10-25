"""Codec attachment through the public Draft/transaction interface."""
from __future__ import annotations

import json
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
        self.target = {"id": conversion_id, "name": "Voice", "type": "Conversion", "classId": 3604496,
                       "path": "\\Conversion Settings\\Default Work Unit\\Voice"}

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": [{"classId": 262145, "name": "Vorbis", "type": "Conversion"}] if self.available else []}
        if uri == "ak.wwise.core.getProjectInfo":
            return {**super().call(uri, args, options), "platforms": [
                {"id": WINDOWS, "name": "Windows"}, {"id": MAC, "name": "Mac"}]}
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
    code, result = gateway.execute_gateway(["confirm", tx, "--confirmation-token", shown["confirmation"]["token"]], env=env)
    assert code == 0, result
    return tx, shown


@pytest.mark.parametrize("version", ["2024.1", "2025.1"])
def test_conversion_type_handle_selects_one_platform_and_verifies_attached_class(tmp_path, version):
    client = ConversionClient(version)
    step, env = declare(tmp_path, version, client)
    tx, shown = preview(step, env)
    assert shown["artifact"]["prepared_operation"]["dispatch"]["args"] == {
        "conversion": CONVERSION, "platform": "Windows", "plugin": "Vorbis"}
    code, result = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, indent=2)
    code, result = gateway.execute_gateway(["verify", tx], env=env, client_factory=lambda _: client)
    assert code == 0, json.dumps(result, indent=2)
    assert result["state"] == "verified"
    assert sum(uri == URI for uri, _, _ in client.calls) == 1


@pytest.mark.parametrize("fault", ["no_effect", "change_other"])
def test_native_acknowledgement_does_not_prove_conversion_or_other_platform_preservation(tmp_path, fault):
    client = ConversionClient("2025.1")
    step, env = declare(tmp_path, "2025.1", client)
    tx, _ = preview(step, env)
    code, result = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert code == 0, result
    setattr(client, fault, True)
    code, result = gateway.execute_gateway(["verify", tx], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert result["state"] == "verification_failed"
    assert "conversion_codec" not in result.get("agent_result", {}).get("business_result", {})
    assert sum(uri == URI for uri, _, _ in client.calls) == 1


def test_conversion_rejects_unknown_platform_before_write(tmp_path):
    client = ConversionClient("2025.1")
    step, _ = declare(tmp_path, "2025.1", client, platform="Imaginary")
    code, result = step("draft-check")
    assert code == 2, result
    assert not any(uri == URI for uri, _, _ in client.calls)


def test_conversion_revalidates_installed_codec_after_preview(tmp_path):
    client = ConversionClient("2025.1")
    step, env = declare(tmp_path, "2025.1", client)
    tx, _ = preview(step, env)
    client.available = False
    code, result = gateway.execute_gateway(["execute", tx], env=env, client_factory=lambda _: client)
    assert code == 2, result
    assert not any(uri == URI for uri, _, _ in client.calls)


def test_verified_attached_codec_can_be_configured_with_exact_object_field_handles(tmp_path):
    client = ConversionClient("2025.1")
    step, env = declare(tmp_path, "2025.1", client)
    tx, _ = preview(step, env)
    for command in ("execute", "verify"):
        code, result = gateway.execute_gateway([command, tx], env=env, client_factory=lambda _: client)
        assert code == 0, json.dumps(result, indent=2)
    codec = result["agent_result"]["business_result"]["conversion_codec"]
    assert result["stdout_projection"]["full_verification_evidence_in_stdout"] is False
    assert list(result)[-1] == "agent_result"
    assert codec["conversion_id"] == CONVERSION and codec["plugin_class"]["classId"] == 262145
    assert codec["configuration_requires_separate_preview"] is True
    code, result = gateway.execute_gateway(["draft-start", "object.setProperty"], env=env)
    assert code == 0, result
    draft_id, authority = result["draft"]["draft_id"], result["task_authority"]

    def field_step(command, *args):
        nonlocal result
        code, result = gateway.execute_gateway([command, draft_id, "--task-authority", authority,
            "--expected-revision", str(result["draft"]["revision"]), *args], env=env, client_factory=lambda _: client)
        return code, result

    code, bound = field_step("draft-bind-object", "--object-id", codec["object_id"])
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

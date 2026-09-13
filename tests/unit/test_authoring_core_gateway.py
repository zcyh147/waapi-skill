"""Public Gateway regression for the approved 2024/2025 Authoring delta."""

from pathlib import Path
import json

import pytest

from tests.unit.test_waapi_gateway import FakeClient, gateway_env, live_info, waapi_gateway as gateway
from wwise_waapi.authoring_core_manifest import COMMON_URIS, FILENAME, merge_authoring_core
from wwise_waapi.authoring_ui_commands_manifest import AuthoringUiCommandsSupplementError
from wwise_waapi.manifest import ManifestStore
from wwise_waapi.capabilities import CapabilityCatalog, CapabilityNotFoundError


ROOT = Path(__file__).resolve().parents[2] / "skills/waapi-skill/resources/manifest"
LANES = [(v, u) for v in ("2024.1", "2025.1") for u in sorted(COMMON_URIS)] + [
    ("2025.1", "ak.wwise.ui.getSelectedFiles"),
]


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_compact_catalog_reaches_all_approved_authoring_entries_offline(tmp_path, version):
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = version
    def no_client(_):
        pytest.fail("catalog and request schema must stay offline")
    code, catalog = gateway.execute_gateway(["operations"], env=env, client_factory=no_client)
    assert code == 0, catalog
    rows = {r["api"]: r for r in catalog["request_schema_routes"]}
    for lane, uri in LANES:
        if lane != version:
            continue
        row = rows[uri]
        assert row["host_surface"] == "wwise-authoring"
        code, schema = gateway.execute_gateway(row["next_command"], env=env, client_factory=no_client)
        assert code == 0, schema
        assert schema["version"] == version
    assert ("ak.wwise.ui.getSelectedFiles" in rows) is (version == "2025.1")
    assert not any(uri.startswith(("ak.wwise.ui.layout.", "ak.wwise.ui.model.")) for uri in rows)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_every_catalog_schema_link_resolves_or_discloses_a_reviewed_boundary(tmp_path, version):
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = version
    def no_client(_):
        pytest.fail("schema discovery must not connect")
    code, catalog = gateway.execute_gateway(["operations"], env=env, client_factory=no_client)
    assert code == 0, catalog
    assert gateway.gateway_json_document_size(catalog) < 48 * 1024
    for row in catalog["request_schema_routes"]:
        assert row["supported_versions"] == [version]
        if row["next_command"] == ["status"]:
            assert row["api"] == "ak.wwise.core.getInfo"
            continue
        code, result = gateway.execute_gateway(row["next_command"], env=env, client_factory=no_client)
        if row["api"] == "ak.wwise.core.sourceControl.setProvider":
            assert code != 0
        else:
            assert code == 0, (row["api"], result)
            assert result["version"] == version


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
@pytest.mark.parametrize("suffix", (
    "layout.getLayoutNames", "layout.setLayout", "layout.resetLayouts",
    "model.createHandle", "model.registerWafm", "window.create",
    "signal.emit", "cli.executeLuaScript", "cli.launch",
))
def test_unapproved_ui_families_remain_unavailable(version, suffix):
    with pytest.raises(CapabilityNotFoundError):
        CapabilityCatalog().authoring_ui_describe(version, "ak.wwise.ui." + suffix)


def test_selected_files_is_not_added_to_2024():
    with pytest.raises(CapabilityNotFoundError):
        CapabilityCatalog().authoring_ui_describe("2024.1", "ak.wwise.ui.getSelectedFiles")


@pytest.mark.parametrize("version,uri", LANES)
def test_approved_delta_has_a_closed_route_only_on_authoring(version, uri):
    catalog = CapabilityCatalog()
    entry = catalog.authoring_ui_describe(version, uri)
    assert entry.host_surface == "wwise-authoring"
    assert entry.schema_status == "ok"
    assert entry.gateway_commands
    with pytest.raises(CapabilityNotFoundError):
        catalog.describe(version, uri)


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_new_authoring_resource_is_digest_bound_and_accepts_crlf(tmp_path, version):
    target = tmp_path / version / FILENAME
    target.parent.mkdir()
    original = (ROOT / version / FILENAME).read_text()
    target.write_bytes(original.replace("\n", "\r\n").encode())
    base = ManifestStore(root=ROOT).load_authoring_ui_profile(version)
    # Reapplying the delta cannot overwrite a pre-existing function.
    with pytest.raises(AuthoringUiCommandsSupplementError, match="replace"):
        merge_authoring_core(base, root=tmp_path, version=version)
    clean = ManifestStore(root=ROOT).load_with_authoring_ui_commands(version)
    assert merge_authoring_core(clean, root=tmp_path, version=version)["functions"]
    payload = json.loads(original)
    payload["schemas"]["ak.wwise.ui.bringToForeground"]["description"] = "changed"
    target.write_text(json.dumps(payload))
    with pytest.raises(AuthoringUiCommandsSupplementError, match="digest"):
        merge_authoring_core(clean, root=tmp_path, version=version)


@pytest.mark.parametrize("result,valid", [({"files": []}, True),
    ({"files": [r"C:\\Audio\\风声.wav"]}, True), ({}, False),
    ({"files": None}, False), ({"files": [42]}, False)])
def test_selected_files_uses_disclosed_zero_input_and_validates_result(tmp_path, result, valid):
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    code, schema = gateway.execute_gateway(
        ["request-schema", "ak.wwise.ui.getSelectedFiles"], env=env,
        client_factory=lambda _: pytest.fail("schema must be offline"),
    )
    assert code == 0, schema
    client = FakeClient({"ak.wwise.core.getInfo": live_info(year=2025, command_line=False),
                         "ak.wwise.ui.getSelectedFiles": result})
    code, payload = gateway.execute_gateway(schema["continuation"]["gateway_argv"],
        env=env, client_factory=lambda _: client)
    assert (code == 0) is valid, payload
    assert client.calls[-1] == ("ak.wwise.ui.getSelectedFiles", {}, {})


def test_selected_files_rejects_console_before_dispatch(tmp_path):
    env = gateway_env(tmp_path)
    env["WWISE_VERSION"] = "2025.1"
    _, schema = gateway.execute_gateway(["request-schema", "ak.wwise.ui.getSelectedFiles"], env=env)
    client = FakeClient({"ak.wwise.core.getInfo": live_info(year=2025, command_line=True)})
    code, payload = gateway.execute_gateway(schema["continuation"]["gateway_argv"],
        env=env, client_factory=lambda _: client)
    assert code == 2
    assert payload["error_code"] == "AUTHORING_HOST_REQUIRED"
    assert [c[0] for c in client.calls] == ["ak.wwise.core.getInfo"]


@pytest.mark.parametrize("version", ("2024.1", "2025.1"))
def test_remote_connect_reuses_closed_preview_and_verification(version, tmp_path):
    from tests.unit.test_runtime_business_gateway import _seal_runtime_control_preview

    artifact = _seal_runtime_control_preview(tmp_path,
        operation="ak.wwise.core.remote.connect", version=version,
        declaration=("--remote-host", "127.0.0.1", "--application-name", "Game Preview", "--command-port", "24024"))
    assert artifact["request"]["arguments"]["args"] == {
        "host": "127.0.0.1", "appName": "Game Preview", "commandPort": 24024,
    }
    assert artifact["prepared_operation"]["verification_plan"]["kind"] == "remote-connection-state"
    assert artifact["prepared_operation"]["cleanup"]["companion_request"]["api"] == "ak.wwise.core.remote.disconnect"

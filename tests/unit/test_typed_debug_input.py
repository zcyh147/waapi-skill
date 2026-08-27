from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_debug_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


def _env(tmp_path: Path, version: str) -> dict[str, str]:
    config = tmp_path / f"config-{version}.json"
    config.write_text(
        json.dumps(
            {"wwise_version": version, "project_modification_policy": "allow_changes"}
        ),
        encoding="utf-8",
    )
    return {"WAAPI_SKILL_CONFIG_PATH": str(config), "WWISE_WAAPI_PORT": "8080"}


@pytest.mark.parametrize(
    ("operation", "versions", "api"),
    (
        ("debug.restartWaapiServers", ("2023.1", "2024.1", "2025.1"), "ak.wwise.debug.restartWaapiServers"),
        ("debug.testAssert", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), "ak.wwise.debug.testAssert"),
        ("debug.testCrash", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"), "ak.wwise.debug.testCrash"),
    ),
)
def test_debug_host_controls_disclose_one_zero_value_business_entry(
    tmp_path: Path,
    operation: str,
    versions: tuple[str, ...],
    api: str,
) -> None:
    for version in versions:
        code, payload = gateway.execute_gateway(
            ["--version", version, "operation-schema", operation],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
        )
        assert code == 0, payload
        contract = payload["business_adapter"]
        assert payload["operation"]["input_mode"] == "business_declaration"
        assert contract["declaration"] == {
            "subcommand": "draft-declare-debug-intent",
            "settings_field": "debug_intent",
            "submit_once": True,
            "business_values_required": False,
            "public_fields": [],
            "choices": [],
            "native_request_fields": "forbidden",
        }
        assert contract["safety"]["explicit_confirmation_only"] is True
        assert contract["safety"]["automatic_retry"] is False
        serialized = json.dumps(payload)
        assert "acknowledge" not in serialized
        assert "args-json" not in serialized

        generic_code, generic = gateway.execute_gateway(
            ["--version", version, "request-schema", api],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"request-schema connected to {url}"),
        )
        assert generic_code == 2, generic
        assert f"operation-schema {operation}" in generic["message"]

        reflected = gateway.request_contract(version, api)
        direct_code, direct = gateway.execute_gateway(
            ["--version", version, "typed-zero-call", api, "--schema-digest", reflected.schema_digest, "--apply"],
            env=_env(tmp_path, version),
            client_factory=lambda url: pytest.fail(f"typed-zero connected to {url}"),
        )
        assert direct_code == 2, direct
        assert f"operation-schema {operation}" in direct["message"]


@pytest.mark.parametrize("operation", ("debug.setAsserts", "debug.setAutomationMode"))
@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_debug_boolean_controls_disclose_only_one_business_outcome(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )

    assert code == 0, payload
    assert payload["operation"]["input_mode"] == "business_declaration"
    declaration = payload["business_adapter"]["declaration"]
    assert declaration["public_fields"] == ["enabled"]
    assert declaration["choices"] == ["--enable", "--disable"]
    serialized = json.dumps(payload)
    assert "args-json" not in serialized
    assert "request-json" not in serialized


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_unsupported_restart_lane_discloses_only_the_version_boundary(
    tmp_path: Path,
    version: str,
) -> None:
    code, payload = gateway.execute_gateway(
        ["--version", version, "operation-schema", "debug.restartWaapiServers"],
        env=_env(tmp_path, version),
        client_factory=lambda url: pytest.fail(f"schema connected to {url}"),
    )

    assert code == 0, payload
    assert "business_adapter" not in payload
    assert payload["operation"]["availability"] == {
        "status": "unsupported_version",
        "requested_version": version,
        "supported_versions": ["2023.1", "2024.1", "2025.1"],
    }
    serialized = json.dumps(payload)
    assert "acknowledge" not in serialized
    assert "request-json" not in serialized
    assert "preview_invocation" not in serialized

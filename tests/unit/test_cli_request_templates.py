from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.builders.cli_request_templates import (
    CLI_REQUEST_TEMPLATE_CONTRACT,
    CLI_REQUEST_TEMPLATE_SET_CONTRACT,
    CLI_REQUEST_TEMPLATE_URIS,
    CliRequestTemplateError,
    build_cli_request_template,
)
from wwise_waapi.capabilities import CapabilityCatalog
from wwise_waapi.config import ResolvedSkillConfig, SkillConfig
from wwise_waapi.operation_registry import (
    FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS,
)
from wwise_waapi.versions import SUPPORTED_WWISE_VERSION_KEYS


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_cli_request_template_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


EXPECTED_DELTA_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    "ak.wwise.cli.generateSoundbank": {
        "no-source-control": frozenset(
            {"2022.1", "2023.1", "2024.1", "2025.1"}
        ),
        "root-output-path": frozenset(
            {"2022.1", "2023.1", "2024.1", "2025.1"}
        ),
        "use-user-overrides": frozenset(
            {"2022.1", "2023.1", "2024.1", "2025.1"}
        ),
        "license-file": frozenset({"2023.1", "2024.1", "2025.1"}),
        "no-wwise-dat": frozenset({"2021.1", "2022.1", "2023.1"}),
    },
    "ak.wwise.cli.tabDelimitedImport": {
        "no-source-control": frozenset({"2023.1", "2024.1", "2025.1"}),
    },
    "ak.wwise.cli.convertExternalSource": {
        "no-wwise-dat": frozenset({"2021.1", "2022.1", "2023.1"}),
    },
    "ak.wwise.cli.migrate": {
        "no-source-control": frozenset({"2023.1", "2024.1", "2025.1"}),
    },
}


def _gateway_env(tmp_path: Path, *, version: str | None) -> dict[str, str]:
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "WAAPI_SKILL_CONFIG_PATH": str(tmp_path / "config.json"),
    }
    if version is not None:
        env["WWISE_VERSION"] = version
    return env


def _template(version: str, uri: str) -> dict[str, Any]:
    entry = CapabilityCatalog().describe(version, uri)
    return build_cli_request_template(
        version=version,
        uri=uri,
        schema=entry.schema,
        forbidden_fields=FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS.get(uri, ()),
    )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("uri", CLI_REQUEST_TEMPLATE_URIS)
def test_cli_request_template_is_exactly_manifest_backed(
    version: str,
    uri: str,
) -> None:
    entry = CapabilityCatalog().describe(version, uri)
    template = _template(version, uri)
    args_schema = entry.schema["argsSchema"]
    manifest_fields = sorted(args_schema["properties"])
    blocked_fields = sorted(
        set(FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS.get(uri, ()))
        & set(manifest_fields)
    )

    assert template["contract"] == CLI_REQUEST_TEMPLATE_CONTRACT
    assert template["status"] == "constraints_only_not_executable"
    assert template["version"] == version
    assert template["api"] == uri
    assert template["operation"] == "waapi.call"
    assert template["args_constraints"]["required_fields"] == args_schema["required"]
    assert template["args_constraints"]["reflected_fields"] == manifest_fields
    assert sorted(template["args_constraints"]["fields"]) == manifest_fields
    assert template["args_constraints"]["blocked_fields"] == blocked_fields
    assert template["args_constraints"]["accepted_fields"] == [
        field for field in manifest_fields if field not in blocked_fields
    ]
    assert template["request_paths"]["options"] == {
        "path": "$.arguments.options",
        "const": {},
    }
    assert template["request_paths"]["io_root"]["required"] is True
    assert template["request_paths"]["io_root"]["absolute"] is True

    # This record is construction guidance, not an illustrative payload that
    # can be copied directly into ``preview``.
    assert "arguments" not in template
    assert "canonical_request_template" not in template
    assert template["materialization_policy"]["directly_executable"] is False
    assert template["materialization_policy"]["payload_values_included"] is False
    assert "<" not in json.dumps(template, sort_keys=True)


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
@pytest.mark.parametrize("uri", CLI_REQUEST_TEMPLATE_URIS)
def test_cli_request_template_reports_reviewed_version_deltas(
    version: str,
    uri: str,
) -> None:
    template = _template(version, uri)
    delta = template["version_delta_fields"]
    expected = EXPECTED_DELTA_FIELDS[uri]

    assert delta["available"] == sorted(
        field for field, versions in expected.items() if version in versions
    )
    assert delta["absent"] == sorted(
        field for field, versions in expected.items() if version not in versions
    )
    assert "use-user-settings" not in template["args_constraints"]["reflected_fields"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda schema: schema["argsSchema"]["properties"].update(
                {"use-user-settings": {"type": "boolean"}}
            ),
            "use-user-settings",
        ),
        (
            lambda schema: schema["argsSchema"]["properties"].pop(
                "root-output-path"
            ),
            "root-output-path",
        ),
        (
            lambda schema: schema["argsSchema"].update(
                {"additionalProperties": True}
            ),
            "closed object",
        ),
    ),
)
def test_cli_request_template_fails_closed_on_manifest_contract_drift(
    mutation: Any,
    message: str,
) -> None:
    entry = CapabilityCatalog().describe(
        "2022.1",
        "ak.wwise.cli.generateSoundbank",
    )
    schema = deepcopy(entry.schema)
    mutation(schema)

    with pytest.raises(CliRequestTemplateError, match=message):
        build_cli_request_template(
            version="2022.1",
            uri="ak.wwise.cli.generateSoundbank",
            schema=schema,
            forbidden_fields=FORBIDDEN_MODEL_AUTHORED_COMMAND_FIELDS[
                "ak.wwise.cli.generateSoundbank"
            ],
        )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSION_KEYS)
def test_operation_schema_exposes_all_four_versioned_cli_templates_offline(
    tmp_path: Path,
    version: str,
) -> None:
    connections: list[str] = []

    def fail_if_connected(url: str) -> None:
        connections.append(url)
        raise AssertionError(url)

    exit_code, payload = waapi_gateway.execute_gateway(
        ["operation-schema", "waapi.call"],
        env=_gateway_env(tmp_path, version=version),
        client_factory=fail_if_connected,
    )

    assert exit_code == 0
    assert connections == []
    template_set = payload["cli_request_templates"]
    assert template_set["contract"] == CLI_REQUEST_TEMPLATE_SET_CONTRACT
    assert template_set["status"] == "ready"
    assert template_set["version"] == version
    assert list(template_set["templates"]) == list(CLI_REQUEST_TEMPLATE_URIS)
    assert template_set["policy"] == {
        "directly_executable": False,
        "detail": "run describe for the exact API",
    }
    for uri, compact in template_set["templates"].items():
        detailed = _template(version, uri)
        assert compact["required"] == detailed["args_constraints"]["required_fields"]
        assert compact["blocked"] == detailed["args_constraints"]["blocked_fields"]
        assert compact["version_delta_fields"] == {
            **{
                field: True
                for field in detailed["version_delta_fields"]["available"]
            },
            **{
                field: False
                for field in detailed["version_delta_fields"]["absent"]
            },
        }


def test_operation_schema_does_not_emit_unpinned_cli_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolution = ResolvedSkillConfig(
        config=SkillConfig(waapi_gateway.SKILL_ROOT),
        source="defaults",
        external_path=tmp_path / "config.json",
        legacy_path=tmp_path / "legacy.json",
        legacy_fallback_used=False,
    )
    monkeypatch.setattr(
        waapi_gateway,
        "load_gateway_config",
        lambda env: resolution,
    )
    exit_code, payload = waapi_gateway.execute_gateway(
        ["operation-schema", "waapi.call"],
        env=_gateway_env(tmp_path, version=None),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["request_envelope"] is None
    assert payload["request_envelope_policy"]["status"] == "version_required"
    assert payload["cli_request_templates"] == {
        "contract": CLI_REQUEST_TEMPLATE_SET_CONTRACT,
        "status": "version_required",
        "version": None,
        "apis": list(CLI_REQUEST_TEMPLATE_URIS),
        "templates": {},
    }


@pytest.mark.parametrize("uri", CLI_REQUEST_TEMPLATE_URIS)
def test_describe_exposes_the_template_for_each_requested_version_offline(
    tmp_path: Path,
    uri: str,
) -> None:
    exit_code, payload = waapi_gateway.execute_gateway(
        ["describe", uri, "--all-versions"],
        env=_gateway_env(tmp_path, version=None),
        client_factory=lambda url: (_ for _ in ()).throw(AssertionError(url)),
    )

    assert exit_code == 0
    assert payload["versions"] == list(SUPPORTED_WWISE_VERSION_KEYS)
    for version, row in payload["availability"].items():
        assert row["available"] is True
        assert row["request_template"]["version"] == version
        assert row["request_template"]["api"] == uri
        assert (
            row["request_template"]["args_constraints"]["reflected_fields"]
            == row["capability"]["schema"]["args"]["properties"]
        )

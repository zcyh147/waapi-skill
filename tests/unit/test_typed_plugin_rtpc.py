from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from wwise_waapi.operation_composer import (
    OPERATION_COMPOSITION_CONTRACT,
    OperationComposerError,
    materialize_operation_request,
)
from wwise_waapi.typed_operations import (
    TypedOperationInputError,
    draft_operation_request_contract,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_typed_plugin_rtpc_gateway",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": "2025.1",
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_PORT": "8080",
    }


@pytest.mark.parametrize(
    ("operation", "versions"),
    (
        ("object.create", ("2021.1", *VERSIONS)),
        ("object.createPlugin", VERSIONS),
        ("object.set", VERSIONS),
        ("object.setRTPC", VERSIONS),
    ),
)
def test_object_graph_typed_draft_schema_is_removed(
    operation: str,
    versions: tuple[str, ...],
) -> None:
    for version in versions:
        with pytest.raises(TypedOperationInputError, match="No typed Draft adapter"):
            draft_operation_request_contract(operation, version)


@pytest.mark.parametrize(
    "operation",
    ("object.create", "object.createPlugin", "object.set", "object.setRTPC"),
)
def test_legacy_typed_composition_is_not_a_production_fallback(
    operation: str,
) -> None:
    legacy_composition = {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "typed_request_schema_digest": "0" * 64,
        "facts": [],
    }

    with pytest.raises(
        OperationComposerError,
        match="business composition fields are invalid",
    ):
        materialize_operation_request(
            operation,
            "2025.1",
            legacy_composition,
        )


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.createPlugin", "object.setRTPC"))
def test_public_schema_and_draft_start_share_one_business_operation(
    tmp_path: Path,
    operation: str,
    version: str,
) -> None:
    code, schema = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(
            f"offline command connected to {url}"
        ),
    )
    assert code == 0, schema
    assert schema["operation"]["input_mode"] == "business_declaration"
    assert "composer" not in schema
    adapter = schema["business_adapter"]
    assert adapter["operation"] == operation
    assert adapter["version"] == version
    assert adapter["start"]["next_command"]["gateway_argv"] == [
        "draft-start",
        operation,
    ]
    assert adapter["legacy_shallow_composer_public"] is False

    start_code, started = gateway.execute_gateway(
        [
            "--version",
            version,
            "--state-dir",
            str(tmp_path / f"{operation}-{version}"),
            "draft-start",
            operation,
        ],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(
            f"offline command connected to {url}"
        ),
    )
    assert start_code == 0, started
    draft = started["draft"]
    assert draft["binding"]["operation"] == operation
    assert draft["missing_fields"] == ["business_declaration"]
    binding = draft["next_action_binding"]
    assert binding["responsibility_split"] == {
        "agent": "natural_language_to_closed_high_level_business_facts",
        "gateway": "business_facts_to_exact_waapi_request_and_execution_plan",
    }
    assert "typed_fact_batch_discipline" not in binding
    assert "draft-apply" not in json.dumps(binding)

from __future__ import annotations

import importlib.util
import json
from collections import deque
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import pytest

from wwise_waapi.operation_composer import (
    OPERATION_COMPOSITION_CONTRACT,
    materialize_operation_request,
)
from wwise_waapi.operation_registry import parse_operation_request
from wwise_waapi.typed_operations import draft_operation_request_contract
from wwise_waapi.typed_requests import (
    MAX_TYPED_ARRAY_ITEMS,
    MAX_TYPED_REQUEST_FACTS,
    MAX_TYPED_REQUEST_BYTES,
    MAX_TYPED_STRING_BYTES,
    TypedRequestFact,
    dynamic_array_item_handle,
    dynamic_container_disclosure,
    materialize_typed_request,
)
from wwise_waapi.transactions import TransactionStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location("waapi_typed_plugin_rtpc_gateway", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)

VERSIONS = ("2022.1", "2023.1", "2024.1", "2025.1")
TARGET_ID = "{11111111-1111-1111-1111-111111111111}"
CONTROL_ID = "{22222222-2222-2222-2222-222222222222}"


class _Client:
    def __init__(self, responses: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
        self.responses = {uri: deque(rows) for uri, rows in responses.items()}
        self.calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((uri, dict(args or {}), dict(options or {})))
        if uri not in self.responses or not self.responses[uri]:
            raise AssertionError(f"Unexpected or exhausted WAAPI call: {uri}")
        return self.responses[uri].popleft()

    def disconnect(self) -> None:
        pass


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"wwise_version": "2025.1", "project_modification_policy": "ask_before_changes"}),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_PORT": "8080",
    }


def _live_rows(tmp_path: Path, operation: str) -> dict[str, Sequence[Mapping[str, Any]]]:
    project_path = tmp_path / "project" / "SampleProject.wproj"
    project_path.parent.mkdir(exist_ok=True)
    project_path.write_text("<Project/>", encoding="utf-8")
    target = {
        "id": TARGET_ID,
        "name": "Parent",
        "type": "Sound" if operation == "object.createPlugin" else "ActorMixer",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Parent",
        "parent": {"id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"},
        "notes": "",
    }
    responses: dict[str, Sequence[Mapping[str, Any]]] = {
        "ak.wwise.core.getInfo": [
            {
                "displayName": "Wwise",
                "isCommandLine": True,
                "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "processId": 42,
                "processPath": "/Applications/Wwise.app/Contents/MacOS/Wwise",
                "apiVersion": 1,
                "platform": "macosx",
                "configuration": "release",
                "version": {"year": 2025, "major": 1, "minor": 0, "build": 1},
            }
        ],
        "ak.wwise.core.getProjectInfo": [
            {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "SampleProject", "path": str(project_path)}
        ],
    }
    if operation == "object.createPlugin":
        responses["ak.wwise.core.object.get"] = [
            {"return": [target]},
            {"return": []},
        ]
    else:
        control = {
            **target,
            "id": CONTROL_ID,
            "name": "Distance",
            "type": "GameParameter",
            "path": r"\Game Parameters\Default Work Unit\Distance",
        }
        responses["ak.wwise.core.object.get"] = [
            {"return": [target]},
            {"return": [control]},
            {"return": [{"id": TARGET_ID, "@RTPC": []}]},
        ]
        responses["ak.wwise.core.object.getPropertyInfo"] = [
            {
                "name": "Volume",
                "type": "Real32",
                "supports": {"randomizer": True, "rtpc": "Additive", "unlink": True},
            }
        ]
    return responses


def _apply_facts(
    tmp_path: Path,
    *,
    state_dir: Path,
    started: Mapping[str, Any],
    facts: Sequence[TypedRequestFact],
) -> int:
    revision = 1
    for fact in facts:
        argv = [
            "--version", "2025.1", "--state-dir", str(state_dir),
            "draft-apply", started["draft"]["draft_id"],
            "--task-authority", started["task_authority"],
            "--expected-revision", str(revision), "--facts",
            "--action", "add_typed_fact", "--fact-action", fact.action,
            "--field-handle", fact.handle,
        ]
        if fact.action in {"choose", "choose-dynamic"}:
            argv += ["--fact-value", fact.value]
        elif fact.action != "present":
            argv += ["--value-type", fact.value_type, "--fact-value", fact.value]
        if fact.key is not None:
            argv += ["--key", fact.key]
        code, payload = gateway.execute_gateway(
            argv,
            env=_env(tmp_path),
            client_factory=lambda url: pytest.fail(f"draft-apply connected to {url}"),
        )
        assert code == 0, payload
        revision = payload["draft"]["revision"]
    return revision


def _identity_facts(contract, path: tuple[str, ...], value: str) -> list[TypedRequestFact]:
    branch = next(
        field
        for field in contract.fields
        if field.path == path and field.shape == "branch" and field.parent_handle is None
    )
    object_branch = next(
        field
        for field in contract.fields
        if field.parent_handle == branch.handle and field.name == "object:0"
    )
    kind = next(
        field
        for field in contract.fields
        if field.parent_handle == object_branch.handle and field.name == "kind"
    )
    selector_value = next(
        field
        for field in contract.fields
        if field.parent_handle == object_branch.handle and field.name == "value"
    )
    return [
        TypedRequestFact("choose", branch.handle, "branch", object_branch.handle),
        TypedRequestFact("set", kind.handle, "string", "id"),
        TypedRequestFact("set", selector_value.handle, "string", value),
    ]


def _composition(contract, facts: list[TypedRequestFact]) -> dict[str, object]:
    return {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "typed_request_schema_digest": contract.schema_digest,
        "facts": [
            {
                "handle": f"tdh1-{index:024x}",
                "fact_action": fact.action,
                "field_handle": fact.handle,
                "value_type": fact.value_type,
                "value": fact.value,
                **({"key": fact.key} if fact.key is not None else {}),
            }
            for index, fact in enumerate(facts)
        ],
    }


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.createPlugin", "object.setRTPC"))
def test_plugin_and_rtpc_compile_as_exact_named_typed_drafts(
    version: str, operation: str
) -> None:
    contract = draft_operation_request_contract(operation, version)
    assert contract.uri == operation
    assert contract.as_gateway_payload()["input_shape"] == "draft"


@pytest.mark.parametrize(
    "operation",
    ("object.createPlugin", "object.setRTPC"),
)
def test_legacy_typed_composition_is_not_a_public_fallback(
    operation: str,
) -> None:
    contract = draft_operation_request_contract(operation, "2025.1")
    legacy_composition = {
        "contract": OPERATION_COMPOSITION_CONTRACT,
        "typed_request_schema_digest": contract.schema_digest,
        "facts": [],
    }

    with pytest.raises(Exception, match="business composition fields are invalid"):
        materialize_operation_request(
            operation,
            "2025.1",
            legacy_composition,
        )
@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("operation", ("object.createPlugin", "object.setRTPC"))
def test_public_schema_and_draft_start_share_one_business_operation(
    tmp_path: Path, operation: str, version: str
) -> None:
    code, schema = gateway.execute_gateway(
        ["--version", version, "operation-schema", operation],
        env=_env(tmp_path),
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
    )
    assert code == 0, schema
    assert schema["operation"]["input_mode"] == "business_declaration"
    assert "composer" not in schema
    adapter = schema["business_adapter"]
    assert adapter["operation"] == operation
    assert adapter["version"] == version
    assert adapter["start"]["gateway_argv"] == ["draft-start", operation]
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
        client_factory=lambda url: pytest.fail(f"offline command connected to {url}"),
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
def test_rtpc_point_shape_fails_before_any_preview() -> None:
    contract = draft_operation_request_contract("object.setRTPC", "2025.1")
    points = next(field for field in contract.fields if field.path == ("points",))
    row = dynamic_array_item_handle(
        contract, array_handle=points.handle, index=0, shape="object"
    )
    with pytest.raises(Exception, match="shape"):
        materialize_typed_request(
            contract,
            schema_digest=contract.schema_digest,
            facts=(
                TypedRequestFact("append", points.handle, "object", row),
                TypedRequestFact("map-put", row, "number", "0", key="x"),
                TypedRequestFact("map-put", row, "number", "0", key="y"),
                TypedRequestFact("map-put", row, "string", "Invented", key="shape"),
            ),
        )

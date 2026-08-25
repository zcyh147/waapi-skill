from __future__ import annotations

import importlib.util
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import OperationDraftStore
from wwise_waapi.business_declarations import business_repair


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_object_metadata_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
OBJECT_ID = "{11111111-1111-1111-1111-111111111111}"


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[tuple[str, Any, Any]] = []

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        self.calls.append((uri, args, options))
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")
        return values.popleft()

    def disconnect(self) -> None:
        return None


def _project_path(tmp_path: Path) -> Path:
    path = tmp_path / "project" / "SampleProject.wproj"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<Project />\n", encoding="utf-8")
    return path


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": None,
                "waapi_host": "127.0.0.1",
                "waapi_port": None,
                "project_modification_policy": "ask_before_changes",
            }
        ),
        encoding="utf-8",
    )
    return {
        "WAAPI_SKILL_CONFIG_PATH": str(config),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": "2022.1",
    }


def _info() -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        "processId": 4242,
        "processPath": "/Applications/Wwise/WwiseConsole",
        "apiVersion": 1,
        "platform": "macosx",
        "configuration": "release",
        "version": {
            "year": 2022,
            "major": 1,
            "minor": 0,
            "build": 1,
            "displayName": "v2022.1.0.1",
        },
    }


def _project(tmp_path: Path) -> dict[str, Any]:
    return {
        "id": PROJECT_ID,
        "name": "SampleProject",
        "path": str(_project_path(tmp_path)),
    }


def _offline(tmp_path: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    def reject_connection(url: str) -> None:
        raise AssertionError(f"offline field command connected to {url}")

    return waapi_gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *argv],
        env=_env(tmp_path),
        client_factory=reject_connection,
    )


def test_property_draft_discovers_opaque_field_and_materializes_business_value(
    tmp_path: Path,
) -> None:
    start_code, started = _offline(tmp_path, "draft-start", "object.setProperty")
    assert start_code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    first = started["draft"]["next_action_binding"]
    assert first["required_next_phase"] == "bind_existing_business_object"
    assert "--token" not in json.dumps(first)

    bind_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": OBJECT_ID,
                            "name": "Alarm",
                            "type": "Sound",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit\Alarm"
                            ),
                        }
                    ]
                }
            ],
        }
    )
    bind_code, bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-object",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--object-id",
            OBJECT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: bind_client,
    )
    assert bind_code == 0, bound
    object_handle = bound["bound_object"]["handle"]
    next_action = bound["draft"]["next_action_binding"]
    assert next_action["field_discovery"]["token_input"] == "forbidden"
    assert "--token" not in json.dumps(next_action)

    discover_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [_project(tmp_path)],
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["Volume", "OutputBus"]},
                {"return": ["Volume", "OutputBus"]},
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "display": {"name": "Volume", "group": "General"},
                    "restriction": {"type": "range", "min": -96.3, "max": 96.3},
                    "supports": {"unlink": True},
                },
                {
                    "name": "Volume",
                    "type": "Real32",
                    "display": {"name": "Volume", "group": "General"},
                    "restriction": {"type": "range", "min": -96.3, "max": 96.3},
                    "supports": {"unlink": True},
                },
            ],
        }
    )
    discover_code, discovered = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-discover-fields",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--object-handle",
            object_handle,
            "--meaning",
            "volume",
            "--platform",
            "Windows",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: discover_client,
    )
    assert discover_code == 0, json.dumps(
        {"payload": discovered, "calls": discover_client.calls},
        default=str,
        indent=2,
    )
    assert discovered["candidate_count"] == 1
    candidate = discovered["field_candidates"][0]
    assert candidate["label"] == "Volume"
    assert candidate["field_kind"] == "property"
    assert candidate["value_type"] == "number"
    assert candidate["platform"] == "Windows"
    assert candidate["handle"].startswith("bfh1-")
    assert "token" not in candidate

    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-field-change",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--object-handle",
        object_handle,
        "--field-handle",
        candidate["handle"],
        "--business-value",
        "-4",
    )
    assert declare_code == 0, declared
    assert declared["draft"]["next_action_binding"]["required_next_phase"] == (
        "check_complete_business_declaration"
    )
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=4,
        schema_digest=waapi_gateway.operation_draft_schema_digest(
            "object.setProperty",
            "2022.1",
        ),
        composer_digest=operation_composer_digest(
            "object.setProperty",
            "2022.1",
        ),
    )
    assert materialized.request["arguments"] == {
        "object": {"kind": "id", "value": OBJECT_ID},
        "property": "Volume",
        "value": -4.0,
        "platform": "Windows",
    }


def test_gateway_preserves_bounded_business_repair_details() -> None:
    error = business_repair(
        "REFERENCE_TARGET_TYPE_MISMATCH",
        field="reference_outcome",
        action="choose one allowed bound target",
        allowed_target_types=["Bus", "AuxBus"],
        actual_target_type="BusRef",
    )

    normalized = waapi_gateway.normalize_gateway_exception(error)

    assert normalized["error_code"] == "REFERENCE_TARGET_TYPE_MISMATCH"
    assert normalized["details"]["repair"] == error.repair

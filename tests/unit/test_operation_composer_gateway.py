from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from wwise_waapi.canonical import canonical_sha256  # pyright: ignore[reportMissingImports]
from wwise_waapi.operation_drafts import (  # pyright: ignore[reportMissingImports]
    OperationDraftStore,
)
from wwise_waapi.operation_composer import (  # pyright: ignore[reportMissingImports]
    OperationComposerError,
    operation_composer_contract,
    operation_composer_digest,
)
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    COMPOSER_INPUT_MODE,
    LEGACY_JSON_INPUT_MODE,
    list_operation_specs,
    operation_input_mode,
    operation_request_schema_digest,
)

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_operation_composer_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


TARGET_HANDLE_RE = re.compile(r"^odh1-[0-9a-f]{24}$")
TARGET_ID = "{01234567-89AB-CDEF-0123-456789ABCDEF}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"
PROJECT_ID = "{22222222-2222-2222-2222-222222222222}"
ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"


BASE_ACTION_FIELDS = {
    "set_request_option": (["name", "value"], []),
    "clear_request_option": (["name"], []),
    "add_target": (
        ["selector"],
        [
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
            "properties",
            "references",
        ],
    ),
    "set_target_field": (["target_handle", "name", "value"], []),
    "clear_target_field": (["target_handle", "name"], []),
    "set_property": (["target_handle", "name", "value"], []),
    "remove_property": (["target_handle", "name"], []),
    "set_reference": (["owner_handle", "name", "target"], []),
    "remove_reference": (["owner_handle", "name"], []),
    "add_child": (["parent_handle", "type", "name"], []),
    "set_node_field": (["node_handle", "name", "value"], []),
    "clear_node_field": (["node_handle", "name"], []),
    "set_node_property": (["node_handle", "name", "value"], []),
    "remove_node_property": (["node_handle", "name"], []),
    "remove_node": (["node_handle"], []),
    "add_list": (["target_handle", "name"], []),
    "remove_list": (["list_handle"], []),
    "add_list_member": (["list_handle", "type", "name"], []),
    "remove_target": (["target_handle"], []),
}
IMPORT_ACTION_FIELDS = {
    "add_import_file": (
        ["owner_handle"],
        [
            "audio_file",
            "audio_file_base64",
            "originals_subfolder",
            "language",
            "object_type",
        ],
    ),
    "set_import_file_field": (["file_handle", "name", "value"], []),
    "clear_import_file_field": (["file_handle", "name"], []),
    "remove_import_file": (["file_handle"], []),
    "set_import_option": (["owner_handle", "name", "value"], []),
    "clear_import_option": (["owner_handle", "name"], []),
    "remove_import": (["owner_handle"], []),
}


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_object_set_composer_contract_covers_every_registry_field_shape(
    version: str,
) -> None:
    contract = operation_composer_contract("object.set", version)

    assert contract["registry_fragments"]["coverage"] == {
        "request_fields": [
            "auto_add_to_source_control",
            "list_mode",
            "objects",
            "on_name_conflict",
            "platform",
        ],
        "target_fields": [
            "children",
            "import",
            "list_mode",
            "lists",
            "name",
            "notes",
            "object",
            "on_name_conflict",
            "platform",
            "properties",
            "references",
        ],
        "node_fields": [
            "children",
            "import",
            "language",
            "name",
            "notes",
            "platform",
            "properties",
            "references",
            "type",
        ],
        "list_fields": ["name", "objects"],
        "import_fields": ["auto_add_to_source_control", "files"],
        "import_file_fields": [
            "audio_file",
            "audio_file_base64",
            "language",
            "object_type",
            "originals_subfolder",
        ],
    }


@pytest.mark.parametrize("version", ("2022.1", "2023.1", "2024.1", "2025.1"))
def test_object_set_composer_discloses_every_exact_typed_action_shape(
    version: str,
) -> None:
    contract = operation_composer_contract("object.set", version)
    expected = dict(BASE_ACTION_FIELDS)
    if version != "2022.1":
        expected.update(IMPORT_ACTION_FIELDS)

    assert set(contract["action_shapes"]) == set(contract["actions"]) == set(expected)
    assert contract["action_construction"] == {
        "fixed_fields_are_required": True,
        "include_every_required_field": True,
        "include_only_selected_optional_fields": True,
        "additional_fields": False,
    }
    assert contract["flat_target_row_discipline"] == {
        "initial_action": "add_target",
        "include_every_known_field": [
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
            "properties",
            "references",
        ],
        "split_initial_row_across_follow_up_actions": False,
        "follow_up_flat_actions": "corrections_only",
        "selector_only_allowed_for": [
            "nested_children",
            "closed_lists",
            "embedded_import",
        ],
    }
    for action_name, (required_fields, optional_fields) in expected.items():
        assert contract["action_shapes"][action_name] == {
            "fixed_fields": {
                "contract": ACTION_CONTRACT,
                "action": action_name,
            },
            "required_fields": required_fields,
            "optional_fields": optional_fields,
        }
    assert {"set_reference", "remove_reference"}.issubset(contract["actions"])
    assert ("add_import_file" in contract["actions"]) is (version != "2022.1")


def test_object_set_composer_does_not_change_other_operation_schema_digests() -> None:
    non_object_set_digests = {
        f"{spec.name}@{version}": operation_request_schema_digest(spec.name, version)
        for spec in list_operation_specs()
        if spec.implemented and spec.name != "object.set"
        for version in spec.supported_versions
    }

    assert len(non_object_set_digests) == 139
    assert canonical_sha256(non_object_set_digests) == (
        "b90e10a9528dfc250453a1958043034d4fdbcde6e52f628e340f9dbacc7499b1"
    )
    assert {
        version: operation_input_mode("object.set", version)
        for version in ("2022.1", "2023.1", "2024.1", "2025.1")
    } == {
        "2022.1": COMPOSER_INPUT_MODE,
        "2023.1": COMPOSER_INPUT_MODE,
        "2024.1": COMPOSER_INPUT_MODE,
        "2025.1": COMPOSER_INPUT_MODE,
    }


def test_object_set_composer_rejects_unsupported_version_before_state_write(
    tmp_path: Path,
) -> None:
    exit_code, rejected = execute(
        tmp_path,
        "--version",
        "2021.1",
        "draft-start",
        "object.set",
    )

    assert exit_code == 2
    assert rejected["error_code"] == "UNAVAILABLE_IN_VERSION"
    records_dir = tmp_path / "state" / "operation-drafts-v1" / "records"
    assert not records_dir.exists() or list(records_dir.iterdir()) == []


class FakeClient:
    def __init__(self, responses: Mapping[str, Sequence[Any]]) -> None:
        self.responses = {uri: deque(values) for uri, values in responses.items()}
        self.calls: list[
            tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]
        ] = []
        self.disconnected = False

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Any:
        self.calls.append((uri, args, options))
        values = self.responses.get(uri)
        if not values:
            raise AssertionError(
                f"Unexpected or exhausted WAAPI call: {uri} {args!r} {options!r}"
            )
        return values.popleft()

    def disconnect(self) -> None:
        self.disconnected = True


def gateway_env(tmp_path: Path) -> dict[str, str]:
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
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
        "WAAPI_SKILL_CONFIG_PATH": str(config_path),
        "WWISE_WAAPI_HOST": "127.0.0.1",
        "WWISE_WAAPI_PORT": "31337",
        "WWISE_VERSION": "2022.1",
    }


def execute(tmp_path: Path, *arguments: str) -> tuple[int, dict[str, Any]]:
    def fail_if_connected(url: str) -> None:
        raise AssertionError(f"Offline Composer command connected to {url}")

    return waapi_gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *arguments],
        env=gateway_env(tmp_path),
        client_factory=fail_if_connected,
    )


def action(action_name: str, **fields: Any) -> str:
    return json.dumps(
        {
            "contract": "waapi-skill.operation-draft-action/v1",
            "action": action_name,
            **fields,
        }
    )


def live_info() -> dict[str, Any]:
    return {
        "displayName": "Wwise",
        "isCommandLine": True,
        "sessionId": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
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
            "displayName": "v2022.1.0",
        },
    }


def project_row(tmp_path: Path) -> dict[str, Any]:
    return {
        "id": PROJECT_ID,
        "name": "SampleProject",
        "path": str((tmp_path / "project" / "SampleProject.wproj").resolve()),
    }


def target_row(*, volume: float | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": TARGET_ID,
        "name": "Target",
        "type": "Sound",
        "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
        "parent": {"id": PARENT_ID},
        "notes": "before",
    }
    if volume is not None:
        row["Volume"] = volume
    return row


def check_client(tmp_path: Path) -> FakeClient:
    return FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project_row(tmp_path)],
            "ak.wwise.core.object.getTypes": [
                {"return": [{"classId": 1, "name": "Sound", "type": "Sound"}]}
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -96.3, "max": 12.0},
                }
            ],
            "ak.wwise.core.object.get": [
                {"return": [target_row()]},
                {"return": [target_row(volume=0.0)]},
                {"return": []},
            ],
        }
    )


def complete_draft(tmp_path: Path, *, value: float = -3.0) -> tuple[str, str, str]:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    handle = targeted["draft"]["current_facts"][0]["handle"]
    code, completed = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=value,
        ),
    )
    assert code == 0
    assert completed["draft"]["revision"] == 3
    return draft_id, authority, handle


def test_object_set_typed_actions_build_one_target_scalar_fact_offline(
    tmp_path: Path,
) -> None:
    start_code, started = execute(tmp_path, "draft-start", "object.set")
    assert start_code == 0
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    target_code, target = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action(
            "add_target",
            selector={"kind": "id", "value": TARGET_ID},
        ),
    )

    assert target_code == 0
    assert target["command"] == "draft-apply"
    assert target["offline"] is True
    target_fact = target["draft"]["current_facts"][0]
    handle = target_fact["handle"]
    assert TARGET_HANDLE_RE.fullmatch(handle)
    assert target["draft"]["revision"] == 2
    assert target["draft"]["next_action_binding"] == {
        "contract": "waapi-skill.operation-draft-next-action/v1",
        "draft_id": draft_id,
        "expected_revision": 2,
        "one_action_only": True,
        "then_read_next_response": True,
        "precompute_or_increment_revision": False,
        "fixed_full_argv_template": [
            "python",
            str(waapi_gateway.GATEWAY_RUNNER_PATH),
            "gateway.py",
            "draft-apply",
            draft_id,
            "--task-authority",
            "<task-authority-from-draft-start>",
            "--expected-revision",
            "2",
            "--compact",
            "--action-json",
            "<typed-action-json>",
        ],
        "replace_only": [
            "<task-authority-from-draft-start>",
            "<typed-action-json>",
        ],
        "copy_all_other_values_exactly": True,
    }
    assert target_fact == {
        "handle": handle,
        "selector": {"kind": "id", "value": TARGET_ID},
        "properties": [],
        "references": [],
        "children": [],
        "lists": [],
        "import": None,
    }
    assert target["draft"]["missing_fields"] == [f"targets[{handle}].change"]

    property_code, property_result = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-6.0,
        ),
    )

    assert property_code == 0
    assert property_result["draft"]["revision"] == 3
    assert property_result["draft"]["current_facts"] == [
        {
            "handle": handle,
            "selector": {"kind": "id", "value": TARGET_ID},
            "properties": [{"name": "Volume", "value": -6.0}],
            "references": [],
            "children": [],
            "lists": [],
            "import": None,
        }
    ]
    assert property_result["draft"]["missing_fields"] == []
    assert property_result["draft"]["missing_fields_status"] == "complete"
    assert "check" in property_result["draft"]["allowed_actions"]
    assert not (tmp_path / "state" / "transactions").exists()


def test_compact_draft_action_returns_only_delta_and_exact_next_prefix(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--compact",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )

    assert code == 0
    draft = targeted["draft"]
    assert "session_context" not in targeted
    assert "current_facts" not in draft
    summary = draft["current_facts_summary"]
    assert summary == {
        "contract": "waapi-skill.operation-draft-facts-summary/v1",
        "target_count": 1,
        "handle_count": 1,
        "canonical_sha256": summary["canonical_sha256"],
    }
    assert draft["schema_required_fields_status"] == "incomplete"
    assert "missing_fields_status" not in draft
    assert draft["response_integrity"] == {
        "complete": True,
        "truncated": False,
        "projection": "action_delta_and_draft_receipt",
        "compact_projection_is_not_truncation": True,
        "user_intent_coverage": "compare_planned_actions_before_draft-check",
        "draft_inspect_required_before_next_planned_action": False,
    }
    assert "draft-inspect" not in json.dumps(targeted)
    handle = draft["action_result"]["created_handles"][0]
    assert TARGET_HANDLE_RE.fullmatch(handle)
    assert draft["action_result"] == {
        "contract": "waapi-skill.operation-draft-action-result/v1",
        "action": "add_target",
        "created_handles": [handle],
        "affected_handles": [],
    }
    assert draft["next_action_binding"]["fixed_full_argv_template"] == [
        "python",
        str(waapi_gateway.GATEWAY_RUNNER_PATH),
        "gateway.py",
        "draft-apply",
        draft_id,
        "--task-authority",
        "<task-authority-from-draft-start>",
        "--expected-revision",
        "2",
        "--compact",
        "--action-json",
        "<typed-action-json>",
    ]
    assert set(draft["next_action_binding"]) == {
        "contract",
        "fixed_full_argv_template",
        "replace_only",
    }

    code, changed = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--compact",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-3.0,
        ),
    )

    assert code == 0
    assert changed["draft"]["action_result"] == {
        "contract": "waapi-skill.operation-draft-action-result/v1",
        "action": "set_property",
        "created_handles": [],
        "affected_handles": [handle],
    }
    inspect_code, inspected = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        authority,
    )
    assert inspect_code == 0
    assert inspected["draft"]["current_facts"][0]["properties"] == [
        {"name": "Volume", "value": -3.0}
    ]


def test_compact_weather_shaped_action_responses_remain_constant_size(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1
    response_sizes: list[int] = []

    for index in range(5):
        code, targeted = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--compact",
            "--action-json",
            action(
                "add_target",
                selector={
                    "kind": "id",
                    "value": f"{{00000000-0000-0000-0000-{index + 1:012d}}}",
                },
            ),
        )
        assert code == 0
        assert set(targeted["draft"]) == {
            "contract",
            "draft_id",
            "lifecycle_state",
            "revision",
            "binding",
            "schema_required_fields_status",
            "current_facts_summary",
            "action_result",
            "response_integrity",
            "next_action_binding",
        }
        handle = targeted["draft"]["action_result"]["created_handles"][0]
        revision += 1
        response_sizes.append(len(json.dumps(targeted).encode("utf-8")))
        for name, value in (("FadeTime", 0.25 + index / 10), ("Delay", index / 10)):
            code, changed = execute(
                tmp_path,
                "draft-apply",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                str(revision),
                "--compact",
                "--action-json",
                action(
                    "set_property",
                    target_handle=handle,
                    name=name,
                    value=value,
                ),
            )
            assert code == 0
            assert "session_context" not in changed
            assert "current_facts" not in changed["draft"]
            assert changed["draft"]["response_integrity"]["complete"] is True
            assert changed["draft"]["response_integrity"]["truncated"] is False
            assert (
                changed["draft"]["response_integrity"]["user_intent_coverage"]
                == "compare_planned_actions_before_draft-check"
            )
            assert (
                changed["draft"]["response_integrity"][
                    "compact_projection_is_not_truncation"
                ]
                is True
            )
            assert (
                changed["draft"]["response_integrity"][
                    "draft_inspect_required_before_next_planned_action"
                ]
                is False
            )
            revision += 1
            response_sizes.append(len(json.dumps(changed).encode("utf-8")))

    assert len(response_sizes) == 15
    assert max(response_sizes) < 1_800
    assert max(response_sizes) - min(response_sizes) < 256
    inspect_code, inspected = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        authority,
    )
    assert inspect_code == 0
    assert len(inspected["draft"]["current_facts"]) == 5


def test_property_correction_and_removal_are_ordered_typed_edits(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    handle = targeted["draft"]["current_facts"][0]["handle"]
    _code, initial = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-6,
        ),
    )
    _code, corrected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-3,
        ),
    )
    assert initial["draft"]["revision"] == 3
    assert corrected["draft"]["revision"] == 4
    assert corrected["draft"]["current_facts"][0]["properties"] == [
        {"name": "Volume", "value": -3}
    ]

    _code, removed_property = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--action-json",
        action("remove_property", target_handle=handle, name="Volume"),
    )
    assert removed_property["draft"]["revision"] == 5
    assert removed_property["draft"]["current_facts"][0]["properties"] == []
    assert removed_property["draft"]["missing_fields"] == [f"targets[{handle}].change"]

    _code, removed_target = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "5",
        "--action-json",
        action("remove_target", target_handle=handle),
    )
    assert removed_target["draft"]["revision"] == 6
    assert removed_target["draft"]["current_facts"] == []
    assert "add_target" in removed_target["draft"]["allowed_actions"]


def test_invalid_action_is_byte_atomic_and_rejects_complete_request_injection(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    exit_code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        json.dumps(
            {
                "contract": "waapi-skill.operation-draft-action/v1",
                "action": "add_target",
                "selector": {"kind": "id", "value": TARGET_ID},
                "request": {
                    "contract": "waapi-skill.operation-request/v1",
                    "version": "2022.1",
                    "operation": "object.set",
                    "arguments": {"objects": []},
                },
            }
        ),
    )

    assert exit_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    assert record_path.read_bytes() == before
    _code, inspected = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        authority,
    )
    assert inspected["draft"] == started["draft"]


def test_invalid_target_selectors_are_registry_rejected_without_any_revision(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    for selector in (
        {"kind": "id", "value": True},
        {"kind": "path", "value": 7},
        {"kind": "path", "value": "not-an-absolute-wwise-path"},
    ):
        exit_code, rejected = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "1",
            "--action-json",
            action("add_target", selector=selector),
        )
        assert exit_code == 2
        assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
        assert record_path.read_bytes() == before

    _code, inspected = execute(
        tmp_path,
        "draft-inspect",
        draft_id,
        "--task-authority",
        authority,
    )
    assert inspected["draft"] == started["draft"]


def test_public_facts_result_budget_rejects_before_durable_revision(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    handle = targeted["draft"]["current_facts"][0]["handle"]
    revision = 2
    for property_name in ("NotesA", "NotesB"):
        code, payload = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action(
                "set_property",
                target_handle=handle,
                name=property_name,
                value="x" * 30_000,
            ),
        )
        assert code == 0
        revision = payload["draft"]["revision"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    rejected_code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="NotesC",
            value="y" * 30_000,
        ),
    )

    assert rejected_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_LIMIT_EXCEEDED"
    assert rejected["details"]["result_limit_bytes"] == 256 * 1024
    assert record_path.read_bytes() == before


def test_legacy_record_is_readable_but_composer_requires_recreate_without_write(
    tmp_path: Path,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    started = store.start(
        operation="object.set",
        version="2022.1",
        schema_digest=(
            "2b6d3903c5b3e11618c3eaf0a3d5a26aa0045db26750320f3a8ce8c7da004cee"
        ),
    )
    record_path = store.records_dir / f"{started.draft_id}.json"
    before = record_path.read_bytes()

    inspect_code, inspected = execute(
        tmp_path,
        "draft-inspect",
        started.draft_id,
        "--task-authority",
        started.task_authority,
    )
    apply_code, rejected = execute(
        tmp_path,
        "draft-apply",
        started.draft_id,
        "--task-authority",
        started.task_authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )

    assert inspect_code == 0
    assert inspected["draft"]["missing_fields_status"] == "no_operation_adapter"
    assert apply_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_RECREATE_REQUIRED"
    assert record_path.read_bytes() == before


def test_composer_is_exactly_isolated_from_shared_uri_operations(
    tmp_path: Path,
) -> None:
    assert operation_input_mode("object.set", "2022.1") == COMPOSER_INPUT_MODE
    assert operation_input_mode("object.setRTPC", "2022.1") == LEGACY_JSON_INPUT_MODE
    _code, started = execute(tmp_path, "draft-start", "object.setRTPC")
    draft_id = started["draft"]["draft_id"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    exit_code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )

    assert exit_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_ADAPTER_UNAVAILABLE"
    assert record_path.read_bytes() == before


def test_live_check_is_bounded_durable_and_any_edit_invalidates_it(
    tmp_path: Path,
) -> None:
    draft_id, authority, handle = complete_draft(tmp_path)
    client = check_client(tmp_path)

    check_code, checked = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "3",
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert check_code == 0
    assert checked["command"] == "draft-check"
    assert checked["offline"] is False
    assert checked["draft"]["revision"] == 4
    assert checked["draft"]["check"]["status"] == "passed"
    assert checked["draft"]["check"]["source_revision"] == 3
    assert checked["draft"]["check"]["request_digest"]
    assert "preview-from-draft" in checked["draft"]["allowed_actions"]
    assert "current_facts" not in checked["draft"]
    facts_summary = checked["draft"]["current_facts_summary"]
    assert facts_summary == {
        "contract": "waapi-skill.operation-draft-facts-summary/v1",
        "target_count": 1,
        "handle_count": 1,
        "canonical_sha256": facts_summary["canonical_sha256"],
    }
    assert checked["draft"]["response_integrity"] == {
        "complete": True,
        "truncated": False,
        "projection": "checked_draft_receipt",
        "compact_projection_is_not_truncation": True,
        "draft_inspect_required_before_preview": False,
    }
    assert checked["draft"]["next_action_binding"] == {
        "contract": "waapi-skill.operation-draft-next-action/v1",
        "draft_id": draft_id,
        "expected_revision": 4,
        "one_action_only": True,
        "then_read_next_response": True,
        "precompute_or_increment_revision": False,
        "fixed_full_argv_template": [
            "python",
            str(waapi_gateway.GATEWAY_RUNNER_PATH),
            "gateway.py",
            "preview-from-draft",
            draft_id,
            "--task-authority",
            "<task-authority-from-draft-start>",
            "--expected-revision",
            "4",
            "--apply",
        ],
        "replace_only": ["<task-authority-from-draft-start>"],
        "copy_all_other_values_exactly": True,
    }
    assert [call[0] for call in client.calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.getPropertyInfo",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.get",
    ]
    assert client.disconnected is True
    assert not (tmp_path / "state" / "transactions").exists()

    edit_code, edited = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--action-json",
        action(
            "set_property",
            target_handle=handle,
            name="Volume",
            value=-2.0,
        ),
    )
    assert edit_code == 0
    assert edited["draft"]["revision"] == 5
    assert edited["draft"]["check"] is None
    assert "preview-from-draft" not in edited["draft"]["allowed_actions"]
    assert "check" in edited["draft"]["allowed_actions"]


def test_live_check_reports_all_invalid_target_rows_without_writing(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1
    target_ids = (
        "{10000000-0000-0000-0000-000000000001}",
        "{10000000-0000-0000-0000-000000000002}",
    )
    for target_id in target_ids:
        code, targeted = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action("add_target", selector={"kind": "id", "value": target_id}),
        )
        assert code == 0
        revision = targeted["draft"]["revision"]
        handle = targeted["draft"]["current_facts"][-1]["handle"]
        code, changed = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action(
                "set_property",
                target_handle=handle,
                name="Volume",
                value=99.0,
            ),
        )
        assert code == 0
        revision = changed["draft"]["revision"]

    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()
    rows = [
        {
            "id": target_id,
            "name": f"Target {index}",
            "type": "Sound",
            "path": rf"\Actor-Mixer Hierarchy\Default Work Unit\Target {index}",
            "parent": {"id": PARENT_ID},
            "notes": "before",
        }
        for index, target_id in enumerate(target_ids, start=1)
    ]
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [live_info()],
            "ak.wwise.core.getProjectInfo": [project_row(tmp_path)],
            "ak.wwise.core.object.getTypes": [
                {"return": [{"classId": 1, "name": "Sound", "type": "Sound"}]}
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "Volume",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -96.3, "max": 12.0},
                },
                {
                    "name": "Volume",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -96.3, "max": 12.0},
                },
            ],
            "ak.wwise.core.object.get": [
                {"return": [rows[0]]},
                {"return": [rows[1]]},
            ],
        }
    )

    exit_code, rejected = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-check",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
        ],
        env=gateway_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert exit_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_CHECK_FAILED"
    assert [issue["row_index"] for issue in rejected["details"]["issues"]] == [0, 1]
    assert {
        issue["error_code"] for issue in rejected["details"]["issues"]
    } == {"PROPERTY_VALUE_OUT_OF_RANGE"}
    assert record_path.read_bytes() == before
    assert not (tmp_path / "state" / "transactions").exists()
    identity_calls = [
        call
        for call in client.calls
        if call[0] == "ak.wwise.core.object.get"
    ]
    assert len(identity_calls) == 2
    assert client.disconnected is True


def test_weather_shape_keeps_multiple_targets_and_request_options_in_business_order(
    tmp_path: Path,
) -> None:
    selectors = [
        {
            "kind": "direct-child",
            "parent": {"kind": "path", "value": rf"\Events\Weather\Play_{name}"},
            "type": "Action",
        }
        for name in ("Rain", "Wind")
    ]
    expected_properties = (
        (("FadeTime", 0.25), ("Delay", 0.0)),
        (("FadeTime", 0.4), ("Delay", 0.1)),
    )
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1

    code, configured = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--action-json",
        action("set_request_option", name="on_name_conflict", value="fail"),
    )
    assert code == 0
    revision = configured["draft"]["revision"]

    handles: list[str] = []
    for selector, properties in zip(selectors, expected_properties, strict=True):
        code, targeted = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action(
                "add_target",
                selector=selector,
                properties=[
                    {"name": name, "value": value}
                    for name, value in properties
                ],
            ),
        )
        assert code == 0
        revision = targeted["draft"]["revision"]
        handles.append(targeted["draft"]["current_facts"][-1]["handle"])

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=revision,
        schema_digest=started["draft"]["binding"]["schema_digest"],
        composer_digest=operation_composer_digest("object.set", "2022.1"),
    )

    assert materialized.request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "object.set",
        "arguments": {
            "objects": [
                {
                    "object": selectors[index],
                    "properties": [
                        {"name": name, "value": value}
                        for name, value in expected_properties[index]
                    ],
                }
                for index in range(2)
            ],
            "on_name_conflict": "fail",
        },
    }
    assert revision == 4
    assert [row["handle"] for row in targeted["draft"]["current_facts"]] == handles


def test_complete_target_row_is_atomic_when_one_inline_reference_is_invalid(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action(
            "add_target",
            selector={"kind": "id", "value": TARGET_ID},
            name="Reviewed Target",
            notes="complete row",
            properties=[{"name": "Volume", "value": -3.0}],
            references=[
                {
                    "name": "OutputBus",
                    "target": {"kind": "id", "value": PARENT_ID},
                },
                {
                    "name": "OutputBus",
                    "target": {"kind": "path", "value": r"\Master-Mixer Hierarchy"},
                },
            ],
        ),
    )

    assert code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    assert record_path.read_bytes() == before
    assert OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    ).revision == 1


def test_target_and_recursive_child_facts_materialize_without_raw_tree_patches(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1

    def apply(action_name: str, **fields: Any) -> dict[str, Any]:
        nonlocal revision
        code, payload = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action(action_name, **fields),
        )
        assert code == 0
        revision = payload["draft"]["revision"]
        return payload

    targeted = apply(
        "add_target",
        selector={"kind": "id", "value": TARGET_ID},
    )
    target_handle = targeted["draft"]["current_facts"][0]["handle"]
    apply("set_target_field", target_handle=target_handle, name="notes", value="batch")
    apply("set_target_field", target_handle=target_handle, name="platform", value="Windows")
    child = apply(
        "add_child",
        parent_handle=target_handle,
        type="Sound",
        name="Rain_Layer",
    )
    child_handle = child["draft"]["current_facts"][0]["children"][0]["handle"]
    apply("set_node_field", node_handle=child_handle, name="notes", value="loop")
    apply("set_node_field", node_handle=child_handle, name="language", value="SFX")
    apply(
        "set_node_property",
        node_handle=child_handle,
        name="Volume",
        value=-4.0,
    )
    final = apply(
        "set_reference",
        owner_handle=child_handle,
        name="OutputBus",
        target={"kind": "path", "value": r"\Master-Mixer Hierarchy\Default Work Unit\Weather"},
    )

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=revision,
        schema_digest=started["draft"]["binding"]["schema_digest"],
        composer_digest=operation_composer_digest("object.set", "2022.1"),
    )
    assert materialized.request["arguments"] == {
        "objects": [
            {
                "object": {"kind": "id", "value": TARGET_ID},
                "notes": "batch",
                "platform": "Windows",
                "children": [
                    {
                        "type": "Sound",
                        "name": "Rain_Layer",
                        "notes": "loop",
                        "language": "SFX",
                        "properties": [{"name": "Volume", "value": -4.0}],
                        "references": [
                            {
                                "name": "OutputBus",
                                "target": {
                                    "kind": "path",
                                    "value": r"\Master-Mixer Hierarchy\Default Work Unit\Weather",
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    assert final["draft"]["missing_fields"] == []


def test_closed_object_list_members_use_handles_and_keep_insertion_order(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1

    def apply(action_name: str, **fields: Any) -> dict[str, Any]:
        nonlocal revision
        code, payload = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action(action_name, **fields),
        )
        assert code == 0
        revision = payload["draft"]["revision"]
        return payload

    targeted = apply("add_target", selector={"kind": "id", "value": TARGET_ID})
    target_handle = targeted["draft"]["current_facts"][0]["handle"]
    listed = apply("add_list", target_handle=target_handle, name="CustomList")
    list_handle = listed["draft"]["current_facts"][0]["lists"][0]["handle"]
    first = apply("add_list_member", list_handle=list_handle, type="Sound", name="Rain")
    first_handle = first["draft"]["current_facts"][0]["lists"][0]["objects"][0]["handle"]
    second = apply("add_list_member", list_handle=list_handle, type="Sound", name="Wind")
    second_handle = second["draft"]["current_facts"][0]["lists"][0]["objects"][1]["handle"]
    apply("set_node_field", node_handle=first_handle, name="notes", value="first")
    apply("set_node_field", node_handle=second_handle, name="platform", value="Windows")
    final = apply(
        "set_reference",
        owner_handle=second_handle,
        name="OutputBus",
        target={"kind": "id", "value": 42},
    )

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=revision,
        schema_digest=started["draft"]["binding"]["schema_digest"],
        composer_digest=operation_composer_digest("object.set", "2022.1"),
    )
    assert materialized.request["arguments"]["objects"][0]["lists"] == [
        {
            "name": "CustomList",
            "objects": [
                {"type": "Sound", "name": "Rain", "notes": "first"},
                {
                    "type": "Sound",
                    "name": "Wind",
                    "platform": "Windows",
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {"kind": "id", "value": 42},
                        }
                    ],
                },
            ],
        }
    ]
    assert [
        item["handle"]
        for item in final["draft"]["current_facts"][0]["lists"][0]["objects"]
    ] == [first_handle, second_handle]


def test_embedded_import_files_are_versioned_correctable_and_handle_addressed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Rain Source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVEpayload")
    _code, started = execute(
        tmp_path,
        "--version",
        "2023.1",
        "draft-start",
        "object.set",
    )
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    revision = 1

    def apply(action_name: str, **fields: Any) -> dict[str, Any]:
        nonlocal revision
        code, payload = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action(action_name, **fields),
        )
        assert code == 0
        revision = payload["draft"]["revision"]
        return payload

    targeted = apply("add_target", selector={"kind": "id", "value": TARGET_ID})
    target_handle = targeted["draft"]["current_facts"][0]["handle"]
    imported = apply(
        "add_import_file",
        owner_handle=target_handle,
        audio_file=str(source),
        language="SFX",
        object_type="AudioFileSource",
    )
    file_fact = imported["draft"]["current_facts"][0]["import"]["files"][0]
    file_handle = file_fact["handle"]
    assert TARGET_HANDLE_RE.fullmatch(file_handle)
    apply(
        "set_import_file_field",
        file_handle=file_handle,
        name="originals_subfolder",
        value="Weather/Rain",
    )
    final = apply(
        "set_import_option",
        owner_handle=target_handle,
        name="auto_add_to_source_control",
        value=False,
    )

    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=revision,
        schema_digest=started["draft"]["binding"]["schema_digest"],
        composer_digest=operation_composer_digest("object.set", "2023.1"),
    )
    assert materialized.request["arguments"]["objects"][0]["import"] == {
        "files": [
            {
                "audio_file": str(source),
                "originals_subfolder": "Weather/Rain",
                "language": "SFX",
                "object_type": "AudioFileSource",
            }
        ],
        "auto_add_to_source_control": False,
    }
    assert final["draft"]["missing_fields"] == []


def test_embedded_import_is_rejected_before_revision_on_wwise_2022(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    assert "add_import_file" not in started["draft"]["allowed_actions"]
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    assert "add_import_file" not in targeted["draft"]["allowed_actions"]
    target_handle = targeted["draft"]["current_facts"][0]["handle"]
    record_path = (
        tmp_path / "state" / "operation-drafts-v1" / "records" / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action(
            "add_import_file",
            owner_handle=target_handle,
            audio_file=str(tmp_path / "not-opened.wav"),
        ),
    )

    assert code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    assert record_path.read_bytes() == before


def test_invalid_options_duplicates_and_target_ceiling_are_byte_atomic(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path / "state" / "operation-drafts-v1" / "records" / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("set_request_option", name="list_mode", value="raw-native-mode"),
    )
    assert code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    assert record_path.read_bytes() == before

    revision = 1
    first_selector: dict[str, Any] | None = None
    for index in range(32):
        selector = {"kind": "id", "value": index + 1}
        code, payload = execute(
            tmp_path,
            "draft-apply",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            str(revision),
            "--action-json",
            action("add_target", selector=selector),
        )
        assert code == 0
        revision = payload["draft"]["revision"]
        first_selector = first_selector or selector

    before_limit = record_path.read_bytes()
    code, limited = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--action-json",
        action("add_target", selector={"kind": "id", "value": 33}),
    )
    assert code == 2
    assert limited["details"]["limit"] == 32
    assert record_path.read_bytes() == before_limit

    code, duplicate = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        str(revision),
        "--action-json",
        action("add_target", selector=first_selector),
    )
    assert code == 2
    assert record_path.read_bytes() == before_limit


def test_empty_append_list_remains_incomplete_but_replace_all_can_clear_it(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    target_handle = targeted["draft"]["current_facts"][0]["handle"]
    _code, listed = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action("add_list", target_handle=target_handle, name="CustomList"),
    )
    assert listed["draft"]["missing_fields"] == [
        f"targets[{target_handle}].lists["
        f"{listed['draft']['current_facts'][0]['lists'][0]['handle']}].objects"
    ]
    store = OperationDraftStore(tmp_path / "state")
    with pytest.raises(OperationComposerError) as incomplete:
        store.materialize_request(
            draft_id,
            task_authority=authority,
            expected_revision=3,
            schema_digest=started["draft"]["binding"]["schema_digest"],
            composer_digest=operation_composer_digest("object.set", "2022.1"),
        )
    assert incomplete.value.error_code == "NO_OP"

    code, replaced = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--action-json",
        action("set_request_option", name="list_mode", value="replaceAll"),
    )
    assert code == 0
    assert replaced["draft"]["missing_fields"] == []
    materialized = store.materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=4,
        schema_digest=started["draft"]["binding"]["schema_digest"],
        composer_digest=operation_composer_digest("object.set", "2022.1"),
    )
    assert materialized.request["arguments"] == {
        "objects": [
            {
                "object": {"kind": "id", "value": TARGET_ID},
                "lists": [{"name": "CustomList", "objects": []}],
            }
        ],
        "list_mode": "replaceAll",
    }


def test_reference_facts_are_typed_correctable_and_keep_exact_selectors(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, targeted = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        action("add_target", selector={"kind": "id", "value": TARGET_ID}),
    )
    handle = targeted["draft"]["current_facts"][0]["handle"]
    first_bus = r"\Master-Mixer Hierarchy\Default Work Unit\Weapons"
    corrected_bus = r"\Master-Mixer Hierarchy\Default Work Unit\Weapons Release"

    first_code, first = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        action(
            "set_reference",
            owner_handle=handle,
            name="OutputBus",
            target={"kind": "path", "value": first_bus},
        ),
    )
    assert first_code == 0
    assert first["draft"]["current_facts"][0]["references"] == [
        {
            "name": "OutputBus",
            "target": {"kind": "path", "value": first_bus},
        }
    ]

    corrected_code, corrected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--action-json",
        action(
            "set_reference",
            owner_handle=handle,
            name="OutputBus",
            target={"kind": "path", "value": corrected_bus},
        ),
    )
    assert corrected_code == 0
    assert corrected["draft"]["current_facts"][0]["references"] == [
        {
            "name": "OutputBus",
            "target": {"kind": "path", "value": corrected_bus},
        }
    ]
    second_code, second = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--action-json",
        action(
            "set_reference",
            owner_handle=handle,
            name="UserAuxSend0",
            target={"kind": "id", "value": 42},
        ),
    )
    assert second_code == 0
    expected_references = [
        {
            "name": "OutputBus",
            "target": {"kind": "path", "value": corrected_bus},
        },
        {"name": "UserAuxSend0", "target": {"kind": "id", "value": 42}},
    ]
    assert second["draft"]["current_facts"][0]["references"] == expected_references
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=5,
        schema_digest=started["draft"]["binding"]["schema_digest"],
        composer_digest=operation_composer_digest("object.set", "2022.1"),
    )
    assert materialized.request["arguments"]["objects"][0]["references"] == (
        expected_references
    )

    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()
    rejected_code, rejected = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "5",
        "--action-json",
        action(
            "set_reference",
            owner_handle=handle,
            name="@OutputBus",
            target={"kind": "id", "value": True},
        ),
    )
    assert rejected_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_ACTION_INVALID"
    assert record_path.read_bytes() == before

    removed_code, removed = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "5",
        "--action-json",
        action(
            "remove_reference",
            owner_handle=handle,
            name="OutputBus",
        ),
    )
    assert removed_code == 0
    assert removed["draft"]["current_facts"][0]["references"] == [
        {"name": "UserAuxSend0", "target": {"kind": "id", "value": 42}}
    ]

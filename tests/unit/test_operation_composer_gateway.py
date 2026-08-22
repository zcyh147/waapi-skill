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
    parse_typed_action_cli_arguments,
    typed_action_cli_arguments,
)
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    COMPOSER_INPUT_MODE,
    INTERNAL_CANONICAL_INPUT_MODE,
    list_operation_specs,
    operation_input_mode,
    operation_request_schema_digest,
)
from wwise_waapi.typed_requests import (  # pyright: ignore[reportMissingImports]
    expand_gateway_field_table,
)
from wwise_waapi.typed_operations import (  # pyright: ignore[reportMissingImports]
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


def _assert_pristine_inspected_draft(
    started: Mapping[str, Any],
    inspected: Mapping[str, Any],
) -> None:
    started_draft = dict(started["draft"])
    started_draft.pop("next_action_binding")
    started_draft.pop("agent_control")
    inspected_draft = dict(inspected["draft"])
    inspected_binding = inspected_draft.pop("next_action_binding")
    assert inspected_draft == started_draft
    assert inspected_binding["fixed_argv_prefix"][6] == (
        "<task-authority-from-draft-start>"
    )


def _composer_fields(composer: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = composer.get("typed_request_fields")
    if isinstance(fields, list):
        return fields
    return expand_gateway_field_table(composer["typed_request_field_table"])


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
    assert contract["identity_value_authority"] == {
        "prior_gateway_result_id_is_opaque_exact_copy": True,
        "replace_prior_result_id_with_path_or_name": "invalid",
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
        "metadata_dependency_activation": (
            "agent_selects_only_requested_exact_tokens; Gateway validates and "
            "activates required dependency values"
        ),
        "unrequested_dependency_flags_are_not_action_fields": True,
        "reference_companion_fact_policy": {
            "submit_reference_only_when_that_is_the_user_fact": True,
            "reference_does_not_authorize_a_companion_property_fact": True,
            "gateway_owns_required_reference_activation": True,
            "output_bus_example": (
                "OutputBus does not authorize an OverrideOutput action field"
            ),
        },
        "selector_only_allowed_for": [
            "nested_children",
            "closed_lists",
            "embedded_import",
        ],
    }
    assert contract["start_preconditions"]["required_sequence"] == [
        "operation-schema",
        "metadata discover",
        "draft-start",
    ]
    assert contract["start_preconditions"]["workflow_control"] == {
        "metadata_success_is_terminal": False,
        "continue_same_turn_after_metadata": "draft-start",
        "reply_before_draft_start": "invalid",
    }
    assert contract["start_preconditions"]["activation_decision"] == {
        "run_metadata_when": (
            "one_or_more_required_tokens_lack_prior_successful_live_result"
        ),
        "skip_metadata_when": (
            "every_required_token_has_prior_successful_live_result"
        ),
        "when_skipped_continue_same_turn_with": "draft-start",
    }
    assert contract["start_preconditions"]["metadata_gateway_argv_template"] == [
        "metadata",
        "discover",
        "--object-type",
        "<exact-shared-target-type>",
        "--query",
        "<requested-field-name>",
        "--limit",
        "<1..8>",
    ]
    assert contract["start_preconditions"]["metadata_scope_decision"] == {
        "first_source": "exact_shared_target_type_from_every_selector",
        "direct_child_selector_type_is_exact_scope": True,
        "reviewed_property_container_fallback": (
            "only_registry_default_actor_mixer_container_scope"
        ),
        "action_target_scope": "Action",
        "property_container_for_action_target": "invalid",
    }
    assert contract["start_preconditions"]["forbidden_scope_flags"] == [
        "--object"
    ]
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


def test_non_object_set_operation_schema_digest_inventory_is_reviewed() -> None:
    non_object_set_digests = {
        f"{spec.name}@{version}": operation_request_schema_digest(spec.name, version)
        for spec in list_operation_specs()
        if spec.implemented and spec.name != "object.set"
        for version in spec.supported_versions
    }

    assert len(non_object_set_digests) == 149
    assert canonical_sha256(non_object_set_digests) == (
        "e584250074e0c237cd2c13e3bc81e0a4b31007884ff0af3bbc23994570debf24"
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

    normalized = list(arguments)
    if "--action-json" in normalized:
        index = normalized.index("--action-json")
        mapping = json.loads(normalized[index + 1])
        try:
            facts = typed_action_cli_arguments(mapping)
        except OperationComposerError:
            facts = ("--action", str(mapping.get("action", "invalid")))
        normalized[index:] = ["--facts", *facts]
    return waapi_gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *normalized],
        env=gateway_env(tmp_path),
        client_factory=fail_if_connected,
    )


def action_mapping(action_name: str, **fields: Any) -> dict[str, Any]:
    return {
        "contract": "waapi-skill.operation-draft-action/v1",
        "action": action_name,
        **fields,
    }


def action(action_name: str, **fields: Any) -> str:
    return json.dumps(action_mapping(action_name, **fields))


def test_production_gateway_rejects_historical_action_json_without_writing(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path / "state" / "operation-drafts-v1" / "records" / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    with pytest.raises(SystemExit) as rejected:
        waapi_gateway.execute_gateway(
            [
                "--state-dir",
                str(tmp_path / "state"),
                "draft-apply",
                draft_id,
                "--task-authority",
                authority,
                "--expected-revision",
                "1",
                "--action-json",
                action("set_request_option", name="list_mode", value="append"),
            ],
            env=gateway_env(tmp_path),
            client_factory=lambda url: pytest.fail(f"unexpected connection: {url}"),
        )

    assert rejected.value.code == 2
    assert record_path.read_bytes() == before


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
    draft_apply_prefix = [
        "python",
        str(waapi_gateway.GATEWAY_RUNNER_PATH),
        "gateway.py",
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--compact",
        "--facts",
    ]
    assert target["draft"]["next_action_binding"] == {
        "contract": "waapi-skill.operation-draft-next-action/v1",
        "shell_tool_timeout_ms": 30_000,
        "draft_id": draft_id,
        "expected_revision": 2,
        "one_atomic_action_batch_only": True,
        "minimum_actions": 1,
        "maximum_actions": 6,
        "then_read_next_response": True,
        "precompute_or_increment_revision": False,
        "fixed_argv_prefix": draft_apply_prefix,
        "fixed_argv_prefix_copy": waapi_gateway.operation_draft_copy_command(
            draft_apply_prefix
        ),
        "fixed_argv_prefix_copy_instruction": {
            "contract": "waapi-skill.operation-draft-command-copy-instruction/v1",
            "source_field": "fixed_argv_prefix_copy",
            "action": "copy_verbatim_then_append_complete_typed_action_groups",
            "forbidden_transformations": [
                "reconstruct",
                "shorten",
                "normalize",
                "substitute_path_segments",
                "select_another_field",
            ],
            "opaque_token_guard": {
                "task_authority": {
                    "prefix": "da1-",
                    "hex_characters_after_prefix": 40,
                    "truncate_to_32_hex_characters": "invalid",
                }
            },
        },
        "append_every_next_complete_handle_ready_typed_action_until_limit_or_new_handle_dependency": [
            "--action",
            "<action-name>",
            "<typed-fact-arguments>",
        ],
        "replace_only": [
            "<action-name>",
            "<typed-fact-arguments>",
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
    assert "check" not in property_result["draft"]["allowed_actions"]
    assert "draft-check" in property_result["draft"]["allowed_lifecycle_commands"]
    assert not (tmp_path / "state" / "transactions").exists()


def test_object_set_normal_typed_argv_preserves_wire_paths_and_scalar_facts(
    tmp_path: Path,
) -> None:
    start_code, started = execute(tmp_path, "draft-start", "object.set")
    assert start_code == 0
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    action_path = (
        r"\Events\Default Work Unit\天气 与 雷声\Play_Rain"
    )
    hostile_notes = '--apply stays data; quotes " & $(no-shell) C:\\Temp\\雪'

    code, result = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "add_target",
        "--target",
        "direct-child",
        "Action",
        "path",
        action_path,
        "--notes",
        hostile_notes,
        "--property",
        "FadeTime",
        "number",
        "0.0",
        "--property",
        "Delay",
        "number",
        "1.25",
    )

    assert code == 0
    assert result["draft"]["current_facts"] == [
        {
            "handle": result["draft"]["current_facts"][0]["handle"],
            "selector": {
                "kind": "direct-child",
                "parent": {"kind": "path", "value": action_path},
                "type": "Action",
            },
            "notes": hostile_notes,
            "properties": [
                {"name": "FadeTime", "value": 0.0},
                {"name": "Delay", "value": 1.25},
            ],
            "references": [],
            "children": [],
            "lists": [],
            "import": None,
        }
    ]


def test_object_set_add_target_uses_direct_reference_flag_without_field_name(
    tmp_path: Path,
) -> None:
    _code, started = execute(tmp_path, "draft-start", "object.set")
    bus_path = r"\Master-Mixer Hierarchy\Default Work Unit\Weapons"

    code, result = execute(
        tmp_path,
        "draft-apply",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "add_target",
        "--target",
        "id",
        TARGET_ID,
        "--reference",
        "OutputBus",
        "path",
        bus_path,
    )

    assert code == 0
    assert result["draft"]["current_facts"][0]["references"] == [
        {
            "name": "OutputBus",
            "target": {"kind": "path", "value": bus_path},
        }
    ]


def test_normal_composer_schema_discloses_typed_argv_not_action_json(
    tmp_path: Path,
) -> None:
    code, payload = execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "object.set",
    )

    assert code == 0
    apply = payload["composer"]["apply"]
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "--action" in encoded
    assert "--target" in encoded
    assert "--property" in encoded
    assert "--value" not in encoded
    assert '"FIELD"' not in encoded
    assert apply["action_argv"]["add_target"] == [
        "--target", "SELECTOR_KIND", "SELECTOR_VALUES...",
        "[--name VALUE]", "[--notes VALUE]", "[--platform VALUE]",
        "[--list-mode VALUE]", "[--on-name-conflict VALUE]",
        "[--property NAME TYPE VALUE]...",
        "[--reference NAME SELECTOR_KIND SELECTOR_VALUES...]...",
    ]
    assert "--action-json" not in encoded
    assert "typed-action-json" not in encoded


@pytest.mark.parametrize(
    ("version", "operation", "path", "expected"),
    (
        (
            "2021.1",
            "object.create",
            ["args", "on_name_conflict"],
            {
                "phase": "before_dynamic_disclosure",
                "fact_action": "set",
            },
        ),
        (
            "2022.1",
            "soundbank.setInclusions",
            ["args", "soundbank", "kind"],
            {
                "phase": "before_dynamic_disclosure",
                "fact_action": "set",
                "constant_fact_required": True,
            },
        ),
    ),
)
def test_public_composer_fields_bind_fact_action_before_disclosure(
    tmp_path: Path,
    version: str,
    operation: str,
    path: list[str],
    expected: dict[str, object],
) -> None:
    code, payload = execute(
        tmp_path,
        "--version",
        version,
        "operation-schema",
        operation,
    )

    assert code == 0, payload
    field = next(
        item
        for item in _composer_fields(payload["composer"])
        if item["path"] == path
    )
    if "constant_fact_required" in expected:
        assert field["constant_values"]
        assert "fact_construction" not in field
    else:
        columns = payload["composer"]["top_level_fact_plan"]["columns"]
        rows = payload["composer"]["top_level_fact_plan"]["rows"]
        plan = [dict(zip(columns, row, strict=True)) for row in rows]
        planned = next(item for item in plan if item["handle"] == field["handle"])
        assert planned["phase"] == "fact"
        assert planned["action"] == expected["fact_action"]
    assert payload["composer"]["construction_order"]["top_level_facts"] == (
        "follow top_level_fact_plan before disclosures"
    )
    assert payload["composer"]["construction_order"]["constant_facts"] == (
        "set selected constants"
    )


def test_choose_response_discloses_the_selected_branch_constant_before_disclosure(
    tmp_path: Path,
) -> None:
    code, schema = execute(
        tmp_path,
        "--version",
        "2023.1",
        "operation-schema",
        "object.create",
    )
    assert code == 0, schema
    parent = next(
        field
        for field in _composer_fields(schema["composer"])
        if field["path"] == ["args", "parent"] and field["shape"] == "branch"
    )
    path_choice = next(
        field
        for field in _composer_fields(schema["composer"])
        if field.get("parent_handle") == parent["handle"]
        and field.get("branch_choice_constants") == {"kind": "path"}
    )
    kind = next(
        field
        for field in _composer_fields(schema["composer"])
        if field.get("parent_handle") == path_choice["handle"]
        and field["name"] == "kind"
    )

    start_code, started = execute(
        tmp_path,
        "--version",
        "2023.1",
        "draft-start",
        "object.create",
    )
    assert start_code == 0, started
    apply_code, applied = execute(
        tmp_path,
        "--version",
        "2023.1",
        "draft-apply",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--compact",
        "--facts",
        "--action",
        "add_typed_fact",
        "--fact-action",
        "choose",
        "--field-handle",
        parent["handle"],
        "--fact-value",
        path_choice["handle"],
    )

    assert apply_code == 0, applied
    assert applied["draft"]["action_result"]["required_followup_facts"] == [
        {
            "reason": "selected_branch_constant",
            "is_next_command": True,
            "literal_copy_policy": {
                "copy_fixed_full_argv_exactly": True,
                "business_value_substitution": "invalid",
            },
            "fixed_full_argv": [
                "python",
                str(waapi_gateway.GATEWAY_RUNNER_PATH),
                "gateway.py",
                "draft-apply",
                started["draft"]["draft_id"],
                "--task-authority",
                started["task_authority"],
                "--expected-revision",
                "2",
                "--compact",
                "--facts",
                "--action",
                "add_typed_fact",
                "--fact-action",
                "set",
                "--field-handle",
                kind["handle"],
                "--value-type",
                "string",
                "--fact-value",
                "path",
            ],
            "typed_fact_arguments": [
                "--action",
                "add_typed_fact",
                "--fact-action",
                "set",
                "--field-handle",
                kind["handle"],
                "--value-type",
                "string",
                "--fact-value",
                "path",
            ],
        }
    ]
    assert applied["draft"]["next_action_binding"]["shell_tool_timeout_ms"] == 30_000


def test_public_object_set_schema_discloses_the_exact_default_container_metadata_scope(
    tmp_path: Path,
) -> None:
    code, payload = execute(
        tmp_path,
        "--version",
        "2025.1",
        "operation-schema",
        "object.set",
    )

    assert code == 0, payload
    exact = payload["composer"]["start"]["preconditions"][
        "reviewed_default_container_metadata_argv"
    ]
    assert exact["gateway_argv_template"] == [
        "metadata",
        "discover",
        "--object-type",
        "PropertyContainer",
        "--query",
        "<requested-field-name>",
        "--limit",
        "<derived-from-query-count>",
    ]
    assert exact["replace_only"] == ["<requested-field-name>"]
    assert exact["query_policy"] == {
        "include_only_requested_dynamic_property_or_reference_tokens": True,
        "known_target_fields_are_not_queries": [
            "name",
            "notes",
            "platform",
            "list_mode",
            "on_name_conflict",
        ],
    }
    assert exact["limit_by_query_count"] == {
        "1..2": 8,
        "3..4": 3,
        "5..8": 2,
    }


def test_object_create_schema_puts_the_top_level_fact_plan_before_large_fields(
    tmp_path: Path,
) -> None:
    code, payload = execute(
        tmp_path,
        "--version",
        "2021.1",
        "operation-schema",
        "object.create",
    )

    assert code == 0, payload
    encoded = waapi_gateway.gateway_stdout_json_encoder(payload).encode(payload)
    assert len((encoded + "\n").encode("utf-8")) < 21 * 1024
    composer = payload["composer"]
    assert list(composer).index("construction_order") < list(composer).index(
        "typed_request_field_table"
    )
    assert list(composer).index("top_level_fact_plan") < list(
        composer
    ).index("typed_request_field_table")
    assert "typed_request_fields" not in composer
    assert composer["typed_request_field_table"]["contract"] == (
        "waapi-skill.compact-typed-field-table/v1"
    )
    expected_fields = []
    for field in draft_operation_request_contract(
        "object.create", "2021.1"
    ).gateway_field_payloads():
        expected = dict(field)
        expected.pop("fact_construction", None)
        expected_fields.append(expected)
    assert _composer_fields(composer) == expected_fields
    table = composer["top_level_fact_plan"]
    plan = [
        dict(zip(table["columns"], row, strict=True)) for row in table["rows"]
    ]
    names = [field["name"] for field in plan]
    assert names.index("on_name_conflict") < names.index("children")
    conflict = next(field for field in plan if field["name"] == "on_name_conflict")
    children = next(field for field in plan if field["name"] == "children")
    assert conflict["phase"] == "fact"
    assert conflict["action"] == "set"
    assert children["phase"] == "disclosure"
    assert table["branch_selection_authority"] == {
        "business_pointer": "/args/parent",
        "preserve_explicit_user_selector_kind_and_value": True,
        "when_explicit_parent_path_is_present": (
            "choose_path_branch_and_set_that_exact_parent_path"
        ),
        "queried_same_name_merge_target_guid_as_parent": (
            "forbidden_identity_proof_only"
        ),
    }
    assert table["dynamic_disclosure_authority"] == (
        "properties,references,children in that order"
    )
    assert not {
        "branch_fact_expansion",
        "business_fact_selection",
        "business_pointer_source",
        "fact_batching",
    }.intersection(table)
    parent = next(field for field in plan if field["name"] == "parent")
    assert parent["business_pointer"] == "/args/parent"
    assert composer["construction_order"]["branch_constants"] == (
        "set selected branch constants before disclosure"
    )
    dynamic = composer["dynamic_container_commands"]
    assert dynamic["schema_binding_choice"] == {
        "root_handle": "schema_digest_required_parent_schema_token_forbidden",
        "returned_child_handle": (
            "parent_schema_token_required_schema_digest_forbidden"
        ),
        "both_or_neither": "invalid",
    }
    assert "--schema-digest" not in dynamic["nested_map_value_argv"]
    assert "--schema-digest" not in dynamic["nested_array_item_argv"]
    assert "--parent-schema-token" in dynamic["nested_map_value_argv"]
    assert "--parent-schema-token" in dynamic["nested_array_item_argv"]
    assert "nested_parent_argv" not in dynamic

    properties = next(
        field
        for field in _composer_fields(composer)
        if field["path"] == ["args", "properties"]
    )
    item_code, item = execute(
        tmp_path,
        "--version",
        "2021.1",
        "request-array-item",
        "object.create",
        "--schema-digest",
        composer["typed_request_schema_digest"],
        "--array-handle",
        properties["handle"],
        "--index",
        "0",
        "--shape",
        "object",
    )
    assert item_code == 0, item
    assert "action_argv" not in item["continuation"]
    assert item["continuation"]["deferred_fact"]["argv"][-1] == item["handle"]


def test_invalid_or_mixed_typed_action_argv_is_atomic(
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
    original = record_path.read_bytes()

    duplicate_code, duplicate = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "set_request_option",
        "--value",
        "name",
        "string",
        "list_mode",
        "--value",
        "name",
        "string",
        "platform",
    )
    mixed_code, mixed = execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "clear_request_option",
        "--action-json",
        action("clear_request_option", name="platform"),
    )

    assert duplicate_code == mixed_code == 2
    assert duplicate["error_code"] == mixed["error_code"] == "GatewayInputError"
    assert record_path.read_bytes() == original


@pytest.mark.parametrize(
    "typed_action",
    [
        action_mapping("set_request_option", name="list_mode", value="append"),
        action_mapping("clear_request_option", name="platform"),
        action_mapping(
            "add_target",
            selector={
                "kind": "scoped-name",
                "type": "Action",
                "name": "Play 雨",
                "parent": {
                    "kind": "path",
                    "value": r"\Events\Default Work Unit\天气",
                },
            },
            name="Renamed Target",
            notes='quotes " and $() stay data',
            properties=[{"name": "Volume", "value": -3.0}],
            references=[
                {
                    "name": "OutputBus",
                    "target": {
                        "kind": "path",
                        "value": r"\Master-Mixer Hierarchy\Default Work Unit\总线",
                    },
                }
            ],
        ),
        action_mapping(
            "set_reference",
            owner_handle="odh1-111111111111111111111111",
            name="OutputBus",
            target={"kind": "id", "value": TARGET_ID},
        ),
        action_mapping(
            "set_import_row_field",
            import_handle="odh1-222222222222222222222222",
            name="event",
            value={
                "action": "Play",
                "path": r"\Events\Default Work Unit\Play_One",
            },
        ),
        action_mapping(
            "add_import_row",
            object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\One",
            object_type="Sound SFX",
            properties=[{"name": "Volume", "value": -6.25}],
            assignment={"mode": "switch", "value": "Snow"},
        ),
    ],
)
def test_typed_action_argv_round_trips_closed_business_facts(
    typed_action: Mapping[str, Any],
) -> None:
    argv = typed_action_cli_arguments(typed_action)

    assert "--action-json" not in argv
    assert parse_typed_action_cli_arguments(argv) == typed_action


@pytest.mark.parametrize(
    "typed_action",
    [
        action_mapping("set_target_field", target_handle="t", name="notes", value="x"),
        action_mapping("clear_target_field", target_handle="t", name="notes"),
        action_mapping("set_property", target_handle="t", name="Volume", value=-3.0),
        action_mapping("remove_property", target_handle="t", name="Volume"),
        action_mapping(
            "set_reference",
            owner_handle="o",
            name="OutputBus",
            target={"kind": "path", "value": r"\Master-Mixer Hierarchy\Bus"},
        ),
        action_mapping("remove_reference", owner_handle="o", name="OutputBus"),
        action_mapping("add_child", parent_handle="p", type="Sound", name="Child"),
        action_mapping("set_node_field", node_handle="n", name="notes", value="x"),
        action_mapping("clear_node_field", node_handle="n", name="notes"),
        action_mapping("set_node_property", node_handle="n", name="Volume", value=-1),
        action_mapping("remove_node_property", node_handle="n", name="Volume"),
        action_mapping("remove_node", node_handle="n"),
        action_mapping("add_list", target_handle="t", name="children"),
        action_mapping("remove_list", list_handle="l"),
        action_mapping("add_list_member", list_handle="l", type="Sound", name="One"),
        action_mapping("remove_target", target_handle="t"),
        action_mapping(
            "add_import_file",
            owner_handle="o",
            audio_file="/tmp/one.wav",
            originals_subfolder="incoming",
            language="SFX",
            object_type="Sound SFX",
        ),
        action_mapping("set_import_file_field", file_handle="f", name="language", value="SFX"),
        action_mapping("clear_import_file_field", file_handle="f", name="language"),
        action_mapping("remove_import_file", file_handle="f"),
        action_mapping("set_import_option", owner_handle="o", name="auto_add", value=False),
        action_mapping("clear_import_option", owner_handle="o", name="auto_add"),
        action_mapping("remove_import", owner_handle="o"),
    ],
)
def test_every_object_set_normal_action_round_trips_specific_flags(
    typed_action: Mapping[str, Any],
) -> None:
    argv = typed_action_cli_arguments(typed_action)

    assert "--value" not in argv
    assert "--null" not in argv
    assert "--assignment" not in argv
    assert parse_typed_action_cli_arguments(argv) == typed_action


@pytest.mark.parametrize(
    "typed_action",
    [
        action_mapping(
            "set_import_option",
            name="auto_add_to_source_control",
            value=True,
        ),
        action_mapping(
            "clear_import_option",
            name="auto_check_out_to_source_control",
        ),
    ],
)
def test_audio_import_source_control_actions_need_no_object_owner_handle(
    typed_action: Mapping[str, Any],
) -> None:
    argv = typed_action_cli_arguments(typed_action)

    assert "--owner-handle" not in argv
    assert parse_typed_action_cli_arguments(argv) == typed_action


def test_audio_import_generic_option_cannot_replace_dedicated_operation_action() -> None:
    with pytest.raises(OperationComposerError, match="not public"):
        parse_typed_action_cli_arguments(
            (
                "--action",
                "set_import_option",
                "--option",
                "import_operation",
                "string",
                "useExisting",
            )
        )


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ("--action", "set_request_option", "--option", "list_mode", "string", "append"),
            action_mapping("set_request_option", name="list_mode", value="append"),
        ),
        (
            (
                "--action", "set_property", "--target-handle",
                "odh1-111111111111111111111111", "--property", "Volume", "number", "-3.0",
            ),
            action_mapping(
                "set_property",
                target_handle="odh1-111111111111111111111111",
                name="Volume",
                value=-3.0,
            ),
        ),
        (
            (
                "--action", "set_reference", "--owner-handle",
                "odh1-111111111111111111111111", "--reference", "OutputBus",
                "path", r"\Master-Mixer Hierarchy\Default Work Unit\Weapons",
            ),
            action_mapping(
                "set_reference",
                owner_handle="odh1-111111111111111111111111",
                name="OutputBus",
                target={
                    "kind": "path",
                    "value": r"\Master-Mixer Hierarchy\Default Work Unit\Weapons",
                },
            ),
        ),
        (
            (
                "--action", "add_child", "--parent-handle",
                "odh1-111111111111111111111111", "--type", "Sound", "--name", "Child",
            ),
            action_mapping(
                "add_child",
                parent_handle="odh1-111111111111111111111111",
                type="Sound",
                name="Child",
            ),
        ),
        (
            (
                "--action", "add_list", "--target-handle",
                "odh1-111111111111111111111111", "--list", "children",
            ),
            action_mapping(
                "add_list",
                target_handle="odh1-111111111111111111111111",
                name="children",
            ),
        ),
    ],
)
def test_object_set_action_specific_argv_never_requires_internal_field_names(
    arguments: tuple[str, ...],
    expected: Mapping[str, Any],
) -> None:
    assert parse_typed_action_cli_arguments(arguments) == expected


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
        "construction_boundary": {
            "phase": "preview_construction",
            "mutation": False,
            "complete": False,
            "required_terminal": "preview",
            "before": "continue_no_confirm_no_end",
        },
    }
    assert draft["agent_control"] == {
        "terminal": False,
        "required_outcome_before_reply": "preview_or_structured_refusal",
        "next": "follow_next_action_binding",
        "reply_or_claim_preview_now": "invalid",
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
    assert draft["next_action_binding"]["fixed_argv_prefix"] == [
        "python",
        str(waapi_gateway.GATEWAY_RUNNER_PATH),
        "gateway.py",
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--compact",
        "--facts",
    ]
    assert draft["next_action_binding"][
        "append_every_next_complete_handle_ready_typed_action_until_limit_or_new_handle_dependency"
    ] == [
        "--action",
        "<action-name>",
        "<typed-fact-arguments>",
    ]
    assert set(draft["next_action_binding"]) == {
        "contract",
        "shell_tool_timeout_ms",
        "fixed_argv_prefix",
        "append_every_next_complete_handle_ready_typed_action_until_limit_or_new_handle_dependency",
        "replace_only",
    }
    assert "completion_candidate" not in draft["next_action_binding"]
    assert draft["next_action_binding"]["replace_only"] == [
        "<action-name>",
        "<typed-fact-arguments>",
    ]

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
    incomplete_sizes: list[int] = []
    complete_sizes: list[int] = []

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
            "agent_control",
        }
        handle = targeted["draft"]["action_result"]["created_handles"][0]
        revision += 1
        targeted_size = len(json.dumps(targeted).encode("utf-8"))
        response_sizes.append(targeted_size)
        assert targeted["draft"]["schema_required_fields_status"] == "incomplete"
        incomplete_sizes.append(targeted_size)
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
            assert changed["draft"]["response_integrity"][
                "construction_boundary"
            ]["complete"] is False
            assert (
                changed["draft"]["response_integrity"][
                    "compact_projection_is_not_truncation"
                ]
                is True
            )
            assert changed["draft"]["response_integrity"][
                "construction_boundary"
            ]["before"] == "continue_no_confirm_no_end"
            revision += 1
            changed_size = len(json.dumps(changed).encode("utf-8"))
            response_sizes.append(changed_size)
            assert changed["draft"]["schema_required_fields_status"] == "complete"
            complete_sizes.append(changed_size)

    assert len(response_sizes) == 15
    # Required-incomplete target-only receipts omit draft-check.  Once a
    # property makes the schema complete, the exact completion candidate adds
    # its copy-ready shell command.  Both projections remain bounded.
    assert max(response_sizes) < 3_500
    assert len(incomplete_sizes) == 5
    assert len(complete_sizes) == 10
    assert max(incomplete_sizes) - min(incomplete_sizes) < 16
    assert max(complete_sizes) - min(complete_sizes) < 16
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
    _assert_pristine_inspected_draft(started, inspected)


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
    _assert_pristine_inspected_draft(started, inspected)


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


def test_shared_uri_composers_are_isolated_by_exact_operation_name(
    tmp_path: Path,
) -> None:
    assert operation_input_mode("object.set", "2022.1") == COMPOSER_INPUT_MODE
    assert operation_input_mode("object.setRTPC", "2022.1") == COMPOSER_INPUT_MODE
    assert operation_input_mode("object.createPlugin", "2022.1") == COMPOSER_INPUT_MODE
    exit_code, started = execute(tmp_path, "draft-start", "object.setRTPC")

    assert exit_code == 0
    assert started["draft"]["binding"]["operation"] == "object.setRTPC"


def test_rtpc_public_composer_discloses_exact_business_mode_mapping(
    tmp_path: Path,
) -> None:
    exit_code, payload = execute(
        tmp_path,
        "--version",
        "2025.1",
        "operation-schema",
        "object.setRTPC",
    )

    assert exit_code == 0
    mode = next(
        field
        for field in payload["composer"]["typed_request_fields"]
        if field["name"] == "mode"
    )
    assert mode["enum"] == ["add", "add_or_replace"]
    assert mode["description"] == (
        "Use add_or_replace when the user asks to replace the matching RTPC if "
        "present and add it if absent; use add only when an existing exact "
        "property and ControlInput match must fail."
    )


def test_audio_import_schema_requires_one_complete_metadata_query_batch(
    tmp_path: Path,
) -> None:
    exit_code, payload = execute(
        tmp_path,
        "--version",
        "2025.1",
        "operation-schema",
        "audio.import",
    )

    assert exit_code == 0, payload
    assert "start_preconditions" not in payload["composer"]
    assert payload["composer"]["start"]["preconditions"][
        "metadata_query_batch"
    ] == {
        "scope": "one exact object, class, or object-type scope",
        "first_request": (
            "include every distinct prompt-present dynamic property/reference "
            "token for this operation and scope"
        ),
        "row_field_inventory": (
            "include shared and every row-local dynamic property/reference, "
            "including scalar fields whose values differ by row"
        ),
        "one_to_eight_queries": "one metadata discover command",
        "split_within_limit": "invalid",
        "successful_complete_scope_result": "do_not_query_that_scope_again",
        "partial_fallback": "one broader retry only when explicitly reported partial",
    }


def test_registry_composer_lanes_and_real_adapters_are_one_to_one() -> None:
    composer_lanes: set[tuple[str, str]] = set()
    adapter_lanes: set[tuple[str, str]] = set()

    for spec in list_operation_specs():
        for version in spec.supported_versions:
            lane = (spec.name, version)
            if operation_input_mode(*lane) == COMPOSER_INPUT_MODE:
                composer_lanes.add(lane)
            try:
                contract = operation_composer_contract(*lane)
            except OperationComposerError as exc:
                assert exc.error_code == "OPERATION_DRAFT_ADAPTER_UNAVAILABLE"
            else:
                assert contract["operation"] == spec.name
                assert contract["version"] == version
                adapter_lanes.add(lane)

    assert adapter_lanes == composer_lanes
    assert {operation for operation, _version in composer_lanes} == {
        "audio.import",
        "object.create",
        "object.createPlugin",
        "object.set",
        "object.setRTPC",
        "soundbank.convertExternalSources",
        "soundbank.generate",
        "soundbank.setInclusions",
        "ui.commands.register",
        "ui.commands.unregister",
        "lua.executeCliFile",
        "lua.executeCoreFile",
        "lua.executeCoreInline",
        "waapi.undoGroup",
    }


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
    assert "preview-from-draft" not in checked["draft"]["allowed_actions"]
    assert "preview-from-draft" in checked["draft"]["allowed_lifecycle_commands"]
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
    assert checked["draft"]["construction_state"] == {
        "draft_complete": True,
        "preview_created": False,
        "required_next_phase": "preview-from-draft",
        "execute_returned_next_command_exactly": True,
        "construction_boundary": {
            "phase": "preview_construction",
            "mutation": False,
            "complete": False,
            "required_terminal": "preview",
            "before": "continue_no_confirm_no_end",
        },
    }
    assert "next_action_binding" not in checked["draft"]
    next_command = checked["next_command"]
    assert next_command["command"] == "preview-from-draft"
    assert next_command["gateway_argv"] == [
        "preview-from-draft",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--apply",
    ]
    assert next_command["copy_exactly"] is True
    source_field = next_command["copy_instruction"]["source_field"]
    assert source_field in {"shell_command", "model_command"}
    assert "--apply" in next_command[source_field]
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
    assert "preview-from-draft" not in edited["draft"]["allowed_lifecycle_commands"]
    assert "draft-check" in edited["draft"]["allowed_lifecycle_commands"]


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

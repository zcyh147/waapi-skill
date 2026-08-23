from __future__ import annotations

import base64
import importlib.util
import json
import re
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest
from tests.support.canonical_preview import bind_canonical_preview_fixture

from wwise_waapi.operation_composer import (  # pyright: ignore[reportMissingImports]
    OperationComposerError,
    materialize_operation_request,
    new_composition,
    operation_composer_contract,
    operation_composer_digest,
    parse_typed_action_cli_arguments,
    typed_action_cli_arguments,
)
from wwise_waapi.operation_drafts import (  # pyright: ignore[reportMissingImports]
    OperationDraftStore,
)
from wwise_waapi.operation_registry import (  # pyright: ignore[reportMissingImports]
    COMPOSER_INPUT_MODE,
    INTERNAL_CANONICAL_INPUT_MODE,
    operation_input_mode,
    operation_request_schema_digest,
)
from wwise_waapi.transactions import TransactionStore  # pyright: ignore[reportMissingImports]


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_audio_import_composer_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)
waapi_gateway.execute_gateway = bind_canonical_preview_fixture(waapi_gateway)


ACTION_CONTRACT = "waapi-skill.operation-draft-action/v1"
IMPORT_HANDLE_RE = re.compile(r"^odh1-[0-9a-f]{24}$")


def _env(tmp_path: Path, *, version: str = "2022.1") -> dict[str, str]:
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
        "WWISE_VERSION": version,
    }


def _execute(tmp_path: Path, *arguments: str) -> tuple[int, dict[str, Any]]:
    def fail_if_connected(url: str) -> None:
        raise AssertionError(f"offline Composer command connected to {url}")

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
        env=_env(tmp_path),
        client_factory=fail_if_connected,
    )


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


def _live_info() -> dict[str, Any]:
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


def _project_info(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "project" / "SampleProject"
    originals = root / "Originals"
    originals.mkdir(parents=True, exist_ok=True)
    project_file = root / "SampleProject.wproj"
    project_file.write_text("<WwiseDocument/>", encoding="utf-8")
    return {
        "id": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
        "name": "SampleProject",
        "displayTitle": "SampleProject",
        "path": str(project_file),
        "isDirty": False,
        "currentLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "referenceLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
        "currentPlatformId": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
        "directories": {
            "root": str(root),
            "cache": str(root / ".cache"),
            "originals": str(originals),
            "soundBankOutputRoot": str(root / "GeneratedSoundBanks"),
            "commands": str(root / "Commands"),
            "properties": str(root / "Properties"),
        },
        "platforms": [
            {
                "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
                "name": "Mac",
                "baseName": "Mac",
                "baseDisplayName": "Mac",
                "soundBankPath": str(root / "GeneratedSoundBanks/Mac"),
                "copiedMediaPath": str(root / "GeneratedSoundBanks/Mac/Media"),
            }
        ],
        "languages": [
            {
                "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "name": "SFX",
                "shortId": 1,
            }
        ],
        "defaultConversion": {
            "id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}",
            "name": "Default",
        },
    }


def _audio_import_client(tmp_path: Path) -> FakeClient:
    parent_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Composer"
    parent = {
        "id": "{11111111-1111-1111-1111-111111111111}",
        "name": "Composer",
        "type": "ActorMixer",
        "path": parent_path,
        "parent": {"id": "{22222222-2222-2222-2222-222222222222}"},
        "notes": "",
    }
    project = _project_info(tmp_path)
    return FakeClient(
        {
            "ak.wwise.core.getInfo": [_live_info()],
            "ak.wwise.core.getProjectInfo": [project, project],
            "ak.wwise.core.object.get": [
                {"return": [parent]},
                {"return": []},
            ],
            "ak.wwise.core.object.getTypes": [
                {
                    "return": [
                        {"classId": 65552, "name": "Sound", "type": "WObject"}
                    ]
                }
            ],
        }
    )


def _live_execute(
    tmp_path: Path,
    client: FakeClient,
    *arguments: str,
) -> tuple[int, dict[str, Any]]:
    return waapi_gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *arguments],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )


def _action(action_name: str, **fields: Any) -> str:
    if action_name == "add_import_row":
        assignment = fields.pop("switch_assignment", None)
        fields["assignment"] = (
            {"mode": "none"}
            if assignment is None
            else {"mode": "switch", "value": assignment}
        )
    return json.dumps(
        {"contract": ACTION_CONTRACT, "action": action_name, **fields},
        ensure_ascii=False,
    )


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_base_audio_import_adapter_is_registry_derived_and_normal_cutover(
    version: str,
) -> None:
    contract = operation_composer_contract("audio.import", version)

    assert contract["operation"] == "audio.import"
    assert "phase" not in contract
    assert "phase" not in contract["registry_fragments"]
    shapes = contract["action_shapes"]
    simple_required = {
        "set_import_operation": ["mode"],
        "set_import_option": ["name", "value"],
        "clear_import_option": ["name"],
        "set_import_default": ["name", "value"],
        "clear_import_default": ["name"],
        "set_import_row_field": ["import_handle", "name", "value"],
        "clear_import_row_field": ["import_handle", "name"],
        "remove_import_row": ["import_handle"],
    }
    assert set(shapes) == {
        *simple_required,
        "add_import_row",
    }
    for action_name, required_fields in simple_required.items():
        expected_shape = {
            "fixed_fields": {
                "contract": ACTION_CONTRACT,
                "action": action_name,
            },
            "required_fields": required_fields,
            "optional_fields": [],
        }
        if action_name in {"set_import_option", "clear_import_option"}:
            expected_shape.update(
                {
                    "allowed_names": [
                        "auto_add_to_source_control",
                        *(
                            ["auto_check_out_to_source_control"]
                            if version in {"2023.1", "2024.1", "2025.1"}
                            else []
                        ),
                    ],
                    "value_type": "boolean",
                    "import_operation_uses": "set_import_operation",
                }
            )
        assert shapes[action_name] == expected_shape
    row_optional = [
        "audio_file",
        "audio_file_base64",
        "audio_source_notes",
        "dialogue_event",
        "event",
        "import_language",
        "import_location",
        "notes",
        "object_type",
        "originals_subfolder",
        "properties",
        "references",
    ]
    row_extra = {
        "optional_fields": row_optional,
        "construction_discipline": contract["flat_import_row_discipline"],
        "user_fact_checklist": shapes["add_import_row"]["user_fact_checklist"],
        "conditional_required_fields": shapes["add_import_row"][
            "conditional_required_fields"
        ],
    }
    assert shapes["add_import_row"] == {
        "fixed_fields": {
            "contract": ACTION_CONTRACT,
            "action": "add_import_row",
        },
        "required_fields": ["object_path", "assignment"],
        "assignment_contract": {
            "required_on_every_row": True,
            "modes": {
                "none": {"fields": ["mode"]},
                "switch": {"fields": ["mode", "value"]},
            },
            "requires_exact_user_value": True,
            "additional_fields": False,
        },
        **row_extra,
    }
    assert "add_import_row_without_switch_assignment" not in shapes
    assert "add_switch_assigned_import_row" not in shapes
    assert contract["flat_import_row_discipline"] == {
        "initial_row_action": "add_import_row",
        "one_initial_action_per_row": True,
        "switch_assignment": {
            "required_in_initial_row_action": True,
            "ordinary_row": {"mode": "none"},
            "when_user_requested": {"mode": "switch", "value": "VALUE"},
            "applies_to": "this_row_object_path",
            "new_parent_or_container": (
                "switch_when_user_assigns_that_object"
            ),
            "other_rows": "none_unless_user_assigns_that_row",
        },
        "never_guess_assignment_intent": True,
        "include_every_known_field_in_one_action": True,
        "same_row_event": {
            "when_requested": "include_in_initial_add_import_row",
            "defer_or_omit": "invalid",
        },
        "hierarchy_row_order": {
            "requested_structure_rows_are_separate": True,
            "structure_rows": "tree_preorder_before_every_media_row",
            "media_rows": "prompt_order_after_all_structure_rows",
            "typed_descendant_path_does_not_replace_requested_structure_row": True,
            "batching": (
                "concatenate_structure_then_media_and_split_only_at_batch_limit"
            ),
        },
        "metadata_dependency_activation": (
            "agent_selects_exact_token_gateway_validates_dependencies"
        ),
    }
    assert contract["start_preconditions"]["workflow_control"] == {
        "metadata_success_is_terminal": False,
        "continue_same_turn_after_metadata": "draft-start",
        "reply_before_draft_start": "invalid",
    }
    assert contract["registry_fragments"]["supported_row_fields"] == [
        "audio_file",
        "audio_file_base64",
        "audio_source_notes",
        "dialogue_event",
        "event",
        "import_language",
        "import_location",
        "notes",
        "object_path",
        "object_type",
        "originals_subfolder",
        "properties",
        "references",
        "switch_assignment",
    ]
    assert set(contract["registry_fragments"]["request_options"]) == {
        "auto_add_to_source_control",
        "auto_check_out_to_source_control",
        "import_operation",
    }
    assert contract["planning_discipline"] == {
        "dynamic_metadata": {
            "fields": ["properties", "references"],
            "discovery_owner": "agent_metadata_discover",
            "validation_owner": "gateway_draft_check",
            "agent_metadata_command_required": (
                "when_token_is_not_already_exact_live_evidence"
            ),
            "action_fields_source": "explicit_user_intent_plus_exact_live_tokens",
            "property_value_type": {
                "source": "metadata.candidates[].metadata.typed_value_type",
                "copy_to": "--property NAME <typed_value_type> VALUE",
                "native_metadata_type_is_not_action_type": True,
            },
            "unrequested_dependency_candidates": (
                "validation_only_do_not_copy_into_action"
            ),
            "validated_at": "draft-check_and_preview",
            "preview_revalidates": True,
        },
        "import_operation": {
            "source": "registry_fragments.request_options.import_operation",
            "action": "set_import_operation",
            "gateway_default": "createNew",
            "default_is_materialized_at": "draft-start",
            "action_required_only_for": ["useExisting", "replaceExisting"],
            "do_not_submit_redundant_default": True,
        },
    }
    import_operation = contract["registry_fragments"]["request_options"][
        "import_operation"
    ]
    assert (
        "preserve the existing object's identity while updating its media"
        in import_operation["description"]
    )
    assert (
        "replaceExisting only when the user authorizes replacing the object"
        in import_operation["description"]
    )
    assert contract["action_shapes"]["add_import_row"][
        "construction_discipline"
    ] == contract["flat_import_row_discipline"]
    assert list(contract).index("flat_import_row_discipline") < list(contract).index(
        "action_shapes"
    )
    assert list(contract).index("planning_discipline") < list(contract).index(
        "action_shapes"
    )
    assert "add_import_row" in contract["actions"]
    assert "add_import_row" in contract["action_shapes"]
    dependency = contract["registry_fragments"]["metadata_dependency_closure"]
    assert dependency["metadata_source"]["same_result_required"] is True
    assert dependency["materialization"]["ordinary_dependencies"]["owner"] == (
        "request"
    )
    assert dependency["materialization"]["supported_reference_activation"][
        "owner"
    ] == "gateway"
    assert contract["registry_fragments"]["source_schema_digest"] == (
        operation_request_schema_digest("audio.import", version)
    )
    assert operation_input_mode("audio.import", version) == COMPOSER_INPUT_MODE
    assert operation_input_mode("audio.importTabDelimited", version) == "inline_typed"


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
def test_audio_import_exposes_one_row_action_with_explicit_assignment_intent(
    version: str,
) -> None:
    """Every row states ordinary or Switch assignment in its one row action."""

    contract = operation_composer_contract("audio.import", version)

    assert contract["operation"] == "audio.import"
    row_actions = [
        action
        for action in contract["actions"]
        if action.startswith("add_") and "import_row" in action
    ]
    assert row_actions == ["add_import_row"]
    row = contract["action_shapes"]["add_import_row"]
    assert row["required_fields"] == ["object_path", "assignment"]
    assert "assignment" not in row["optional_fields"]
    assert "switch_assignment" not in row["optional_fields"]
    assert "add_switch_assigned_import_row" not in contract["action_shapes"]
    assert "assign_import_row_switch" not in contract["action_shapes"]
    assert contract["flat_import_row_discipline"] == {
        "initial_row_action": "add_import_row",
        "one_initial_action_per_row": True,
        "switch_assignment": {
            "required_in_initial_row_action": True,
            "ordinary_row": {"mode": "none"},
            "when_user_requested": {"mode": "switch", "value": "VALUE"},
            "applies_to": "this_row_object_path",
            "new_parent_or_container": (
                "switch_when_user_assigns_that_object"
            ),
            "other_rows": "none_unless_user_assigns_that_row",
        },
        "never_guess_assignment_intent": True,
        "include_every_known_field_in_one_action": True,
        "same_row_event": {
            "when_requested": "include_in_initial_add_import_row",
            "defer_or_omit": "invalid",
        },
        "hierarchy_row_order": {
            "requested_structure_rows_are_separate": True,
            "structure_rows": "tree_preorder_before_every_media_row",
            "media_rows": "prompt_order_after_all_structure_rows",
            "typed_descendant_path_does_not_replace_requested_structure_row": True,
            "batching": (
                "concatenate_structure_then_media_and_split_only_at_batch_limit"
            ),
        },
        "metadata_dependency_activation": (
            "agent_selects_exact_token_gateway_validates_dependencies"
        ),
    }


def test_audio_import_draft_start_places_assignment_rule_on_the_row_action(
    tmp_path: Path,
) -> None:
    code, started = _execute(tmp_path, "draft-start", "audio.import")

    assert code == 0
    assert started["draft"]["action_guidance"]["switch_assignment"] == {
        "action": "add_import_row",
        "required_on_every_row": True,
        "ordinary_row": ["--assignment", "none"],
        "when_user_requested": ["--assignment", "switch", "<exact-value>"],
        "applies_to": "this row's --object-path",
        "new_parent_or_container": (
            "use switch on that row when the user assigns the new object"
        ),
        "other_rows": "use none unless the user assigns that row",
        "guessing_allowed": False,
    }
    assert started["draft"]["action_guidance"]["hierarchy_row_order"] == {
        "requested_structure_rows_are_separate": True,
        "structure_rows": "tree_preorder_before_every_media_row",
        "media_rows": "prompt_order_after_all_structure_rows",
        "typed_descendant_path_does_not_replace_requested_structure_row": True,
        "batching": (
            "concatenate_structure_then_media_and_split_only_at_batch_limit"
        ),
    }
    assert "cancel" not in started["draft"]["allowed_actions"]
    assert "inspect" not in started["draft"]["allowed_actions"]
    assert started["draft"]["allowed_lifecycle_commands"] == [
        "draft-inspect",
        "draft-cancel",
    ]


def test_base_audio_import_media_row_materializes_existing_canonical_request(
    tmp_path: Path,
) -> None:
    source = tmp_path / "雨 source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    start_code, started = _execute(tmp_path, "draft-start", "audio.import")
    assert start_code == 0
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    row_code, rowed = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "add_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Rain"
            ),
            audio_file=str(source),
            object_type="Sound SFX",
            import_language="SFX",
            switch_assignment=None,
        ),
    )

    assert row_code == 0
    fact = rowed["draft"]["current_facts"][0]
    assert IMPORT_HANDLE_RE.fullmatch(fact["handle"])
    assert fact == {
        "handle": fact["handle"],
        "audio_file": str(source),
        "import_language": "SFX",
        "object_path": (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Rain"
        ),
        "object_type": "Sound SFX",
    }
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=2,
        schema_digest=operation_request_schema_digest("audio.import", "2022.1"),
        composer_digest=operation_composer_digest("audio.import", "2022.1"),
    )
    assert materialized.request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2022.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Rain"
                    ),
                    "audio_file": str(source),
                    "object_type": "Sound SFX",
                    "import_language": "SFX",
                }
            ],
            "import_operation": "createNew",
        },
    }


def test_ordinary_import_row_has_no_switch_assignment_fact(
    tmp_path: Path,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    exit_code, result = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "add_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Container"
            ),
            object_type="RandomSequenceContainer",
        ),
    )

    assert exit_code == 0
    assert "switch_assignment" not in result["draft"]["current_facts"][0]


@pytest.mark.parametrize(
    "assignment",
    (None, {"mode": "switch"}, {"mode": "none", "value": "Snow"}, {"mode": "later"}),
)
def test_import_row_rejects_invalid_assignment_intent_atomically(
    tmp_path: Path,
    assignment: dict[str, Any] | None,
) -> None:
    contract = operation_composer_contract("audio.import", "2022.1")
    assert "assignment" in contract["action_shapes"]["add_import_row"]["required_fields"]
    assert "add_switch_assigned_import_row" not in contract["action_shapes"]
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
    store = OperationDraftStore(tmp_path / "state")
    before = store.inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    exit_code, result = _execute(
        tmp_path,
        "draft-apply",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--action-json",
        json.dumps(
            {
                "contract": ACTION_CONTRACT,
                "action": "add_import_row",
                "object_path": (
                    r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Legacy"
                ),
                "object_type": "RandomSequenceContainer",
                "assignment": assignment,
            }
        ),
    )

    assert exit_code != 0
    assert result["error_code"] in {
        "GatewayInputError",
        "OPERATION_DRAFT_ACTION_INVALID",
    }
    after = store.inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    assert after == before


def test_removed_assigned_row_action_is_not_a_hidden_normal_entry(
    tmp_path: Path,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
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

    exit_code, rejected = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "add_switch_assigned_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Snow"
            ),
            object_type="RandomSequenceContainer",
            switch_assignment="Snow",
        ),
    )

    assert exit_code == 2
    assert rejected["error_code"] in {
        "GatewayInputError",
        "OPERATION_DRAFT_ACTION_INVALID",
    }
    assert record_path.read_bytes() == before


def test_audio_import_normal_typed_argv_preserves_host_paths_and_explicit_assignment(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "音频 Source" / "Weather" / "Snow One.wav"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    source = str(source_path)
    object_path = (
        r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Snow One"
    )
    event_path = r"\Events\Default Work Unit\Weather\Play_Snow"
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    code, result = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "add_import_row",
        "--object-path",
        object_path,
        "--audio-file",
        source,
        "--object-type",
        "Sound SFX",
        "--import-language",
        "SFX",
        "--event",
        "Play",
        event_path,
        "--assignment",
        "switch",
        "Snow",
    )

    assert code == 0
    fact = result["draft"]["current_facts"][0]
    assert fact == {
        "handle": fact["handle"],
        "audio_file": source,
        "event": {"action": "Play", "path": event_path},
        "import_language": "SFX",
        "object_path": object_path,
        "object_type": "Sound SFX",
        "switch_assignment": "Snow",
    }


def test_audio_import_row_uses_direct_flags_with_explicit_ordinary_assignment(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "音频 Source" / "Rifle.wav"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Rifle"
    _code, started = _execute(tmp_path, "draft-start", "audio.import")

    code, result = _execute(
        tmp_path,
        "draft-apply",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "add_import_row",
        "--object-path",
        object_path,
        "--audio-file",
        str(source_path),
        "--object-type",
        "Sound SFX",
            "--import-language",
            "SFX",
            "--assignment",
            "none",
    )

    assert code == 0
    fact = result["draft"]["current_facts"][0]
    assert fact == {
        "handle": fact["handle"],
        "audio_file": str(source_path),
        "import_language": "SFX",
        "object_path": object_path,
        "object_type": "Sound SFX",
    }


def test_audio_import_normal_typed_argv_rejects_handle_bound_assignment_action(
    tmp_path: Path,
) -> None:
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps\Snow"
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
    row_code, rowed = _execute(
        tmp_path,
        "draft-apply",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "add_import_row",
        "--object-path",
        object_path,
        "--object-type",
        "RandomSequenceContainer",
        "--assignment",
        "none",
    )
    assert row_code == 0
    import_handle = rowed["draft"]["current_facts"][0]["handle"]

    assignment_code, assigned = _execute(
        tmp_path,
        "draft-apply",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
        "--facts",
        "--action",
        "assign_import_row_switch",
        "--import-handle",
        import_handle,
        "--switch",
        "Snow",
    )

    assert assignment_code == 2
    assert assigned["error_code"] == "GatewayInputError"


def test_audio_import_operation_uses_one_mode_flag_instead_of_name_value_meta_fields(
    tmp_path: Path,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")

    code, result = _execute(
        tmp_path,
        "draft-apply",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "set_import_operation",
        "--mode",
        "useExisting",
    )

    assert code == 0
    assert result["draft"]["revision"] == 2


def test_audio_import_normal_schema_discloses_operation_specific_action_flags(
    tmp_path: Path,
) -> None:
    code, payload = _execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "audio.import",
    )

    assert code == 0
    apply = payload["composer"]["apply"]
    encoded = json.dumps(apply, ensure_ascii=False)
    assert "--value" not in encoded
    assert '"FIELD"' not in encoded
    assert "--assignment" in encoded
    assert apply["action_argv"]["set_import_operation"] == ["--mode", "MODE"]
    assert payload["composer"]["action_shapes"]["set_import_option"][
        "allowed_names"
    ] == ["auto_add_to_source_control"]
    assert payload["composer"]["action_shapes"]["set_import_option"][
        "import_operation_uses"
    ] == "set_import_operation"
    assert "assign_import_row_switch" not in apply["action_argv"]
    assert apply["action_argv"]["add_import_row"][0:4] == [
        "--object-path", "PATH", "--object-type", "TYPE"
    ]
    assert apply["action_argv"]["add_import_row"][-1] == (
        "(--assignment none | --assignment switch VALUE)"
    )


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ("--action", "set_import_default", "--default", "import_language", "string", "SFX"),
            {
                "contract": ACTION_CONTRACT,
                "action": "set_import_default",
                "name": "import_language",
                "value": "SFX",
            },
        ),
        (
            (
                "--action", "set_import_row_field", "--import-handle",
                "odh1-111111111111111111111111", "--field", "notes", "string", "Ready",
            ),
            {
                "contract": ACTION_CONTRACT,
                "action": "set_import_row_field",
                "import_handle": "odh1-111111111111111111111111",
                "name": "notes",
                "value": "Ready",
            },
        ),
    ],
)
def test_audio_import_action_specific_argv_avoids_name_value_meta_fields(
    arguments: tuple[str, ...],
    expected: Mapping[str, Any],
) -> None:
    assert parse_typed_action_cli_arguments(arguments) == expected


@pytest.mark.parametrize(
    "action",
    (
        {
            "contract": ACTION_CONTRACT,
            "action": "add_import_row",
            "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
            "object_type": "Sound SFX",
            "import_location": {"kind": "id", "value": 42},
            "event": {"path": r"\Events\Default Work Unit\Play_Rain"},
            "properties": [],
            "references": [],
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_default",
            "name": "event",
            "value": {"path": r"\Events\Default Work Unit\Play_Rain"},
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_default",
            "name": "properties",
            "value": [],
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_default",
            "name": "references",
            "value": [],
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_default",
            "name": "properties",
            "value": [
                {"name": "Volume", "value": -3.0},
                {"name": "IsLoopingEnabled", "value": True},
            ],
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_default",
            "name": "references",
            "value": [
                {
                    "name": "OutputBus",
                    "target": {
                        "kind": "scoped-name",
                        "type": "AudioDevice",
                        "name": "Device",
                        "parent": {"kind": "id", "value": 7},
                    },
                }
            ],
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_row_field",
            "import_handle": "odh1-" + "1" * 24,
            "name": "import_location",
            "value": {
                "kind": "direct-child",
                "type": "ActorMixer",
                "parent": {"kind": "id", "value": 12},
            },
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_row_field",
            "import_handle": "odh1-" + "1" * 24,
            "name": "event",
            "value": {"path": r"\Events\Default Work Unit\Play_Rain"},
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_row_field",
            "import_handle": "odh1-" + "1" * 24,
            "name": "properties",
            "value": [],
        },
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_row_field",
            "import_handle": "odh1-" + "1" * 24,
            "name": "references",
            "value": [],
        },
    ),
)
def test_audio_import_structured_registry_values_round_trip_without_json(
    action: Mapping[str, Any],
) -> None:
    argv = typed_action_cli_arguments(action)

    assert "--value" not in argv
    assert "--null" not in argv
    assert parse_typed_action_cli_arguments(argv) == action


@pytest.mark.parametrize(
    "legacy_argv",
    (
        ("--action", "add_import_row", "--value", "object_path", "string", "x"),
        ("--action", "add_import_row", "--null", "notes"),
        ("--action", "add_import_row", "--selector", "import_location", "path", r"\A"),
        ("--action", "add_import_row", "--property", "properties", "Volume", "number", "-3"),
        ("--action", "add_import_row", "--reference", "references", "OutputBus", "path", r"\B"),
        ("--action", "add_import_row", "--event", "event", "Play", r"\Events\Play"),
    ),
)
def test_normal_parser_rejects_frozen_generic_fact_grammar(
    legacy_argv: tuple[str, ...],
) -> None:
    with pytest.raises(OperationComposerError):
        parse_typed_action_cli_arguments(legacy_argv)


@pytest.mark.parametrize(
    "selector",
    (
        {"kind": "id", "value": "{11111111-1111-1111-1111-111111111111}"},
        {"kind": "id", "value": 42},
        {"kind": "path", "value": r"\Actor-Mixer Hierarchy\Default Work Unit"},
        {"kind": "exact-type-name", "type": "ActorMixer", "name": "Rain"},
        {
            "kind": "direct-child",
            "type": "ActorMixer",
            "parent": {"kind": "id", "value": 7},
        },
        {
            "kind": "scoped-name",
            "type": "ActorMixer",
            "name": "Rain",
            "parent": {"kind": "id", "value": "{22222222-2222-2222-2222-222222222222}"},
        },
    ),
)
def test_audio_import_selector_kinds_preserve_string_and_integer_ids(
    selector: Mapping[str, Any],
) -> None:
    action = {
        "contract": ACTION_CONTRACT,
        "action": "set_import_default",
        "name": "import_location",
        "value": selector,
    }

    argv = typed_action_cli_arguments(action)

    assert parse_typed_action_cli_arguments(argv) == action


def test_audio_import_switch_assignment_is_part_of_the_created_row(
    tmp_path: Path,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")

    code, added = _execute(
        tmp_path,
        "draft-apply",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "1",
        "--facts",
        "--action",
        "add_import_row",
        "--object-path",
        r"\Actor-Mixer Hierarchy\Default Work Unit\Snow",
        "--object-type",
        "RandomSequenceContainer",
        "--assignment",
        "switch",
        "Snow",
    )

    assert code == 0
    assert added["draft"]["current_facts"][0]["switch_assignment"] == "Snow"


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_audio_import_row_actions_disclose_complete_structure_and_media_facts(
    version: str,
) -> None:
    contract = operation_composer_contract("audio.import", version)

    row = contract["action_shapes"]["add_import_row"]
    assert row["required_fields"] == ["object_path", "assignment"]
    assert "assignment" not in row["optional_fields"]
    assert "switch_assignment" not in row["optional_fields"]
    assert row["conditional_required_fields"] == [
        {
            "when": "every_row",
            "require_effective": ["object_type"],
            "effective_sources": ["row", "explicit_defaults"],
            "reason": "every row requires an explicit object type",
        },
        {
            "when_any_present": ["audio_file", "audio_file_base64"],
            "require_effective": ["import_language"],
            "effective_sources": ["row", "explicit_defaults"],
            "reason": "media rows require an explicit import language",
        }
    ]
    assert "add_switch_assigned_import_row" not in contract["action_shapes"]


def test_audio_import_media_row_without_explicit_language_is_atomic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
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

    exit_code, rejected = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "add_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Rain"
            ),
            object_type="Sound SFX",
            audio_file=str(source),
            switch_assignment=None,
        ),
    )

    assert exit_code == 2
    assert rejected["error_code"] in {
        "GatewayInputError",
        OperationComposerError.error_code,
    }
    assert rejected["details"] == {
        "missing_fields": ["import_language"],
        "row_kind": "media",
    }
    assert record_path.read_bytes() == before


def test_switch_assignment_is_set_on_the_created_row_before_materialization(
    tmp_path: Path,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]

    row_code, rowed = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "add_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps\Snow"
            ),
            object_type="RandomSequenceContainer",
            switch_assignment="Snow",
        ),
    )

    assert row_code == 0
    assert rowed["draft"]["current_facts"][0]["switch_assignment"] == "Snow"
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=2,
        schema_digest=operation_request_schema_digest("audio.import", "2022.1"),
        composer_digest=operation_composer_digest("audio.import", "2022.1"),
    )
    assert materialized.request["arguments"]["imports"] == [
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\Footsteps\Snow"
            ),
            "object_type": "RandomSequenceContainer",
            "switch_assignment": "Snow",
        }
    ]


def test_base_audio_import_structure_row_is_correctable_by_stable_handle(
    tmp_path: Path,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    added_code, added = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "add_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Container"
            ),
            object_type="RandomSequenceContainer",
            switch_assignment=None,
        ),
    )
    assert added_code == 0
    handle = added["draft"]["current_facts"][0]["handle"]

    corrected_code, corrected = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        _action(
            "set_import_row_field",
            import_handle=handle,
            name="object_type",
            value="SwitchContainer",
        ),
    )
    assert corrected_code == 0
    assert corrected["draft"]["current_facts"] == [
        {
            "handle": handle,
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Container"
            ),
            "object_type": "SwitchContainer",
        }
    ]
    request = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=3,
        schema_digest=operation_request_schema_digest("audio.import", "2022.1"),
        composer_digest=operation_composer_digest("audio.import", "2022.1"),
    ).request
    assert request["arguments"]["imports"] == [
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Container"
            ),
            "object_type": "SwitchContainer",
        }
    ]


def test_complete_audio_import_adapter_materializes_every_registry_field(
    tmp_path: Path,
) -> None:
    source = tmp_path / "full.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    composition = new_composition("audio.import", "2023.1")
    from wwise_waapi.operation_composer import apply_composer_action

    def apply(action_name: str, **fields: Any) -> None:
        nonlocal composition
        composition, _ = apply_composer_action(
            "audio.import",
            "2023.1",
            composition,
            {
                "contract": ACTION_CONTRACT,
                "action": action_name,
                **fields,
            },
        )

    apply("set_import_option", name="import_operation", value="useExisting")
    apply("set_import_option", name="auto_add_to_source_control", value=True)
    apply("set_import_option", name="auto_check_out_to_source_control", value=True)
    apply("set_import_default", name="import_language", value="SFX")
    apply(
        "set_import_default",
        name="properties",
        value=[{"name": "Volume", "value": -6.0}],
    )
    apply(
        "set_import_default",
        name="references",
        value=[
            {
                "name": "OutputBus",
                "target": {
                    "kind": "id",
                    "value": "{33333333-3333-3333-3333-333333333333}",
                },
            }
        ],
    )
    apply(
        "add_import_row",
        object_path=(
            r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Full"
        ),
        object_type="Sound SFX",
        audio_file=str(source),
        import_location={
            "kind": "path",
            "value": r"\Actor-Mixer Hierarchy\Default Work Unit\Composer",
        },
        originals_subfolder="Composer/雨",
        notes="target notes",
        audio_source_notes="source notes",
        event={"path": r"\Events\Default Work Unit\Play_Full", "action": "Play"},
        dialogue_event="DialogueEvent:Full",
        properties=[{"name": "Pitch", "value": 2.0}],
        references=[
            {
                "name": "OutputBus",
                "target": {
                    "kind": "path",
                    "value": r"\Master-Mixer Hierarchy\Default Work Unit\Bus",
                },
            }
        ],
        assignment={"mode": "switch", "value": "Mud"},
    )

    request = materialize_operation_request("audio.import", "2023.1", composition)
    assert request == {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2023.1",
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": (
                        r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Full"
                    ),
                    "object_type": "Sound SFX",
                    "audio_file": str(source),
                    "import_location": {
                        "kind": "path",
                        "value": (
                            r"\Actor-Mixer Hierarchy\Default Work Unit\Composer"
                        ),
                    },
                    "originals_subfolder": r"Composer\雨",
                    "notes": "target notes",
                    "audio_source_notes": "source notes",
                    "event": {
                        "path": r"\Events\Default Work Unit\Play_Full",
                        "action": "Play",
                    },
                    "dialogue_event": "DialogueEvent:Full",
                    "switch_assignment": "Mud",
                    "properties": [{"name": "Pitch", "value": 2.0}],
                    "references": [
                        {
                            "name": "OutputBus",
                            "target": {
                                "kind": "path",
                                "value": (
                                    r"\Master-Mixer Hierarchy\Default Work Unit\Bus"
                                ),
                            },
                        }
                    ],
                }
            ],
            "defaults": {
                "import_language": "SFX",
                "properties": [{"name": "Volume", "value": -6.0}],
                "references": [
                    {
                        "name": "OutputBus",
                        "target": {
                            "kind": "id",
                            "value": "{33333333-3333-3333-3333-333333333333}",
                        },
                    }
                ],
            },
            "import_operation": "useExisting",
            "auto_add_to_source_control": True,
            "auto_check_out_to_source_control": True,
        },
    }


def test_complete_audio_import_inline_media_is_bounded_and_not_echoed(
    tmp_path: Path,
) -> None:
    wave = b"RIFF" + (96 * 1024 - 8).to_bytes(4, "little") + b"WAVE" + (
        b"\x00" * (96 * 1024 - 12)
    )
    encoded = "Inline.wav|" + base64.b64encode(wave).decode("ascii")
    start_code, started = _execute(
        tmp_path,
        "draft-start",
        "audio.import",
    )
    assert start_code == 0
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    apply_code, applied = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--compact",
        "--action-json",
        _action(
            "add_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Inline"
            ),
            object_type="Sound SFX",
            audio_file_base64=encoded,
            import_language="SFX",
            switch_assignment=None,
        ),
    )

    assert apply_code == 0, applied
    output = json.dumps(applied)
    assert encoded not in output
    materialized = OperationDraftStore(tmp_path / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=2,
        schema_digest=operation_request_schema_digest("audio.import", "2022.1"),
        composer_digest=operation_composer_digest("audio.import", "2022.1"),
    )
    assert materialized.request["arguments"]["imports"][0][
        "audio_file_base64"
    ] == encoded
    check_code, checked = _live_execute(
        tmp_path,
        _audio_import_client(tmp_path),
        "draft-check",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
    )
    assert check_code == 0, checked
    assert encoded not in json.dumps(checked)


@pytest.mark.parametrize(
    "import_operation", ("createNew", "useExisting", "replaceExisting")
)
def test_complete_audio_import_adapter_accepts_every_import_operation(
    import_operation: str,
) -> None:
    from wwise_waapi.operation_composer import apply_composer_action

    composition, _ = apply_composer_action(
        "audio.import",
        "2025.1",
        new_composition("audio.import", "2025.1"),
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_option",
            "name": "import_operation",
            "value": import_operation,
        },
    )
    assert composition["request_options"] == {
        "import_operation": import_operation
    }


def test_complete_audio_import_default_can_be_corrected_and_removed() -> None:
    from wwise_waapi.operation_composer import apply_composer_action

    composition = new_composition("audio.import", "2025.1")
    composition, _ = apply_composer_action(
        "audio.import",
        "2025.1",
        composition,
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_default",
            "name": "notes",
            "value": "before",
        },
    )
    composition, _ = apply_composer_action(
        "audio.import",
        "2025.1",
        composition,
        {
            "contract": ACTION_CONTRACT,
            "action": "set_import_default",
            "name": "notes",
            "value": "after",
        },
    )
    assert composition["defaults"] == {"notes": "after"}
    composition, _ = apply_composer_action(
        "audio.import",
        "2025.1",
        composition,
        {
            "contract": ACTION_CONTRACT,
            "action": "clear_import_default",
            "name": "notes",
        },
    )
    assert composition["defaults"] == {}


def test_audio_import_auto_checkout_is_version_bound_and_atomic(tmp_path: Path) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
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

    exit_code, rejected = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "set_import_option",
            name="auto_check_out_to_source_control",
            value=True,
        ),
    )

    assert exit_code == 2
    assert rejected["error_code"] in {
        "GatewayInputError",
        OperationComposerError.error_code,
    }
    assert record_path.read_bytes() == before


def test_larger_audio_action_parser_does_not_expand_object_set_action_limit(
    tmp_path: Path,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "object.set")
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

    exit_code, rejected = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "add_target",
            selector={
                "kind": "id",
                "value": "{11111111-1111-1111-1111-111111111111}",
            },
            notes="N" * (64 * 1024),
        ),
    )

    assert exit_code == 2
    assert rejected["error_code"] in {
        "GatewayInputError",
        OperationComposerError.error_code,
    }
    assert record_path.read_bytes() == before


@pytest.mark.parametrize(
    "invalid_action",
    (
        json.dumps(
            {
                "contract": ACTION_CONTRACT,
                "action": "add_import_row",
                "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
                "object_type": "Sound SFX",
                "assignment": None,
            }
        ),
        json.dumps(
            {
                "contract": ACTION_CONTRACT,
                "action": "add_import_row",
                "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
                "object_type": "Sound SFX",
                "assignment": {"mode": "switch"},
            }
        ),
        json.dumps(
            {
                "contract": ACTION_CONTRACT,
                "action": "add_import_row",
                "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
                "object_type": "Sound SFX",
                "assignment": {"mode": "none", "value": "Snow"},
            }
        ),
        json.dumps(
            {
                "contract": ACTION_CONTRACT,
                "action": "add_import_row",
                "object_path": r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
                "object_type": "Sound SFX",
                "assignment": {"mode": "later"},
            }
        ),
        json.dumps(
            {
                "contract": ACTION_CONTRACT,
                "action": "add_import_row",
                "object_path": (
                    r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"
                ),
                "object_type": "Sound SFX",
                "switch_assignment": None,
            }
        ),
        json.dumps(
            {
                "contract": ACTION_CONTRACT,
                "action": "add_import_row",
                "object_path": (
                    r"\Actor-Mixer Hierarchy\Default Work Unit\Rain"
                ),
                "object_type": "Sound SFX",
                "switch_assignment": "Snow",
            }
        ),
        _action(
            "add_import_row",
            object_path="relative\\Rain",
            object_type="Sound SFX",
            switch_assignment=None,
        ),
        _action(
            "add_import_row",
            object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
            audio_file=7,
            switch_assignment=None,
        ),
        _action(
            "add_import_row",
            object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
            import_language="",
            switch_assignment=None,
        ),
        _action(
            "add_import_row",
            object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
            event={"path": r"\Not Events\Play_Rain"},
            switch_assignment=None,
        ),
        _action(
            "add_import_row",
            object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
            properties=[{"name": "@Volume", "value": -3.0}],
            switch_assignment=None,
        ),
        _action(
            "add_import_row",
            object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\Rain",
            native_args={"@Volume": -3},
            switch_assignment=None,
        ),
    ),
)
def test_invalid_base_audio_import_action_is_atomic(
    tmp_path: Path,
    invalid_action: str,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
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

    exit_code, rejected = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        invalid_action,
    )

    assert exit_code == 2
    assert rejected["error_code"] in {
        "GatewayInputError",
        OperationComposerError.error_code,
    }
    assert record_path.read_bytes() == before


def test_new_audio_import_composition_does_not_enable_tab_delimited_adapter() -> None:
    with pytest.raises(OperationComposerError) as exc_info:
        new_composition("audio.importTabDelimited", "2022.1")

    assert exc_info.value.error_code == "OPERATION_DRAFT_ADAPTER_UNAVAILABLE"


def test_base_audio_import_adapter_is_the_only_disclosed_normal_input_after_cutover(
    tmp_path: Path,
) -> None:
    schema_code, schema = _execute(
        tmp_path,
        "--version",
        "2022.1",
        "operation-schema",
        "audio.import",
    )

    assert schema_code == 0
    assert schema["operation"]["input_mode"] == COMPOSER_INPUT_MODE
    assert "request_envelope" not in schema
    assert schema["composer"]["start"]["gateway_argv"] == [
        "draft-start",
        "audio.import",
    ]
    assert "add_import_row" in schema["composer"]["action_shapes"]
    assert "legacy-preview" not in json.dumps(schema)


def test_audio_import_materializer_rejects_incomplete_empty_composition() -> None:
    with pytest.raises(OperationComposerError) as exc_info:
        materialize_operation_request(
            "audio.import",
            "2022.1",
            new_composition("audio.import", "2022.1"),
        )

    assert exc_info.value.error_code == "OPERATION_DRAFT_INCOMPLETE"


def _complete_media_draft(
    root: Path,
    *,
    source: Path,
) -> tuple[str, str, dict[str, Any]]:
    _code, started = _execute(root, "draft-start", "audio.import")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    _code, configured = _execute(
        root,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action("set_import_operation", mode="createNew"),
    )
    assert configured["draft"]["revision"] == 2
    _code, completed = _execute(
        root,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--action-json",
        _action(
            "add_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Rain"
            ),
            audio_file=str(source),
            object_type="Sound SFX",
            import_language="SFX",
            switch_assignment=None,
        ),
    )
    request = OperationDraftStore(root / "state").materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=3,
        schema_digest=operation_request_schema_digest("audio.import", "2022.1"),
        composer_digest=operation_composer_digest("audio.import", "2022.1"),
    ).request
    assert completed["draft"]["revision"] == 3
    return draft_id, authority, request


def test_base_audio_import_public_draft_check_and_seal_reuse_existing_preview(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    draft_id, authority, request = _complete_media_draft(
        tmp_path,
        source=source,
    )
    check_client = _audio_import_client(tmp_path)

    check_code, checked = _live_execute(
        tmp_path,
        check_client,
        "draft-check",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
    )

    assert check_code == 0, checked
    assert checked["draft"]["revision"] == 4
    assert checked["draft"]["check"]["source_revision"] == 3
    assert all(call[0] != "ak.wwise.core.audio.import" for call in check_client.calls)
    assert not (tmp_path / "state" / "transactions").exists()

    preview_client = _audio_import_client(tmp_path)
    preview_code, previewed = _live_execute(
        tmp_path,
        preview_client,
        "preview-from-draft",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--apply",
        "--ttl",
        "300",
    )

    assert preview_code == 0, previewed
    assert previewed["command"] == "preview-from-draft"
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["agent_result"]["request"] == request
    assert list(previewed)[-1] == "agent_result"
    assert all(call[0] != "ak.wwise.core.audio.import" for call in preview_client.calls)
    artifact = TransactionStore(tmp_path / "state").load_preview(
        previewed["transaction_id"]
    ).artifact
    assert artifact["request"] == request
    assert artifact["prepared_operation"]["dispatch"]["uri"] == (
        "ak.wwise.core.audio.import"
    )
    assert artifact["prepared_operation"]["pre_state"]["closed_import_plan"][
        "file_proofs"
    ][0]["sha256"]
    assert check_client.disconnected is preview_client.disconnected is True


def test_base_audio_import_composer_matches_legacy_preview_artifact_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = waapi_gateway.build_transaction_preview_artifact
    fixed_now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    def deterministic_builder(*args: Any, **kwargs: Any) -> Any:
        kwargs["now"] = fixed_now
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(
        waapi_gateway,
        "build_transaction_preview_artifact",
        deterministic_builder,
    )
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    composer_root = tmp_path / "composer"
    draft_id, authority, request = _complete_media_draft(
        composer_root,
        source=source,
    )
    check_client = _audio_import_client(tmp_path)
    check_code, checked = _live_execute(
        composer_root,
        check_client,
        "draft-check",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
    )
    assert check_code == 0, checked
    composer_client = _audio_import_client(tmp_path)
    composer_code, composer_payload = _live_execute(
        composer_root,
        composer_client,
        "preview-from-draft",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--apply",
        "--ttl",
        "300",
    )
    assert composer_code == 0, composer_payload
    composer_artifact = TransactionStore(composer_root / "state").load_preview(
        composer_payload["transaction_id"]
    ).artifact

    legacy_root = tmp_path / "legacy"
    legacy_client = _audio_import_client(tmp_path)
    legacy_code, legacy_payload = _live_execute(
        legacy_root,
        legacy_client,
        "legacy-preview",
        "--request-json",
        json.dumps(request),
        "--apply",
        "--ttl",
        "300",
    )
    assert legacy_code == 0, legacy_payload
    legacy_artifact = TransactionStore(legacy_root / "state").load_preview(
        legacy_payload["transaction_id"]
    ).artifact

    assert composer_artifact == legacy_artifact
    assert composer_payload["artifact_hash"] == legacy_payload["artifact_hash"]
    assert composer_payload["preview_summary"] == legacy_payload["preview_summary"]
    assert composer_payload["authorization"] == legacy_payload["authorization"]
    assert composer_payload["cleanup"] == legacy_payload["cleanup"]
    assert composer_client.calls == legacy_client.calls
    assert list(composer_payload)[-1] == list(legacy_payload)[-1] == "agent_result"


def test_base_audio_import_missing_file_fails_check_without_changing_draft(
    tmp_path: Path,
) -> None:
    missing_source = tmp_path / "missing.wav"
    draft_id, authority, _request = _complete_media_draft(
        tmp_path,
        source=missing_source,
    )
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()
    client = _audio_import_client(tmp_path)

    exit_code, rejected = _live_execute(
        tmp_path,
        client,
        "draft-check",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
    )

    assert exit_code == 2
    assert rejected["error_code"] == "INPUT_FILE_NOT_FOUND"
    assert record_path.read_bytes() == before
    assert not (tmp_path / "state" / "transactions").exists()


def test_base_audio_import_preview_repeats_file_proof_after_successful_check(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
    draft_id, authority, _request = _complete_media_draft(
        tmp_path,
        source=source,
    )
    check_code, checked = _live_execute(
        tmp_path,
        _audio_import_client(tmp_path),
        "draft-check",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
    )
    assert check_code == 0, checked
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()
    source.write_bytes(b"RIFF\x08\x00\x00\x00WAVEchanged")

    exit_code, rejected = _live_execute(
        tmp_path,
        _audio_import_client(tmp_path),
        "preview-from-draft",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--apply",
        "--ttl",
        "300",
    )

    assert exit_code == 2
    assert rejected["error_code"] == "OPERATION_DRAFT_BINDING_DRIFT"
    assert record_path.read_bytes() == before
    transactions = tmp_path / "state" / "transactions"
    assert not transactions.exists() or list(transactions.iterdir()) == []


def test_base_audio_import_unknown_structure_type_fails_check_atomically(
    tmp_path: Path,
) -> None:
    _code, started = _execute(tmp_path, "draft-start", "audio.import")
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    apply_code, applied = _execute(
        tmp_path,
        "draft-apply",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "1",
        "--action-json",
        _action(
            "add_import_row",
            object_path=(
                r"\Actor-Mixer Hierarchy\Default Work Unit\Composer\Unknown"
            ),
            object_type="UnreviewedContainer",
            switch_assignment=None,
        ),
    )
    assert apply_code == 0, applied
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before = record_path.read_bytes()

    exit_code, rejected = _live_execute(
        tmp_path,
        _audio_import_client(tmp_path),
        "draft-check",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
    )

    assert exit_code == 2
    assert rejected["error_code"] == "INVALID_OBJECT_TYPE"
    assert record_path.read_bytes() == before
    assert not (tmp_path / "state" / "transactions").exists()

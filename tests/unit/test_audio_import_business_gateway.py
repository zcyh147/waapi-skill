from __future__ import annotations

from tests.support.gateway_config import set_gateway_config

import importlib.util
import json
import sys
import pytest
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.canonical import canonical_sha256
from wwise_waapi.operation_drafts import (
    OperationDraftState,
    OperationDraftStore,
    parse_operation_draft_archive_bytes,
)
from wwise_waapi.operation_registry import (
    audio_import_business_contract,
    operation_request_schema_digest,
)


def test_audio_import_draft_digest_binds_only_the_registry_business_adapter() -> None:
    version = "2022.1"

    assert operation_composer_digest("audio.import", version) == canonical_sha256(
        {
            "contract": "waapi-skill.audio-import-draft-binding/v1",
            "business_adapter": audio_import_business_contract(version),
        }
    )


def test_audio_import_contract_exposes_only_explicit_replace_mode() -> None:
    contract = audio_import_business_contract("2022.1")

    assert "mode" not in contract["settings"]
    assert contract["modes"] == ["replace"]
    assert contract["start"]["first_required_phase"] == (
        "bind_only_handle_typed_business_objects_then_append_bounded_import_"
        "chunks"
    )
    assert contract["declaration_discipline"]["rows_per_command"] == {
        "minimum": 1,
        "maximum": 6,
    }
    assert contract["declaration_discipline"]["row_order_transport"] == {
        "grouped": "one_--row-order_followed_by_one_to_six_ids",
        "repeated": "one_--row-order_per_id",
        "forms_are_equivalent": True,
    }
    assert contract["declaration_discipline"]["completion"] == (
        "append_chunks_until_every_requested_row_is_present_then_check"
    )

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "waapi-skill"
    / "scripts"
    / "gateway.py"
)
SPEC = importlib.util.spec_from_file_location(
    "waapi_audio_import_business_gateway_script",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
waapi_gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waapi_gateway
SPEC.loader.exec_module(waapi_gateway)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"


def _project_path(tmp_path: Path) -> Path:
    return tmp_path / "project" / "SampleProject.wproj"


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


class BusinessCheckClient:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[tuple[str, Any, Any]] = []

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return _info()
        if uri == "ak.wwise.core.getProjectInfo":
            return {
                "id": PROJECT_ID,
                "name": "SampleProject",
                "path": str(_project_path(self.tmp_path)),
            }
        if uri == "ak.wwise.core.object.getTypes":
            return {
                "return": [
                    {"classId": 1, "name": "ActorMixer", "type": "ActorMixer"},
                    {
                        "classId": 2,
                        "name": "RandomSequenceContainer",
                        "type": "RandomSequenceContainer",
                    },
                ]
            }
        if uri == "ak.wwise.core.object.get":
            source = args.get("from", {}) if isinstance(args, Mapping) else {}
            paths = source.get("path", []) if isinstance(source, Mapping) else []
            ids = source.get("id", []) if isinstance(source, Mapping) else []
            if ids == [PARENT_ID] or paths == [
                r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
            ]:
                return {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Weather",
                            "type": "ActorMixer",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
                            ),
                        }
                    ]
                }
            return {"return": []}
        raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")

    def disconnect(self) -> None:
        return None


def _env(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "wwise_version": "2022.1",
                "waapi_host": "127.0.0.1",
                "waapi_port": 31337,
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


def _offline(tmp_path: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    def reject_connection(url: str) -> None:
        raise AssertionError(f"offline business command connected to {url}")

    return waapi_gateway.execute_gateway(
        ["--state-dir", str(tmp_path / "state"), *argv],
        env=_env(tmp_path),
        client_factory=reject_connection,
    )


def test_audio_import_business_binds_user_path_segments_without_model_separators(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    object_path = r"\Containers\Default Work Unit\BusinessImportRoot\Weapons"
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
                }
            ],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Weapons",
                            "type": "ActorMixer",
                            "path": object_path,
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
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-path-segment",
            "Containers",
            "--object-path-segment",
            "Default Work Unit",
            "--object-path-segment",
            "BusinessImportRoot",
            "--object-path-segment",
            "Weapons",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )

    assert bind_code == 0, bound
    assert bound["bound_object"]["name"] == "Weapons"
    assert client.calls[-1] == (
        "ak.wwise.core.object.get",
        {"from": {"path": [object_path]}},
        {"return": ["id", "name", "type", "path"]},
    )


def test_audio_import_business_gateway_binds_and_declares_without_native_facts(
    tmp_path: Path,
) -> None:
    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF-test")
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    start_next = started["draft"]["next_action_binding"]
    assert start_next["required_next_phase"] == "bind_existing_business_object"
    assert start_next["object_binding"]["by_id"]["fixed_argv_prefix"][3] == (
        "draft-bind-object"
    )
    assert "by_unique_name" not in start_next["object_binding"]
    assert start_next["object_binding"]["by_path_segments"][
        "fixed_argv_prefix"
    ][3] == "draft-bind-object"
    assert "gateway_inserts_every_wwise_separator" in (
        start_next["object_binding"]["path_rule"]
    )
    assert "type_prefixes_are_forbidden" in start_next["object_binding"]["path_rule"]
    assert "bind_every_segment_except_the_final_new_object_name" in (
        start_next["object_binding"]["new_target_parent_rule"]
    )
    assert start_next["object_binding"]["import_row_path_rule"] == (
        "existing_import_row_bind_the_complete_existing_sound_path_including_"
        "its_final_sound_name; new_import_row_bind_only_its_exact_existing_"
        "immediate_parent_and_pass_the_final_new_sound_name_once_in_the_"
        "declaration; never_reuse_a_parent_binding_for_an_existing_row; "
        "semantic_kind_belongs_to_the_business_declaration; wwise_type_prefixes_"
        "are_forbidden"
    )
    result_validation = start_next["object_binding"]["result_validation_rule"]
    assert "returned_name_and_path" in result_validation
    assert "compare_business_kind_not_the_version_specific_reflected_type" in (
        result_validation
    )
    assert "stop_only_when_the_user_supplied_a_business_type" in result_validation
    assert "continue_when_the_user_did_not_state_a_business_type" in (
        result_validation
    )
    assert "hierarchy_label_is_not_an_object_type" in result_validation
    assert "by_path" not in start_next["object_binding"]
    assert "configure" not in start_next
    assert "declare_new" not in start_next
    assert "draft-apply" not in json.dumps(start_next)
    assert "wwise_path_discipline" not in start_next
    assert "object_path" not in start_next["forbidden_inputs"]
    assert "model_invented_object_path" in start_next["forbidden_inputs"]
    assert "object_type" in start_next["forbidden_inputs"]
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    before_legacy_attempt = record_path.read_bytes()
    legacy_code, legacy = _offline(
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
        r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\Rain_Bed",
        "--object-type",
        "Sound SFX",
        "--assignment-mode",
        "none",
    )
    assert legacy_code == 2
    assert legacy["error_code"] == "GatewayInputError"
    assert "no longer accepts shallow" in legacy["message"]
    assert record_path.read_bytes() == before_legacy_attempt
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
                }
            ],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Weather",
                            "type": "ActorMixer",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
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
            PARENT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, json.dumps(bound, indent=2)
    parent_handle = bound["bound_object"]["handle"]
    assert parent_handle.startswith("boh1-")
    assert bound["draft"]["revision"] == 2
    bound_next = bound["draft"]["next_action_binding"]
    assert bound_next["contract"] == (
        "waapi-skill.business-draft-next-action/v1"
    )
    assert bound_next["required_next_phase"] == (
        "bind_all_prompt_visible_handle_dependencies_before_any_import_chunk_"
        "then_append_bounded_complete_rows"
    )
    for scope_name in ("object_scope", "new_object_scope"):
        scope = bound_next["field_discovery"][scope_name]
        assert scope["fixed_argv_prefix_copy_instruction"]["source_field"] == (
            "fixed_argv_prefix_copy"
        )
        assert scope["fixed_argv_prefix_copy"]
    batch_action = bound_next["declare_import_batch"]
    assert "configure" not in bound_next
    assert bound_next["target_form_mode"] == {
        "all_new_rows": "Gateway derives create",
        "one_or_more_existing_rows": "Gateway derives reimport",
        "explicit_replace_request": "use explicit_batch_overrides --mode replace",
        "use_existing_is_not_a_batch_override": True,
    }
    overrides = bound_next["explicit_batch_overrides"]
    assert overrides["use_only_when"] == (
        "the_user_explicitly_requests_replace_existing_media_source_control_"
        "behavior_or_one_global_default"
    )
    assert overrides["append"][0] == (
        "[--mode replace] only_for_explicit_replace_existing"
    )
    assert "fixed_argv_prefix" not in batch_action
    assert "gateway.py" in batch_action["fixed_argv_prefix_copy"]
    assert "draft-declare-import-batch" in batch_action[
        "fixed_argv_prefix_copy"
    ]
    assert batch_action["fixed_argv_prefix_copy_instruction"]["source_field"] == (
        "fixed_argv_prefix_copy"
    )
    assert batch_action["derived_batch_facts"] == {
        "declaration_count": "Gateway_counts_the_closed_row_set",
        "switch_assignment_count": "Gateway_counts_rows_with_switch_assignment",
        "caller_supplied_counts": "forbidden",
    }
    assert batch_action["rows_per_command"] == {"minimum": 1, "maximum": 6}
    assert batch_action["row_completeness"] == (
        "each_row_must_include_every_known_requested_field_switch_"
        "assignment_and_event_in_the_same_command; partial_rows_are_forbidden; "
        "media_bearing_rows_include_their_media; structure_only_rows_omit_media_and_language"
    )
    assert batch_action["dependency_closure"] == {
        "scope": "all_remaining_user_requested_rows_not_only_the_next_chunk",
        "bind_before_append": [
            "existing_row_target_or_new_row_parent",
            "output_bus_or_custom_reference",
            "event_parent_for_every_row_requesting_an_event",
        ],
        "never_bind": [
            "switch_group",
            "switch_value",
            "preservation_only_object",
        ],
        "literal_transport": {
            "switch_value": (
                "copy_the_exact_user_value_into_--switch-value; "
                "never_call_draft-bind-object_for_it"
            ),
        },
        "event_row": (
            "include_--event_in_that_rows_same_chunk; omission_is_not_deferred"
        ),
        "append_gate": "every_handle_needed_by_the_next_chunk_is_already_bound",
    }
    assert batch_action["repeat_with_next_response_revision"] is True
    assert batch_action["check_only_after"] == (
        "every_user_requested_row_has_been_appended"
    )
    assert "complete_on_first_submission" not in batch_action
    assert "submit_once" not in batch_action
    assert set(batch_action["row_forms"]) == {"new", "existing"}
    assert batch_action["media_source"]["directory"] == [
        "--media-directory",
        "<one-absolute-source-directory>",
    ]
    assert batch_action["media_source"]["file"] == [
        "--media-file",
        "<id>",
        "<one-file-name-without-separators>",
    ]
    assert "switch_assignment" in batch_action["row_fields"]
    assert batch_action["switch_assignment_ownership"] == {
        "attach_to": "the_exact_declaration_assigned_as_the_Switch_Container_child",
        "container_with_media_children": (
            "put_switch_value_on_the_container_row_only_not_its_descendant_"
            "Sound_rows"
        ),
        "sound_row_exception": (
            "only_when_the_user_explicitly_assigns_that_Sound_directly"
        ),
    }
    assert bound_next["object_binding"]["use_only_for"] == [
        "existing_import_row_target",
        "new_import_row_parent",
        "output_bus_reference",
        "new_event_parent",
        "custom_reference_value",
    ]
    assert bound_next["object_binding"]["forbidden_for"] == [
        "switch_group",
        "switch_value",
        "preservation_only_object",
    ]
    assert all(
        name not in bound_next
        for name in (
            "declare_new",
            "declare_existing",
            "revise",
            "remove",
            "explicit_global_defaults",
        )
    )

    field_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
                }
            ],
            "ak.wwise.core.object.getTypes": [
                {"return": [{"classId": 65552, "name": "Sound", "type": "Sound"}]}
            ] * 2,
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["CustomGain"]}
            ] * 2,
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "CustomGain",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -12.0, "max": 12.0},
                }
            ] * 2,
        }
    )
    field_code, field_bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-discover-fields",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--semantic-kind",
            "sound-sfx",
            "--meaning",
            "CustomGain",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: field_client,
    )
    assert field_code == 0, json.dumps(
        {"payload": field_bound, "calls": field_client.calls}, indent=2
    )
    selected_field = field_bound["meaning_results"][0]["candidates"][0]
    field_handle = selected_field["handle"]
    assert selected_field["restrictions"] == {
        "maximum": 12.0,
        "minimum": -12.0,
    }

    config_code, configured = _offline(
        tmp_path,
        "draft-business-configure",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "3",
        "--mode",
        "create",
        "--add-to-source-control",
        "--default-field-value",
        field_handle,
        "-2.5",
    )
    assert config_code == 0, configured
    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-new",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "4",
        "--declaration-id",
        "rain-bed",
        "--parent-handle",
        parent_handle,
        "--name",
        "Rain_Bed",
        "--kind",
        "sound-sfx",
        "--field",
        "media_file",
        str(media),
        "--field",
        "language",
        "SFX",
        "--field",
        "volume_db",
        "-4",
        "--field",
        "loop",
        "infinite",
        "--field",
        "audio_source_notes",
        "现场录音 · take 2",
        "--field",
        "originals_subfolder",
        "Weather/Rain",
    )
    assert declare_code == 0, declared
    assert declared["draft"]["revision"] == 5
    assert "declarations" not in declared["draft"]
    assert declared["draft"]["declaration_receipt"]["fields"] == {
        "audio_source_notes": "现场录音 · take 2",
        "language": "SFX",
        "loop": "infinite",
        "media_file": str(media),
        "originals_subfolder": "Weather/Rain",
        "volume_db": -4.0,
    }
    assert declared["draft"]["declarations_summary"]["count"] == 1
    assert len(
        declared["draft"]["declarations_summary"]["canonical_sha256"]
    ) == 64
    assert declared["draft"]["response_integrity"] == {
        "complete": True,
        "truncated": False,
        "projection": "business_declaration_receipt_and_continuation",
        "compact_projection_is_not_truncation": True,
    }
    declaration_next = declared["draft"]["next_action_binding"]
    assert declaration_next["required_next_phase"] == (
        "check_complete_business_declaration"
    )
    assert set(declaration_next) == {
        "contract",
        "required_next_phase",
        "check",
        "shell_tool_timeout_ms",
        "then_read_next_response",
        "precompute_or_increment_revision",
    }
    assert all(
        key not in declaration_next
        for key in (
            "business_contract",
            "object_binding",
            "field_binding",
            "binding_decision",
            "configure",
            "explicit_global_defaults",
            "revise",
            "remove",
        )
    )
    assert len(
        json.dumps(declared, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ) <= 10_000

    store = OperationDraftStore(tmp_path / "state")
    materialized = store.materialize_request(
        draft_id,
        task_authority=authority,
        expected_revision=5,
        schema_digest=operation_request_schema_digest("audio.import", "2022.1"),
        composer_digest=operation_composer_digest("audio.import", "2022.1"),
    )
    assert materialized.request["arguments"]["imports"][0] == {
        "audio_file": str(media),
        "audio_source_notes": "现场录音 · take 2",
        "import_language": "SFX",
        "object_path": (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\<Sound SFX>Rain_Bed"
        ),
        "object_type": "Sound SFX",
        "originals_subfolder": r"Weather\Rain",
        "properties": [
            {"name": "IsLoopingEnabled", "value": True},
            {"name": "IsLoopingInfinite", "value": True},
            {"name": "Volume", "value": -4.0},
            {"name": "CustomGain", "value": -2.5},
        ],
    }


def test_audio_import_batch_chunks_are_atomic_cumulative_and_compact(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
                }
            ],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Player_Footsteps",
                            "type": "SwitchContainer",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Player_Footsteps",
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
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-id",
            PARENT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, bound
    parent_handle = bound["bound_object"]["handle"]
    media_files = []
    for index in range(1, 7):
        path = tmp_path / f"snow_step_{index:02d}.wav"
        path.write_bytes(b"RIFF-test")
        media_files.append(path)

    batch_argv = [
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
        "--row-order",
        "snow",
        "snow-step-01",
        "snow-step-02",
        "snow-step-03",
        "snow-step-04",
        "snow-step-05",
        "--new-row",
        "snow",
        parent_handle,
        "Snow",
        "random-container",
        "--switch-value",
        "snow",
        "Snow",
        "--media-directory",
        str(tmp_path),
    ]
    for index, path in enumerate(media_files[:5], start=1):
        declaration_id = f"snow-step-{index:02d}"
        batch_argv.extend(
            (
                "--new-row",
                declaration_id,
                "snow",
                f"Snow_Step_{index:02d}",
                "sound-sfx",
                "--media-file",
                declaration_id,
                path.name,
            )
        )

    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{started['draft']['draft_id']}.json"
    )
    before_missing_directory = record_path.read_bytes()
    missing_code, missing = _offline(
        tmp_path,
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
        "--row-order",
        "missing-directory",
        "--new-row",
        "missing-directory",
        parent_handle,
        "Missing_Directory",
        "sound-sfx",
        "--media-file",
        "missing-directory",
        media_files[0].name,
    )

    assert missing_code == 2
    assert missing["error_code"] == "GatewayInputError"
    assert "exactly one media directory" in missing["message"]
    assert record_path.read_bytes() == before_missing_directory

    too_many_argv = [*batch_argv]
    too_many_argv.extend(
        (
            "--row-order",
            "snow-step-06",
            "--new-row",
            "snow-step-06",
            "snow",
            "Snow_Step_06",
            "sound-sfx",
            "--media-file",
            "snow-step-06",
            media_files[5].name,
        )
    )
    before_too_many = record_path.read_bytes()
    too_many_code, too_many = _offline(tmp_path, *too_many_argv)
    assert too_many_code == 2
    assert too_many["error_code"] == "GatewayInputError"
    assert "at most 6 rows" in too_many["message"]
    assert record_path.read_bytes() == before_too_many

    first_code, first = _offline(tmp_path, *batch_argv)

    assert first_code == 0, first
    assert first["draft"]["revision"] == 3
    assert first["draft"]["batch_receipt"] == {
        "contract": "waapi-skill.business-declaration-batch-receipt/v1",
        "chunk_declaration_count": 6,
        "cumulative_declaration_count": 6,
        "switch_assignment_count": 1,
    }
    first_next = first["draft"]["next_action_binding"]
    assert first_next["required_next_phase"] == (
        "bind_all_remaining_user_requested_dependencies_before_append_next_"
        "import_chunk_or_use_draft_next_command_when_complete"
    )
    assert "append_import_chunk" in first_next
    assert first_next["bind_additional_object_by_path_segments"][
        "append_repeated"
    ] == [
        "--object-path-segment",
        "<one-exact-user-path-segment-without-separators>",
    ]
    assert first_next["append_import_chunk"]["rows_per_command"] == {
        "minimum": 1,
        "maximum": 6,
    }
    assert first_next["append_import_chunk"]["row_order"]["grouped"] == [
        "--row-order",
        "<declaration-id-1>",
        "[<declaration-id-2>...]",
    ]
    assert first_next["append_import_chunk"]["row_order"]["rule"] == (
        "both_forms_are_equivalent; preserve_exact_import_order; "
        "supply_one_to_six_ids"
    )
    assert first_next["append_import_chunk"]["row_completeness"] == (
        "each_row_must_include_every_known_requested_field_switch_"
        "assignment_and_event_in_the_same_command; partial_rows_are_forbidden; "
        "media_bearing_rows_include_their_media; structure_only_rows_omit_media_and_language"
    )
    assert first_next["append_import_chunk"]["dependency_closure"][
        "event_row"
    ] == "include_--event_in_that_rows_same_chunk; omission_is_not_deferred"

    second_argv = [
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "3",
    ]
    for index, path in enumerate(media_files[5:], start=6):
        declaration_id = f"snow-step-{index:02d}"
        second_argv.extend(
            (
                "--row-order",
                declaration_id,
                "--new-row",
                declaration_id,
                "snow",
                f"Snow_Step_{index:02d}",
                "sound-sfx",
                "--media-file",
                declaration_id,
                path.name,
            )
        )

    batch_code, batch = _offline(tmp_path, *second_argv)

    assert batch_code == 0, batch
    assert batch["draft"]["revision"] == 4
    assert batch["draft"]["batch_receipt"] == {
        "contract": "waapi-skill.business-declaration-batch-receipt/v1",
        "chunk_declaration_count": 1,
        "cumulative_declaration_count": 7,
        "switch_assignment_count": 1,
    }
    assert "declarations_summary" not in batch["draft"]
    assert batch["draft"]["binding"]["operation"] == "audio.import"
    assert "business_revision" not in batch["draft"]
    assert set(batch["draft"]["next_action_binding"]) == {
        "contract",
        "required_next_phase",
        "bind_additional_object_by_path_segments",
        "append_import_chunk",
        "shell_tool_timeout_ms",
    }
    assert batch["draft"]["next_action_binding"]["required_next_phase"] == (
        "bind_all_remaining_user_requested_dependencies_before_append_next_"
        "import_chunk_or_use_draft_next_command_when_complete"
    )
    assert batch["draft"]["next_command"]["command"] == "draft-check"
    assert batch["draft"]["next_command"]["copy_exactly"] is True
    assert batch["draft"]["next_command"]["gateway_argv"][:2] == [
        "draft-check",
        started["draft"]["draft_id"],
    ]
    compact_batch = {**batch, "draft": {
        key: value for key, value in batch["draft"].items() if key != "next_command"
    }}
    response_size = len(
        json.dumps(compact_batch, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    # Measure business data separately from the host-owned continuation. The
    # encoded Windows envelope repeats absolute paths whose length is variable;
    # its correctness and delivery ceilings have their own Gateway tests.
    assert response_size <= 8_000

    stored = OperationDraftStore(tmp_path / "state").inspect(
        started["draft"]["draft_id"],
        task_authority=started["task_authority"],
    )
    session = stored.composition["business_session"]
    assert [row["declaration_id"] for row in session["declarations"]] == [
        "snow",
        "snow-step-01",
        "snow-step-02",
        "snow-step-03",
        "snow-step-04",
        "snow-step-05",
        "snow-step-06",
    ]
    assert [
        row["fields"]["media_file"]
        for row in session["declarations"][1:]
    ] == [str(path) for path in media_files]

    alternate_directory = tmp_path / "alternate"
    alternate_directory.mkdir()
    alternate_media = alternate_directory / "alternate.wav"
    alternate_media.write_bytes(b"RIFF-alternate")
    alternate_code, alternate = _offline(
        tmp_path,
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "4",
        "--media-directory",
        str(alternate_directory),
        "--row-order",
        "alternate",
        "--new-row",
        "alternate",
        parent_handle,
        "Alternate",
        "sound-sfx",
        "--media-file",
        "alternate",
        alternate_media.name,
    )
    assert alternate_code == 0, alternate

    before_ambiguous_directory = record_path.read_bytes()
    ambiguous_code, ambiguous = _offline(
        tmp_path,
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "5",
        "--row-order",
        "ambiguous",
        "--new-row",
        "ambiguous",
        parent_handle,
        "Ambiguous",
        "sound-sfx",
        "--media-file",
        "ambiguous",
        "ambiguous.wav",
    )
    assert ambiguous_code == 2
    assert ambiguous["error_code"] == "GatewayInputError"
    assert "exactly one media directory" in ambiguous["message"]
    assert record_path.read_bytes() == before_ambiguous_directory


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_music_import_batch_accepts_omitted_language_without_native_dispatch(
    tmp_path: Path, version: str,
) -> None:
    env = set_gateway_config(_env(tmp_path), wwise_version=version)
    state_args = ["--state-dir", str(tmp_path / "state")]
    def offline(*argv):
        return waapi_gateway.execute_gateway(
            [*state_args, *argv], env=env,
            client_factory=lambda _: pytest.fail("declaration must not connect"),
        )
    code, schema = offline("operation-schema", "audio.import")
    assert code == 0, schema
    requirements = schema["business_adapter"]["row_requirements"]
    assert requirements["structure_only"]["semantic_kinds"] == schema["business_adapter"]["semantic_kinds"]
    assert "music-segment" in requirements["structure_only"]["semantic_kinds"]
    assert requirements["structure_only"]["media"] == "omit_media_file_and_inline_wav"
    assert requirements["structure_only"]["language"] == "omit"
    assert requirements["new_parent"] == "bound_parent_handle_or_earlier_new_row_id_in_this_Draft; declare_parent_before_children"
    assert requirements["media_bearing"]["media"] == "include_exactly_one_media_file_or_inline_wav_in_that_row"
    assert requirements["media_bearing"]["language"] == "sound-sfx_and_music-track_default_to_SFX; otherwise_supply_the_exact_project_language"
    code, started = offline("draft-start", "audio.import")
    assert code == 0, started
    assert started["draft"]["next_action_binding"]["business_contract"]["row_requirements"] == requirements
    info = _info()
    info["version"]["year"] = int(version[:4])
    info["version"]["displayName"] = f"v{version}.0.1"
    info["isCommandLine"] = False
    client = FakeClient({
        "ak.wwise.core.getInfo": [info],
        "ak.wwise.core.getProjectInfo": [{
            "id": PROJECT_ID, "name": "SampleProject", "path": str(_project_path(tmp_path)),
        }],
        "ak.wwise.core.object.get": ([{"return": [{
            "id": PROJECT_ID, "name": "SampleProject", "type": "Project",
            "path": str(_project_path(tmp_path)),
        }]}] if version == "2021.1" else []) + [{"return": [{
            "id": PARENT_ID, "name": "Default Work Unit", "type": "WorkUnit",
            "path": r"\Containers\Default Work Unit",
        }]}],
    })
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    code, bound = waapi_gateway.execute_gateway([
        *state_args, "draft-bind-object", draft_id, "--task-authority", authority,
        "--expected-revision", "1", "--object-id", PARENT_ID,
    ], env=env, client_factory=lambda _: client)
    assert code == 0, bound
    batch = bound["draft"]["next_action_binding"]["declare_import_batch"]
    assert batch["row_requirements"] == requirements
    assert "structure_only_rows_omit_media_and_language" in batch["row_completeness"]
    media = tmp_path / "music.wav"
    media.write_bytes(b"RIFF-test")
    code, declared = offline(
        "draft-declare-import-batch", draft_id, "--task-authority", authority,
        "--expected-revision", "2", "--row-order", "segment", "track",
        "--new-row", "segment", bound["bound_object"]["handle"], "Intro", "music-segment",
        "--new-row", "track", "segment", "Music", "music-track",
        "--media-directory", str(tmp_path), "--media-file", "track", media.name,
        "--field", "track", "volume_db", "-6",
    )
    assert code == 0, declared
    assert declared["draft"]["revision"] > 2
    assert declared["draft"]["next_action_binding"]["append_import_chunk"]["row_requirements"] == requirements
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _, _ in client.calls)


def test_audio_import_batch_count_mismatch_is_atomic(tmp_path: Path) -> None:
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
                }
            ],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Weather",
                            "type": "ActorMixer",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
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
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-id",
            PARENT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, bound
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{started['draft']['draft_id']}.json"
    )
    before = record_path.read_bytes()

    missing_directory_code, missing_directory = _offline(
        tmp_path,
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
        "--row-order",
        "rain",
        "--new-root-row",
        "rain",
        bound["bound_object"]["handle"],
        "Rain",
        "sound-sfx",
        "--media-file",
        "rain",
        "rain.wav",
    )

    assert missing_directory_code == 2
    assert missing_directory["error_code"] == "GatewayInputError"
    assert "media directory" in missing_directory["message"].casefold()
    assert record_path.read_bytes() == before

    traversal_code, traversal = _offline(
        tmp_path,
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
        "--row-order",
        "rain",
        "--new-root-row",
        "rain",
        bound["bound_object"]["handle"],
        "Rain",
        "sound-sfx",
        "--media-directory",
        str(tmp_path),
        "--media-file",
        "rain",
        "../rain.wav",
    )

    assert traversal_code == 2
    assert traversal["error_code"] == "GatewayInputError"
    assert "file name" in traversal["message"].casefold()
    assert record_path.read_bytes() == before

    mismatch_code, mismatch = _offline(
        tmp_path,
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
        "--row-order",
        "rain",
        "--row-order",
        "missing",
        "--new-root-row",
        "rain",
        bound["bound_object"]["handle"],
        "Rain",
        "random-container",
    )

    assert mismatch_code == 2
    assert mismatch["error_code"] == "GatewayInputError"
    assert "row order" in mismatch["message"].casefold()
    assert record_path.read_bytes() == before

    oversized_argv = [
        "draft-declare-import-batch",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
    ]
    for index in range(7):
        declaration_id = f"row-{index}"
        oversized_argv.extend(
            (
                "--row-order",
                declaration_id,
                "--new-root-row",
                declaration_id,
                bound["bound_object"]["handle"],
                f"Row {index}",
                "actor-mixer",
            )
        )
    oversized_code, oversized = _offline(tmp_path, *oversized_argv)

    assert oversized_code == 2
    assert oversized["error_code"] == "GatewayInputError"
    assert "at most 6 rows" in oversized["message"]
    assert record_path.read_bytes() == before


def test_audio_import_business_start_discloses_only_copy_ready_object_binding(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "audio.import")

    assert code == 0, started
    next_action = started["draft"]["next_action_binding"]
    assert next_action["required_next_phase"] == "bind_existing_business_object"
    assert all(
        name not in next_action
        for name in (
            "field_binding",
            "configure",
            "declare_new",
            "declare_existing",
            "completion_candidate",
        )
    )
    assert "by_unique_name" not in next_action["object_binding"]
    by_segments = next_action["object_binding"]["by_path_segments"]
    assert by_segments["fixed_argv_prefix"][3] == "draft-bind-object"
    assert by_segments["fixed_argv_prefix_copy_instruction"]["source_field"] == (
        "fixed_argv_prefix_copy"
    )
    assert by_segments["append_repeated"] == [
        "--object-path-segment",
        "<one-exact-user-path-segment-without-separators>",
    ]
    assert by_segments["segment_order"] == "root_to_leaf"
    assert "by_exact_user_path" not in next_action["object_binding"]
    assert (
        next_action["object_binding"]["selection_rule"]
        == "user_supplied_complete_path_requires_by_path_segments; "
        "user_supplied_name_without_a_path_requires_query_then_by_id; "
        "user_selected_guid_uses_by_id"
    )


def test_audio_import_switch_value_is_a_first_class_business_argument(
    tmp_path: Path,
) -> None:
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
                }
            ],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Player_Footsteps",
                            "type": "SwitchContainer",
                            "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Player_Footsteps",
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
            started["draft"]["draft_id"],
            "--task-authority",
            started["task_authority"],
            "--expected-revision",
            "1",
            "--object-id",
            PARENT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: client,
    )
    assert bind_code == 0, bound

    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-new",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "2",
        "--declaration-id",
        "snow",
        "--parent-handle",
        bound["bound_object"]["handle"],
        "--name",
        "Snow",
        "--kind",
        "random-container",
        "--switch-value",
        "Snow",
    )

    assert declare_code == 0, declared
    assert declared["draft"]["declaration_receipt"]["fields"] == {
        "switch_value": "Snow"
    }
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{started['draft']['draft_id']}.json"
    )
    before_ambiguous_attempt = record_path.read_bytes()
    ambiguous_code, ambiguous = _offline(
        tmp_path,
        "draft-revise-declaration",
        started["draft"]["draft_id"],
        "--task-authority",
        started["task_authority"],
        "--expected-revision",
        "3",
        "--declaration-id",
        "snow",
        "--field",
        "switch_value",
        "Rain",
    )
    assert ambiguous_code == 2
    assert ambiguous["error_code"] == "GatewayInputError"
    assert "--switch-value" in ambiguous["message"]
    assert record_path.read_bytes() == before_ambiguous_attempt


@pytest.mark.parametrize("continuation_mode", ("absolute", "task-local", "invalid"))
def test_structure_declaration_reaches_live_check_and_persists_readable_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation_mode: str,
) -> None:
    if continuation_mode == "task-local":
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(waapi_gateway, "GATEWAY_RUNNER_PATH", tmp_path / ".agents/skills/waapi-skill/scripts/run.py")
    code, started = _offline(tmp_path, "draft-start", "audio.import")
    assert code == 0, started
    draft_id = started["draft"]["draft_id"]
    authority = started["task_authority"]
    bind_client = FakeClient(
        {
            "ak.wwise.core.getInfo": [_info()],
            "ak.wwise.core.getProjectInfo": [
                {
                    "id": PROJECT_ID,
                    "name": "SampleProject",
                    "path": str(_project_path(tmp_path)),
                }
            ],
            "ak.wwise.core.object.get": [
                {
                    "return": [
                        {
                            "id": PARENT_ID,
                            "name": "Weather",
                            "type": "ActorMixer",
                            "path": (
                                r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
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
            PARENT_ID,
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: bind_client,
    )
    assert bind_code == 0, bound
    declare_code, declared = _offline(
        tmp_path,
        "draft-declare-new",
        draft_id,
        "--task-authority",
        authority,
        "--expected-revision",
        "2",
        "--declaration-id",
        "variants",
        "--parent-handle",
        bound["bound_object"]["handle"],
        "--name",
        "Variants",
        "--kind",
        "random-container",
    )
    assert declare_code == 0, declared
    check_client = BusinessCheckClient(tmp_path)

    record_path = tmp_path / "state/operation-drafts-v1/records" / f"{draft_id}.json"
    before_check = record_path.read_bytes()
    if continuation_mode == "invalid":
        original_next_command = waapi_gateway.transaction_next_command

        def invalid_next_command(*args, **kwargs):
            result = original_next_command(*args, **kwargs)
            result["shell_command"] = "python wrong.py"
            return result

        monkeypatch.setattr(waapi_gateway, "transaction_next_command", invalid_next_command)

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
        env=_env(tmp_path),
        client_factory=lambda _url: check_client,
    )

    if continuation_mode == "invalid":
        assert check_code == 2
        assert checked["error_code"] == "BUSINESS_CONTINUATION_INVALID"
        assert checked["details"]["repair"]["draft_revision"] == 3
        assert record_path.read_bytes() == before_check
        return

    assert check_code == 0, json.dumps(checked, indent=2)
    assert checked["draft"]["revision"] == 4
    assert checked["draft"]["preview"]["readable_lines"] == [
        "对象：Variants",
        "类型：Random Container",
    ]
    assert "next_action_binding" not in checked["draft"]
    assert checked["draft"]["construction_state"] == {
        "draft_complete": True,
        "preview_created": False,
        "required_next_phase": "preview-from-draft",
        "sole_continuation_source": "/next_command",
    }
    assert "copy_command" not in json.dumps(checked["draft"])
    assert "fixed_argv_prefix_copy" not in json.dumps(checked["draft"])
    assert checked["next_command"]["gateway_argv"][0] == "preview-from-draft"
    assert checked["next_command"]["copy_instruction"]["source_field"] in {
        "model_command",
        "shell_command",
    }
    assert "--apply" not in checked["next_command"]["gateway_argv"]
    record = OperationDraftStore(tmp_path / "state").inspect(
        draft_id,
        task_authority=authority,
    )
    assert record.composition is not None
    session = record.composition["business_session"]
    assert session["active_preview"]["readable_lines"] == [
        "对象：Variants",
        "类型：Random Container",
    ]

    preview_client = BusinessCheckClient(tmp_path)
    preview_code, previewed = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "preview-from-draft",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "4",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: preview_client,
    )
    assert preview_code == 0, json.dumps(previewed, indent=2)
    assert previewed["state"] == "awaiting_confirmation"
    assert previewed["agent_result"]["request"]["arguments"]["imports"] == [
        {
            "object_path": (
                r"\Actor-Mixer Hierarchy\Default Work Unit\Weather"
                r"\<Random Container>Variants"
            ),
            "object_type": "RandomSequenceContainer",
        }
    ]
    record_path = (
        tmp_path
        / "state"
        / "operation-drafts-v1"
        / "records"
        / f"{draft_id}.json"
    )
    archived = parse_operation_draft_archive_bytes(
        record_path.read_bytes(),
        expected_draft_id=draft_id,
        allow_cleaned_file_evidence=True,
    )
    assert archived.state is OperationDraftState.SEALED
    assert archived.seal is not None
    assert archived.seal["request"] == previewed["agent_result"]["request"]


class ImportFieldsClient(BusinessCheckClient):
    """External read boundary for the versioned public import Draft tests."""

    def __init__(self, tmp_path: Path, version: str) -> None:
        super().__init__(tmp_path)
        self.version = version
        root = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
        self.parent = {
            "id": PARENT_ID, "name": "Weather", "type": "ActorMixer" if version != "2025.1" else "PropertyContainer",
            "path": rf"\{root}\Default Work Unit\Weather",
        }
        self.field_ranges = {"Volume": (-200, 200), "Pitch": (-2400, 2400), "Lowpass": (0, 100)}
        project_file = _project_path(tmp_path)
        (project_file.parent / "Originals").mkdir(parents=True)
        project_file.write_text(
            '<WwiseDocument Type="Project" SchemaVersion="103" WwiseVersion="v2021.1.0" WwiseBuild="7485">'
            f'<ProjectInfo><Project Name="SampleProject" ID="{PROJECT_ID}">'
            '<LanguageList><Language Name="SFX" ID="{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"/></LanguageList>'
            '<MiscSettings><MiscSettingEntry Name="Originals">Originals</MiscSettingEntry></MiscSettings>'
            '</Project></ProjectInfo></WwiseDocument>', encoding="utf-8")

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        self.calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            info = _info()
            info["version"].update(year=int(self.version[:4]), displayName=f"v{self.version}.0.1")
            return info
        if uri == "ak.wwise.core.getProjectInfo":
            project_root = _project_path(self.tmp_path).parent
            language_id = "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}"
            platform_id = "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}"
            return {
                "id": PROJECT_ID, "name": "SampleProject", "displayTitle": "SampleProject",
                "path": str(_project_path(self.tmp_path)), "isDirty": False,
                "currentLanguageId": language_id, "referenceLanguageId": language_id,
                "currentPlatformId": platform_id,
                "languages": [{"id": language_id, "name": "SFX", "shortId": 1}],
                "platforms": [{"id": platform_id, "name": "Mac", "baseName": "Mac", "baseDisplayName": "Mac",
                    "soundBankPath": str(project_root / "GeneratedSoundBanks/Mac"),
                    "copiedMediaPath": str(project_root / "GeneratedSoundBanks/Mac/Media")}],
                "defaultConversion": {"id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}", "name": "Default"},
                "directories": {name: str(project_root / suffix) for name, suffix in (
                    ("root", ""), ("originals", "Originals"), ("cache", ".cache"),
                    ("soundBankOutputRoot", "GeneratedSoundBanks"), ("commands", "Commands"), ("properties", "Properties"))},
            }
        if uri == "ak.wwise.core.object.getTypes":
            return {"return": [{"classId": 2, "name": "RandomSequenceContainer", "type": "RandomSequenceContainer"},
                {"classId": 65552, "name": "Sound", "type": "Sound"},
                {"classId": 16, "name": "AudioSource" if self.version == "2021.1" else "AudioFileSource", "type": "WObject"},
                {"classId": 1, "name": self.parent["type"], "type": self.parent["type"]}]}
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            return {"return": list(self.field_ranges)}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            name = args["property"]
            low, high = self.field_ranges[name]
            return {"name": name, "type": "Real32", "restriction": {"type": "range", "min": low, "max": high}}
        if uri == "ak.wwise.core.object.get":
            if args.get("waql") in {"from type Project take 1", "from type Project take 2"}:
                return {"return": [{"id": PROJECT_ID, "name": "SampleProject", "type": "Project",
                    "path": "\\", "filePath": str(_project_path(self.tmp_path)), "workunitIsDirty": False}]}
            source = args.get("from", {})
            if source.get("id") == [PARENT_ID] or source.get("path") == [self.parent["path"]]:
                return {"return": [dict(self.parent)]}
            return {"return": []}
        raise AssertionError(f"Unexpected WAAPI call: {uri} {args!r} {options!r}")


def _import_fields_draft(tmp_path: Path, version: str, client: ImportFieldsClient | None = None):
    env = set_gateway_config(_env(tmp_path), wwise_version=version)
    client = client or ImportFieldsClient(tmp_path, version)

    def gateway(*argv: str):
        return waapi_gateway.execute_gateway(
            ["--state-dir", str(tmp_path / "state"), *argv], env=env,
            client_factory=lambda _url: client,
        )

    code, started = gateway("draft-start", "audio.import")
    assert code == 0, started
    draft_id, authority = started["draft"]["draft_id"], started["task_authority"]
    revision = started["draft"]["revision"]

    def command(name: str, *argv: str, expected_error: str | None = None):
        nonlocal revision
        if name.startswith("draft-") or name == "preview-from-draft":
            code, result = gateway(name, draft_id, "--task-authority", authority,
                "--expected-revision", str(revision), *argv)
        else:
            code, result = gateway(name, *argv)
        if expected_error is not None:
            assert code == 2, result
            assert result["error_code"] == expected_error, result
        else:
            assert code == 0, json.dumps(result, indent=2)
            if "draft" in result:
                revision = result["draft"]["revision"]
        return result

    bound = command("draft-bind-object", "--object-id", PARENT_ID)
    return command, bound["bound_object"]["handle"], client


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_import_preview_preserves_independent_default_fields_and_row_overrides(tmp_path: Path, version: str) -> None:
    command, parent, _client = _import_fields_draft(tmp_path, version)
    handles = {}
    for meaning in ("Volume", "Pitch", "Lowpass"):
        discovered = command("draft-discover-fields", "--semantic-kind", "random-container", "--meaning", meaning)
        handles[meaning] = discovered["meaning_results"][0]["candidates"][0]["handle"]
    command("draft-business-configure", "--default-field-value", handles["Volume"], "-4",
        "--default-field-value", handles["Pitch"], "-100")
    rediscovered = command("draft-discover-fields", "--semantic-kind", "random-container", "--meaning", "Pitch")
    row_pitch = rediscovered["meaning_results"][0]["candidates"][0]["handle"]
    assert row_pitch != handles["Pitch"]
    command("draft-declare-new", "--declaration-id", "baseline", "--parent-handle", parent,
        "--name", "Baseline", "--kind", "random-container")
    command("draft-declare-new", "--declaration-id", "overridden", "--parent-handle", parent,
        "--name", "Overridden", "--kind", "random-container",
        "--field-value", row_pitch, "-200", "--field-value", handles["Lowpass"], "10")
    command("draft-check")
    preview = command("preview-from-draft")
    assert preview["state"] == "awaiting_confirmation"
    rows = preview["agent_result"]["request"]["arguments"]["imports"]
    assert [row["object_path"].rsplit("\\", 1)[-1] for row in rows] == [
        "<Random Container>Baseline", "<Random Container>Overridden"]
    assert [sorted(row["properties"], key=lambda field: field["name"]) for row in rows] == [
        [{"name": "Pitch", "value": -100.0}, {"name": "Volume", "value": -4.0}],
        [{"name": "Lowpass", "value": 10.0}, {"name": "Pitch", "value": -200.0}, {"name": "Volume", "value": -4.0}],
    ]


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("empty_at", ("default", "row"))
def test_import_preview_transports_empty_notes_without_conflating_omission(
    tmp_path: Path, version: str, empty_at: str,
) -> None:
    command, parent, client = _import_fields_draft(tmp_path, version)
    media = tmp_path / "small.wav"
    media.write_bytes(b"RIFF-test-media")
    if empty_at == "default":
        command("draft-business-configure", "--default", "notes", "", "--default", "audio_source_notes", "")
    command("draft-declare-new", "--declaration-id", "inherited", "--parent-handle", parent,
        "--name", "Inherited", "--kind", "sound-sfx", "--field", "media_file", str(media))
    row_note = "explicit row note" if empty_at == "default" else ""
    command("draft-declare-new", "--declaration-id", "explicit", "--parent-handle", parent,
        "--name", "Explicit", "--kind", "sound-sfx", "--field", "media_file", str(media),
        "--field", "notes", row_note, "--field", "audio_source_notes", row_note)
    command("draft-check")
    preview = command("preview-from-draft")
    assert preview["state"] == "awaiting_confirmation"
    rows = preview["agent_result"]["request"]["arguments"]["imports"]
    for field in ("notes", "audio_source_notes"):
        if empty_at == "default":
            assert rows[0][field] == ""
        else:
            assert field not in rows[0]
        assert rows[1][field] == row_note
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _args, _options in client.calls)


class MixedReplaceClient(ImportFieldsClient):
    OLD_ID = "{22222222-2222-2222-2222-222222222222}"
    REPLACEMENT_ID = "{33333333-3333-3333-3333-333333333333}"
    CREATED_ID = "{44444444-4444-4444-4444-444444444444}"
    UNRELATED_ID = "{55555555-5555-5555-5555-555555555555}"

    def __init__(self, tmp_path: Path, version: str) -> None:
        super().__init__(tmp_path, version)
        self.existing_path = self.parent["path"] + r"\Existing"
        self.new_path = self.parent["path"] + r"\New"
        self.objects = {
            self.OLD_ID: self.sound(self.OLD_ID, self.existing_path),
            self.UNRELATED_ID: self.sound(self.UNRELATED_ID, self.parent["path"] + r"\Unrelated"),
        }
        self.swap_on_existing_path_read = False

    @staticmethod
    def sound(object_id: str, path: str) -> dict[str, Any]:
        return {"id": object_id, "name": path.rsplit("\\", 1)[-1], "type": "Sound", "classId": 65552,
            "path": path, "notes": "", "@IsVoice": False}

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri == "ak.wwise.core.object.get" and "from" in args:
            self.calls.append((uri, args, options))
            source = args["from"]
            if self.swap_on_existing_path_read and source.get("path") == [self.existing_path]:
                self.swap_on_existing_path_read = False
                self.objects[self.REPLACEMENT_ID] = {**self.objects.pop(self.OLD_ID), "id": self.REPLACEMENT_ID}
            rows = [self.parent, *self.objects.values()]
            matches = [row for row in rows if row["id"] in source.get("id", []) or row["path"] in source.get("path", [])]
            return {"return": [{key: value for key, value in row.items() if key in options.get("return", [])} for row in matches]}
        if uri == "ak.wwise.core.audio.import":
            self.calls.append((uri, args, options))
            assert args["importOperation"] == "replaceExisting"
            self.objects.pop(self.OLD_ID)
            result_rows, files = [], []
            for index, (object_id, path) in enumerate(((self.REPLACEMENT_ID, self.existing_path), (self.CREATED_ID, self.new_path))):
                source_file = Path(args["imports"][index]["audioFile"])
                copied = _project_path(self.tmp_path).parent / "Originals/SFX" / source_file.name
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(source_file.read_bytes())
                source_id = "{66666666-6666-6666-6666-66666666666" + str(index) + "}"
                language = {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "SFX"}
                sound = {**self.sound(object_id, path), "activeSource": {"id": source_id},
                    "sound:originalWavFilePath": str(copied), "originalFilePath": str(copied), "audioSource:language": language}
                source = {"id": source_id, "name": source_file.stem, "type": "AudioFileSource", "classId": 16,
                    "path": path + "\\" + source_file.stem, "notes": "", "parent": {"id": object_id},
                    "originalFilePath": str(copied), "audioSource:language": language}
                self.objects.update({object_id: sound, source_id: source})
                result_rows.extend({key: row[key] for key in options["return"] if key in row} for row in (sound, source))
                files.append(str(copied))
            result = {"objects": result_rows}
            if self.version in {"2023.1", "2024.1", "2025.1"}:
                result.update(log=[], files=files)
            return result
        return super().call(uri, args, options)


def _mixed_replace_draft(tmp_path: Path, version: str):
    client = MixedReplaceClient(tmp_path, version)
    command, parent, client = _import_fields_draft(tmp_path, version, client)
    bound = command("draft-bind-object", "--object-id", client.OLD_ID)
    command("draft-business-configure", "--mode", "replace")
    for name in ("existing", "new"):
        (tmp_path / f"{name}.wav").write_bytes(b"RIFF-owned-" + name.encode())
    command("draft-declare-existing", "--declaration-id", "replace", "--object-handle", bound["bound_object"]["handle"],
        "--field", "media_file", str(tmp_path / "existing.wav"))
    command("draft-declare-new", "--declaration-id", "create", "--parent-handle", parent,
        "--name", "New", "--kind", "sound-sfx", "--field", "media_file", str(tmp_path / "new.wav"))
    return command, client


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_mixed_replace_import_public_transaction_replaces_and_creates_exact_targets(tmp_path: Path, version: str) -> None:
    command, client = _mixed_replace_draft(tmp_path, version)
    unrelated = dict(client.objects[client.UNRELATED_ID])
    command("draft-check")
    preview = command("preview-from-draft")
    assert preview["state"] == "awaiting_confirmation"
    request = preview["agent_result"]["request"]
    assert request["arguments"]["import_operation"] == "replaceExisting"
    assert len(request["arguments"]["imports"]) == 2
    transaction_id = preview["transaction_id"]
    shown = command(*preview["next_command"]["gateway_argv"])
    command(*shown["next_command"]["gateway_argv"])
    executed = command("execute", transaction_id)
    assert executed["state"] == "executed_unverified"
    verified = command("verify", transaction_id)
    assert verified["state"] == "verified", verified
    assert client.OLD_ID not in client.objects
    assert client.objects[client.REPLACEMENT_ID]["path"] == client.existing_path
    assert client.objects[client.CREATED_ID]["path"] == client.new_path
    assert client.objects[client.UNRELATED_ID] == unrelated
    for name in ("existing", "new"):
        assert (tmp_path / f"{name}.wav").read_bytes() == b"RIFF-owned-" + name.encode()
        copied = _project_path(tmp_path).parent / "Originals/SFX" / f"{name}.wav"
        assert copied.read_bytes() == (tmp_path / f"{name}.wav").read_bytes()
    assert sum(uri == "ak.wwise.core.audio.import" for uri, _args, _options in client.calls) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_mixed_replace_import_does_not_authorize_replacing_declared_new_collision(tmp_path: Path, version: str) -> None:
    command, client = _mixed_replace_draft(tmp_path, version)
    client.objects[client.CREATED_ID] = client.sound(client.CREATED_ID, client.new_path)
    record = next((tmp_path / "state/operation-drafts-v1/records").glob("*.json"))
    before = record.read_bytes()
    command("draft-check", expected_error="NEW_IMPORT_TARGET_EXISTS")
    assert record.read_bytes() == before
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _args, _options in client.calls)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_mixed_replace_import_keeps_exact_bound_guid_during_preparation(tmp_path: Path, version: str) -> None:
    command, client = _mixed_replace_draft(tmp_path, version)
    client.swap_on_existing_path_read = True
    record = next((tmp_path / "state/operation-drafts-v1/records").glob("*.json"))
    before = record.read_bytes()
    command("draft-check", expected_error="EXISTING_IMPORT_TARGET_CHANGED")
    assert record.read_bytes() == before
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _args, _options in client.calls)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("change", ("collision_before_preview", "collision_before_execute", "media_before_execute"))
def test_mixed_replace_import_rejects_scope_and_media_drift_before_dispatch(tmp_path: Path, version: str, change: str) -> None:
    command, client = _mixed_replace_draft(tmp_path, version)
    command("draft-check")
    if change == "collision_before_preview":
        record = next((tmp_path / "state/operation-drafts-v1/records").glob("*.json"))
        before = record.read_bytes()
        client.objects[client.CREATED_ID] = client.sound(client.CREATED_ID, client.new_path)
        command("preview-from-draft", expected_error="OPERATION_DRAFT_BINDING_DRIFT")
        assert record.read_bytes() == before
    else:
        preview = command("preview-from-draft")
        shown = command(*preview["next_command"]["gateway_argv"])
        command(*shown["next_command"]["gateway_argv"])
        if change == "collision_before_execute":
            client.objects[client.CREATED_ID] = client.sound(client.CREATED_ID, client.new_path)
        else:
            (tmp_path / "new.wav").write_bytes(b"changed after Preview")
        rejected = command("execute", preview["transaction_id"], expected_error="ROLE_GUARD_MISMATCH")
        assert rejected["state"] == "repreview_required"
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _args, _options in client.calls)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_import_inherited_field_conflict_rejects_check_without_changing_draft(tmp_path: Path, version: str) -> None:
    command, parent, client = _import_fields_draft(tmp_path, version)
    handles = {}
    for meaning in ("Volume", "Pitch"):
        discovered = command("draft-discover-fields", "--semantic-kind", "random-container", "--meaning", meaning)
        handles[meaning] = discovered["meaning_results"][0]["candidates"][0]["handle"]
    command("draft-business-configure", "--default-field-value", handles["Volume"], "-4")
    command("draft-declare-new", "--declaration-id", "conflict", "--parent-handle", parent,
        "--name", "Conflict", "--kind", "random-container", "--field", "volume_db", "-6",
        "--field-value", handles["Pitch"], "-100")
    record = next((tmp_path / "state/operation-drafts-v1/records").glob("*.json"))
    before = record.read_bytes()
    command("draft-check", expected_error="OPERATION_DRAFT_ACTION_INVALID")
    assert record.read_bytes() == before
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _args, _options in client.calls)


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("field,value,error", (
    ("dialogue_event_directive", "", "OPERATION_DRAFT_ACTION_INVALID"),
    ("switch_value", "", "OPERATION_DRAFT_ACTION_INVALID"),
    ("notes", "bad\x00note", "LIMIT_EXCEEDED"),
))
def test_import_empty_notes_change_preserves_other_string_guards(
    tmp_path: Path, version: str, field: str, value: str, error: str,
) -> None:
    command, parent, client = _import_fields_draft(tmp_path, version)
    field_args = ("--switch-value", value) if field == "switch_value" else ("--field", field, value)
    command("draft-declare-new", "--declaration-id", "invalid", "--parent-handle", parent,
        "--name", "Invalid", "--kind", "random-container", *field_args)
    record = next((tmp_path / "state/operation-drafts-v1/records").glob("*.json"))
    before = record.read_bytes()
    command("draft-check", expected_error=error)
    assert record.read_bytes() == before
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _args, _options in client.calls)


class LocalizedFieldsClient(ImportFieldsClient):
    """Stateful Wwise boundary for localized public reimport field effects."""

    OWNER = "{33333333-3333-3333-3333-333333333333}"
    SOURCE = "{44444444-4444-4444-4444-444444444444}"
    OTHER_SOURCE = "{55555555-5555-5555-5555-555555555555}"
    EVENT = "{66666666-6666-6666-6666-666666666666}"
    ACTION = "{77777777-7777-7777-7777-777777777777}"
    EVENT_PARENT = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
    LANGUAGE = "{88888888-8888-8888-8888-888888888888}"

    def __init__(self, tmp_path: Path, version: str, *, outcome: str = "normal") -> None:
        super().__init__(tmp_path, version)
        self.outcome = outcome
        self.imported = False
        self.owner = {"id": self.OWNER, "name": "Voice", "type": "Sound", "classId": 65552,
            "path": self.parent["path"] + r"\Voice", "parent": {"id": PARENT_ID},
            "notes": "keep owner notes", "@IsVoice": True, "activeSource": {"id": self.SOURCE}}
        self.copied = _project_path(tmp_path).parent / "Originals/Voices/English(US)/Dialogue/Line.wav"
        self.copied.parent.mkdir(parents=True)
        self.copied.write_bytes(b"old English media")
        self.other_file = self.copied.parent.parent.parent / "Japanese/Line.wav"
        self.other_file.parent.mkdir(parents=True)
        self.other_file.write_bytes(b"keep Japanese media")
        self.sources = [
            {"id": self.SOURCE, "name": "Line", "type": "AudioFileSource", "classId": 16,
             "path": self.owner["path"] + r"\Line", "parent": {"id": self.OWNER}, "notes": "old source notes",
             "audioSource:language": {"id": self.LANGUAGE, "name": "English(US)"},
             "originalFilePath": str(self.copied), "originalWavFilePath": str(self.copied)},
            {"id": self.OTHER_SOURCE, "name": "Line", "type": "AudioFileSource", "classId": 16,
             "path": self.owner["path"] + r"\Line", "parent": {"id": self.OWNER}, "notes": "keep Japanese notes",
             "audioSource:language": {"id": "{99999999-9999-9999-9999-999999999999}", "name": "Japanese"},
             "originalFilePath": str(self.other_file), "originalWavFilePath": str(self.other_file)},
        ]
        self.event_parent = {"id": self.EVENT_PARENT, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
            "path": r"\Events\Default Work Unit"}
        self.event_path = r"\Events\Default Work Unit\Play_Voice"
        self.event = {"id": self.EVENT, "name": "Play_Voice", "type": "Event", "path": self.event_path}
        self.action = {"id": self.ACTION, "name": "Play", "type": "Action", "path": self.event_path + r"\Play",
            "parent": {"id": self.EVENT}, "@ActionType": 1, "@Target": {"id": self.OWNER, "path": self.owner["path"]}}
        project = _project_path(tmp_path)
        project.write_text(project.read_text().replace("</LanguageList>",
            f'<Language Name="English(US)" ID="{self.LANGUAGE}"/></LanguageList>'), encoding="utf-8")

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        from copy import deepcopy
        args, options = args or {}, options or {}
        if uri == "ak.wwise.core.getProjectInfo":
            result = super().call(uri, args, options)
            result["languages"].append({"id": self.LANGUAGE, "name": "English(US)", "shortId": 2})
            return result
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            self.calls.append((uri, args, options))
            return {"return": ["IsVoice"]}
        if uri == "ak.wwise.core.object.getPropertyInfo":
            self.calls.append((uri, args, options))
            assert args["property"] == "IsVoice"
            return {"name": "IsVoice", "type": "bool", "default": False, "dependencies": []}
        if uri == "ak.wwise.core.audio.import":
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            self.imported = True
            row, = args["imports"]
            self.copied.write_bytes(Path(row["audioFile"]).read_bytes())
            if self.outcome != "ignored-notes":
                self.sources[0]["notes"] = row.get("audioSourceNotes", row.get("notes", self.sources[0]["notes"]))
            if self.outcome == "wrong-subfolder":
                self.sources[0]["originalFilePath"] = str(self.other_file)
            if self.outcome == "lost-other-language":
                self.sources.pop()
            if self.outcome == "wrong-event-target":
                self.action["@Target"] = {"id": PARENT_ID}
            result = {"objects": deepcopy([self.owner, self.sources[0]])}
            if self.version in {"2023.1", "2024.1", "2025.1"}:
                result.update(log=[], files=[str(self.copied)])
            return result
        if uri.startswith("ak.wwise.core.undo."):
            self.calls.append((uri, args, options))
            return {}
        if uri == "ak.wwise.core.object.get":
            identity = args.get("from", {})
            if args.get("waql") == f'from object "{self.OWNER}" select children take 129':
                self.calls.append((uri, args, options))
                return {"return": [{key: deepcopy(row[key]) for key in options["return"] if key in row}
                    for row in self.sources]}
            known = [self.parent, self.owner, self.event_parent, *self.sources, *([self.event, self.action] if self.imported or self.outcome == "event-exists" else [])]
            if (args.get("waql") == f'from object "{self.EVENT}" select children take 129'
                    or identity.get("id") == [self.EVENT] and args.get("transform")):
                self.calls.append((uri, args, options))
                return {"return": [deepcopy(self.action)]}
            selected = [row for row in known if row["id"] in identity.get("id", [])
                or row["path"] in identity.get("path", [])]
            if selected or self.event_path in identity.get("path", []):
                self.calls.append((uri, args, options))
                return {"return": deepcopy(selected)}
        return super().call(uri, args, options)


def _localized_fields_draft(tmp_path: Path, version: str, *, note_field: str = "audio_source_notes", outcome: str = "normal"):
    client = LocalizedFieldsClient(tmp_path, version, outcome=outcome)
    env = set_gateway_config(_env(tmp_path), wwise_version=version)

    def run(*argv):
        return waapi_gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv],
            env=env, client_factory=lambda _url: client)

    code, started = run("draft-start", "audio.import")
    assert code == 0, started
    draft, authority, revision = started["draft"]["draft_id"], started["task_authority"], 1

    def command(name, *argv, expected_error=None):
        nonlocal revision
        code, result = run(name, draft, "--task-authority", authority, "--expected-revision", str(revision), *argv)
        if expected_error is not None:
            assert code == 2 and result["error_code"] == expected_error, result
        else:
            assert code == 0, result
        if "draft" in result:
            revision = result["draft"]["revision"]
        return result

    bound = command("draft-bind-object", "--object-id", client.OWNER)
    event_bound = command("draft-bind-object", "--object-id", client.EVENT_PARENT)
    command("draft-declare-existing", "--declaration-id", "voice", "--object-handle", bound["bound_object"]["handle"],
        "--field", "language", "English(US)", "--field", "media_file", str(tmp_path / "Line.wav"),
        "--field", "originals_subfolder", "Dialogue", "--field", note_field, "requested source notes",
        *(("--field", "notes", "conflicting notes") if outcome == "competing-notes" else ()),
        "--event-parent-handle", event_bound["bound_object"]["handle"], "--event-name", "Play_Voice", "--event-action", "Play")
    return command, run, client


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("note_field", ("notes", "audio_source_notes"))
def test_localized_existing_fields_reach_public_execute_and_independent_verification(tmp_path: Path, version: str, note_field: str) -> None:
    (tmp_path / "Line.wav").write_bytes(b"requested English media")
    command, run, client = _localized_fields_draft(tmp_path, version, note_field=note_field)
    command("draft-check")
    preview = command("preview-from-draft")
    assert preview["state"] == "awaiting_confirmation"
    assert preview["agent_result"]["request"]["arguments"]["import_operation"] == "useExisting"
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _, _ in client.calls)
    transaction = preview["transaction_id"]
    code, shown = run("transaction-show", transaction, "--summary-only")
    assert code == 0, shown
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, json.dumps(executed, indent=2)
    code, verified = run("verify", transaction)
    assert code == 0 and verified["verified"] is True, json.dumps(verified, indent=2)
    writes = [args for uri, args, _ in client.calls if uri == "ak.wwise.core.audio.import"]
    assert len(writes) == 1
    row, = writes[0]["imports"]
    assert row["originalsSubFolder"] == "Dialogue"
    assert row["audioSourceNotes" if note_field == "audio_source_notes" else "notes"] == "requested source notes"
    assert row["event"] == r"\Events\Default Work Unit\Play_Voice@Play"
    assert client.owner["notes"] == "keep owner notes"
    assert client.sources[0]["notes"] == "requested source notes"
    assert client.other_file.read_bytes() == b"keep Japanese media"
    code, repeated = run("execute", transaction)
    assert code == 2, repeated
    assert len([1 for uri, _, _ in client.calls if uri == "ak.wwise.core.audio.import"]) == 1


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
@pytest.mark.parametrize("outcome,failed_check", (
    ("ignored-notes", "Audio Source notes match exactly"),
    ("wrong-subfolder", "Originals subfolder matches"),
    ("wrong-event-target", "Action target is the imported object"),
    ("lost-other-language", "preserves existing source identities and other languages"),
))
def test_localized_existing_fields_do_not_verify_missing_requested_effects(
    tmp_path: Path, version: str, outcome: str, failed_check: str,
) -> None:
    (tmp_path / "Line.wav").write_bytes(b"requested English media")
    command, run, client = _localized_fields_draft(tmp_path, version, outcome=outcome)
    command("draft-check")
    preview = command("preview-from-draft")
    transaction = preview["transaction_id"]
    code, shown = run("transaction-show", transaction, "--summary-only")
    assert code == 0, shown
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, executed
    code, verified = run("verify", transaction)
    assert code == 2 and verified["verified"] is False, verified
    assert any(failed_check in assertion["name"] and not assertion["passed"]
        for assertion in verified["verification"]["assertions"]), verified
    assert len([1 for uri, _, _ in client.calls if uri == "ak.wwise.core.audio.import"]) == 1


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
@pytest.mark.parametrize("drift", ("media", "other-language-identity"))
def test_localized_existing_fields_still_reject_preview_drift_before_dispatch(
    tmp_path: Path, version: str, drift: str,
) -> None:
    media = tmp_path / "Line.wav"
    media.write_bytes(b"requested English media")
    command, run, client = _localized_fields_draft(tmp_path, version)
    command("draft-check")
    preview = command("preview-from-draft")
    transaction = preview["transaction_id"]
    code, shown = run("transaction-show", transaction, "--summary-only")
    assert code == 0, shown
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "media":
        media.write_bytes(b"changed since Preview")
    else:
        client.sources[1]["id"] = "{DEDEDEDE-DEDE-DEDE-DEDE-DEDEDEDEDEDE}"
    code, executed = run("execute", transaction)
    assert code == 2 and executed["executed"] is False, executed
    assert executed["status"] == "repreview_required", executed
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
@pytest.mark.parametrize("fault,error", (
    ("event-exists", "EVENT_TARGET_EXISTS"),
    ("competing-notes", "AMBIGUOUS_EXISTING_AUDIO_SOURCE_NOTES"),
))
def test_localized_existing_fields_keep_event_ownership_and_notes_unambiguous(
    tmp_path: Path, version: str, fault: str, error: str,
) -> None:
    (tmp_path / "Line.wav").write_bytes(b"requested English media")
    command, _run, client = _localized_fields_draft(tmp_path, version, outcome=fault)
    record = next((tmp_path / "state/operation-drafts-v1/records").glob("*.json"))
    before = record.read_bytes()
    command("draft-check", expected_error=error)
    assert record.read_bytes() == before
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _, _ in client.calls)


class LocalizedTabClient(LocalizedFieldsClient):
    """Separate object/Source column effects; native reuse remains unproven."""

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri != "ak.wwise.core.audio.importTabDelimited":
            result = super().call(uri, args, options)
            if uri == "ak.wwise.core.object.get" and options and "return" in options:
                result = {**result, "return": [{key: value for key, value in row.items() if key in options["return"] or key.lstrip("@") in options["return"]}
                    for row in result.get("return", [])]}
            return result
        import csv
        from copy import deepcopy
        args, options = args or {}, options or {}
        self.calls.append((uri, deepcopy(args), deepcopy(options)))
        self.imported = True
        with Path(args["importFile"]).open(encoding="utf-8", newline="") as table:
            row, = list(csv.DictReader(table, delimiter="\t"))
        if self.outcome != "ignored-notes":
            self.owner["notes"] = row["Notes"]
        if self.outcome != "ignored-source-notes":
            self.sources[0]["notes"] = row["Audio Source Notes"]
        if "OriginalsSubFolder" in row and self.outcome != "ignored-placement":
            self.copied = self.copied.parent.parent / row["OriginalsSubFolder"] / "Line.wav"
            self.copied.parent.mkdir(parents=True, exist_ok=True)
            self.sources[0]["originalFilePath"] = str(self.copied)
            self.sources[0]["originalWavFilePath"] = str(self.copied)
        if self.outcome != "ignored-media":
            self.copied.write_bytes(Path(row["Audio File"]).read_bytes())
        else:
            self.copied.write_bytes(b"old English media")
        if self.outcome == "wrong-event-target":
            self.action["@Target"] = {"id": PARENT_ID}
        if self.outcome == "lost-other-language":
            self.sources.pop()
        if self.outcome == "reset-voice":
            self.owner["@IsVoice"] = False
        return {"objects": deepcopy([self.owner, self.sources[0]])}


def _localized_tab_draft(tmp_path: Path, version: str, *, outcome: str = "normal"):
    client = LocalizedTabClient(tmp_path, version, outcome=outcome)
    media = tmp_path / "Line.wav"
    media.write_bytes(b"requested English media")
    table = tmp_path / "localized.tsv"
    placement = "\tOriginalsSubFolder" if version not in {"2021.1", "2022.1"} else ""
    table.write_text("Audio File\tObject Path\tNotes\tAudio Source Notes\tEvent" + placement + "\n"
        + str(media) + "\t<Sound Voice>Voice\trequested owner notes\trequested Source notes\t"
        + client.event_path + "@Play" + ("\tMoved" if placement else "") + "\n", encoding="utf-8")
    env = set_gateway_config(_env(tmp_path), wwise_version=version)

    def run(*argv):
        return waapi_gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv],
            env=env, client_factory=lambda _url: client)

    code, started = run("draft-start", "audio.importTabDelimited")
    assert code == 0, started
    draft, authority, revision = started["draft"]["draft_id"], started["task_authority"], 1

    def command(name, *argv, expected_error=None):
        nonlocal revision
        code, result = run(name, draft, "--task-authority", authority, "--expected-revision", str(revision), *argv)
        if expected_error is not None:
            assert code == 2 and result["error_code"] == expected_error, result
        else:
            assert code == 0, json.dumps(result, indent=2)
        if "draft" in result:
            revision = result["draft"]["revision"]
        return result

    bound = command("draft-bind-object", "--role", "import_location", "--object-id", PARENT_ID)
    command("draft-declare-artifact-plan", "--table-file", str(table),
        "--location-handle", bound["bound_object"]["handle"], "--language", "English(US)", "--mode", "reimport")
    return command, run, client, table


@pytest.mark.parametrize("version", ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1"))
def test_localized_exact_table_preserves_distinct_notes_and_owned_media_event(tmp_path: Path, version: str) -> None:
    command, run, client, table = _localized_tab_draft(tmp_path, version)
    original = table.read_bytes()
    command("draft-check")
    preview = command("preview-from-draft")
    transaction = preview["transaction_id"]
    code, shown = run("transaction-show", transaction)
    assert code == 0, shown
    dispatch = shown["artifact"]["prepared_operation"]["dispatch"]
    assert dispatch["args"]["importFile"] == str(table.resolve())
    assert dispatch["args"]["importLocation"] == PARENT_ID
    assert "imports" not in dispatch["args"]
    target = shown["artifact"]["prepared_operation"]["verification_plan"]["targets"][0]
    assert target["localized_audio_file_source_id"] == client.SOURCE
    assert target["requested_notes_destination"] == "target_object"
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, json.dumps(executed, indent=2)
    code, verified = run("verify", transaction)
    assert code == 0 and verified["verified"] is True, json.dumps(verified, indent=2)
    assert client.owner["notes"] == "requested owner notes"
    assert client.sources[0]["notes"] == "requested Source notes"
    assert client.other_file.read_bytes() == b"keep Japanese media"
    assert table.read_bytes() == original
    code, repeated = run("execute", transaction)
    assert code == 2, repeated
    assert len([1 for uri, _, _ in client.calls if uri == "ak.wwise.core.audio.importTabDelimited"]) == 1


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
@pytest.mark.parametrize("fault,failed_check", (
    ("ignored-notes", "notes match exactly"),
    ("ignored-source-notes", "Audio Source notes match exactly"),
    ("ignored-media", "copied original WAV hash matches"),
    ("wrong-event-target", "Action target is the imported object"),
    ("lost-other-language", "preserves existing source identities and other languages"),
    ("reset-voice", "localized TSV owner remains a Sound Voice"),
))
def test_localized_exact_table_verifier_rejects_ignored_fields_and_scope_loss(
    tmp_path: Path, version: str, fault: str, failed_check: str,
) -> None:
    command, run, client, table = _localized_tab_draft(tmp_path, version, outcome=fault)
    original = table.read_bytes()
    command("draft-check")
    transaction = command("preview-from-draft")["transaction_id"]
    code, shown = run("transaction-show", transaction, "--summary-only")
    assert code == 0, shown
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, executed
    code, verified = run("verify", transaction)
    assert code == 2 and verified["verified"] is False, verified
    assert any(failed_check in row["name"] and not row["passed"]
        for row in verified["verification"]["assertions"]), verified
    assert table.read_bytes() == original
    assert len([1 for uri, _, _ in client.calls if uri == "ak.wwise.core.audio.importTabDelimited"]) == 1


@pytest.mark.parametrize("version", ("2022.1", "2025.1"))
@pytest.mark.parametrize("drift", ("table", "media", "source-language"))
def test_localized_exact_table_guard_rejects_input_and_language_drift(
    tmp_path: Path, version: str, drift: str,
) -> None:
    command, run, client, table = _localized_tab_draft(tmp_path, version)
    command("draft-check")
    transaction = command("preview-from-draft")["transaction_id"]
    code, shown = run("transaction-show", transaction, "--summary-only")
    assert code == 0, shown
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    if drift == "table":
        table.write_bytes(table.read_bytes() + b"\n")
    elif drift == "media":
        (tmp_path / "Line.wav").write_bytes(b"changed after Preview")
    else:
        client.sources[1]["audioSource:language"]["name"] = "changed language"
    code, rejected = run("execute", transaction)
    assert code == 2 and rejected["executed"] is False, rejected
    assert not any(uri == "ak.wwise.core.audio.importTabDelimited" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault,error", (
    ("typed-sfx", "INVALID_TARGET_TYPE"),
    ("live-sfx", "INVALID_TARGET_TYPE"),
    ("duplicate-source", "AMBIGUOUS_LOCALIZED_SOURCE"),
    ("foreign-source", "INVALID_READBACK"),
    ("missing-language", "IMPORT_LANGUAGE_UNAVAILABLE"),
))
def test_localized_exact_table_checks_live_owner_source_and_language_before_preview(
    tmp_path: Path, fault: str, error: str,
) -> None:
    from copy import deepcopy
    command, _run, client, table = _localized_tab_draft(tmp_path, "2025.1")
    if fault == "typed-sfx":
        table.write_text(table.read_text().replace("<Sound Voice>", "<Sound SFX>"), encoding="utf-8")
    elif fault == "live-sfx":
        client.owner["@IsVoice"] = False
    elif fault == "duplicate-source":
        duplicate = deepcopy(client.sources[0]); duplicate["id"] = client.ACTION
        client.sources.append(duplicate)
    elif fault == "foreign-source":
        client.sources[0]["parent"]["id"] = PARENT_ID
    else:
        command("draft-declare-artifact-plan", "--table-file", str(table), "--location-handle",
            # Rebind the same exact placement to obtain a current public handle.
            command("draft-bind-object", "--role", "import_location", "--object-id", PARENT_ID)["bound_object"]["handle"],
            "--language", "Unknown", "--mode", "reimport")
    record = next((tmp_path / "state/operation-drafts-v1/records").glob("*.json"))
    before = record.read_bytes()
    command("draft-check", expected_error=error)
    assert record.read_bytes() == before
    assert not any(uri == "ak.wwise.core.audio.importTabDelimited" for uri, _, _ in client.calls)


@pytest.mark.parametrize("version", ("2021.1", "2022.1"))
def test_localized_exact_table_reports_originals_column_introduction_before_preview(tmp_path: Path, version: str) -> None:
    command, _run, client, table = _localized_tab_draft(tmp_path, version)
    lines = table.read_text().splitlines()
    table.write_text(lines[0] + "\tOriginalsSubFolder\n" + lines[1] + "\tMoved\n", encoding="utf-8")
    original = table.read_bytes()
    rejected = command("draft-check", expected_error="VERSION_BEHAVIOR_BOUNDARY")
    assert rejected["details"]["introduced_version"] == "2023.1"
    assert rejected["details"]["source_change"] == "WG-60834"
    assert table.read_bytes() == original
    assert not any(uri == "ak.wwise.core.audio.importTabDelimited" for uri, _, _ in client.calls)


def test_localized_exact_table_verifier_rejects_ignored_originals_placement(tmp_path: Path) -> None:
    command, run, client, table = _localized_tab_draft(tmp_path, "2025.1", outcome="ignored-placement")
    command("draft-check")
    transaction = command("preview-from-draft")["transaction_id"]
    code, shown = run("transaction-show", transaction, "--summary-only")
    assert code == 0, shown
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, executed
    code, verified = run("verify", transaction)
    assert code == 2 and verified["verified"] is False, verified
    assert any("Originals subfolder matches" in row["name"] and not row["passed"]
        for row in verified["verification"]["assertions"]), verified


def test_localized_exact_table_new_language_source_is_independent_of_default_active_source(tmp_path: Path) -> None:
    command, run, client, table = _localized_tab_draft(tmp_path, "2025.1")
    pending_source = client.sources.pop(0)
    client.owner["activeSource"] = {"id": client.OTHER_SOURCE}
    prior = client.call
    def call(uri, args=None, options=None):
        if uri == "ak.wwise.core.audio.importTabDelimited":
            client.sources.insert(0, pending_source)
        return prior(uri, args, options)
    client.call = call
    command("draft-check")
    transaction = command("preview-from-draft")["transaction_id"]
    code, shown = run("transaction-show", transaction)
    assert code == 0, shown
    assert shown["artifact"]["prepared_operation"]["verification_plan"]["targets"][0]["localized_audio_file_source_id"] is None
    code, confirmed = run("confirm", transaction, "--confirmation-token", shown["confirmation"]["token"])
    assert code == 0, confirmed
    code, executed = run("execute", transaction)
    assert code == 0, executed
    code, verified = run("verify", transaction)
    assert code == 0 and verified["verified"] is True, verified
    assert client.owner["activeSource"]["id"] == client.OTHER_SOURCE
    assert client.sources[1]["notes"] == "keep Japanese notes"
    assert client.other_file.read_bytes() == b"keep Japanese media"

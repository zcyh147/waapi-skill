from __future__ import annotations

import importlib.util
import json
import sys
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
    for scope_name in ("object_scope", "class_scope"):
        scope = bound_next["field_binding"][scope_name]
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
        "each_row_must_include_its_media_every_known_requested_field_switch_"
        "assignment_and_event_in_the_same_command; partial_rows_are_forbidden"
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
            ],
            "ak.wwise.core.object.getPropertyAndReferenceNames": [
                {"return": ["CustomGain"]}
            ],
            "ak.wwise.core.object.getPropertyInfo": [
                {
                    "name": "CustomGain",
                    "type": "Real32",
                    "restriction": {"type": "range", "min": -12.0, "max": 12.0},
                }
            ],
        }
    )
    field_code, field_bound = waapi_gateway.execute_gateway(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "draft-bind-field",
            draft_id,
            "--task-authority",
            authority,
            "--expected-revision",
            "2",
            "--class-name",
            "Sound",
            "--token",
            "CustomGain",
        ],
        env=_env(tmp_path),
        client_factory=lambda _url: field_client,
    )
    assert field_code == 0, json.dumps(
        {"payload": field_bound, "calls": field_client.calls}, indent=2
    )
    field_handle = field_bound["bound_field"]["handle"]
    assert field_bound["bound_field"]["restrictions"] == {
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
    )
    assert declare_code == 0, declared
    assert declared["draft"]["revision"] == 5
    assert "declarations" not in declared["draft"]
    assert declared["draft"]["declaration_receipt"]["fields"] == {
        "language": "SFX",
        "loop": "infinite",
        "media_file": str(media),
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
        "import_language": "SFX",
        "object_path": (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Weather\<Sound SFX>Rain_Bed"
        ),
        "object_type": "Sound SFX",
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
    assert first_next["append_import_chunk"]["row_completeness"] == (
        "each_row_must_include_its_media_every_known_requested_field_switch_"
        "assignment_and_event_in_the_same_command; partial_rows_are_forbidden"
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
    response_size = len(
        json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    # Native Windows must retain the canonical encoded PowerShell audit
    # envelope; POSIX has no equivalent expansion in next_command.  The
    # copy-exact continuation also retains an explicit caller state directory
    # so the next phase cannot silently fall back to another transaction store.
    assert response_size <= (9_500 if sys.platform == "win32" else 8_000)

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


def test_structure_declaration_reaches_live_check_and_persists_readable_preview(
    tmp_path: Path,
) -> None:
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
